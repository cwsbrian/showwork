import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/showwork/scripts'
sys.path.insert(0, str(SCRIPTS))
import store

SERIAL = 'emulator-5554'

class EmulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'repo'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.adb = self.root / 'adb'
        self.adb.write_text('#!/usr/bin/env python3\nimport sys\nif sys.argv[1:] == ["devices", "-l"]: print("List of devices attached\\nemulator-5554 device product:sdk")\nelif "sys.boot_completed" in sys.argv or "ro.kernel.qemu" in sys.argv: print("1")\nelif "get-state" in sys.argv: print("device")\n')
        self.adb.chmod(0o755)
        self.env = patch.dict(os.environ, {'SHOWWORK_STORE': str(self.root/'store'), 'PATH': str(self.root)+os.pathsep+os.environ['PATH']})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.android = importlib.import_module('android_emulator')

    def sessions(self):
        return store.list_sessions(store.project_identity(self.project)['id'])

    def test_requires_run_and_explicit_valid_serial(self):
        with self.assertRaisesRegex(ValueError, 'start first'):
            self.android.open_emulator(self.project, SERIAL)
        store.start_run(self.project, 'result', 'codex')
        for bad in ['booted', '', '../bad']:
            with self.assertRaises(ValueError): self.android.open_emulator(self.project, bad)
        self.assertEqual(self.sessions(), [])

    def test_missing_adb_and_shutdown_leave_no_record(self):
        store.start_run(self.project, 'result', 'codex')
        with patch.object(self.android.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'adb'): self.android.open_emulator(self.project, SERIAL)
        self.adb.write_text(self.adb.read_text().replace('print("1")', 'print("0")'))
        with self.assertRaisesRegex(ValueError, 'booted'): self.android.open_emulator(self.project, SERIAL)
        self.assertEqual(self.sessions(), [])

    def fake_relay(self, ready=True):
        relay = self.root/'android_relay.py'
        relay.write_text('import json,time\n'+('print(json.dumps({"port":12345,"width":1080,"height":1920}),flush=True)\n' if ready else '')+'time.sleep(60)\n')
        return patch.object(self.android, 'RELAY', relay)

    def test_ready_idempotence_conflict_and_close(self):
        run = store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            s = self.android.open_emulator(self.project, SERIAL)
            self.assertEqual(self.android.open_emulator(self.project, SERIAL)['id'], s['id'])
            self.assertEqual((s['width'],s['height'],s['title']), (1080,1920,SERIAL))
            self.assertNotIn('url', s)
            store.start_run(self.project, 'review', 'codex')
            with self.assertRaisesRegex(ValueError, 'another'): self.android.open_emulator(self.project, SERIAL)
            self.android.close_run(s['project_id'],run['id'])
        self.assertIsNotNone(self.sessions()[0]['ended_at'])
        self.assertEqual(subprocess.check_output([str(self.adb), '-s', SERIAL, 'get-state'], text=True).strip(), 'device')

    def test_dead_claim_recovers_for_same_and_other_run(self):
        for other_run in (False, True):
            with self.subTest(other_run=other_run), self.fake_relay():
                store.start_run(self.project, 'result', 'codex')
                old = self.android.open_emulator(self.project, SERIAL)
                self.android._stop(old['pid'], old['id'])
                if other_run: store.start_run(self.project, 'review', 'codex')
                new = self.android.open_emulator(self.project, SERIAL)
                try:
                    self.assertNotEqual(old['id'], new['id'])
                    self.assertIsNotNone(next(s for s in self.sessions() if s['id'] == old['id'])['ended_at'])
                finally:
                    self.android.close_emulator(new['project_id'], new['id'])

    def test_active_claim_with_reused_pid_is_not_signaled(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            old = self.android.open_emulator(self.project, SERIAL)
            self.android._stop(old['pid'], old['id'])
            old['pid'] = 123456
            store.write_session(old)
            original = self.android.subprocess.run
            def run(args, **kwargs):
                if args[0] == 'ps': return subprocess.CompletedProcess(args, 0, 'python other.py --session wrong', '')
                return original(args, **kwargs)
            with patch.object(self.android.subprocess, 'run', side_effect=run), patch.object(self.android.os, 'kill') as kill:
                new = self.android.open_emulator(self.project, SERIAL)
                kill.assert_not_called()
            try: self.assertNotEqual(old['id'], new['id'])
            finally: self.android.close_emulator(new['project_id'], new['id'])

    def test_preflight_rejects_unusable_devices(self):
        store.start_run(self.project, 'result', 'codex')
        original = self.adb.read_text()
        for state in ('offline', 'unauthorized', 'missing'):
            self.adb.write_text(original.replace('emulator-5554 device', 'emulator-5554 '+state))
            with self.assertRaises(ValueError): self.android.open_emulator(self.project, SERIAL)
            self.assertEqual(self.sessions(), [])
            self.assertFalse(self.android._OWNED)
        self.adb.write_text(original.replace('print("1")', 'print("0")'))
        with self.assertRaises(ValueError): self.android.open_emulator(self.project, SERIAL)
        self.assertEqual(self.sessions(), [])

    def test_physical_device_rejected_even_with_emulator_serial(self):
        store.start_run(self.project, 'result', 'codex')
        self.adb.write_text(self.adb.read_text().replace('or "ro.kernel.qemu" in sys.argv', '').replace('elif "get-state"', 'elif "ro.kernel.qemu" in sys.argv: print("0")\n'+'elif "get-state"'))
        with self.assertRaisesRegex(ValueError, 'emulator'):
            self.android.open_emulator(self.project, SERIAL)
        self.assertEqual(self.sessions(), [])
        self.assertFalse(self.android._OWNED)

    def test_invalid_ready_dimensions_and_changed_marker_reap_relay(self):
        run = store.start_run(self.project, 'result', 'codex')
        relay = self.root/'android_relay.py'
        for payload in ({'port':12345,'width':True,'height':1920}, {'port':0,'width':1080,'height':1920}):
            relay.write_text(f'import time\nprint({json.dumps(payload)!r},flush=True)\ntime.sleep(60)\n')
            with patch.object(self.android, 'RELAY', relay), self.assertRaisesRegex(ValueError, 'ready'):
                self.android.open_emulator(self.project, SERIAL)
            self.assertFalse(self.android._OWNED)
            self.assertEqual(self.sessions(), [])
        marker = store.store_root()/'projects'/run['project_id']/'running'/(run['id']+'.json')
        relay.write_text(f'from pathlib import Path\nimport time,json\nPath({str(marker)!r}).unlink()\n' + 'print(json.dumps(dict(port=12345,width=1080,height=1920)),flush=True)\ntime.sleep(60)\n')
        with patch.object(self.android, 'RELAY', relay), self.assertRaisesRegex(ValueError, 'run ended'):
            self.android.open_emulator(self.project, SERIAL)
        self.assertFalse(self.android._OWNED)
        self.assertEqual(self.sessions(), [])

    def test_never_ready_terminates_without_record(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay(False), patch.object(self.android, 'READY_TIMEOUT', .1):
            with self.assertRaisesRegex(ValueError,'ready'): self.android.open_emulator(self.project, SERIAL)
        self.assertFalse(self.android._OWNED)
        self.assertEqual(self.sessions(), [])

    def test_orphan_reused_pid_is_not_signaled(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            s = self.android.open_emulator(self.project, SERIAL)
            self.android._stop(s['pid'], s['id'])
        s['pid'] = 123456
        store.write_session(s)
        store.finish_run(s['project_id'],store.worktree_key(self.project),'result')
        with patch.object(self.android.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'python other.py --session wrong','')), patch.object(self.android.os,'kill') as kill:
            self.android.close_orphans(s['project_id'])
            kill.assert_not_called()
        self.assertIsNotNone(self.sessions()[0]['ended_at'])

    def test_publish_and_stop_end_relays_without_shutdown(self):
        for action in ('publish', 'stop'):
            store.start_run(self.project, 'result', 'codex')
            with self.fake_relay():
                s = self.android.open_emulator(self.project, SERIAL)
                proc = self.android._OWNED[s['pid']]
                if action == 'publish':
                    store.save_report(self.project, {'mode':'handoff','title':'T','version':'v'}, [], 'result', 'codex')
                else:
                    result = subprocess.run([sys.executable,str(SCRIPTS/'companion.py'),'stop','--project',str(self.project)],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    proc.wait(timeout=10)
                    self.android._OWNED.pop(proc.pid,None)
                    proc.stdout.close()
                self.assertIsNotNone(proc.poll())
                self.assertIsNotNone(next(x for x in self.sessions() if x['id']==s['id'])['ended_at'])
                self.assertEqual(subprocess.check_output([str(self.adb), '-s', SERIAL, 'get-state'], text=True).strip(), 'device')

    def test_cli_real_relay_close_reaps_capture_child(self):
        import time
        child_pid = self.root/'capture.pid'
        original = self.adb.read_text()
        self.adb.write_text(original +
            'elif "screencap" in sys.argv:\n'
            '    import os,time,struct,zlib\n'
            f'    from pathlib import Path\n    p=Path({str(child_pid)!r})\n'
            '    if not p.exists():\n'
            '        hdr=b"IHDR"+struct.pack(">II",1080,1920)+bytes([8,2,0,0,0])\n'
            '        def chunk(kind,data):\n            body=kind+data\n            return struct.pack(">I",len(data))+body+struct.pack(">I",zlib.crc32(body))\n'
            '        sys.stdout.buffer.write(b"\\x89PNG\\r\\n\\x1a\\n"+chunk(b"IHDR",hdr[4:])+chunk(b"IDAT",zlib.compress(bytes(3241)*1920))+chunk(b"IEND",b""))\n'
            '    else:\n        p.write_text(str(os.getpid()))\n        time.sleep(60)\n')
        # First frame succeeds; the next capture remains in flight during close.
        store.start_run(self.project, 'result', 'codex')
        def cli(*args):
            return subprocess.run([sys.executable,str(SCRIPTS/'companion.py'),'emulator',*args,'--project',str(self.project)], capture_output=True,text=True,timeout=30)
        opened = cli('open','--serial',SERIAL)
        self.assertEqual(opened.returncode, 0, opened.stderr)
        output = json.loads(opened.stdout)
        child_pid.touch()
        try:
            deadline = time.monotonic()+5
            while not child_pid.read_text() and time.monotonic()<deadline: time.sleep(.02)
            capture_pid = int(child_pid.read_text())
        finally:
            closed = cli('close','--session',output['session'])
        self.assertEqual(closed.returncode,0,closed.stderr)
        self.assertEqual(json.loads(closed.stdout), {'closed':output['session']})
        with self.assertRaises(ProcessLookupError): os.kill(capture_pid,0)
        self.assertEqual(subprocess.check_output([str(self.adb),'-s',SERIAL,'get-state'],text=True).strip(),'device')

    def test_orphan_cleanup_serializes_snapshot_with_new_start_and_attachment(self):
        from contextlib import contextmanager
        import threading
        project_id = store.project_identity(self.project)['id']
        snapshot = threading.Event()
        release = threading.Event()
        attempted = threading.Event()
        acquired = threading.Event()
        attached = threading.Event()
        failures = []
        sessions = []
        self.addCleanup(lambda: [self.android.close_emulator(project_id, s['id']) for s in sessions])
        original_list = store.list_sessions
        original_lock = store.simulator_lifecycle_lock

        def list_sessions(*args, **kwargs):
            if threading.current_thread().name == 'orphan-cleanup':
                snapshot.set()  # close_orphans has already read the marker snapshot.
                if not release.wait(5): raise RuntimeError('snapshot release timed out')
            return original_list(*args, **kwargs)

        @contextmanager
        def lifecycle_lock():
            if threading.current_thread().name == 'new-attachment': attempted.set()
            with original_lock():
                if threading.current_thread().name == 'new-attachment': acquired.set()
                yield

        def cleanup():
            try: self.android.close_orphans(project_id)
            except Exception as error: failures.append(error)

        def start_and_attach():
            try:
                store.start_run(self.project, 'result', 'codex')
                sessions.append(self.android.open_emulator(self.project, SERIAL))
                attached.set()
            except Exception as error: failures.append(error)

        with self.fake_relay(), patch.object(store, 'list_sessions', side_effect=list_sessions), \
             patch.object(store, 'simulator_lifecycle_lock', side_effect=lifecycle_lock):
            cleaning = threading.Thread(target=cleanup, name='orphan-cleanup')
            starting = threading.Thread(target=start_and_attach, name='new-attachment')
            cleaning.start()
            try:
                self.assertTrue(snapshot.wait(5))
                starting.start()
                self.assertTrue(attempted.wait(5))
                self.assertFalse(acquired.wait(.3), 'start/attach must wait for orphan classification to finish')
            finally:
                release.set()
                cleaning.join(10)
                if starting.ident is not None: starting.join(10)
            try:
                self.assertFalse(cleaning.is_alive() or starting.is_alive())
                self.assertFalse(failures, failures)
                self.assertTrue(attached.is_set())
                self.assertEqual(len(sessions), 1)
                current = next(s for s in self.sessions() if s['id'] == sessions[0]['id'])
                self.assertIsNone(current['ended_at'])
                self.assertTrue(self.android._relay_alive(current['pid'], current['id']))
            finally:
                for session in sessions: self.android.close_emulator(project_id, session['id'])

    def test_completion_waits_for_pending_attachment_then_ends_it(self):
        import threading
        import time
        for action in ('stop', 'publish'):
            with self.subTest(action=action):
                store.start_run(self.project, 'result', 'codex')
                ready = self.root/'waiting'
                release = self.root/'release'
                ready.unlink(missing_ok=True)
                release.unlink(missing_ok=True)
                relay = self.root/'android_relay.py'
                relay.write_text('from pathlib import Path\nimport time,json\n'
                    + f'Path({str(ready)!r}).touch()\n'
                    + f'while not Path({str(release)!r}).exists(): time.sleep(.01)\n'
                    + 'print(json.dumps({"port":12345,"width":1080,"height":1920}),flush=True)\ntime.sleep(60)\n')
                entered = threading.Event()
                completed = threading.Event()
                failures = []
                processes = []
                original_popen = self.android.subprocess.Popen
                def popen(*args, **kwargs):
                    proc = original_popen(*args, **kwargs)
                    if str(relay) in args[0]: processes.append(proc)
                    return proc
                original = store.finish_run
                def finish(*args, **kwargs):
                    entered.set()
                    return original(*args, **kwargs)
                def attach():
                    try: self.android.open_emulator(self.project, SERIAL)
                    except Exception as error: failures.append(error)
                def complete():
                    try:
                        if action == 'publish':
                            store.save_report(self.project, {'mode':'handoff','title':'T','version':'v'}, [], 'result', 'codex')
                        else:
                            project_id = store.project_identity(self.project)['id']
                            run_id = store.finish_run(project_id,store.worktree_key(self.project),'result')
                            store.cleanup_sessions(project_id,run_id)
                    except Exception as error: failures.append(error)
                    finally: completed.set()
                with patch.object(self.android,'RELAY',relay), patch.object(store,'finish_run',side_effect=finish), patch.object(self.android.subprocess,'Popen',side_effect=popen):
                    opening = threading.Thread(target=attach)
                    ending = threading.Thread(target=complete)
                    opening.start()
                    deadline = time.monotonic()+5
                    while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
                    self.assertTrue(ready.exists())
                    ending.start()
                    try:
                        self.assertTrue(entered.wait(5))
                        self.assertFalse(completed.wait(.15), 'completion must synchronize with pending attachment')
                        release.touch()
                        opening.join(10)
                        ending.join(10)
                        self.assertFalse(failures, failures)
                        self.assertFalse(opening.is_alive() or ending.is_alive())
                        self.assertTrue(self.sessions())
                        self.assertTrue(all(s['ended_at'] is not None for s in self.sessions()))
                        self.assertFalse(self.android._OWNED)
                        self.assertTrue(processes)
                        self.assertTrue(all(proc.poll() is not None for proc in processes))
                    finally:
                        release.touch()
                        opening.join(10)
                        ending.join(10)
                        store.cleanup_sessions(store.project_identity(self.project)['id'])
                self.assertFalse(failures, failures)
                self.assertFalse(opening.is_alive() or ending.is_alive())
                self.assertTrue(all(s['ended_at'] is not None for s in self.sessions()))
                self.assertFalse(self.android._OWNED)
