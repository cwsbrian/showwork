"""Persistent report store shared by the companion, the browser and the desktop app."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import ensure_private_dir

ID_PATTERN = re.compile(r"\A[A-Za-z0-9-]+\Z")


def store_root():
    if os.environ.get("SHOWWORK_STORE"):
        root = Path(os.environ["SHOWWORK_STORE"]).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Showwork"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "showwork"
    for directory in (root, root / "projects"):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        ensure_private_dir(directory)
    return root


def run_git(project, *args):
    try:
        result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def strip_credentials(url):
    """Drop user:password@ from a remote URL so tokens never reach the store or the app."""
    if not url:
        return None
    transport, sep, inner = url.partition("::")
    if sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", transport):
        return transport + "::" + (strip_credentials(inner) or "")  # git remote helpers: "hg::https://..."
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*://)(.*)$", url, re.S)
    if not match:
        return url  # scp-style "git@host:o/r.git" carries no secret
    rest = match.group(2)
    # The host part ends at the first "/"; a raw "#", "?" or "[" in a password stays inside it.
    authority = rest.split("/", 1)[0]
    if "@" in authority:
        userinfo, host = authority.rsplit("@", 1)
        # Only ssh/git user names are kept (ssh://git@...); anywhere else userinfo may be a token.
        plain_user = match.group(1).lower() in ("ssh://", "git+ssh://", "ssh+git://", "git://")
        keep = userinfo.split(":", 1)[0] + "@" if plain_user else ""
        rest = keep + host + rest[len(authority):]
    return match.group(1) + rest


def worktree_key(project):
    """The folder a report belongs to: the git top-level folder, or the project folder outside git."""
    project = Path(project).expanduser()
    return os.path.realpath(run_git(project, "rev-parse", "--show-toplevel") or project)


def project_identity(project):
    project = Path(project).expanduser()
    common = run_git(project, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common_dir = os.path.realpath(common or project)
    folder = Path(common_dir)
    name = folder.name
    if common and folder.name.startswith("."):
        name = folder.parent.name  # ".git", or a bare-repo layout such as "Repo/.bare"
    elif common and folder.name.endswith(".git") and len(folder.name) > 4:
        name = folder.name[:-4]  # bare clone "repo.git"
    return {
        "id": hashlib.sha256(common_dir.encode()).hexdigest()[:16],
        "name": name,
        "common_dir": common_dir,
        "remote": strip_credentials(run_git(project, "config", "--get", "remote.origin.url")) if common else None,
    }


def git_state(project):
    commit = run_git(project, "rev-parse", "HEAD")
    if not commit:
        return {"branch": None, "commit": None}
    branch = run_git(project, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        branch = "detached@" + (run_git(project, "rev-parse", "--short", "HEAD") or commit[:7])
    return {"branch": branch, "commit": commit}


def detect_agent(explicit):
    if explicit:
        return explicit
    if os.environ.get("CLAUDECODE") == "1":
        return "claude"
    if any(key.startswith("CODEX_") for key in os.environ):
        return "codex"
    return "unknown"


def agent_session(project, agent):
    """Capture the exact Orca terminal that authored this report, when available."""
    handle = os.environ.get("ORCA_TERMINAL_HANDLE", "")
    worktree_id = os.environ.get("ORCA_WORKTREE_ID", "")
    if (not re.fullmatch(r"term_[0-9a-f-]{36}", handle) or not worktree_id
            or os.path.realpath(worktree_id.rsplit("::", 1)[-1]) != worktree_key(project)):
        return None
    binary_dir = os.environ.get("ORCA_CLI_BIN_DIR")
    executable = str(Path(binary_dir) / "orca") if binary_dir else shutil.which("orca")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "terminal", "show", "--terminal", handle, "--json"],
                                capture_output=True, text=True, timeout=5)
        terminal = json.loads(result.stdout).get("result", {}).get("terminal", {}) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if (terminal.get("handle") != handle or terminal.get("worktreeId") != worktree_id
            or os.path.realpath(terminal.get("worktreePath") or "") != worktree_key(project)
            or terminal.get("agentIdentity") != agent or not terminal.get("incarnationId")):
        return None
    thread_id = (os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")) if agent == "codex" else os.environ.get("CLAUDE_SESSION_ID")
    return {"terminal_handle": handle, "terminal_incarnation": terminal["incarnationId"],
            "worktree_id": worktree_id, "thread_id": thread_id or None}


def new_report_id(now):
    return now.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(2)


def write_json(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sessions_dir(project_id):
    if not ID_PATTERN.fullmatch(project_id):
        raise ValueError("Invalid project id")
    path = store_root() / "projects" / project_id / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_sessions(project_id, run_id=None):
    if not ID_PATTERN.fullmatch(project_id) or (run_id is not None and not ID_PATTERN.fullmatch(run_id)):
        return []
    folder = sessions_dir(project_id)
    sessions = []
    for path in sorted(folder.glob("*.json")):
        if not ID_PATTERN.fullmatch(path.stem):
            continue
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(session, dict) and session.get("id") == path.stem and session.get("project_id") == project_id:
            if run_id is None or session.get("run") == run_id:
                sessions.append(session)
    return sessions


def write_session(session):
    project_id, session_id = session["project_id"], session["id"]
    if not ID_PATTERN.fullmatch(project_id) or not ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    write_json(sessions_dir(project_id) / (session_id + ".json"), session)


@contextmanager
def simulator_lifecycle_lock():
    """Serialize device claims and run-marker mutations across companion processes."""
    with (store_root() / '.ios-simulator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def cleanup_sessions(project_id, run_id=None):
    """Attempt every owner's cleanup even if another owner fails."""
    import browser
    import ios_simulator
    errors = []
    for owner in (browser, ios_simulator):
        if run_id:
            try: owner.close_run(project_id, run_id)
            except Exception as error: errors.append(error)
        try: owner.close_orphans(project_id)
        except Exception as error: errors.append(error)
    if errors:
        raise ValueError("Session cleanup failed: " + "; ".join(str(error) for error in errors))


def save_report(project, page, images, report_type, agent):
    project = Path(project).expanduser()
    identity = project_identity(project)
    project_dir = store_root() / "projects" / identity["id"]
    reports = project_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    # The app only lists projects that have project.json, so write it before the report appears.
    write_json(project_dir / "project.json", identity)
    now = datetime.now(timezone.utc)
    state = git_state(project)
    worktree = worktree_key(project)
    run = current_run(identity["id"], worktree, report_type)
    while True:
        report_id = new_report_id(datetime.now(timezone.utc))
        pending = reports / (".pending-" + report_id)
        try:
            pending.mkdir()
        except FileExistsError:
            continue
        try:
            for source, relative in images:
                target = pending / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            meta = {
                "id": report_id, "project_id": identity["id"], "type": report_type, "mode": page["mode"],
                "title": page["title"], "branch": state["branch"], "commit": state["commit"],
                "worktree": worktree, "agent": agent, "run": run["id"] if run else None,
                "agent_session": (run.get("agent_session") if run else None) or agent_session(project, agent),
                "created_at": page.get("published_at") or now.isoformat(), "version": page["version"],
            }
            write_json(pending / "page.json", page)
            write_json(pending / "meta.json", meta)
            try:
                os.rename(pending, reports / report_id)
            except OSError:
                if (reports / report_id).exists():
                    continue
                raise
        finally:
            shutil.rmtree(pending, ignore_errors=True)
        if meta["run"]:
            finish_run(identity["id"], worktree, report_type, meta["run"])
            cleanup_sessions(identity["id"], meta["run"])
        close_older_decisions(meta)
        return meta


def matching_runs(project_id, worktree, report_type):
    """Markers for this worktree and report type, newest first."""
    runs = []
    try:
        for path in (store_root() / "projects" / project_id / "running").glob("*.json"):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(run, dict) and run.get("worktree") == worktree and run.get("type") == report_type:
                runs.append((path, run))
    except OSError:
        pass
    return sorted(runs, key=lambda item: item[1].get("id") or item[0].stem, reverse=True)


def current_run(project_id, worktree, report_type):
    """The newest "working" marker for this worktree and report type, or None."""
    runs = matching_runs(project_id, worktree, report_type)
    return runs[0][1] if runs else None


def append_draft_text(project, report_type, text):
    """Append text to the visible in-progress document without publishing it."""
    if not isinstance(text, str) or not text:
        raise ValueError("Draft text must be nonempty")
    if len(text.encode("utf-8")) > 8192:
        raise ValueError("Draft text chunk is too long")
    identity = project_identity(project)
    worktree = worktree_key(project)
    with simulator_lifecycle_lock():
        matches = matching_runs(identity["id"], worktree, report_type)
        if not matches:
            raise ValueError("Run companion.py start first")
        path, run = matches[0]
        draft = run.get("draft_text", "")
        if not isinstance(draft, str) or len((draft + text).encode("utf-8")) > 256 * 1024:
            raise ValueError("Draft is too long")
        if not path.is_file():
            raise ValueError("This run is no longer in progress")
        run["draft_text"] = draft + text
        run["revision"] = run.get("revision", 0) + 1
        write_json(path, run)
        return {"run": run["id"], "revision": run["revision"]}


def start_run(project, report_type, agent, title=None):
    with simulator_lifecycle_lock():
        return _start_run(project, report_type, agent, title)


def _start_run(project, report_type, agent, title=None):
    """Record that an agent started a report, so the app can show it as in progress.
    Each start is a new run; older markers of the same worktree and type are replaced."""
    project = Path(project).expanduser()
    identity = project_identity(project)
    project_dir = store_root() / "projects" / identity["id"]
    running = project_dir / "running"
    running.mkdir(parents=True, exist_ok=True)
    write_json(project_dir / "project.json", identity)
    state = git_state(project)
    worktree = worktree_key(project)
    now = datetime.now(timezone.utc)
    run = {
        "id": new_report_id(now), "project_id": identity["id"], "type": report_type, "title": title or None,
        "branch": state["branch"], "worktree": worktree, "agent": agent,
        "started_at": now.isoformat(timespec="seconds"),
        "agent_session": agent_session(project, agent),
    }
    write_json(running / (run["id"] + ".json"), run)
    for path, old in matching_runs(identity["id"], worktree, report_type):
        if old.get("id", "") < run["id"]:
            path.unlink(missing_ok=True)
    return run


def finish_run(project_id, worktree, report_type, up_to_id=None):
    try:
        with simulator_lifecycle_lock():
            return _finish_run(project_id, worktree, report_type, up_to_id)
    except Exception:
        return None


def _finish_run(project_id, worktree, report_type, up_to_id=None):
    """Remove the matching "working" markers and return the newest one's id; never raises,
    a leftover marker only ages out in the app."""
    try:
        runs = matching_runs(project_id, worktree, report_type)
        stopped = [(path, run) for path, run in runs if up_to_id is None or (run.get("id") or path.stem) <= up_to_id]
        for path, _ in stopped:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return (stopped[0][1].get("id") or stopped[0][0].stem) if stopped else None
    except Exception:
        return None


def close_older_decisions(newer):
    """Mark older decisions from the same worktree closed, so deleting the newer report cannot reopen them."""
    try:
        marker = {"by": newer["id"], "time": datetime.now(timezone.utc).isoformat()}
        older = list_reports(newer["project_id"])
    except Exception:
        return
    for meta in older:
        try:
            if (str(meta.get("id", "")) >= newer["id"] or meta.get("mode") != "decision"
                    or meta.get("worktree") != newer.get("worktree")):
                continue
            path = report_dir(meta) / "closed.json"
            # Skip a report the app is deleting right now, so the marker cannot keep its folder alive.
            if not path.exists() and (path.parent / "meta.json").exists():
                write_json(path, marker)
        except Exception:
            pass  # a missing marker must not fail the publish; the newer report still closes it


def list_reports(project_id):
    if not ID_PATTERN.match(project_id):
        return []
    reports = store_root() / "projects" / project_id / "reports"
    if not reports.is_dir():
        return []
    metas = []
    for folder in sorted(reports.iterdir()):
        if folder.name.startswith(".") or not folder.is_dir() or not ID_PATTERN.match(folder.name):
            continue
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("id") == folder.name:
            metas.append(meta)
    return metas


def latest_report(project, mode=None):
    worktree = worktree_key(project)
    for meta in reversed(list_reports(project_identity(project)["id"])):
        if meta.get("worktree") == worktree and (mode is None or meta.get("mode") == mode):
            return meta
    return None


def is_open(meta):
    if meta.get("mode") != "decision":
        return False
    if (report_dir(meta) / "closed.json").exists():
        return False
    return not any(other["id"] > meta["id"] and other.get("worktree") == meta.get("worktree")
                   for other in list_reports(meta["project_id"]))


def report_dir(meta):
    if not ID_PATTERN.match(meta["project_id"]) or not ID_PATTERN.match(meta["id"]):
        raise ValueError("Invalid report id")
    return store_root() / "projects" / meta["project_id"] / "reports" / meta["id"]


def read_events(meta):
    try:
        lines = (report_dir(meta) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue  # a torn append (crash, full disk) must not hide the valid choices
        if isinstance(event, dict):
            events.append(event)
    return events


def read_comments(meta):
    try:
        lines = (report_dir(meta) / "comments.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    comments = []
    for line in lines:
        try:
            comment = json.loads(line)
        except ValueError:
            continue
        if isinstance(comment, dict) and comment.get("version") == meta["version"]:
            comments.append(comment)
    return comments


def read_plan_note(meta):
    try:
        note = json.loads((report_dir(meta) / "note.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return note if isinstance(note, dict) and note.get("version") == meta["version"] else None


def append_event(meta, choice):
    if next((event.get("choice") for event in reversed(read_events(meta)) if event.get("version") == meta["version"]), None) == choice:
        return None
    event = {"version": meta["version"], "title": meta["title"], "choice": choice,
             "time": datetime.now(timezone.utc).isoformat()}
    with open(report_dir(meta) / "events.jsonl", "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def deliver_decision(meta, page, choice):
    """Send a recorded choice to its exact original Orca terminal, if linked."""
    folder = report_dir(meta)
    receipt_path = folder / "decision-delivery.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("version") == meta["version"] and receipt.get("choice") == choice:
            return {"sent": True, "retryable": False, "reason": None}
    except (OSError, ValueError):
        pass
    session = meta.get("agent_session")
    if not session:
        return {"sent": False, "retryable": False, "reason": "This report has no linked agent session."}
    binary_dir = os.environ.get("ORCA_CLI_BIN_DIR")
    installed = Path("/Applications/Orca.app/Contents/Resources/bin/orca")
    executable = (os.environ.get("SHOWWORK_ORCA_CLI") or (str(Path(binary_dir) / "orca") if binary_dir else None)
                  or (str(installed) if sys.platform == "darwin" and installed.is_file() else shutil.which("orca")))
    if not executable:
        return {"sent": False, "retryable": True, "reason": "Orca CLI is unavailable."}
    handle = session.get("terminal_handle", "")
    try:
        shown = subprocess.run([executable, "terminal", "show", "--terminal", handle, "--json"], capture_output=True, text=True, timeout=10)
        terminal = json.loads(shown.stdout).get("result", {}).get("terminal", {}) if shown.returncode == 0 else {}
        if not (terminal.get("handle") == handle and terminal.get("incarnationId") == session.get("terminal_incarnation")
                and terminal.get("worktreeId") == session.get("worktree_id")
                and os.path.realpath(terminal.get("worktreePath") or "") == os.path.realpath(meta["worktree"])
                and terminal.get("agentIdentity") == meta["agent"] and terminal.get("connected") and terminal.get("writable")):
            raise ValueError("The original terminal has changed or closed.")
        option = next(item for item in page["options"] if item["id"] == choice)
        message = (f"Showwork decision for: {meta['title']}\nReport ID: {meta['id']}\n"
                   f"Question: {page.get('question', '')}\nSelected option: {option['title']}\n"
                   f"Details: {option.get('body', '')}\n\nPlease continue this plan using this choice in this session.")
        if len(message.encode("utf-8")) > 65536:
            raise ValueError("Choice message is too long.")
        sent = subprocess.run([executable, "terminal", "send", "--terminal", handle, "--text", message,
                               "--enter", "--wait-submit", "10", "--json"], capture_output=True, text=True, timeout=20)
        result = json.loads(sent.stdout) if sent.returncode == 0 else {}
        if not result.get("result", {}).get("send", {}).get("accepted"):
            raise ValueError(result.get("error", {}).get("message", "Orca did not accept the message."))
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration) as error:
        return {"sent": False, "retryable": True, "reason": str(error)}
    write_json(receipt_path, {"version": meta["version"], "choice": choice, "sent_at": datetime.now(timezone.utc).isoformat()})
    return {"sent": True, "retryable": False, "reason": None}
