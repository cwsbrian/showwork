import importlib
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zlib
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/showwork/scripts'))
relay = importlib.import_module('android_relay')


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(w, h, raw=None):
    data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    if raw is None: raw = (b'\x00' * (1 + w * 3)) * h
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', data) +
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class AndroidTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.adb = self.root / 'adb'
        self.adb.write_text('#!' + sys.executable + '\nimport sys,time,os,json,signal\nfrom pathlib import Path\nr=Path(__file__).parent\nwith (r/"calls").open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\nif "exec-out" in sys.argv:\n (r/"pid").write_text(str(os.getpid()))\n mode=(r/"mode").read_text()\n if mode=="stuck":\n  signal.signal(signal.SIGTERM,signal.SIG_IGN)\n  time.sleep(60)\n elif mode=="large": sys.stdout.buffer.write(b"x"*(8*1024*1024+1))\n elif mode=="bad": sys.stdout.buffer.write(b"bad")\n else: sys.stdout.buffer.write((r/"frame").read_bytes())\nelse:\n if (r/"stuck-input").exists():\n  signal.signal(signal.SIGTERM,signal.SIG_IGN)\n  (r/"input-pid").write_text(str(os.getpid()))\n  time.sleep(60)\n else: time.sleep(0.03)\n')
        self.adb.chmod(0o755)
        (self.root/'mode').write_text('ok')
        (self.root/'frame').write_bytes(png(20,40))
        self.state = relay.AndroidRelayState('emulator-5554','secret',{'tauri://localhost'},str(self.adb))

    def test_dimensions_and_rejection(self):
        for w,h in ((20,40),(40,20)):
            self.assertEqual(relay.png_dimensions(png(w,h)),(w,h))
        for data in (b'bad', png(0,40), png(20,40)[:24]):
            with self.assertRaises(ValueError): relay.png_dimensions(data)
        for mode in ('bad','large'):
            (self.root/'mode').write_text(mode)
            with self.assertRaises(ValueError): relay.capture_png(str(self.adb),'emulator-5554',threading.Event())

    def test_malformed_frames_never_publish_or_become_ready(self):
        valid = png(20, 40)
        corrupt = bytearray(valid)
        corrupt[45] ^= 1
        samples = (valid[:33], valid[:-5], bytes(corrupt),
                   valid[:33] + chunk(b'IDAT', b'broken zlib') + chunk(b'IEND', b''),
                   valid[:33] + chunk(b'IDAT', zlib.compress(bytes(2440))[:-2]) + chunk(b'IEND', b''),
                   png(20, 40, b'\x00' * 10), png(20, 40, b'\x05' + b'\x00' * 2439),
                   png(20, 40, b'\x00' * 2441),
                   png(100000, 100000, b''))
        for data in samples:
            with self.subTest(size=len(data)):
                with self.assertRaises(ValueError): self.state.publish_frame(data)
                self.assertEqual(self.state.seq, 0)
                self.assertFalse(self.state.health_payload()['ready'])
                (self.root/'frame').write_bytes(data)
                with self.assertRaises(ValueError):
                    relay.capture_png(str(self.adb), 'emulator-5554', threading.Event())

    def test_malformed_captures_after_good_frame_end_stream(self):
        good = png(20, 40)
        with patch.object(relay, 'capture_png', side_effect=[good, good[:33], good[:-1], good[:33]]) as capture:
            self.state.capture_loop(threading.Event())
        self.assertEqual(capture.call_count, 4)
        self.assertEqual(self.state.seq, 1)
        self.assertIsNone(self.state.frame)
        self.assertFalse(self.state.health_payload()['ready'])
        self.assertEqual(self.state.reason, 'Three consecutive capture failures')

    def test_repeated_malformed_captures_end_without_ready_line(self):
        (self.root/'frame').write_bytes(png(20, 40)[:33])
        proc = subprocess.run([sys.executable, relay.__file__, 'serve', '--serial',
                               'emulator-5554', '--session', 'test', '--adb-path', str(self.adb)],
                              env={**os.environ, 'SHOWWORK_ANDROID_TOKEN': 'secret'},
                              capture_output=True, timeout=4)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b'')
        self.assertEqual(len((self.root/'calls').read_text().splitlines()), 3)

    def test_capture_deadline_kills_and_reaps(self):
        (self.root/'mode').write_text('stuck')
        start=time.monotonic()
        with self.assertRaises((ValueError,RuntimeError)): relay.capture_png(str(self.adb),'emulator-5554',threading.Event())
        self.assertLess(time.monotonic()-start,6)
        with self.assertRaises(ProcessLookupError): os.kill(int((self.root/'pid').read_text()),0)

    def test_rotation_and_inputs(self):
        self.state.publish_frame(png(20,40))
        self.state.run_input({'type':'tap','x':19,'y':39})
        self.state.publish_frame(png(40,20))
        self.assertEqual(self.state.frame_dimensions(),(40,20))
        self.state.run_input({'type':'swipe','x1':0,'y1':0,'x2':39,'y2':19,'duration':0.05})
        calls=[json.loads(x) for x in (self.root/'calls').read_text().splitlines()]
        self.assertEqual(calls,[['-s','emulator-5554','shell','input','tap','19','39'],['-s','emulator-5554','shell','input','swipe','0','0','39','19','50']])
        for v in (True,-1,40,1.5,float('inf')):
            with self.assertRaises(ValueError): self.state.run_input({'type':'tap','x':v,'y':0})
        for v in (True,0.049,2.01,float('nan')):
            with self.assertRaises(ValueError): self.state.run_input({'type':'swipe','x1':0,'y1':0,'x2':1,'y2':1,'duration':v})

    def test_poll_rate_no_overlap_and_three_failures_410(self):
        stop=threading.Event()
        worker=threading.Thread(target=self.state.capture_loop,args=(stop,))
        worker.start()
        time.sleep(0.85)
        stop.set(); worker.join(2)
        captures=(self.root/'calls').read_text().splitlines()
        self.assertLessEqual(len(captures),4)
        self.assertGreaterEqual(len(captures),2)
        (self.root/'mode').write_text('bad')
        state=relay.AndroidRelayState('emulator-5554','secret',{'tauri://localhost'},str(self.adb))
        state.capture_loop(threading.Event())
        server=relay.make_server(state)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(f'http://127.0.0.1:{server.server_port}/frame',headers={'Origin':'tauri://localhost','X-Session-Token':'secret'}))
            self.assertEqual(error.exception.code,410)
            error.exception.close()
        finally: server.shutdown(); server.server_close()

    def test_capture_and_input_are_serialized(self):
        active = 0
        maximum = 0
        starts = []
        lock = threading.Lock()
        def capture(*_):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                starts.append(time.monotonic())
            time.sleep(.05)
            with lock: active -= 1
            return png(20, 40)
        stop = threading.Event()
        with patch.object(relay, 'capture_png', side_effect=capture):
            worker = threading.Thread(target=self.state.capture_loop, args=(stop,))
            worker.start()
            time.sleep(.75)
            stop.set()
            worker.join(2)
        self.assertEqual(maximum, 1)
        self.assertGreaterEqual(len(starts), 2)
        self.assertTrue(all(b-a >= .25 for a,b in zip(starts, starts[1:])))
        self.state = relay.AndroidRelayState('emulator-5554', 'secret', {'tauri://localhost'}, str(self.adb))
        self.state.publish_frame(png(20, 40))
        active = maximum = 0
        children = []
        def command(*args, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(.05)
            with lock: active -= 1
            child = Mock()
            child.wait.return_value = 0
            child.poll.return_value = 0
            children.append(child)
            return child
        with patch.object(relay.subprocess, 'Popen', side_effect=command) as run:
            workers = [threading.Thread(target=self.state.run_input, args=({'type':'tap', 'x':1, 'y':1},)) for _ in range(3)]
            for worker in workers: worker.start()
            for worker in workers: worker.join(2)
            self.assertEqual(run.call_count, 3)
            for child in children: child.wait.assert_any_call(timeout=5)
        self.assertEqual(maximum, 1)

    def test_finish_coordinates_with_input_startup(self):
        self.state.publish_frame(png(20, 40))
        entered, release = threading.Event(), threading.Event()
        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = 0
        def launch(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return child
        errors = []
        def send():
            try: self.state.run_input({'type':'tap', 'x':1, 'y':1})
            except RuntimeError as error: errors.append(error)
        with patch.object(relay.subprocess, 'Popen', side_effect=launch) as popen:
            sender = threading.Thread(target=send)
            sender.start()
            self.assertTrue(entered.wait(2))
            closer = threading.Thread(target=self.state.finish, args=('Relay stopped',))
            closer.start()
            release.set()
            sender.join(2); closer.join(2)
            self.assertFalse(sender.is_alive())
            self.assertFalse(closer.is_alive())
            child.kill.assert_called()
            child.wait.assert_called()
            self.assertIsNone(self.state.input_child)
            with self.assertRaises(RuntimeError): self.state.run_input({'type':'tap', 'x':1, 'y':1})
            self.assertEqual(popen.call_count, 1)

    def test_ready_json_and_png_http_rotation(self):
        proc = subprocess.Popen([sys.executable, relay.__file__, 'serve', '--serial',
                                 'emulator-5554', '--session', 'test', '--adb-path', str(self.adb)],
                                env={**os.environ, 'SHOWWORK_ANDROID_TOKEN': 'secret'},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(3))
            ready = json.loads(proc.stdout.readline())
            self.assertEqual(set(ready), {'port', 'width', 'height'})
            self.assertEqual((ready['width'], ready['height']), (20, 40))
            def request(path):
                return urlopen(Request(f"http://127.0.0.1:{ready['port']}{path}",
                                      headers={'Origin': 'tauri://localhost', 'X-Session-Token': 'secret'}), timeout=3)
            with request('/frame') as response:
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertEqual(response.headers['X-Pixels-Width'], '20')
                seq = int(response.headers['X-Frame-Seq'])
            (self.root/'frame').write_bytes(png(40, 20))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with request(f'/frame?after={seq}') as response:
                    seq = int(response.headers['X-Frame-Seq'])
                    if response.headers['X-Pixels-Width'] == '40':
                        self.assertEqual(response.headers['X-Pixels-Height'], '20')
                        break
            else: self.fail('Rotation was not published')
            with request('/health') as response:
                self.assertEqual(json.load(response), {'ready': True, 'pixels_width': 40, 'pixels_height': 20})
        finally:
            proc.terminate()
            proc.communicate(timeout=3)

    def test_sigterm_reaps_current_input(self):
        (self.root/'stuck-input').touch()
        proc = subprocess.Popen([sys.executable, relay.__file__, 'serve', '--serial',
                                 'emulator-5554', '--session', 'test', '--adb-path', str(self.adb)],
                                env={**os.environ, 'SHOWWORK_ANDROID_TOKEN': 'secret'},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sender = None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(3))
            ready = json.loads(proc.stdout.readline())
            def send():
                try:
                    with urlopen(Request(f"http://127.0.0.1:{ready['port']}/input",
                                         data=b'{"type":"tap","x":1,"y":1}',
                                         headers={'Origin':'tauri://localhost', 'X-Session-Token':'secret'}), timeout=4):
                        pass
                except HTTPError as error: error.close()
                except (OSError, ValueError): pass
            sender = threading.Thread(target=send)
            sender.start()
            deadline = time.monotonic() + 3
            while not (self.root/'input-pid').exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertTrue((self.root/'input-pid').exists())
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=3)
            with self.assertRaises(ProcessLookupError): os.kill(int((self.root/'input-pid').read_text()), 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()
            if sender is not None: sender.join(5)
            if (self.root/'input-pid').exists():
                try: os.kill(int((self.root/'input-pid').read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_sigterm_reaps_current_capture(self):
        (self.root/'mode').write_text('stuck')
        proc=subprocess.Popen([sys.executable,relay.__file__,'serve','--serial','emulator-5554','--session','test','--adb-path',str(self.adb)],env={**os.environ,'SHOWWORK_ANDROID_TOKEN':'secret'},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+3
            while not (self.root/'pid').exists() and time.monotonic()<deadline: time.sleep(.02)
            self.assertTrue((self.root/'pid').exists())
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=3)
            with self.assertRaises(ProcessLookupError): os.kill(int((self.root/'pid').read_text()),0)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()
