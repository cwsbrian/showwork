"""Persistent report store shared by the companion, the browser and the desktop app."""

from datetime import datetime, timezone
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
                "worktree": worktree, "agent": agent,
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
        close_older_decisions(meta)
        return meta


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


def append_event(meta, choice):
    event = {"version": meta["version"], "title": meta["title"], "choice": choice,
             "time": datetime.now(timezone.utc).isoformat()}
    with open(report_dir(meta) / "events.jsonl", "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event
