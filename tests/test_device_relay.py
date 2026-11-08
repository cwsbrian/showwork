import importlib
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/showwork/scripts'))
relay = importlib.import_module('device_relay')


class FakeState:
    token = 'secret'
    origins = {'tauri://localhost'}
    content_type = 'image/png'
    width_header = 'X-Pixels-Width'
    height_header = 'X-Pixels-Height'

    def __init__(self):
        self.condition = threading.Condition()
        self.frame, self.seq, self.reason = b'png-frame', 1, None
        self.actions = []

    def frame_dimensions(self):
        return 1080, 1920

    def health_payload(self):
        return {'ready': self.frame is not None and self.reason is None,
                'pixels_width': 1080, 'pixels_height': 1920}

    def run_input(self, action):
        self.actions.append(action)
        if action != {'type': 'tap', 'x': 1, 'y': 2}:
            raise ValueError('Invalid action')


class DeviceRelayTests(unittest.TestCase):
    def setUp(self):
        self.state = FakeState()
        self.server = relay.make_server(self.state)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method='GET', data=None, **headers):
        headers = {'Origin': 'tauri://localhost', 'X-Session-Token': 'secret', **headers}
        req = Request(f'http://127.0.0.1:{self.server.server_port}{path}',
                      method=method, data=data, headers=headers)
        try:
            response = urlopen(req, timeout=4)
        except HTTPError as error:
            response = error
        self.addCleanup(response.close)
        return response

    def test_preflight_validates_origin_method_and_headers(self):
        headers = {'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'X-Session-Token, Content-Type',
                   'X-Session-Token': ''}
        response = self.request('/input', 'OPTIONS', **headers)
        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'tauri://localhost')
        for bad in ({'Origin': 'http://evil'}, {'Access-Control-Request-Method': 'DELETE'},
                    {'Access-Control-Request-Headers': 'Other'}):
            self.assertEqual(self.request('/input', 'OPTIONS', **{**headers, **bad}).status, 403)
        self.assertEqual(self.state.actions, [])

    def test_png_health_sequence_and_finish(self):
        response = self.request('/health')
        self.assertEqual(json.load(response), self.state.health_payload())
        response = self.request('/frame?after=0')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'png-frame')
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        for header, value in [('X-Frame-Seq', '1'), ('X-Pixels-Width', '1080'), ('X-Pixels-Height', '1920')]:
            self.assertEqual(response.headers[header], value)
            self.assertIn(header, response.headers['Access-Control-Expose-Headers'])
        self.assertEqual(self.request('/frame?after=1').status, 204)
        with self.state.condition:
            self.state.reason = 'Finished'
            self.state.condition.notify_all()
        self.assertEqual(self.request('/frame?after=1').status, 410)

    def test_input_rejects_http_errors_without_dispatch(self):
        for headers in ({'Origin': 'http://evil'}, {'X-Session-Token': 'wrong'}):
            self.assertEqual(self.request('/input', 'POST', b'{}', **headers).status, 403)
        for body in (b'x' * 4097, b'{', b'\xff'):
            self.assertEqual(self.request('/input', 'POST', body).status, 400)
        self.assertEqual(self.request('/input', 'POST', b'{}', **{'Transfer-Encoding': 'chunked'}).status, 400)
        self.assertEqual(self.state.actions, [])
        self.assertEqual(self.request('/input', 'POST', b'{}').status, 400)
        self.assertEqual(self.state.actions, [{}])
        action = {'type': 'tap', 'x': 1, 'y': 2}
        self.assertEqual(self.request('/input', 'POST', json.dumps(action).encode()).status, 200)
        self.assertEqual(self.state.actions[-1], action)
