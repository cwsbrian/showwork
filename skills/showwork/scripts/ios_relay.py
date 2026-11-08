"""Loopback-only, authenticated iOS Simulator frame and input relay."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import signal
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit

MAX_FRAME = 8 * 1024 * 1024


class MjpegFramer:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        frames = []
        while True:
            start = self.buffer.find(b'\xff\xd8')
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer.endswith(b'\xff') else b''
                return frames
            del self.buffer[:start]
            end = self.buffer.find(b'\xff\xd9', 2)
            size = end + 2 if end >= 0 else len(self.buffer)
            if size > MAX_FRAME:
                self.buffer.clear()
                raise ValueError('JPEG exceeds 8 MiB')
            if end < 0:
                return frames
            frames.append(bytes(self.buffer[:size]))
            del self.buffer[:size]


def jpeg_dimensions(jpeg: bytes) -> tuple[int, int]:
    if not jpeg.startswith(b'\xff\xd8'):
        raise ValueError('Invalid JPEG')
    pos = 2
    while pos < len(jpeg):
        if jpeg[pos] != 255:
            raise ValueError('Invalid JPEG marker')
        while pos < len(jpeg) and jpeg[pos] == 255:
            pos += 1
        if pos >= len(jpeg): break
        marker = jpeg[pos]
        pos += 1
        if marker in (0xD9, 0xDA): break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7: continue
        if pos + 2 > len(jpeg): break
        size = int.from_bytes(jpeg[pos:pos+2], 'big')
        if size < 2 or pos + size > len(jpeg): break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if size < 8: break
            h = int.from_bytes(jpeg[pos+3:pos+5], 'big')
            w = int.from_bytes(jpeg[pos+5:pos+7], 'big')
            if w and h: return w, h
            break
        pos += size
    raise ValueError('JPEG has no dimensions')


class RelayState:
    def __init__(self, udid: str, token: str, origins: set[str], points_width: int, points_height: int, idb_path: str):
        if not token or min(points_width, points_height) <= 0:
            raise ValueError('Token and positive point dimensions required')
        self.udid, self.token, self.origins, self.idb_path = udid, token, origins, idb_path
        self.portrait = sorted((points_width, points_height))
        self.points_width, self.points_height = points_width, points_height
        self.condition = threading.Condition()
        self.input_lock = threading.Lock()
        self.frame, self.seq, self.reason = None, 0, None

    def publish_frame(self, jpeg: bytes):
        if len(jpeg) > MAX_FRAME: raise ValueError('JPEG exceeds 8 MiB')
        w, h = jpeg_dimensions(jpeg)
        with self.condition:
            if self.reason is not None: return
            self.points_width, self.points_height = self.portrait if w <= h else self.portrait[::-1]
            self.frame = jpeg
            self.seq += 1
            self.condition.notify_all()

    def finish(self, reason: str):
        with self.condition:
            if self.reason is None: self.reason = reason
            self.condition.notify_all()

    def run_input(self, action: dict) -> None:
        with self.input_lock:
            if not isinstance(action, dict): raise ValueError('Action must be an object')
            with self.condition:
                if self.reason is not None: raise RuntimeError('Stream ended')
                width, height = self.points_width, self.points_height
            def number(key, limit):
                value = action.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)) or not 0 <= value < limit:
                    raise ValueError('Invalid coordinate')
                return str(value)
            kind = action.get('type')
            if kind == 'tap': args = ['tap', number('x', width), number('y', height)]
            elif kind == 'swipe':
                duration = action.get('duration')
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.05 <= duration <= 2: raise ValueError('Invalid swipe duration')
                args = ['swipe', number('x1', width), number('y1', height), number('x2', width), number('y2', height), '--duration', str(duration)]
            elif kind == 'text':
                value = action.get('text')
                if not isinstance(value, str) or len(value) > 2048 or '\x00' in value: raise ValueError('Invalid text')
                args = ['text', value]
            elif kind == 'button' and action.get('button') == 'HOME': args = ['button', 'HOME']
            else: raise ValueError('Unknown action')
            try:
                subprocess.run([self.idb_path, 'ui', *args, '--udid', self.udid], timeout=5, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                self.finish('Input command failed')
                raise RuntimeError('Input command failed') from None


def make_server(state: RelayState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self, status, body=b'', content_type='application/json', headers=None):
            self.send_response(status)
            origin = self.headers.get('Origin')
            if origin in state.origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Expose-Headers', 'X-Frame-Seq, X-Points-Width, X-Points-Height')
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
                    payload = {'ready': state.frame is not None and state.reason is None, 'points_width':state.points_width, 'points_height':state.points_height}
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
                headers = {'X-Frame-Seq':state.seq, 'X-Points-Width':state.points_width, 'X-Points-Height':state.points_height}
            self.respond(200, frame, 'image/jpeg', headers)

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


def stop_child(child):
    if child.poll() is None:
        try: child.terminate()
        except ProcessLookupError: pass
    try: child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: child.kill()
        except ProcessLookupError: pass
        child.wait(timeout=5)


def consume_stream(state, child):
    framer = MjpegFramer()
    try:
        while chunk := child.stdout.read1(65536) if hasattr(child.stdout, 'read1') else child.stdout.read(65536):
            for frame in framer.feed(chunk): state.publish_frame(frame)
    except (OSError, ValueError):
        state.finish('Invalid or interrupted video stream')
    finally:
        state.finish('Video stream ended')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve'])
    for arg in ('udid', 'session', 'idb-path'): parser.add_argument('--' + arg, required=True)
    for arg in ('points-width', 'points-height'): parser.add_argument('--' + arg, required=True, type=int)
    args = parser.parse_args()
    state = RelayState(args.udid, os.environ.get('SHOWWORK_IOS_TOKEN', ''), set(os.environ.get('SHOWWORK_IOS_ORIGINS', 'tauri://localhost,http://localhost:1420').split(',')), args.points_width, args.points_height, args.idb_path)
    child = subprocess.Popen([args.idb_path, 'video-stream', '--format', 'mjpeg', '--fps', '10', '--scale-factor', '0.5', '--udid', args.udid], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    server = make_server(state)
    stopped = threading.Event()
    def stop(*_):
        stopped.set()
        state.finish('Relay stopped')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    reader = threading.Thread(target=consume_stream, args=(state, child), daemon=True)
    reader.start()
    serving = None
    try:
        with state.condition:
            state.condition.wait_for(lambda: state.frame is not None or state.reason is not None, timeout=15)
            if state.frame is None or state.reason is not None: return 1
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        print(json.dumps({'port': server.server_port}), flush=True)
        while not stopped.wait(0.1):
            if state.reason is not None:
                # Give pending frame requests a chance to observe 410 before exit.
                stopped.wait(0.2)
                break
    finally:
        state.finish('Relay stopped')
        # Main owns all process waits: a blocked reader cannot prevent kill escalation.
        try:
            stop_child(child)
        finally:
            if serving is not None: server.shutdown()
            server.server_close()
            reader.join(timeout=6)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
