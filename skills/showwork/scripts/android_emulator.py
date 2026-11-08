"""Own Showwork attachments to already booted Android Emulators."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time

import store

RELAY = Path(__file__).with_name('android_relay.py')
READY_TIMEOUT = 20
_OWNED = {}


def _relay_alive(pid, session_id):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    proc = _OWNED.get(pid)
    if proc is not None and proc.poll() is not None:
        _OWNED.pop(pid, None)
        if proc.stdout is not None: proc.stdout.close()
        return False
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=5)
    try:
        args = shlex.split(result.stdout)
        return result.returncode == 0 and args[args.index('--session') + 1] == session_id and any(Path(arg).name == 'android_relay.py' for arg in args)
    except (ValueError, IndexError):
        return False


def _preflight(adb, serial):
    try:
        devices = subprocess.run([adb, 'devices', '-l'], capture_output=True, text=True, timeout=5, check=True)
        states = [line.split()[1] for line in devices.stdout.splitlines()
                  if len(line.split()) >= 2 and line.split()[0] == serial]
        if states != ['device']:
            raise ValueError('Selected emulator must be listed as device by adb devices -l')
        for prop in ('sys.boot_completed', 'ro.kernel.qemu'):
            result = subprocess.run([adb, '-s', serial, 'shell', 'getprop', prop], capture_output=True, text=True, timeout=5, check=True)
            if result.stdout.strip() != '1':
                raise ValueError('Selected device must be a booted Android emulator')
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f'adb preflight failed: {error}') from error


def _stop(pid, session_id):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return
    proc = _OWNED.get(pid)
    # Check both the script and explicit session before every initial signal,
    # including children started by this process.
    if not _relay_alive(pid, session_id):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        if proc is not None:
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if _relay_alive(pid, session_id):
                    proc.kill()
                    proc.wait(timeout=2)
        else:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try: os.kill(pid, 0)
                except ProcessLookupError: break
                time.sleep(.05)
            else:
                # Recheck identity before escalation, in case the PID was reused.
                if _relay_alive(pid, session_id):
                    os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        _OWNED.pop(pid, None)
        if proc is not None and proc.stdout is not None: proc.stdout.close()


def open_emulator(project: Path, serial: str, title: str | None = None) -> dict:
    with store.simulator_lifecycle_lock():
        return _open_emulator(project, serial, title)


def _open_emulator(project, serial, title):
    project = Path(project).expanduser()
    identity = store.project_identity(project)
    running = store.store_root()/'projects'/identity['id']/'running'
    runs = []
    for path in running.glob('*.json'):
        try: run = json.loads(path.read_text())
        except (OSError, ValueError): continue
        if isinstance(run,dict) and run.get('id') == path.stem and run.get('worktree') == store.worktree_key(project): runs.append(run)
    if not runs: raise ValueError('Run companion.py start first')
    run = max(runs,key=lambda r:r['id'])
    if not isinstance(serial,str) or not re.fullmatch(r'emulator-[0-9]+',serial):
        raise ValueError('An explicit emulator-<digits> serial is required')
    # The device is shared across projects and worktrees.
    for folder in (store.store_root()/'projects').glob('*/sessions'):
        _close_orphans_locked(folder.parent.name)
        for session in store.list_sessions(folder.parent.name):
            if session.get('kind') == 'android-emulator' and session.get('serial','') == serial and session.get('ended_at') is None:
                if not _relay_alive(session.get('pid'), session['id']):
                    session['ended_at'] = datetime.now(timezone.utc).isoformat()
                    store.write_session(session)
                    continue
                if session.get('project_id') == identity['id'] and session.get('run') == run['id']: return session
                raise ValueError('Emulator is attached to another active run')
    adb = shutil.which('adb')
    if not adb: raise ValueError('adb command not found')
    _preflight(adb, serial)
    session_id = store.new_report_id(datetime.now(timezone.utc))
    token = secrets.token_urlsafe(32)
    env = dict(os.environ, SHOWWORK_ANDROID_TOKEN=token)
    proc = None
    try:
        proc = subprocess.Popen([sys.executable,str(RELAY),'serve','--serial',serial,'--session',session_id,'--adb-path',adb],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        _OWNED[proc.pid] = proc
        # Read a bounded line without blocking on a relay that never becomes ready.
        data = bytearray()
        deadline = time.monotonic()+READY_TIMEOUT
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if not selector.select(max(0,deadline-time.monotonic())): break
                chunk = os.read(proc.stdout.fileno(),4096)
                if not chunk: break
                data.extend(chunk)
                if len(data)>4096: break
                if b'\n' in data: break
        try:
            ready = json.loads(bytes(data).split(b'\n')[0])
            if len(data) > 4096: raise ValueError()
            port = ready['port']
            width, height = ready['width'], ready['height']
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height)): raise ValueError()
            if isinstance(port,bool) or not isinstance(port,int) or not 1 <= port <= 65535 or proc.poll() is not None: raise ValueError()
        except (ValueError,KeyError,TypeError):
            raise ValueError('Android relay did not become ready') from None
        session = dict(id=session_id,project_id=identity['id'],run=run['id'],kind='android-emulator',title=title or serial,width=width,height=height,pid=proc.pid,started_at=datetime.now(timezone.utc).isoformat(),ended_at=None,serial=serial,port=port,token=token)
        # Run completion and marker replacement take the same lifecycle lock.
        # Reject a removed/replaced marker before committing the attachment.
        try:
            current = json.loads((running / (run['id'] + '.json')).read_text())
        except (OSError, ValueError):
            raise ValueError('Showwork run ended before emulator attachment was ready') from None
        if current != run:
            raise ValueError('Showwork run changed before emulator attachment was ready')
        store.write_session(session)
        return session
    except Exception:
        if proc is not None: _stop(proc.pid,session_id)
        raise


def close_emulator(project_id: str, session_id: str) -> dict:
    if not store.ID_PATTERN.fullmatch(session_id): raise ValueError('Invalid session id')
    session = next((s for s in store.list_sessions(project_id) if s['id']==session_id and s.get('kind')=='android-emulator'),None)
    if session is None: raise ValueError('Emulator session not found')
    if session.get('ended_at') is None:
        _stop(session.get('pid'),session_id)
        session['ended_at'] = datetime.now(timezone.utc).isoformat()
        store.write_session(session)
    return session


def close_run(project_id: str, run_id: str) -> None:
    for s in store.list_sessions(project_id,run_id):
        if s.get('kind')=='android-emulator' and s.get('ended_at') is None: close_emulator(project_id,s['id'])


def close_orphans(project_id: str) -> None:
    with store.simulator_lifecycle_lock():
        _close_orphans_locked(project_id)


def _close_orphans_locked(project_id: str) -> None:
    # Keep the marker snapshot, session scan, and termination in one claim lock.
    active = {p.stem for p in (store.store_root()/'projects'/project_id/'running').glob('*.json') if store.ID_PATTERN.fullmatch(p.stem)}
    for s in store.list_sessions(project_id):
        if s.get('kind')=='android-emulator' and s.get('ended_at') is None and s.get('run') not in active: close_emulator(project_id,s['id'])
