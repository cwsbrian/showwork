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

UDID = '11111111-2222-3333-4444-555555555555'

class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'repo'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.idb = self.root / 'idb'
        self.idb.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"target_type":"simulator","state":"Booted","name":"Phone","screen_dimensions":{"width":1200,"height":2400,"width_points":400,"height_points":800}}))\n')
        self.idb.chmod(0o755)
        self.env = patch.dict(os.environ, {'SHOWWORK_STORE': str(self.root/'store'), 'PATH': str(self.root)+os.pathsep+os.environ['PATH']})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ios = importlib.import_module('ios_simulator')

    def sessions(self):
        return store.list_sessions(store.project_identity(self.project)['id'])

    def test_requires_run_and_explicit_valid_udid(self):
        with self.assertRaisesRegex(ValueError, 'start first'):
            self.ios.open_simulator(self.project, UDID)
        store.start_run(self.project, 'result', 'codex')
        for bad in ['booted', '', '../bad']:
            with self.assertRaises(ValueError): self.ios.open_simulator(self.project, bad)
        self.assertEqual(self.sessions(), [])

    def test_missing_idb_and_shutdown_leave_no_record(self):
        store.start_run(self.project, 'result', 'codex')
        with patch.object(self.ios.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'idb'): self.ios.open_simulator(self.project, UDID)
        self.idb.write_text(self.idb.read_text().replace('Booted','Shutdown'))
        with self.assertRaisesRegex(ValueError, 'Booted'): self.ios.open_simulator(self.project, UDID)
        self.assertEqual(self.sessions(), [])

    def fake_relay(self, ready=True):
        relay = self.root/'ios_relay.py'
        relay.write_text('import json,time\n'+('print(json.dumps({"port":12345}),flush=True)\n' if ready else '')+'time.sleep(60)\n')
        return patch.object(self.ios, 'RELAY', relay)

    def test_ready_idempotence_conflict_and_close(self):
        run = store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            s = self.ios.open_simulator(self.project, UDID)
            self.assertEqual(self.ios.open_simulator(self.project, UDID)['id'], s['id'])
            self.assertEqual((s['width'],s['points_width'],s['title']), (1200,400,'Phone'))
            self.assertNotIn('url', s)
            store.start_run(self.project, 'review', 'codex')
            with self.assertRaisesRegex(ValueError, 'another'): self.ios.open_simulator(self.project, UDID)
            self.ios.close_run(s['project_id'],run['id'])
        self.assertIsNotNone(self.sessions()[0]['ended_at'])
        self.assertIn('Booted',self.idb.read_text())

    def test_dead_claim_recovers_for_same_and_other_run(self):
        for other_run in (False, True):
            with self.subTest(other_run=other_run), self.fake_relay():
                store.start_run(self.project, 'result', 'codex')
                old = self.ios.open_simulator(self.project, UDID)
                self.ios._stop(old['pid'], old['id'])
                if other_run: store.start_run(self.project, 'review', 'codex')
                new = self.ios.open_simulator(self.project, UDID)
                try:
                    self.assertNotEqual(old['id'], new['id'])
                    self.assertIsNotNone(next(s for s in self.sessions() if s['id'] == old['id'])['ended_at'])
                finally:
                    self.ios.close_simulator(new['project_id'], new['id'])

    def test_active_claim_with_reused_pid_is_not_signaled(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            old = self.ios.open_simulator(self.project, UDID)
            self.ios._stop(old['pid'], old['id'])
            old['pid'] = 123456
            store.write_session(old)
            original = self.ios.subprocess.run
            def run(args, **kwargs):
                if args[0] == 'ps': return subprocess.CompletedProcess(args, 0, 'python other.py --session wrong', '')
                return original(args, **kwargs)
            with patch.object(self.ios.subprocess, 'run', side_effect=run), patch.object(self.ios.os, 'kill') as kill:
                new = self.ios.open_simulator(self.project, UDID)
                kill.assert_not_called()
            try: self.assertNotEqual(old['id'], new['id'])
            finally: self.ios.close_simulator(new['project_id'], new['id'])

    def test_missing_capability_creates_no_session(self):
        store.start_run(self.project, 'result', 'codex')
        original = self.idb.read_text()
        for command in ('describe', 'video-stream', 'tap', 'swipe', 'text'):
            with self.subTest(command=command):
                self.idb.write_text(original.replace('import json',
                    f"import sys\nif '--help' in sys.argv and {command!r} in sys.argv: sys.exit(2)\nimport json"))
                with self.assertRaisesRegex(ValueError, command):
                    self.ios.open_simulator(self.project, UDID)
                self.assertEqual(self.sessions(), [])

    def test_never_ready_terminates_without_record(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay(False), patch.object(self.ios, 'READY_TIMEOUT', .1):
            with self.assertRaisesRegex(ValueError,'ready'): self.ios.open_simulator(self.project, UDID)
        self.assertFalse(self.ios._OWNED)
        self.assertEqual(self.sessions(), [])

    def test_orphan_reused_pid_is_not_signaled(self):
        store.start_run(self.project, 'result', 'codex')
        with self.fake_relay():
            s = self.ios.open_simulator(self.project, UDID)
            self.ios._stop(s['pid'], s['id'])
        s['pid'] = 123456
        store.write_session(s)
        store.finish_run(s['project_id'],store.worktree_key(self.project),'result')
        with patch.object(self.ios.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'python other.py --session wrong','')), patch.object(self.ios.os,'kill') as kill:
            self.ios.close_orphans(s['project_id'])
            kill.assert_not_called()
        self.assertIsNotNone(self.sessions()[0]['ended_at'])

    def test_publish_and_stop_end_relays_without_shutdown(self):
        for action in ('publish', 'stop'):
            store.start_run(self.project, 'result', 'codex')
            with self.fake_relay():
                s = self.ios.open_simulator(self.project, UDID)
                proc = self.ios._OWNED[s['pid']]
                if action == 'publish':
                    store.save_report(self.project, {'mode':'handoff','title':'T','version':'v'}, [], 'result', 'codex')
                else:
                    result = subprocess.run([sys.executable,str(SCRIPTS/'companion.py'),'stop','--project',str(self.project)],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    proc.wait(timeout=10)
                    self.ios._OWNED.pop(proc.pid,None)
                    proc.stdout.close()
                self.assertIsNotNone(proc.poll())
                self.assertIsNotNone(next(x for x in self.sessions() if x['id']==s['id'])['ended_at'])
                self.assertIn('Booted', self.idb.read_text())

    def test_cli_uses_real_relay_and_close_stops_stream_child(self):
        describe = self.idb.read_text().split('\n',1)[1]
        child_pid = self.root/'stream.pid'
        self.idb.write_text('#!/usr/bin/env python3\nimport sys,time,os\n'
            + "if '--help' in sys.argv: sys.exit(0)\n"
            + "if 'describe' in sys.argv:\n" + ''.join('    '+line+'\n' for line in describe.splitlines())
            + "else:\n"
            + f"    open({str(child_pid)!r},'w').write(str(os.getpid()))\n"
            + "    frame=bytes.fromhex('ffd8ffc0000b080320019001011100ffd9')\n"
            + "    while True:\n        sys.stdout.buffer.write(frame);sys.stdout.buffer.flush();time.sleep(.1)\n")
        store.start_run(self.project,'result','codex')
        def cli(*args):
            return subprocess.run([sys.executable,str(SCRIPTS/'companion.py'),'simulator',*args,'--project',str(self.project)],capture_output=True,text=True,timeout=30)
        opened = cli('open','--udid',UDID)
        self.assertEqual(opened.returncode,0,opened.stderr)
        output = json.loads(opened.stdout)
        self.assertTrue(output['endpoint'].startswith('http://127.0.0.1:'))
        stream_pid = int(child_pid.read_text())
        closed = cli('close','--session',output['session'])
        self.assertEqual(closed.returncode,0,closed.stderr)
        self.assertEqual(json.loads(closed.stdout),{'closed':output['session']})
        with self.assertRaises(ProcessLookupError): os.kill(stream_pid,0)

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
                relay = self.root/'ios_relay.py'
                relay.write_text('from pathlib import Path\nimport time,json\n'
                    + f'Path({str(ready)!r}).touch()\n'
                    + f'while not Path({str(release)!r}).exists(): time.sleep(.01)\n'
                    + 'print(json.dumps({"port":12345}),flush=True)\ntime.sleep(60)\n')
                entered = threading.Event()
                completed = threading.Event()
                failures = []
                processes = []
                original_popen = self.ios.subprocess.Popen
                def popen(*args, **kwargs):
                    proc = original_popen(*args, **kwargs)
                    if str(relay) in args[0]: processes.append(proc)
                    return proc
                original = store.finish_run
                def finish(*args, **kwargs):
                    entered.set()
                    return original(*args, **kwargs)
                def attach():
                    try: self.ios.open_simulator(self.project, UDID)
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
                with patch.object(self.ios,'RELAY',relay), patch.object(store,'finish_run',side_effect=finish), patch.object(self.ios.subprocess,'Popen',side_effect=popen):
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
                        self.assertFalse(self.ios._OWNED)
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
                self.assertFalse(self.ios._OWNED)
