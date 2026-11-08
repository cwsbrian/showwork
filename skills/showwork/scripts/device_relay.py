"""Shared loopback-only, authenticated device frame and input HTTP transport."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Protocol
from urllib.parse import parse_qs, urlsplit


class RelayHttpState(Protocol):
    """Device state; frame metadata access is guarded by condition by the server."""
    token: str
    origins: set[str]
    condition: threading.Condition
    frame: bytes | None
    seq: int
    reason: str | None
    content_type: str
    width_header: str
    height_header: str

    def frame_dimensions(self) -> tuple[int, int]: ...
    def health_payload(self) -> dict: ...
    def run_input(self, action: dict) -> None: ...


def make_server(state: RelayHttpState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self, status, body=b'', content_type='application/json', headers=None):
            self.send_response(status)
            origin = self.headers.get('Origin')
            if origin in state.origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Expose-Headers', f'X-Frame-Seq, {state.width_header}, {state.height_header}')
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (headers or {}).items(): self.send_header(k, str(v))
            self.end_headers()
            if body: self.wfile.write(body)

        def authorized(self):
            if self.headers.get('Origin') not in state.origins or not hmac.compare_digest(self.headers.get('X-Session-Token', '').encode(), state.token.encode()):
                self.respond(403)
                return False
            return True

        def do_OPTIONS(self):
            requested = {h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers', '').split(',') if h.strip()}
            if self.headers.get('Origin') not in state.origins or not requested <= {'x-session-token', 'content-type'} or self.headers.get('Access-Control-Request-Method', 'GET') not in ('GET', 'POST'):
                return self.respond(403)
            self.respond(204, headers={'Access-Control-Allow-Headers':'X-Session-Token, Content-Type', 'Access-Control-Allow-Methods':'GET, POST, OPTIONS'})

        def do_GET(self):
            if not self.authorized(): return
            url = urlsplit(self.path)
            if url.path == '/health':
                with state.condition:
                    payload = state.health_payload()
                return self.respond(200, json.dumps(payload).encode())
            if url.path != '/frame': return self.respond(404)
            try:
                after = int(parse_qs(url.query).get('after', ['0'])[0])
                if after < 0: raise ValueError()
            except ValueError: return self.respond(400)
            with state.condition:
                state.condition.wait_for(lambda: state.reason is not None or state.seq > after, timeout=2)
                if state.reason is not None: return self.respond(410)
                if state.seq <= after: return self.respond(204)
                frame = state.frame
                width, height = state.frame_dimensions()
                headers = {'X-Frame-Seq':state.seq, state.width_header:width, state.height_header:height}
            self.respond(200, frame, state.content_type, headers)

        def do_POST(self):
            if not self.authorized(): return
            if self.path != '/input': return self.respond(404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096 or self.headers.get('Transfer-Encoding'): raise ValueError()
                self.connection.settimeout(5)
                body = self.rfile.read(size)
                if len(body) != size: raise ValueError()
                state.run_input(json.loads(body))
            except (ValueError, UnicodeError): return self.respond(400)
            except (RuntimeError, OSError): return self.respond(503)
            self.respond(200, b'{"ok":true}')
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)
