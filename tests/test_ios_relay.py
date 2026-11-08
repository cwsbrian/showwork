import importlib
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/showwork/scripts'))
relay = importlib.import_module('ios_relay')

def jpeg(w, h):
    return b'\xff\xd8\xff\xc0\x00\x0b\x08' + h.to_bytes(2, 'big') + w.to_bytes(2, 'big') + b'\x01\x01\x11\x00\xff\xd9'

class RelayTests(unittest.TestCase):
    def test_framer_reassembles_two_split_jpegs_and_rejects_over_8_mib(self):
        f = relay.MjpegFramer()
        a, b = jpeg(20, 40), jpeg(40, 20)
        self.assertEqual(f.feed(b'junk' + a[:1]), [])
        self.assertEqual(f.feed(a[1:] + b[:7]), [a])
        self.assertEqual(f.feed(b[7:]), [b])
        with self.assertRaises(ValueError):
            f.feed(b'\xff\xd8' + b'x' * (8 * 1024 * 1024))

    def test_jpeg_dimensions(self):
        self.assertEqual(relay.jpeg_dimensions(jpeg(200, 400)), (200, 400))
        self.assertEqual(relay.jpeg_dimensions(jpeg(400, 200)), (400, 200))
        with self.assertRaises(ValueError): relay.jpeg_dimensions(b'invalid')

    def setUp(self):
        self.state = relay.RelayState('U', 'secret', {'tauri://localhost'}, 402, 874, '/fake/idb')
        self.server = relay.make_server(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method='GET', data=None, **headers):
        h = {'Origin': 'tauri://localhost', 'X-Session-Token': 'secret', **headers}
        req = Request('http://127.0.0.1:%d%s' % (self.server.server_port, path), data=data, headers=h, method=method)
        try: response = urlopen(req, timeout=4)
        except HTTPError as e: response = e
        self.addCleanup(response.close)
        return response

    def test_frame_auth_and_long_poll(self):
        self.assertEqual(self.request('/frame', 'OPTIONS', **{'Access-Control-Request-Headers':'X-Session-Token, Content-Type', 'X-Session-Token':''}).status, 204)
        self.assertEqual(self.request('/frame', **{'X-Session-Token':'bad'}).status, 403)
        self.assertEqual(self.request('/health', Origin='http://evil').status, 403)
        self.assertEqual(self.request('/frame', 'OPTIONS', **{'Access-Control-Request-Headers':'evil'}).status, 403)
        self.state.publish_frame(jpeg(400,200))
        r = self.request('/frame?after=0')
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers['X-Frame-Seq'], '1')
        self.assertEqual(r.headers['X-Points-Width'], '874')
        self.assertEqual(r.headers['X-Points-Height'], '402')
        self.assertEqual(self.request('/frame?after=1').status, 204)
        self.state.publish_frame(jpeg(200,400))
        self.assertEqual(self.request('/frame?after=1').headers['X-Points-Width'], '402')
        self.state.finish('stream exited')
        self.assertEqual(self.request('/frame?after=1').status, 410)

    def test_input_validation_and_argv(self):
        def send(a): return self.request('/input', 'POST', json.dumps(a).encode())
        with patch.object(relay.subprocess, 'run') as run:
            self.assertEqual(send({'type':'tap','x':201,'y':286}).status,200)
            run.assert_called_once_with(['/fake/idb','ui','tap','201','286','--udid','U'], timeout=5, check=True, stdout=relay.subprocess.DEVNULL, stderr=relay.subprocess.DEVNULL)
            for action in ({'type':'tap','x':-1,'y':0}, {'type':'tap','x':402,'y':0}, {'type':'text','text':'a'*2049}, {'type':'swipe','x1':0,'y1':0,'x2':10,'y2':10,'duration':3}):
                self.assertEqual(send(action).status,400)
            self.assertEqual(self.request('/input','POST',b'x'*4097).status,400)
            self.assertEqual(run.call_count,1)

    def test_stream_exit_stops_relay(self):
        child = Mock(stdout=io.BytesIO(jpeg(200,400)))
        child.poll.return_value = None
        relay.consume_stream(self.state, child)
        self.assertIsNotNone(self.state.reason)
        child.terminate.assert_not_called()
        child.wait.assert_not_called()

    def test_shutdown_kills_child_that_keeps_stdout_open(self):
        released = threading.Event()
        blocked = threading.Event()
        signals = {}
        class Stream:
            first = True
            def read1(self, _size):
                if self.first:
                    self.first = False
                    return jpeg(200, 400)
                blocked.set()
                released.wait(10)
                return b''
        child = Mock(stdout=Stream())
        child.poll.return_value = None
        child.wait.side_effect = [relay.subprocess.TimeoutExpired('idb', 5), 0]
        child.kill.side_effect = released.set
        server = Mock()
        server.server_port = 12345
        def ready(*_args, **_kwargs):
            self.assertTrue(blocked.wait(1))
            signals[relay.signal.SIGTERM](relay.signal.SIGTERM, None)
        argv = ['ios_relay.py', 'serve', '--udid', 'U', '--session', 'S', '--points-width', '402', '--points-height', '874', '--idb-path', '/fake/idb']
        try:
            with patch.object(sys, 'argv', argv), patch.dict(relay.os.environ, {'SHOWWORK_IOS_TOKEN':'secret'}), patch.object(relay.subprocess, 'Popen', return_value=child), patch.object(relay, 'make_server', return_value=server), patch.object(relay.signal, 'signal', side_effect=lambda sig, handler: signals.update({sig:handler})), patch('builtins.print', side_effect=ready):
                self.assertEqual(relay.main(), 0)
            child.terminate.assert_called_once()
            child.kill.assert_called_once()
            self.assertEqual(child.wait.call_count, 2)
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()
        finally:
            released.set()
