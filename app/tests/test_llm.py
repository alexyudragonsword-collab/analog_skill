"""Tests for the LLM-assisted sizing features — fully offline: the single
HTTP chokepoint (llm_client._post_json) or llm_client.chat is faked."""

import json

import numpy as np
import os
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from app import paths
paths.init_runtime()

from app.core import llm_client, llm_sizing, sizing

needs_ngspice = pytest.mark.skipif(
    shutil.which('ngspice') is None, reason='ngspice not installed')

CFG_OPENAI = {'provider': 'openai', 'base_url': 'https://api.example/v1',
              'api_key': 'sk-test', 'model': 'test-model'}
CFG_ANTHROPIC = {'provider': 'anthropic', 'base_url': '',
                 'api_key': 'sk-ant', 'model': 'claude-test'}


# ── client protocol shapes ───────────────────────────────────────────────────
def test_openai_payload_shape(monkeypatch):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {'choices': [{'message': {'content': 'hi'}}]}

    monkeypatch.setattr(llm_client, '_post_json', fake_post)
    out = llm_client.chat([{'role': 'user', 'content': 'q'}],
                          system='sys', cfg=CFG_OPENAI)
    assert out == 'hi'
    assert seen['url'] == 'https://api.example/v1/chat/completions'
    assert seen['headers']['Authorization'] == 'Bearer sk-test'
    assert seen['payload']['model'] == 'test-model'
    assert seen['payload']['messages'][0] == {'role': 'system',
                                              'content': 'sys'}


def test_anthropic_payload_shape(monkeypatch):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {'content': [{'type': 'text', 'text': 'ok'}]}

    monkeypatch.setattr(llm_client, '_post_json', fake_post)
    out = llm_client.chat([{'role': 'user', 'content': 'q'}],
                          system='sys', cfg=CFG_ANTHROPIC)
    assert out == 'ok'
    assert seen['url'] == 'https://api.anthropic.com/v1/messages'
    assert seen['headers']['x-api-key'] == 'sk-ant'
    assert seen['payload']['system'] == 'sys'
    assert all(m['role'] != 'system' for m in seen['payload']['messages'])


def test_unconfigured_raises():
    with pytest.raises(llm_client.LLMError):
        llm_client.chat([{'role': 'user', 'content': 'q'}],
                        cfg={'provider': 'openai', 'base_url': '',
                             'api_key': '', 'model': ''})


def test_extract_json_variants():
    assert llm_client.extract_json('{"a": 1}') == {'a': 1}
    assert llm_client.extract_json(
        'sure!\n```json\n{"a": [1, 2]}\n```\nthanks') == {'a': [1, 2]}
    assert llm_client.extract_json(
        'text {"a": {"b": 2}} trailing')['a']['b'] == 2
    assert llm_client.extract_json('list: [1, 2, 3] done') == [1, 2, 3]
    with pytest.raises(llm_client.LLMError):
        llm_client.extract_json('no json here at all')


# ── prompts ──────────────────────────────────────────────────────────────────
def test_describe_circuit_contents():
    variables = sizing.parse_variables('amp_hoilee_affc')
    text = llm_sizing.describe_circuit('amp_hoilee_affc', variables)
    assert 'HoiLee_AFFC' in text
    assert 'CURRENT_0_BIAS' in text          # variable with bounds
    assert 'dcgain' in text                  # metric target line
    assert '.subckt' in text.lower() or '.SUBCKT' in text  # netlist excerpt
    skill = sizing.parse_variables('skill_ota5t')
    text2 = llm_sizing.describe_circuit('skill_ota5t', skill)
    assert 'W_IN_UM' in text2 and 'ugb_hz' in text2


def test_explain_and_suggest_prompts(monkeypatch):
    prompts = []

    def fake_chat(messages, system=None, **kw):
        prompts.append(messages[-1]['content'])
        if 'STRICT JSON' in messages[-1]['content']:
            return json.dumps({'rationale': '增大输入对宽度',
                               'budget': 120,
                               'variables': {'W_IN_UM': {
                                   'init': 12.0, 'lo': 4.0, 'hi': 40.0}}})
        return '瓶颈在相位裕度。'

    variables = sizing.parse_variables('skill_ota5t')
    sugg, why = llm_sizing.suggest_setup('skill_ota5t', variables,
                                         chat=fake_chat)
    assert sugg['W_IN_UM'] == {'init': 12.0, 'lo': 4.0, 'hi': 40.0}
    assert sugg['_budget'] == 120 and why == '增大输入对宽度'
    assert 'W_IN_UM' in prompts[0]

    run = sizing.SizingRun(
        circuit='skill_ota5t', best_values={'W_IN_UM': 8.0},
        best_metrics={'dc_gain_db': 34.0}, best_cost=0.5, initial_cost=1.0,
        history=[(1, 1.0)], evals=1, cancelled=False, elapsed=2.0)
    text = llm_sizing.explain_run(run, variables, chat=fake_chat)
    assert text == '瓶颈在相位裕度。'
    assert 'DC gain' in prompts[1] or 'dc_gain_db' in prompts[1]


def test_suggest_setup_clips_bad_values(monkeypatch):
    def fake_chat(messages, system=None, **kw):
        return json.dumps({'rationale': 'x', 'budget': 999999,
                           'variables': {
                               'W_IN_UM': {'init': -5, 'lo': 8, 'hi': 2},
                               'NOT_A_VAR': {'init': 1, 'lo': 0, 'hi': 2}}})

    variables = sizing.parse_variables('skill_ota5t')
    v = {x.name: x for x in variables}['W_IN_UM']
    sugg, _ = llm_sizing.suggest_setup('skill_ota5t', variables,
                                       chat=fake_chat)
    assert 'NOT_A_VAR' not in sugg and '_budget' not in sugg
    d = sugg['W_IN_UM']
    assert d['lo'] == v.lo and d['hi'] == v.hi        # hi<=lo → defaults
    assert d['lo'] <= d['init'] <= d['hi']             # init clipped


# ── the closed loop (real ngspice evaluations, fake LLM) ─────────────────────
def _fake_llm_candidates(variables, jitter=0.9):
    """A scripted 'LLM' proposing slight shrinks of the defaults."""
    def fake_chat(messages, system=None, **kw):
        cands = []
        for i in range(4):
            f = jitter + 0.05 * i
            cands.append({v.name: min(max(v.default * f, v.lo), v.hi)
                          for v in variables})
        return json.dumps({'rationale': 'probe', 'candidates': cands})
    return fake_chat


@needs_ngspice
def test_llm_optimize_micro(monkeypatch):
    variables = sizing.parse_variables('amp_hoilee_affc')
    monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: True)
    monkeypatch.setattr(llm_client, 'chat',
                        _fake_llm_candidates(variables))
    run = sizing.optimize('amp_hoilee_affc', variables, budget=6,
                          algo='llm', workers=2)
    assert run.evals == 6                     # budget is a hard cap
    assert run.best_cost <= run.initial_cost
    assert len(run.history) == 6


@needs_ngspice
def test_llm_optimize_bad_json_falls_back(monkeypatch):
    variables = sizing.parse_variables('amp_hoilee_affc')
    monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: True)
    monkeypatch.setattr(llm_client, 'chat',
                        lambda *a, **k: 'sorry, no JSON today')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=4,
                          algo='llm', workers=2)
    assert run.evals == 4                     # Sobol fallback kept it going
    assert run.best_cost <= run.initial_cost


def test_llm_optimize_unconfigured_fails_fast(monkeypatch):
    variables = sizing.parse_variables('skill_ota5t')
    monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: False)
    with pytest.raises(llm_client.LLMError):
        llm_sizing.run_loop('skill_ota5t', variables, None,
                            state={'cancel': False, 'dispatched': 0,
                                   'best': None, 'best_x': None,
                                   'best_m': {}},
                            run_batch=lambda pts: [0.0] * len(pts),
                            budget=5, workers=1)


# ── GUI hooks ────────────────────────────────────────────────────────────────
def test_sizing_tab_llm_controls(monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.core.worker import SimWorker
    from app.ui.sizing_tab import SizingTab
    worker = SimWorker()
    try:
        tab = SizingTab(worker)
        algos = {tab.algo_combo.itemData(i)
                 for i in range(tab.algo_combo.count())}
        assert 'llm' in algos
        assert not tab.explain_btn.isEnabled()      # no run yet
        # unconfigured LLM → algo 'llm' refuses to start with a hint
        monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: False)
        tab.algo_combo.setCurrentIndex(
            [tab.algo_combo.itemData(i)
             for i in range(tab.algo_combo.count())].index('llm'))
        tab._run()
        assert 'not configured' in tab._status.text()
    finally:
        worker.stop()


# ── where the API key lives ───────────────────────────
def test_env_api_key_overrides_the_stored_one(isolated_settings, monkeypatch):
    """A key in the environment is what gets used, so a user on a shared
    machine can run the AI features without the key reaching disk."""
    monkeypatch.delenv(llm_client.ENV_API_KEY, raising=False)
    llm_client.set_config('openai', '', 'sk-on-disk', 'm')
    cfg = llm_client.get_config()
    assert cfg['api_key'] == 'sk-on-disk' and not cfg['api_key_from_env']

    monkeypatch.setenv(llm_client.ENV_API_KEY, 'sk-from-env')
    cfg = llm_client.get_config()
    assert cfg['api_key'] == 'sk-from-env' and cfg['api_key_from_env']


def test_env_api_key_is_never_written_to_disk(isolated_settings, monkeypatch):
    """Settings saves every field on OK.  Saving the environment-supplied key
    would put it in plain text after all — the case the variable exists to
    avoid — so that one field is left alone."""
    from PySide6.QtCore import QSettings
    monkeypatch.delenv(llm_client.ENV_API_KEY, raising=False)
    llm_client.set_config('openai', '', 'sk-on-disk', 'm')
    monkeypatch.setenv(llm_client.ENV_API_KEY, 'sk-from-env')

    # what the dialog does on OK when the key came from the environment
    cfg = llm_client.get_config()
    llm_client.set_config(cfg['provider'], cfg['base_url'], cfg['api_key'],
                          cfg['model'], store_api_key=False)
    stored = str(QSettings().value(llm_client.KEY_API_KEY, ''))
    assert stored == 'sk-on-disk'      # untouched, and not 'sk-from-env'

    # the ordinary path still saves it
    monkeypatch.delenv(llm_client.ENV_API_KEY)
    llm_client.set_config('openai', '', 'sk-typed-in', 'm')
    assert str(QSettings().value(llm_client.KEY_API_KEY, '')) == 'sk-typed-in'


# ── the Claude Code provider (subscription instead of an API key) ────────────
def _cc_cfg(model='sonnet'):
    return {'provider': 'claude_code', 'base_url': '', 'api_key': '',
            'model': model, 'api_key_from_env': False}


def _fake_cli(monkeypatch, result='hello', **extra):
    """Stand in for the CLI, recording the argv and prompt it was given."""
    seen = {}

    def run(argv, prompt, timeout):
        seen.update(argv=argv, prompt=prompt, timeout=timeout)
        return {'result': result, 'is_error': False, **extra}

    monkeypatch.setattr(llm_client, '_run_cli', run)
    monkeypatch.setattr('app.core.claude_locator.resolve', lambda: '/bin/claude')
    return seen


def test_claude_code_flattens_the_history_into_one_prompt(monkeypatch):
    """The CLI takes a prompt, not a message array.  Nothing may be dropped:
    llm_sizing.run_loop feeds back each round's measured costs as assistant
    and user turns, and a lost turn is a silently worse search."""
    seen = _fake_cli(monkeypatch, result='{"candidates": []}')
    out = llm_client.chat(
        [{'role': 'user', 'content': 'first'},
         {'role': 'assistant', 'content': 'second'},
         {'role': 'user', 'content': 'third'}],
        system='be terse', cfg=_cc_cfg())
    assert out == '{"candidates": []}'
    assert seen['prompt'] == 'User: first\n\nAssistant: second\n\nUser: third'
    assert '--system-prompt' in seen['argv']
    assert seen['argv'][seen['argv'].index('--system-prompt') + 1] == 'be terse'
    assert seen['argv'][seen['argv'].index('--model') + 1] == 'sonnet'


def test_claude_code_is_run_with_its_tools_switched_off(monkeypatch):
    """This spawns an agent on the user's machine.  It must not be able to
    run commands, touch files, or inherit the user's own project
    instructions — an analog netlist prompt has no business being steered
    by whatever CLAUDE.md happens to be on that disk."""
    seen = _fake_cli(monkeypatch)
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())
    argv = seen['argv']
    assert '--restricted' in argv                     # no Bash, no WebFetch
    assert '--strict-mcp-config' in argv              # no user MCP servers
    i = argv.index('--setting-sources')
    assert argv[i + 1] == ''                          # no CLAUDE.md / hooks
    denied = argv[argv.index('--disallowed-tools') + 1]
    for tool in ('Read', 'Write', 'Edit', 'Bash', 'WebFetch', 'Task'):
        assert tool in denied
    # the two flags that would hand the machine over
    assert '--dangerously-skip-permissions' not in argv
    assert 'bypassPermissions' not in argv


def test_claude_code_never_joins_an_inherited_session(monkeypatch):
    """Launched from inside a Claude Code session, the CLI picks up that
    session from the environment — and would append a sizing prompt to the
    user's own conversation.  Every call pins a fresh id."""
    ids = []
    for _ in range(2):
        seen = _fake_cli(monkeypatch)
        llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())
        ids.append(seen['argv'][seen['argv'].index('--session-id') + 1])
    assert ids[0] != ids[1] and all(len(i) == 36 for i in ids)


def test_claude_code_reports_a_cli_error_as_an_llm_error(monkeypatch):
    """is_error in the envelope, not a non-zero exit — the CLI returns 0
    and describes the failure in its JSON."""
    monkeypatch.setattr('app.core.claude_locator.resolve', lambda: '/bin/claude')
    monkeypatch.setattr(llm_client, '_run_cli',
                        lambda *a: {'is_error': True,
                                    'result': 'usage limit reached'})
    with pytest.raises(llm_client.LLMError, match='usage limit reached'):
        llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())


def test_claude_code_says_how_to_install_when_it_is_missing(monkeypatch):
    monkeypatch.setattr('app.core.claude_locator.resolve', lambda: None)
    assert not llm_client.configured(_cc_cfg())
    with pytest.raises(llm_client.LLMError, match='npm i -g'):
        llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())


def test_claude_code_needs_no_api_key_but_does_need_the_binary(monkeypatch):
    """configured() gates every AI button.  For this provider the question
    is not "is there a key" — there is none — but "is the CLI there"."""
    monkeypatch.setattr('app.core.claude_locator.resolve', lambda: '/bin/claude')
    assert llm_client.configured(_cc_cfg())            # no key, still fine
    assert not llm_client.configured(_cc_cfg(model=''))  # but a model is needed
    monkeypatch.setattr('app.core.claude_locator.resolve', lambda: None)
    assert not llm_client.configured(_cc_cfg())


def test_claude_code_timeout_is_never_shorter_than_a_cold_start(monkeypatch):
    """test_connection() asks for 15 s, which is fine for an HTTP round trip
    and not for a whole agent booting.  The floor keeps the Test button from
    reporting a timeout on a CLI that works."""
    seen = _fake_cli(monkeypatch, result='OK')
    llm_client.test_connection(_cc_cfg())
    assert seen['timeout'] >= llm_client.CLI_MIN_TIMEOUT


class _FakeProc:
    """Enough of Popen for _run_cli: it writes the prompt through
    communicate(), reads returncode, and may have to kill the thing."""

    def __init__(self, out='', err='', rc=0, raises=None):
        self._out, self._err, self._raises = out, err, raises
        self.returncode, self.pid = rc, 424242
        self.killed = False

    def communicate(self, input=None, timeout=None):
        if self._raises is not None:
            raise self._raises
        return self._out, self._err

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


def _fake_popen(monkeypatch, proc=None, on_spawn=None, record=None):
    import subprocess
    from app.core import claude_locator
    monkeypatch.setattr(claude_locator, '_no_window', dict)

    def popen(argv, **kw):
        if record is not None:
            # the directory only exists while the call is in flight, so
            # look now rather than after _run_cli has cleaned it up
            from pathlib import Path as _P
            record.update(kw)
            record['listing'] = list(_P(kw['cwd']).iterdir())
        if on_spawn is not None:
            raise on_spawn
        return proc

    monkeypatch.setattr(subprocess, 'Popen', popen)
    # killpg would signal this very test process
    monkeypatch.setattr('app.core.llm_client._kill_tree', lambda p: None)
    return proc


def test_run_cli_turns_every_failure_into_a_readable_llm_error(monkeypatch):
    """_run_cli is the chokepoint the rest of the suite fakes, so it is the
    one place these have to be handled for real.  A tab shows the last line
    of the error, so a traceback or an empty string there is useless."""
    import subprocess

    _fake_popen(monkeypatch, on_spawn=OSError('no such file'))
    with pytest.raises(llm_client.LLMError, match='could not run'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    _fake_popen(monkeypatch, _FakeProc(
        raises=subprocess.TimeoutExpired('claude', 90)))
    with pytest.raises(llm_client.LLMError, match='within 90s'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    _fake_popen(monkeypatch, _FakeProc(out='', err='not logged in\n', rc=1))
    with pytest.raises(llm_client.LLMError, match='not logged in'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    _fake_popen(monkeypatch, _FakeProc(out='Welcome to Claude!', rc=0))
    with pytest.raises(llm_client.LLMError, match='non-JSON'):
        llm_client._run_cli(['claude'], 'hi', 90.0)


def test_run_cli_runs_in_an_empty_directory(monkeypatch):
    """Belt to the disallowed-tools braces: if a file tool ever does get
    through, there is nothing where it lands to read."""
    from pathlib import Path
    kw = {}
    _fake_popen(monkeypatch, _FakeProc(out='{"result": "x"}'), record=kw)
    assert llm_client._run_cli(['claude'], 'hi', 90.0) == {'result': 'x'}
    assert kw['listing'] == []                 # empty while it ran...
    assert not Path(kw['cwd']).exists()        # ...and gone afterwards


def test_claude_locator_prefers_the_configured_path(isolated_settings,
                                                    monkeypatch):
    """Same contract as the ngspice row: empty means auto-detect."""
    import shutil
    from app.core import claude_locator
    monkeypatch.setattr(shutil, 'which',
                        lambda name: '/usr/bin/claude' if name == 'claude'
                        else None)
    claude_locator.set_user_path('')
    assert claude_locator.resolve() == '/usr/bin/claude'
    claude_locator.set_user_path('/opt/mine/claude')
    assert claude_locator.resolve() == '/opt/mine/claude'
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    claude_locator.set_user_path('')
    assert claude_locator.resolve() is None


def test_claude_locator_only_reports_ok_for_a_binary_that_answers(monkeypatch):
    """A path that exists but is not the CLI must read as 'not found'
    rather than as a working install that fails on the first real call."""
    import subprocess
    from app.core import claude_locator
    monkeypatch.setattr(claude_locator, 'resolve', lambda: '/bin/claude')
    monkeypatch.setattr(claude_locator, '_no_window', dict)

    good = type('R', (), {'stdout': '2.1.270 (Claude Code)\n', 'stderr': '',
                          'returncode': 0})
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: good())
    st = claude_locator.locate()
    assert st.ok and st.version == '2.1.270 (Claude Code)'

    bad = type('R', (), {'stdout': '', 'stderr': '', 'returncode': 127})
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: bad())
    assert not claude_locator.locate().ok


# ── structured output ────────────────────────────────────────────────────────
def test_schema_reaches_the_cli_and_is_optional(monkeypatch):
    """chat(schema=...) is a request, not a guarantee: the provider that can
    enforce it does, and callers still parse defensively because the same
    code runs against providers that cannot."""
    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())
    assert '--json-schema' not in seen['argv']       # omitted when unused

    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg(),
                    schema={'type': 'object'})
    sent = seen['argv'][seen['argv'].index('--json-schema') + 1]
    assert json.loads(sent) == {'type': 'object'}


def test_schema_is_ignored_rather_than_sent_to_a_provider_that_cannot(
        monkeypatch):
    """The HTTP providers have their own mechanisms and have not been taught
    this one.  Passing schema must not leak into the request body, where it
    would be an unknown field."""
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(payload=payload)
        return {'choices': [{'message': {'content': 'hi'}}]}

    monkeypatch.setattr(llm_client, '_post_json', fake_post)
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=CFG_OPENAI,
                    schema={'type': 'object'})
    assert 'schema' not in seen['payload']
    assert 'json_schema' not in seen['payload']


def test_candidates_schema_demands_every_variable(monkeypatch):
    """The whole point.  A candidate missing one of 33 long key names is
    dropped silently by _parse_candidates; the schema makes it unbuildable."""
    import numpy as np
    from app.core import llm_sizing
    names = ['W_IN', 'L_IN', 'CURRENT_0_BIAS']
    lo, hi = np.array([1.0, 0.15, 5e-6]), np.array([10.0, 4.0, 8e-5])
    s = llm_sizing.candidates_schema(names, lo, hi, 4)
    item = s['properties']['candidates']['items']
    assert item['required'] == names          # all of them, not a subset
    assert item['additionalProperties'] is False
    assert item['properties']['CURRENT_0_BIAS'] == {
        'type': 'number', 'minimum': 5e-6, 'maximum': 8e-5}
    assert s['properties']['candidates']['maxItems'] == 4


def test_setup_schema_is_partial_on_purpose():
    """suggest_setup asks for "only variables worth changing", so requiring
    every name would be wrong.  What it does pin down is that a suggestion
    cannot name a variable this circuit does not have."""
    from app.core import llm_sizing
    s = llm_sizing.setup_schema(['W_IN', 'L_IN'])
    variables = s['properties']['variables']
    assert 'required' not in variables         # partial is allowed
    assert variables['additionalProperties'] is False
    assert set(variables['properties']) == {'W_IN', 'L_IN'}


def test_run_loop_asks_for_the_schema_of_the_circuit_it_is_sizing(monkeypatch):
    """Built per round from that circuit's own variables — a schema for the
    wrong circuit would reject every candidate."""
    import numpy as np
    from app.core import llm_sizing
    from app.core.sizing.spec import VarSpec
    variables = [
        VarSpec(name='W_IN', default=5.0, lo=1.0, hi=10.0, is_int=False),
        VarSpec(name='L_IN', default=0.5, lo=0.15, hi=4.0, is_int=False)]
    seen = {}

    def fake_chat(messages, system=None, schema=None, **kw):
        seen['schema'] = schema
        return json.dumps({'rationale': 'r',
                           'candidates': [{'W_IN': 6.0, 'L_IN': 0.6}]})

    state = {'best': 1.0, 'best_x': None, 'cancel': False, 'dispatched': 0}

    def run_batch(points, with_metrics=False):
        state['dispatched'] += len(points)
        costs = [1.0] * len(points)
        return (costs, [None] * len(points)) if with_metrics else costs

    llm_sizing.run_loop('amp_hoilee_affc', variables, None, state=state,
                        run_batch=run_batch, budget=3, workers=1,
                        chat=fake_chat)
    assert seen['schema'] is not None
    assert seen['schema']['properties']['candidates']['items']['required'] \
        == ['W_IN', 'L_IN']
    assert np.isclose(
        seen['schema']['properties']['candidates']['items'][
            'properties']['W_IN']['maximum'], 10.0)


def test_cli_timeout_floor_covers_a_real_sizing_round(monkeypatch):
    """chat()'s 120 s default is an HTTP-shaped number.  A measured round on
    a 33-variable circuit takes 88-112 s through the CLI, so at 120 s the
    LLM algorithm would time out, retry, and fall back to Sobol — quietly
    ceasing to be the LLM algorithm."""
    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())
    assert seen['timeout'] >= 120.0 * 2


def test_effort_is_passed_when_asked_for_and_validated(monkeypatch):
    """Same contract as schema — a hint the provider may honour.  An
    unrecognised level is dropped rather than handed to the CLI, which
    would reject the whole invocation and take the round with it."""
    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg())
    assert '--effort' not in seen['argv']

    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg(),
                    effort='low')
    assert seen['argv'][seen['argv'].index('--effort') + 1] == 'low'

    seen = _fake_cli(monkeypatch, result='{}')
    llm_client.chat([{'role': 'user', 'content': 'q'}], cfg=_cc_cfg(),
                    effort='ludicrous')
    assert '--effort' not in seen['argv']


def test_the_search_loop_asks_for_low_effort_and_the_one_shots_do_not(
        monkeypatch):
    """The loop runs ~38 times for points nobody reads; advise and explain
    run once for text the user does read.  Spending the same reasoning on
    both is what made a two-minute optimization take an hour."""
    from app.core import llm_sizing
    from app.core.sizing.spec import VarSpec
    variables = [
        VarSpec(name='W_IN', default=5.0, lo=1.0, hi=10.0, is_int=False)]
    efforts = []

    def fake_chat(messages, system=None, schema=None, effort=None, **kw):
        efforts.append(effort)
        return json.dumps({'rationale': 'r', 'budget': 60,
                           'candidates': [{'W_IN': 6.0}],
                           'variables': {}})

    state = {'best': 1.0, 'best_x': None, 'cancel': False, 'dispatched': 0}

    def run_batch(points, with_metrics=False):
        state['dispatched'] += len(points)
        costs = [1.0] * len(points)
        return (costs, [None] * len(points)) if with_metrics else costs

    llm_sizing.run_loop('amp_hoilee_affc', variables, None, state=state,
                        run_batch=run_batch, budget=2, workers=1,
                        chat=fake_chat)
    assert efforts and set(efforts) == {'low'}

    efforts.clear()
    llm_sizing.suggest_setup('amp_hoilee_affc', variables, chat=fake_chat)
    assert efforts == [None]          # the provider's own default


# ── telling the model which target it missed ─────────────────────────────────
_M = {'dcgain': 62.1, 'gain_bandwidth_product': 1.35e6, 'phase_in_deg': 59.2,
      'dcpsrp': -71.0, 'dcpsrn': -68.0, 'cmrrdc': -64.0, 'power': 8.1e-4,
      'vos25': 4.2e-5, 'tc': 6.0e-6, 'tsettle': 1.1e-6}


def test_metric_feedback_names_the_misses_and_counts_the_slack():
    """"cost 1.398" tells the model nothing about where to push.  The line
    has to name the worst offenders with their real numbers, and say how
    many targets are already met, because that slack is what a designer
    trades away."""
    from app.core import llm_sizing
    line = llm_sizing.metric_feedback('amp_hoilee_affc', _M)
    assert '7/10 met' in line
    assert 'DC gain 62.1 dB (want >= 100' in line       # value and target
    assert 'off 38%' in line                            # and by how much
    assert 'Power' in line and 'want <= 0.0005' in line  # direction per spec
    assert 'PSRR' not in line                           # met ones are not listed


def test_metric_feedback_says_so_when_everything_is_met_or_nothing_ran():
    from app.core import llm_sizing
    good = dict(_M, dcgain=104.0, power=3.0e-4, phase_in_deg=60.0)
    assert llm_sizing.metric_feedback('amp_hoilee_affc', good) == \
        'all 10 targets met'
    assert 'no metrics' in llm_sizing.metric_feedback('amp_hoilee_affc', None)


def test_metric_feedback_is_bounded_when_everything_fails():
    """A deck that misses every target must not paste nine clauses into
    every candidate line of every round."""
    from app.core import llm_sizing
    line = llm_sizing.metric_feedback('amp_hoilee_affc', {'dcgain': 1.0},
                                      limit=3)
    assert line.count('want') <= 3 and 'more' in line


def test_run_loop_feeds_the_metrics_back_not_just_the_cost(monkeypatch):
    """The whole point: the conversation the model sees must carry which
    target each candidate missed."""
    from app.core import llm_sizing
    from app.core.sizing.spec import VarSpec
    variables = [
        VarSpec(name='W_IN', default=5.0, lo=1.0, hi=10.0, is_int=False)]
    seen = []

    def fake_chat(messages, system=None, schema=None, effort=None, **kw):
        seen.append(messages[-1]['content'])
        return json.dumps({'rationale': 'r', 'candidates': [{'W_IN': 6.0}]})

    state = {'best': 1.0, 'best_x': None, 'cancel': False, 'dispatched': 0}
    asked = {}

    def run_batch(points, with_metrics=False):
        asked['with_metrics'] = with_metrics
        state['dispatched'] += len(points)
        costs = [1.4] * len(points)
        return (costs, [dict(_M)] * len(points)) if with_metrics else costs

    llm_sizing.run_loop('amp_hoilee_affc', variables, None, state=state,
                        run_batch=run_batch, budget=3, workers=1,
                        chat=fake_chat)
    assert asked['with_metrics'] is True
    later = '\n'.join(seen[1:])            # the feedback turns
    assert 'DC gain 62.1 dB' in later and 'want >= 100' in later


def test_the_loop_shows_the_operating_point_only_when_the_best_improves(
        monkeypatch):
    """One extra ngspice run per improvement, not per round — a plateaued
    search must stop paying for a picture that has not changed.  And it is
    deliberately not charged to the evaluation budget: the budget bounds
    the search, this observes a point the search already paid for."""
    from app.core import llm_sizing
    from app.core.sizing.spec import VarSpec
    variables = [
        VarSpec(name='W_IN', default=5.0, lo=1.0, hi=10.0, is_int=False)]
    captured = []
    # the mechanism, not the default — see the test below for that
    monkeypatch.setattr(llm_sizing, 'LOOP_OPERATING_POINTS', True)
    monkeypatch.setattr(llm_sizing, '_operating_point_note',
                        lambda c, v: captured.append(v) or 'OP-TEXT-HERE')
    seen = []

    def fake_chat(messages, **kw):
        seen.append(messages[-1]['content'])
        return json.dumps({'rationale': 'r', 'candidates': [{'W_IN': 6.0}]})

    # costs improve, then plateau
    costs = iter([2.0, 1.0, 1.0, 1.0])
    state = {'best': None, 'best_x': None, 'best_m': {'dcgain': 60.0},
             'cancel': False, 'dispatched': 0}

    def run_batch(points, with_metrics=False):
        state['dispatched'] += len(points)
        c = next(costs, 1.0)
        if state['best'] is None or c < state['best']:
            state['best'], state['best_x'] = c, {'W_IN': 6.0}
        out = [c] * len(points)
        return (out, [{'dcgain': 60.0}] * len(points)) if with_metrics else out

    llm_sizing.run_loop('amp_hoilee_affc', variables, None, state=state,
                        run_batch=run_batch, budget=4, workers=1,
                        chat=fake_chat)
    body = '\n'.join(seen)
    assert 'OP-TEXT-HERE' in body, 'the operating point never reached a prompt'
    # improved twice (2.0 then 1.0); the plateau rounds must not re-capture
    assert len(captured) <= 2, f'captured {len(captured)} times on 2 improvements'
    assert all(v == {'W_IN': 6.0} for v in captured)   # the *best* point


def test_a_failed_operating_point_capture_costs_only_its_context(monkeypatch):
    """ngspice can fail on a point the search accepted.  That must cost the
    round its extra context, not the round."""
    from app.core import llm_sizing
    from app.core.sizing import evaluation as ev

    def boom(circuit, values, slot=0):
        raise RuntimeError('ngspice went away')

    monkeypatch.setattr(ev, 'operating_points', boom)
    assert llm_sizing._operating_point_note('amp_hoilee_affc',
                                            {'W_IN': 1.0}) == ''
    assert llm_sizing._operating_point_note('amp_hoilee_affc', None) == ''


def test_the_loop_does_not_show_operating_points_by_default():
    """Off on measurement, after being on for a measurement.

    Turning it on rested on a cold-start result — shown the operating point
    the model targets the implicated variables 10-12x harder.  Two later
    runs undid it: those devices are structurally out of saturation on this
    circuit (same seven across the whole design space, so unfixable by
    sizing), and in the loop the targeting collapses to exactly zero after
    four rounds once real cost feedback arrives.  What is left is four
    rounds down a dead end.
    """
    from app.core import llm_sizing
    assert llm_sizing.LOOP_OPERATING_POINTS is False
    # the capture itself stays available and unconditional
    assert callable(llm_sizing._operating_point_note)


# ── the finish: one diagnosis, then a line search along it ───────────────────
def _finish_harness(best_w, cost_of, budget):
    """A one-variable circuit with a fake optimizer state, wired the way
    sizing.optimize wires the real one (budget cap, best tracking)."""
    from app.core.sizing.spec import VarSpec
    variables = [VarSpec(name='W_IN', default=5.0, lo=0.0, hi=20.0,
                         is_int=False)]
    state = {'best': cost_of(best_w), 'best_x': {'W_IN': best_w},
             'best_m': {'dcgain': 60.0}, 'cancel': False,
             'dispatched': 0, 'cap': budget}
    evaluated = []

    def run_batch(points, with_metrics=False):
        allowed = max(0, budget - state['dispatched'])
        out = [float('inf')] * len(points)
        for i, p in enumerate(points[:allowed]):
            w = float(p[0]) * 20.0
            evaluated.append(w)
            out[i] = cost_of(w)
            if out[i] < state['best']:
                state['best'], state['best_x'] = out[i], {'W_IN': w}
        state['dispatched'] += min(allowed, len(points))
        return (out, [None] * len(points)) if with_metrics else out

    return variables, state, run_batch, evaluated


def test_finish_treats_the_proposal_as_a_direction_and_lands():
    """Measured on the reference amplifier: the model picks the right
    variables and the wrong amount, every time.  So the proposal is a
    direction, and the app walks it.  Here the optimum is at 7.3, the
    search stopped at 5, the model says 9 — and the finish has to land
    within a tenth without spending more than its reserve."""
    from app.core import llm_sizing
    cost_of = lambda w: abs(w - 7.3)
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, cost_of, llm_sizing.FINISH_EVALS)

    def fake_chat(messages, **kw):
        return json.dumps({'rationale': 'widen the input pair',
                           'candidates': [{'W_IN': 9.0}]})

    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=llm_sizing.FINISH_EVALS, workers=4,
                                 chat=fake_chat)
    assert state['best'] < 0.1, (state, evaluated)
    assert state['dispatched'] <= llm_sizing.FINISH_EVALS
    assert len(evaluated) == len(set(round(w, 9) for w in evaluated)), \
        'a point was paid for twice'
    assert 'round 1: 1 proposals; best moved 1 of 1 variables (W_IN)' in note
    assert 'cost 2.3000 ->' in note and 'widen the input pair' in note


def test_finish_uses_the_archive_around_the_best_point(monkeypatch,
                                                       tmp_path):
    """With archived evaluations around the search's best, the finish
    tells the model what each missed target responds to, and centres
    its first scan on the amount the local fit predicts: here dcgain
    rises 17.4 dB per unit of W_IN and needs 100, so the fit says 7.3
    and the first scan already lands there instead of walking a fixed
    grid."""
    from app.core import llm_sizing, sizing
    monkeypatch.setattr(sizing.archive, 'archive_dir', lambda: tmp_path)
    monkeypatch.setattr(llm_sizing, 'FINISH_SENSITIVITY', True)   # off by default
    cost_of = lambda w: abs(w - 7.3)
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, cost_of, llm_sizing.FINISH_EVALS)
    for w in np.linspace(4.0, 6.0, 12):
        sizing.archive.record('amp_hoilee_affc', {'W_IN': float(w)},
                              {'dcgain': 60.0 + 17.4 * (w - 5.0)})
    prompts = []

    def fake_chat(messages, **kw):
        prompts.append(messages[-1]['content'])
        return json.dumps({'rationale': 'widen', 'candidates': [{'W_IN': 9.0}]})

    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=llm_sizing.FINISH_EVALS, workers=4,
                                 chat=fake_chat)
    assert 'per +10% of range' in prompts[0] and 'W_IN' in prompts[0]
    assert 'dcgain (now 60' in prompts[0]
    assert 'local fit on 10 points' in note and 'scan centred at' in note
    # the proposal is 4 units away; the fit wants 2.3 of them (alpha
    # 0.575, grid 0.6): the first scan's closest point is within the
    # grid's 0.4 units of 7.3, where the fixed grid's closest is 7.0
    first = evaluated[:len(llm_sizing.FINISH_ALPHA_SPREAD) + 1]
    assert min(abs(w - 7.3) for w in first) <= 0.2, first
    assert state['best'] < 0.1
    # without the switch the old grid is walked
    monkeypatch.setattr(llm_sizing, 'FINISH_SENSITIVITY', False)
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, cost_of, llm_sizing.FINISH_EVALS)
    prompts.clear()
    llm_sizing.run_finish('amp_hoilee_affc', variables, None, state=state,
                          run_batch=run_batch, budget=llm_sizing.FINISH_EVALS,
                          workers=4, chat=fake_chat)
    assert 'per +10% of range' not in prompts[0]
    assert sorted(round(w, 6) for w in evaluated[:6]) == \
        [round(5 + a * 4, 6) for a in llm_sizing.FINISH_ALPHAS]


def test_finish_asks_several_times_and_keeps_the_best_line():
    """The model's answer is not repeatable call to call (two sonnet runs
    from one point: 37% and nothing), so a round asks three times and
    searches along each.  Here the three answers are wrong, right and
    timid; the right one has to win, and the timid one must not be
    paid for twice."""
    from itertools import cycle
    from app.core import llm_sizing
    cost_of = lambda w: abs(w - 7.3)
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, cost_of, llm_sizing.FINISH_EVALS)
    answers = cycle([3.0, 9.0, 6.0])

    def fake_chat(messages, **kw):
        w = next(answers)
        return json.dumps({'rationale': f'try {w}',
                           'candidates': [{'W_IN': w}]})

    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=llm_sizing.FINISH_EVALS, workers=4,
                                 chat=fake_chat)
    assert state['best'] < 0.1
    assert '3 proposals' in note and 'try 9.0' in note
    assert state['dispatched'] <= llm_sizing.FINISH_EVALS
    assert len(evaluated) == len(set(round(w, 9) for w in evaluated))


def test_finish_rounds_continue_from_the_new_best_with_history():
    """A second round is a second opinion, not a repeat: it starts from
    the first round's best and the model is shown what was proposed and
    what the search made of it.  Re-running the converged search would
    return the same point, which is why the continuation is another
    question."""
    from app.core import llm_sizing
    cost_of = lambda w: abs(w - 7.3)
    budget = llm_sizing.finish_reserve()
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, cost_of, budget)
    prompts = []

    k = llm_sizing.FINISH_PROPOSALS

    def fake_chat(messages, **kw):
        prompts.append(messages[-1]['content'])
        w = 6.0 if len(prompts) <= k else 9.0       # timid, then bolder
        return json.dumps({'rationale': f'try {w}',
                           'candidates': [{'W_IN': w}]})

    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=budget, workers=4, chat=fake_chat)
    assert 'round 1' in prompts[k] and 'cost 2.3000 ->' in prompts[k] \
        and 'Do not repeat' in prompts[k]
    assert 'round 1' not in prompts[0]
    assert 'W_IN: 5' not in prompts[k]            # round 2 starts further on
    assert state['best'] < 0.1
    assert note.count('round ') >= 2
    assert state['dispatched'] <= budget


def test_finish_keeps_asking_after_a_failed_round_unless_told_not_to(
        monkeypatch):
    """A first measurement said the round after a failed round always
    fails; asked anyway, later runs improved after a failure three times
    in six, once by 44%.  So a failed round no longer ends the finish by
    default; FINISH_STOP_ON_STALL restores the old behaviour."""
    from app.core import llm_sizing
    budget = llm_sizing.finish_reserve()
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, lambda w: abs(w - 7.3), budget)
    calls = []
    fake_chat = lambda messages, **kw: calls.append(1) or json.dumps(
        {'rationale': 'wrong way', 'candidates': [{'W_IN': 3.0}]})
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=budget, workers=4, chat=fake_chat)
    assert len(calls) == llm_sizing.FINISH_ROUNDS * llm_sizing.FINISH_PROPOSALS
    assert note.count('no point along any improved') == llm_sizing.FINISH_ROUNDS
    assert state['best'] == 2.3                   # the search result survives
    # a failed line is scanned once and never refined toward the start,
    # and the same wrong proposal is not paid for again in later rounds
    assert len(evaluated) <= len(llm_sizing.FINISH_ALPHAS)

    monkeypatch.setattr(llm_sizing, 'FINISH_STOP_ON_STALL', True)
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, lambda w: abs(w - 7.3), budget)
    calls.clear()
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=budget, workers=4, chat=fake_chat)
    assert len(calls) == llm_sizing.FINISH_PROPOSALS
    assert note.count('round ') == 1


def test_finish_stops_at_zero_and_leaves_the_rest_of_the_budget():
    """Once every target is met there is nothing to ask."""
    from app.core import llm_sizing
    budget = llm_sizing.finish_reserve()
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, lambda w: 0.0 if abs(w - 7.0) < 1e-9 else 1.0, budget)
    calls = []
    fake_chat = lambda messages, **kw: calls.append(1) or json.dumps(
        {'rationale': '', 'candidates': [{'W_IN': 9.0}]})   # 0.5x hits 7
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=budget, workers=4, chat=fake_chat)
    assert state['best'] == 0.0 and len(calls) == llm_sizing.FINISH_PROPOSALS
    assert state['dispatched'] <= len(llm_sizing.FINISH_ALPHAS)
    assert '-> 0.0000' in note


def test_finish_judges_change_against_what_the_model_saw():
    """The model is shown four significant figures and echoes them back.
    Compared with the exact values every echo is a change (the first
    experiment reported 23 of 33 variables moved, real count 2-3); the
    baseline for "what changed" is the prompt."""
    from app.core import llm_sizing
    variables, state, run_batch, evaluated = _finish_harness(
        5.123456789, lambda w: 1.0, 10)
    fake_chat = lambda messages, **kw: json.dumps(
        {'rationale': '', 'candidates': [{'W_IN': 5.123}]})
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=10, workers=1, chat=fake_chat)
    assert 'proposed the current sizing' in note
    assert evaluated == []


def test_finish_spends_nothing_when_there_is_nothing_to_do():
    from app.core import llm_sizing
    variables, state, run_batch, evaluated = _finish_harness(
        5.0, lambda w: 0.0, 10)
    calls = []
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=10, workers=1,
                                 chat=lambda *a, **k: calls.append(1))
    assert 'already met' in note and not calls and not evaluated

    variables, state, run_batch, evaluated = _finish_harness(
        5.0, lambda w: 1.0, 10)
    note = llm_sizing.run_finish('amp_hoilee_affc', variables, None,
                                 state=state, run_batch=run_batch,
                                 budget=10, workers=1,
                                 chat=lambda *a, **k: 'no json here')
    assert 'no usable diagnosis' in note and not evaluated
    assert state['best'] == 1.0                 # the search result survives


def test_finish_asks_one_question_at_the_provider_default_effort():
    """One call, its quality is the whole point: effort is the provider's
    default (the loop runs at 'low'), the schema allows exactly one
    candidate, and the prompt says the app will search along the answer —
    so the model spends its thinking on which variables, not how much."""
    from app.core import llm_sizing
    variables, state, run_batch, _ = _finish_harness(5.0, lambda w: 1.0, 10)
    seen = {}

    def fake_chat(messages, **kw):
        seen.update(kw, prompt=messages[-1]['content'])
        return json.dumps({'rationale': 'r', 'candidates': [{'W_IN': 6.0}]})

    llm_sizing.run_finish('amp_hoilee_affc', variables, None, state=state,
                          run_batch=run_batch, budget=10, workers=1,
                          chat=fake_chat)
    assert seen['effort'] is llm_sizing.FINISH_EFFORT is None
    assert seen['schema']['properties']['candidates']['maxItems'] == 1
    assert 'search along it' in seen['prompt']
    assert 'W_IN: 5' in seen['prompt']              # the point it starts from
    assert 'ONE sizing' in seen['prompt']
