"""MCP stdio server exposing one tool: evaluate a batch of sizings.

Claude Code spawns this; it forwards every call to the EvalService running
inside Analog Studio (address and token arrive in the environment), so the
budget, the Cancel button and the ngspice scratch slots stay where they
already work.

JSON-RPC 2.0 over newline-delimited stdin/stdout, written by hand rather
than against an SDK: `llm_client` is standard-library only so the frozen
bundles gain no dependency, and the three methods a tool server needs are
smaller than the argument for adding one.

Run as:  python -m app.core.mcp_eval_server
"""

import json
import os
import socket
import sys

ENV_ADDR = 'ANALOG_EVAL_ADDR'        # "host:port"
ENV_TOKEN = 'ANALOG_EVAL_TOKEN'

PROTOCOL_VERSION = '2024-11-05'

TOOL_NAME = 'evaluate_sizings'


def _tool_schema(names: list[str], lo: list[float], hi: list[float]) -> dict:
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['sizings'],
        'properties': {
            'sizings': {
                'type': 'array', 'minItems': 1, 'maxItems': 8,
                'description': 'One or more complete sizings to simulate. '
                               'They run in parallel, so asking for several '
                               'at once costs little more than one.',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': list(names),
                    'properties': {
                        n: {'type': 'number', 'minimum': a, 'maximum': b}
                        for n, a, b in zip(names, lo, hi, strict=True)},
                },
            },
        },
    }


def _ask_app(points: list[list[float]]) -> dict:
    """One request to the app.  A fresh connection per call: these are
    seconds apart and a held socket only adds ways to fail."""
    host, _, port = os.environ.get(ENV_ADDR, '').rpartition(':')
    if not host or not port.isdigit():
        return {'ok': False, 'error': f'{ENV_ADDR} not set'}
    try:
        with socket.create_connection((host, int(port)), timeout=900) as s:
            s.sendall((json.dumps({
                'token': os.environ.get(ENV_TOKEN, ''),
                'points': points}) + '\n').encode('utf-8'))
            buf = b''
            while not buf.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode('utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'error': f'cannot reach Analog Studio: {exc}'}


class Server:
    """The three JSON-RPC methods a tool server has to answer."""

    def __init__(self, names, lo, hi, ask=_ask_app):
        self.names, self.lo, self.hi, self._ask = names, lo, hi, ask

    def handle(self, msg: dict) -> dict | None:
        """Return the reply, or None for a notification."""
        method, mid = msg.get('method'), msg.get('id')
        if method == 'initialize':
            return self._ok(mid, {
                'protocolVersion': PROTOCOL_VERSION,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'analog-studio-eval',
                               'version': '1.0'}})
        if method == 'tools/list':
            return self._ok(mid, {'tools': [{
                'name': TOOL_NAME,
                'description':
                    'Simulate one or more candidate sizings with ngspice and '
                    'return each one\'s cost and per-metric results. Lower '
                    'cost is better; 0 means every target is met. The '
                    'evaluation budget is finite and enforced by the app — '
                    'when it is spent, calls return spent=true and the '
                    'search is over.',
                'inputSchema': _tool_schema(self.names, self.lo, self.hi),
            }]})
        if method == 'tools/call':
            return self._ok(mid, self._call(msg.get('params') or {}))
        if mid is None:                       # notification: nothing to say
            return None
        return {'jsonrpc': '2.0', 'id': mid,
                'error': {'code': -32601, 'message': f'no method {method}'}}

    def _call(self, params: dict) -> dict:
        if params.get('name') != TOOL_NAME:
            return self._text(f'no tool named {params.get("name")}',
                              is_error=True)
        sizings = (params.get('arguments') or {}).get('sizings') or []
        try:
            points = [[float(s[n]) for n in self.names] for s in sizings]
        except (KeyError, TypeError, ValueError) as exc:
            return self._text(
                f'each sizing needs every variable as a number ({exc})',
                is_error=True)
        reply = self._ask(points)
        if not reply.get('ok'):
            return self._text(reply.get('error', 'evaluation failed'),
                              is_error=True)
        return self._text(json.dumps({'results': reply['results']}))

    @staticmethod
    def _ok(mid, result):
        return {'jsonrpc': '2.0', 'id': mid, 'result': result}

    @staticmethod
    def _text(text: str, is_error: bool = False) -> dict:
        return {'content': [{'type': 'text', 'text': text}],
                'isError': is_error}


def serve(stdin=None, stdout=None, server: Server | None = None) -> int:
    """Read messages until stdin closes.  Never raises — a tool server that
    dies mid-conversation leaves the model waiting on nothing."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if server is None:
        spec = json.loads(os.environ.get('ANALOG_EVAL_VARS', '{}'))
        server = Server(spec.get('names', []), spec.get('lo', []),
                        spec.get('hi', []))
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = server.handle(json.loads(line))
        except Exception as exc:                      # noqa: BLE001
            reply = {'jsonrpc': '2.0', 'id': None,
                     'error': {'code': -32603, 'message': str(exc)}}
        if reply is not None:
            stdout.write(json.dumps(reply) + '\n')
            stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(serve())
