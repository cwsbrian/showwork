"""Own Showwork attachments to already booted iOS Simulators."""
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

RELAY = Path(__file__).with_name('ios_relay.py')
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
        return result.returncode == 0 and args[args.index('--session') + 1] == session_id and any(Path(arg).name == 'ios_relay.py' for arg in args)
    except (ValueError, IndexError):
        return False


def _check_capabilities(idb):
    # Help parsing is local: it never connects to or changes a simulator.
    # Pass the actual stream options so argparse also checks mjpeg support.
    commands = [('describe',), ('video-stream', '--format', 'mjpeg', '--fps', '10', '--scale-factor', '0.5'),
                ('ui', 'tap'), ('ui', 'swipe'), ('ui', 'text')]
    for command in commands:
        try:
            subprocess.run([idb, *command, '--help'], capture_output=True, text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f"Required idb command unavailable: idb {' '.join(command)} ({error})") from error


def _stop(pid, session_id):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return
    proc = _OWNED.get(pid)
    if proc is None:
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=5)
        try:
            args = shlex.split(result.stdout)
            session_index = args.index('--session')
            if args[session_index + 1] != session_id or not any(Path(arg).name == 'ios_relay.py' for arg in args):
                return
        except (ValueError, IndexError):
            return
    elif proc.poll() is not None:
        _OWNED.pop(pid, None)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        if proc is not None:
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
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
                command = subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=5).stdout
                args = shlex.split(command)
                if '--session' in args and args[args.index('--session')+1] == session_id and any(Path(a).name == 'ios_relay.py' for a in args):
                    os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        _OWNED.pop(pid, None)
        if proc is not None and proc.stdout is not None: proc.stdout.close()


def open_simulator(project: Path, udid: str, title: str | None = None) -> dict:
    with store.simulator_lifecycle_lock():
        return _open_simulator(project, udid, title)


def _open_simulator(project, udid, title):
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
    if not isinstance(udid,str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',udid):
        raise ValueError('A simulator UDID is required')
    udid = udid.upper()
    # The device is shared across projects and worktrees.
    for folder in (store.store_root()/'projects').glob('*/sessions'):
        close_orphans(folder.parent.name)
        for session in store.list_sessions(folder.parent.name):
            if session.get('kind') == 'ios-simulator' and session.get('udid','').upper() == udid and session.get('ended_at') is None:
                if not _relay_alive(session.get('pid'), session['id']):
                    session['ended_at'] = datetime.now(timezone.utc).isoformat()
                    store.write_session(session)
                    continue
                if session.get('project_id') == identity['id'] and session.get('run') == run['id']: return session
                raise ValueError('Simulator is attached to another active run')
    idb = shutil.which('idb')
    if not idb: raise ValueError('idb command not found')
    _check_capabilities(idb)
    try:
        result = subprocess.run([idb,'describe','--udid',udid,'--json'],capture_output=True,text=True,timeout=10,check=True)
        device = json.loads(result.stdout)
        if device.get('target_type') != 'simulator' or device.get('state') != 'Booted':
            raise ValueError('Selected device must be a Booted simulator')
        dims = device['screen_dimensions']
        width,height,pw,ph = (dims[k] for k in ('width','height','width_points','height_points'))
        if any(isinstance(v,bool) or not isinstance(v,int) or v <= 0 for v in (width,height,pw,ph)):
            raise ValueError('idb describe must return positive pixel and point dimensions')
    except (subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f'idb describe failed: {error}') from error
    session_id = store.new_report_id(datetime.now(timezone.utc))
    token = secrets.token_urlsafe(32)
    env = dict(os.environ, SHOWWORK_IOS_TOKEN=token)
    proc = None
    try:
        proc = subprocess.Popen([sys.executable,str(RELAY),'serve','--udid',udid,'--session',session_id,'--idb-path',idb,'--points-width',str(pw),'--points-height',str(ph)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
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
            port = ready['port']
            if isinstance(port,bool) or not isinstance(port,int) or not 1 <= port <= 65535 or proc.poll() is not None: raise ValueError()
        except (ValueError,KeyError,TypeError):
            raise ValueError('iOS relay did not become ready') from None
        session = dict(id=session_id,project_id=identity['id'],run=run['id'],kind='ios-simulator',title=title or device.get('name') or udid,width=width,height=height,pid=proc.pid,started_at=datetime.now(timezone.utc).isoformat(),ended_at=None,udid=udid,points_width=pw,points_height=ph,port=port,token=token)
        # Run completion and marker replacement take the same lifecycle lock.
        # Reject a removed/replaced marker before committing the attachment.
        try:
            current = json.loads((running / (run['id'] + '.json')).read_text())
        except (OSError, ValueError):
            raise ValueError('Showwork run ended before simulator attachment was ready') from None
        if current != run:
            raise ValueError('Showwork run changed before simulator attachment was ready')
        store.write_session(session)
        return session
    except Exception:
        if proc is not None: _stop(proc.pid,session_id)
        raise


def close_simulator(project_id: str, session_id: str) -> dict:
    if not store.ID_PATTERN.fullmatch(session_id): raise ValueError('Invalid session id')
    session = next((s for s in store.list_sessions(project_id) if s['id']==session_id and s.get('kind')=='ios-simulator'),None)
    if session is None: raise ValueError('Simulator session not found')
    if session.get('ended_at') is None:
        _stop(session.get('pid'),session_id)
        session['ended_at'] = datetime.now(timezone.utc).isoformat()
        store.write_session(session)
    return session


def close_run(project_id: str, run_id: str) -> None:
    for s in store.list_sessions(project_id,run_id):
        if s.get('kind')=='ios-simulator' and s.get('ended_at') is None: close_simulator(project_id,s['id'])


def close_orphans(project_id: str) -> None:
    active = {p.stem for p in (store.store_root()/'projects'/project_id/'running').glob('*.json') if store.ID_PATTERN.fullmatch(p.stem)}
    for s in store.list_sessions(project_id):
        if s.get('kind')=='ios-simulator' and s.get('ended_at') is None and s.get('run') not in active: close_simulator(project_id,s['id'])
