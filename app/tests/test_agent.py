"""Tests for the agentic algorithm's plumbing — the loopback evaluation
service and the MCP server that fronts it.

All offline: no Claude Code, no ngspice.  What is being checked is the
contract between the app and a child process it spawns, which is exactly
the part that fails silently — a tool server that dies leaves the model
waiting on nothing, and it says so in its own words rather than raising.
"""

import io
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


import pytest

from app.core import mcp_eval_server as mes
from app.core.eval_service import EvalService

NAMES = ['W_IN', 'L_IN']
LO, HI = [1.0, 0.15], [10.0, 4.0]


def _rpc(server, *messages) -> list[dict]:
    out = io.StringIO()
    mes.serve(io.StringIO('\n'.join(json.dumps(m) for m in messages)),
              out, server)
    return [json.loads(x) for x in out.getvalue().strip().splitlines()
            if x.strip()]


def _srv(ask):
    return mes.Server(NAMES, LO, HI, ask=ask)


# ── the JSON-RPC contract ────────────────────────────────────────────────────
def test_handshake_and_tool_advertisement():
    """A tool server that answers `initialize` wrongly is simply never
    used, and the CLI reports it as a connection failure rather than as a
    protocol error."""
    r = _rpc(_srv(lambda p: {'ok': True, 'results': []}),
             {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
             {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
    assert len(r) == 2, 'the notification must get no reply at all'
    assert r[0]['result']['capabilities'] == {'tools': {}}
    tool = r[1]['result']['tools'][0]
    assert tool['name'] == mes.TOOL_NAME
    items = tool['inputSchema']['properties']['sizings']['items']
    assert items['required'] == NAMES          # every variable, per circuit
    assert items['properties']['W_IN'] == {'type': 'number', 'minimum': 1.0,
                                           'maximum': 10.0}


def test_unknown_method_is_an_error_not_a_crash():
    r = _rpc(_srv(lambda p: None),
             {'jsonrpc': '2.0', 'id': 9, 'method': 'resources/list'})
    assert r[0]['error']['code'] == -32601


def test_a_malformed_message_does_not_kill_the_server():
    """stdin is driven by another program; one bad line must not end the
    conversation, or the model is left waiting on a dead pipe."""
    out = io.StringIO()
    mes.serve(io.StringIO('{not json\n'
                          + json.dumps({'jsonrpc': '2.0', 'id': 1,
                                        'method': 'initialize'}) + '\n'),
              out, _srv(lambda p: None))
    replies = [json.loads(x) for x in out.getvalue().strip().splitlines()]
    assert replies[0]['error']['code'] == -32603      # the bad line
    assert replies[1]['result']['protocolVersion']    # and it kept going


# ── the tool itself ──────────────────────────────────────────────────────────
def test_tool_call_forwards_points_in_variable_order():
    """The model sends a dict; run_batch wants a vector.  Getting the order
    wrong would size the wrong devices and nothing would complain."""
    seen = {}

    def ask(points):
        seen['points'] = points
        return {'ok': True, 'results': [{'cost': 0.5, 'metrics': {'g': 1}}]}

    r = _rpc(_srv(ask), {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                         'params': {'name': mes.TOOL_NAME, 'arguments': {
                             'sizings': [{'L_IN': 0.5, 'W_IN': 3.0}]}}})
    assert seen['points'] == [[3.0, 0.5]]          # W_IN first, as NAMES says
    body = json.loads(r[0]['result']['content'][0]['text'])
    assert body['results'][0]['cost'] == 0.5


def test_an_incomplete_sizing_is_refused_in_a_sentence():
    """The reply goes to a language model, so it has to be readable and it
    has to be flagged isError, not raised."""
    r = _rpc(_srv(lambda p: {'ok': True, 'results': []}),
             {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
              'params': {'name': mes.TOOL_NAME,
                         'arguments': {'sizings': [{'W_IN': 3.0}]}}})
    res = r[0]['result']
    assert res['isError'] is True
    assert 'every variable' in res['content'][0]['text']


def test_an_app_side_failure_reaches_the_model_as_text():
    r = _rpc(_srv(lambda p: {'ok': False, 'error': 'budget spent'}),
             {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
              'params': {'name': mes.TOOL_NAME, 'arguments': {
                  'sizings': [{'W_IN': 3.0, 'L_IN': 0.5}]}}})
    assert r[0]['result']['isError'] is True
    assert 'budget spent' in r[0]['result']['content'][0]['text']


# ── the loopback service ─────────────────────────────────────────────────────
def test_the_token_is_what_stands_between_this_and_any_local_process():
    calls = []

    with EvalService(lambda p: (calls.append(p) or ([1.0] * len(p),
                                                    [None] * len(p)))) as svc:
        os.environ[mes.ENV_ADDR] = f'{svc.host}:{svc.port}'
        os.environ[mes.ENV_TOKEN] = svc.token
        assert mes._ask_app([[3.0, 0.5]])['ok'] is True
        os.environ[mes.ENV_TOKEN] = 'not-the-token'
        bad = mes._ask_app([[3.0, 0.5]])
    assert bad['ok'] is False and 'bad token' in bad['error']
    assert len(calls) == 1, 'the rejected call must never reach the handler'


def test_the_service_listens_on_loopback_only():
    with EvalService(lambda p: ([], [])) as svc:
        assert svc.host == '127.0.0.1'
        assert len(svc.token) >= 20


def test_a_handler_exception_becomes_a_sentence_not_a_traceback():
    def boom(points):
        raise RuntimeError('ngspice vanished')

    with EvalService(boom) as svc:
        os.environ[mes.ENV_ADDR] = f'{svc.host}:{svc.port}'
        os.environ[mes.ENV_TOKEN] = svc.token
        reply = mes._ask_app([[3.0, 0.5]])
    assert reply['ok'] is False
    assert 'ngspice vanished' in reply['error']
    assert 'Traceback' not in reply['error']


def test_a_failed_evaluation_is_null_rather_than_infinity():
    """inf is not JSON.  json.dumps emits `Infinity`, which is not valid
    JSON either, and the child would fail to parse its own reply."""
    with EvalService(lambda p: ([float('inf')], [None])) as svc:
        os.environ[mes.ENV_ADDR] = f'{svc.host}:{svc.port}'
        os.environ[mes.ENV_TOKEN] = svc.token
        reply = mes._ask_app([[3.0, 0.5]])
    assert reply['results'][0]['cost'] is None


# ── the loop's own arithmetic ────────────────────────────────────────────────
def test_agent_loop_denormalizes_and_clips_what_the_model_sends(monkeypatch):
    """The model works in real units; run_batch works in the unit box.  A
    value outside the bounds is clipped rather than refused — the schema
    already asked for in-range numbers, and losing a whole batch to one
    stray digit would cost the run more than the clip does."""
    import numpy as np
    from app.core import llm_sizing
    from app.core.sizing.spec import VarSpec
    variables = [
        VarSpec(name='W_IN', default=5.0, lo=1.0, hi=10.0, is_int=False),
        VarSpec(name='L_IN', default=0.5, lo=0.15, hi=4.0, is_int=False)]
    got = []

    def run_batch(points, with_metrics=False):
        got.extend(np.asarray(p).tolist() for p in points)
        return ([1.0] * len(points), [None] * len(points))

    captured = {}

    def fake_agent(**kw):
        captured.update(kw)
        return 'done'

    state = {'cancel': False}
    llm_sizing.run_agent_loop('amp_hoilee_affc', variables, None,
                              state=state, run_batch=run_batch, budget=10,
                              workers=4, run_agent=fake_agent)
    assert captured['vars_spec'] == {'names': ['W_IN', 'L_IN'],
                                     'lo': [1.0, 0.15], 'hi': [10.0, 4.0]}
    assert captured['addr'].startswith('127.0.0.1:')
    assert captured['token']


# ── stopping an agentic run ──────────────────────────────────────────────────
def test_cancel_kills_the_cli_instead_of_waiting_it_out():
    """An agentic search is one invocation that may be the whole run, so
    without this Cancel does nothing visible until the model happens to
    finish — or until a budget x 25 s timeout expires."""
    import sys
    import threading
    import time
    from app.core import llm_client

    flag = {'stop': False}
    threading.Timer(0.5, lambda: flag.__setitem__('stop', True)).start()
    t0 = time.time()
    with pytest.raises(llm_client.CallCancelled):
        llm_client._run_cli([sys.executable, '-c', 'import time; '
                             'time.sleep(60)'], 'ignored', timeout=120,
                            should_stop=lambda: flag['stop'])
    assert time.time() - t0 < 20, 'it waited for the child instead of killing'


def test_an_uncancelled_call_still_returns_normally():
    """The watcher must not change the ordinary path — every other LLM call
    in the app goes through this same function."""
    import json
    import sys
    from app.core import llm_client

    payload = json.dumps({'result': 'hi', 'is_error': False})
    out = llm_client._run_cli(
        [sys.executable, '-c',
         f'import sys; sys.stdin.read(); print({payload!r})'],
        'the prompt', timeout=60, should_stop=lambda: False)
    assert out == {'result': 'hi', 'is_error': False}


def test_cancel_is_reported_as_a_stop_not_a_failure(monkeypatch):
    """The tabs render an LLMError as a red "Failed:" line, which is the
    wrong thing to show someone who just pressed Cancel."""
    from app.core import claude_locator, llm_client

    def cancelled(*a, **kw):
        raise llm_client.CallCancelled

    monkeypatch.setattr(llm_client, '_run_cli', cancelled)
    monkeypatch.setattr(claude_locator, 'resolve', lambda: '/bin/claude')
    note = llm_client.run_agent(
        prompt='p', system='s', vars_spec={'names': [], 'lo': [], 'hi': []},
        addr='127.0.0.1:1', token='t', timeout=60,
        cfg={'provider': 'claude_code', 'model': 'sonnet', 'base_url': '',
             'api_key': ''})
    assert 'stopped by the user' in note


def test_agent_effort_is_a_stated_choice_not_an_accident(monkeypatch):
    """AGENT_EFFORT is deliberately not LOOP_EFFORT — the measurement that
    justified 'low' for the round-based loop was about 38 shallow turns,
    not about a handful of turns that each read the whole history."""
    from app.core import claude_locator, llm_client, llm_sizing

    seen = {}
    monkeypatch.setattr(llm_client, '_run_cli',
                        lambda argv, prompt, timeout, should_stop=None:
                        seen.update(argv=argv) or {'result': 'ok'})
    monkeypatch.setattr(claude_locator, 'resolve', lambda: '/bin/claude')
    cfg = {'provider': 'claude_code', 'model': 'sonnet', 'base_url': '',
           'api_key': ''}
    kw = dict(prompt='p', system='s',
              vars_spec={'names': [], 'lo': [], 'hi': []},
              addr='127.0.0.1:1', token='t', timeout=60, cfg=cfg)

    llm_client.run_agent(effort=None, **kw)
    assert '--effort' not in seen['argv']
    llm_client.run_agent(effort='medium', **kw)
    assert seen['argv'][seen['argv'].index('--effort') + 1] == 'medium'
    # and the loop's own setting is not silently reused here
    assert llm_sizing.AGENT_EFFORT != llm_sizing.LOOP_EFFORT
