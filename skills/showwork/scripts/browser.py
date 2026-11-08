"""Headless Chrome sessions owned by a Showwork run."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.request import urlopen

import store

_OWNED = {}


def find_chrome():
    candidates = [os.environ["SHOWWORK_CHROMIUM"]] if os.environ.get("SHOWWORK_CHROMIUM") else [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ValueError("Chrome not found; set SHOWWORK_CHROMIUM")


def _alive(pid):
    owned = _OWNED.get(pid)
    if owned is not None:
        return owned.poll() is None
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def _stop(pid, profile=None):
    if not isinstance(pid, int) or pid <= 0:
        return
    if profile and pid not in _OWNED:
        command = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                 capture_output=True, text=True).stdout
        if f"--user-data-dir={profile}" not in command:
            return  # PID was reused, or the session file does not describe this Chrome
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _OWNED.pop(pid, None)
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _alive(pid):
            _OWNED.pop(pid, None)
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    owned = _OWNED.pop(pid, None)
    if owned is not None:
        try:
            owned.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _page_socket(port):
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
        pages = json.load(response)
    return next((page["webSocketDebuggerUrl"] for page in pages
                 if page.get("type") == "page" and page.get("webSocketDebuggerUrl")), None)


def open_browser(project, url, title=None, width=1280, height=800):
    project = Path(project).expanduser()
    identity = store.project_identity(project)
    folder = store.store_root() / "projects" / identity["id"] / "running"
    runs = []
    for path in folder.glob("*.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(run, dict) and run.get("worktree") == store.worktree_key(project) and run.get("id") == path.stem:
            runs.append(run)
    if not runs:
        raise ValueError("Run companion.py start first")
    run = max(runs, key=lambda item: item["id"])
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL is required")
    if not isinstance(width, int) or not isinstance(height, int) or not 100 <= width <= 8192 or not 100 <= height <= 8192:
        raise ValueError("Browser size must be between 100 and 8192 pixels")
    chrome = find_chrome()
    profile = Path(tempfile.mkdtemp(prefix="showwork-browser-"))
    origins = os.environ.get("SHOWWORK_BROWSER_ORIGINS") or "tauri://localhost,http://localhost:1420"
    args = [chrome, "--headless=new", "--remote-debugging-port=0", f"--remote-allow-origins={origins}",
            f"--user-data-dir={profile}", f"--window-size={width},{height}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--hide-scrollbars",
            "--mute-audio", url]
    proc = None
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        _OWNED[proc.pid] = proc
        deadline = time.monotonic() + 15
        port = None
        ws = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ValueError("Chrome exited before its debugging port was ready")
            try:
                port = int((profile / "DevToolsActivePort").read_text().splitlines()[0])
                ws = _page_socket(port)
            except (OSError, ValueError, IndexError, KeyError):
                pass
            if ws:
                break
            time.sleep(0.1)
        if not ws:
            raise ValueError("Chrome debugging page did not become ready")
        session = {
            "id": store.new_report_id(datetime.now(timezone.utc)), "project_id": identity["id"],
            "run": run["id"], "kind": "browser", "title": title, "url": url,
            "width": width, "height": height, "port": port, "ws": ws,
            "pid": proc.pid, "profile": str(profile),
            "started_at": datetime.now(timezone.utc).isoformat(), "ended_at": None,
        }
        store.write_session(session)
        return session
    except Exception:
        if proc is not None:
            _stop(proc.pid)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(profile, ignore_errors=True)
        raise


def close_browser(project_id, session_id):
    if not store.ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    session = next((s for s in store.list_sessions(project_id) if s["id"] == session_id and s.get("kind") == "browser"), None)
    if session is None:
        raise ValueError("Browser session not found")
    if session.get("ended_at") is not None:
        return session
    profile = session.get("profile")
    if isinstance(profile, str) and Path(profile).name.startswith("showwork-browser-"):
        _stop(session.get("pid"), profile)
        shutil.rmtree(profile, ignore_errors=True)
    session["ended_at"] = datetime.now(timezone.utc).isoformat()
    store.write_session(session)
    return session


def close_run(project_id, run_id):
    for session in store.list_sessions(project_id, run_id):
        if session.get("kind") == "browser" and session.get("ended_at") is None:
            close_browser(project_id, session["id"])


def close_orphans(project_id):
    running = store.store_root() / "projects" / project_id / "running"
    active = {path.stem for path in running.glob("*.json") if store.ID_PATTERN.fullmatch(path.stem)}
    for session in store.list_sessions(project_id):
        if session.get("kind") == "browser" and session.get("ended_at") is None and session.get("run") not in active:
            close_browser(project_id, session["id"])
