"""Tests for the LLM-assisted sizing features — fully offline: the single
HTTP chokepoint (llm_client._post_json) or llm_client.chat is faked."""

import json
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


def test_run_cli_turns_every_failure_into_a_readable_llm_error(monkeypatch,
                                                               tmp_path):
    """_run_cli is the chokepoint the rest of the suite fakes, so it is the
    one place these have to be handled for real.  A tab shows the last line
    of the error, so a traceback or an empty string there is useless."""
    import subprocess
    from app.core import claude_locator
    monkeypatch.setattr(claude_locator, '_no_window', dict)

    def fails(exc):
        def run(*a, **kw):
            raise exc
        return run

    monkeypatch.setattr(subprocess, 'run',
                        fails(subprocess.TimeoutExpired('claude', 90)))
    with pytest.raises(llm_client.LLMError, match='within 90s'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    monkeypatch.setattr(subprocess, 'run', fails(OSError('no such file')))
    with pytest.raises(llm_client.LLMError, match='could not run'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    done = type('R', (), {'stdout': '', 'stderr': 'not logged in\n',
                          'returncode': 1})
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: done())
    with pytest.raises(llm_client.LLMError, match='not logged in'):
        llm_client._run_cli(['claude'], 'hi', 90.0)

    junk = type('R', (), {'stdout': 'Welcome to Claude!', 'stderr': '',
                          'returncode': 0})
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: junk())
    with pytest.raises(llm_client.LLMError, match='non-JSON'):
        llm_client._run_cli(['claude'], 'hi', 90.0)


def test_run_cli_runs_in_an_empty_directory(monkeypatch):
    """Belt to the disallowed-tools braces: if a file tool ever does get
    through, there is nothing where it lands to read."""
    import subprocess
    from pathlib import Path
    from app.core import claude_locator
    monkeypatch.setattr(claude_locator, '_no_window', dict)
    seen = {}

    def run(argv, **kw):
        seen['cwd'] = kw['cwd']
        seen['listing'] = list(Path(kw['cwd']).iterdir())
        return type('R', (), {'stdout': '{"result": "x"}', 'stderr': '',
                              'returncode': 0})()

    monkeypatch.setattr(subprocess, 'run', run)
    assert llm_client._run_cli(['claude'], 'hi', 90.0) == {'result': 'x'}
    assert seen['listing'] == []
    assert not Path(seen['cwd']).exists()      # and cleaned up afterwards


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
