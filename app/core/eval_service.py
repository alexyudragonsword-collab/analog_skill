"""A loopback service that lets an external process ask for evaluations.

This exists so the model can drive the search instead of being driven by
it: Claude Code reaches an MCP server (see mcp_eval_server), that server
forwards here, and this runs the evaluation inside the app — which is the
only place that knows the budget, the cancel flag and which scratch slot is
free.

Why not let the MCP server simulate on its own?  It would be a second
process writing into the same ngspice scratch tree, which is the failure
this project already has a rule about, and it would have no way to stop
when the user presses Cancel or the budget runs out.  Keeping evaluation
here means the agentic algorithm reuses the machinery the other four
already use, unchanged.

Loopback only, one random token per run, and the port is never written
anywhere but the child's environment.
"""

import json
import secrets
import socket
import socketserver
import threading
from collections.abc import Callable


class EvalService:
    """Serves newline-delimited JSON requests on 127.0.0.1.

    Request:  {"token": str, "points": [[float, ...], ...]}
    Response: {"ok": true, "results": [{"cost": float,
                                        "metrics": {...} | null}, ...]}
              {"ok": false, "error": str}

    `handler` is called with a list of normalized points and returns
    (costs, metric_dicts) — in practice optimizer.run_batch.
    """

    def __init__(self, handler: Callable):
        self._handler = handler
        self.token = secrets.token_urlsafe(24)
        service = self

        class _Handler(socketserver.StreamRequestHandler):
            # a stuck child must not wedge the run forever
            timeout = 600

            def handle(self):
                for raw in self.rfile:
                    try:
                        req = json.loads(raw.decode('utf-8'))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._send({'ok': False, 'error': 'malformed request'})
                        return
                    # constant-time compare: the token is the only thing
                    # standing between this and any local process
                    if not secrets.compare_digest(
                            str(req.get('token', '')), service.token):
                        self._send({'ok': False, 'error': 'bad token'})
                        return
                    self._send(service._evaluate(req.get('points') or []))

            def _send(self, payload: dict):
                self.wfile.write(
                    (json.dumps(payload) + '\n').encode('utf-8'))
                self.wfile.flush()

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            address_family = socket.AF_INET

        self._srv = _Server(('127.0.0.1', 0), _Handler)
        self.host, self.port = self._srv.server_address[:2]
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True)

    def _evaluate(self, points) -> dict:
        if not isinstance(points, list) or not points:
            return {'ok': False, 'error': 'points must be a non-empty list'}
        try:
            costs, mets = self._handler(points)
        except Exception as exc:                      # noqa: BLE001
            # the child is a language model; it gets a sentence, not a
            # traceback, and the run continues
            return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        return {'ok': True,
                'results': [{'cost': None if c != c or c in (
                    float('inf'), float('-inf')) else float(c),
                    'metrics': m}
                    for c, m in zip(costs, mets, strict=True)]}

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)
        return False
