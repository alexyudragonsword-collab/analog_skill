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
