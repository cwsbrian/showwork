#!/usr/bin/env python3
"""Local browser companion for design choices and evidence-backed handoffs."""

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import workspace
import store
import browser
import ios_simulator

ASSETS = Path(__file__).resolve().parents[1] / "assets"
TEMPLATE = ASSETS / "companion.html"
REPORT_TYPES = ["plan", "review", "verify", "result", "adversarial-review"]
MAX_BODY = 2 * 1024 * 1024
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FILE = 512 * 1024  # one file read for "Files worth reviewing"
MAX_CODE = 1536 * 1024  # all code shown on one page


def directory(project):
    return workspace(project) / "visual"


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")


def line_number(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def attach_code(project, files):
    """Show Git changes for changed files, or current code when there is no diff."""
    root = Path(project).resolve()
    git_root = store.run_git(root, "rev-parse", "--show-toplevel")
    total = 0
    for item in files:
        if "code" not in item:
            path = (root / item["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"File to review not found in the project: {item['path']}")
            # Compare case-insensitively: .GIT/config and .ENV are the same files on macOS.
            if (any(part.casefold() == ".git" for part in path.relative_to(root).parts)
                    or path.name.casefold().startswith(".env")):
                raise ValueError(f"Refusing to show a git or environment file: {item['path']}")
            if path.is_file() and path.stat().st_size > MAX_FILE:
                raise ValueError(f"{item['path']} is too large; pass lines or a code excerpt")
            relative = path.relative_to(root).as_posix()
            code = None
            if git_root and "lines" not in item and item.get("diff") is not False:
                result = subprocess.run(
                    ["git", "-C", str(root), "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3", "HEAD", "--", relative],
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout:
                    try:
                        code = result.stdout.decode("utf-8")
                    except UnicodeDecodeError:
                        raise ValueError(f"{item['path']} is not a UTF-8 text file") from None
                    if "Binary files " in code or "GIT binary patch" in code:
                        raise ValueError(f"{item['path']} is not a UTF-8 text file")
                elif path.is_file() and store.run_git(root, "ls-files", "--error-unmatch", "--", relative) is None:
                    try:
                        current = path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        raise ValueError(f"{item['path']} is not a UTF-8 text file") from None
                    if current:
                        changes = difflib.unified_diff([], current.splitlines(), fromfile=f"a/{relative}", tofile=f"b/{relative}", lineterm="")
                        code = f"diff --git a/{relative} b/{relative}\nnew file mode 100644\n" + "\n".join(changes)
                if code:
                    if len(code.encode("utf-8")) > MAX_FILE:
                        raise ValueError(f"{item['path']} diff is too large; pass a smaller diff excerpt")
                    item["code"] = code
                    item["diff"] = True
            if code is None:
                if item.get("diff") is True:
                    raise ValueError(f"No Git diff for {item['path']}; provide a diff or omit diff: true")
                if not path.is_file():
                    raise ValueError(f"File to review not found in the project: {item['path']}")
                try:
                    code = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raise ValueError(f"{item['path']} is not a UTF-8 text file") from None
            if "lines" in item:
                first, last = item.pop("lines")
                rows = code.splitlines()
                if first > len(rows):
                    raise ValueError(f"{item['path']} has only {len(rows)} lines")
                code = "\n".join(rows[first - 1:last])
                item["start_line"] = first
            if not code.strip():
                raise ValueError(f"{item['path']} has no code to show")
            item["code"] = code
        total += len(item["code"].encode("utf-8"))
    if total > MAX_CODE:
        raise ValueError("Files to review hold too much code; show the changed parts with lines or a diff")


def validate(page, report_type="result"):
    if not isinstance(page, dict) or page.get("mode") not in {"decision", "handoff"}:
        raise ValueError("mode must be decision or handoff")
    require_text(page.get("title"), "title")
    require_text(page.get("summary"), "summary")
    sections = page.get("sections", [])
    options = page.get("options", [])
    checks = page.get("checks", [])
    if not all(isinstance(value, list) for value in [sections, options, checks]):
        raise ValueError("sections, options and checks must be lists")
    if page["mode"] == "decision":
        require_text(page.get("question"), "question")
        if len(options) < 2:
            raise ValueError("A decision needs at least two visual options")
    elif options:
        raise ValueError("A handoff explains the result; it must not request option selection")
    if page["mode"] == "handoff":
        if not sections:
            raise ValueError("A handoff needs visual sections")
        if not checks and report_type not in ("plan", "review"):
            raise ValueError("A handoff needs verification results")
    for item in sections + options:
        if not isinstance(item, dict):
            raise ValueError("Each section/option must be an object")
        require_text(item.get("title"), "section/option title")
        require_text(item.get("body"), "section/option body")
        if not item.get("html") and not item.get("image"):
            raise ValueError("Each section/option needs a rendered HTML visual or image")
        for key in ["html", "image"]:
            if key in item:
                require_text(item[key], key)
        if item in sections and item.get("kind") not in {"proposal", "observed", "explanation"}:
            raise ValueError("Section kind must be proposal, observed or explanation")
    files = page.get("files", [])
    if not isinstance(files, list):
        raise ValueError("files must be a list")
    if files and page["mode"] != "handoff":
        raise ValueError("Only a handoff lists files to review")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Each file must be an object")
        require_text(item.get("path"), "file path")
        require_text(item.get("why"), "file why")
        for key in ["code", "language"]:
            if key in item:
                require_text(item[key], f"file {key}")
        if "diff" in item and not isinstance(item["diff"], bool):
            raise ValueError("file diff must be true or false")
        if "start_line" in item and not line_number(item["start_line"]):
            raise ValueError("file start_line must be a positive integer")
        if "lines" in item:
            if "code" in item:
                raise ValueError("Give a file either code or lines, not both")
            span = item["lines"]
            if not (isinstance(span, list) and len(span) == 2 and all(map(line_number, span)) and span[0] <= span[1]):
                raise ValueError("file lines must be [first, last] line numbers")
    ids = []
    for option in options:
        require_text(option.get("id"), "option id")
        ids.append(option["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Option IDs must be unique")
    for check in checks:
        if not isinstance(check, dict) or check.get("status") not in {"verified", "failed", "unverified"}:
            raise ValueError("Check status must be verified, failed or unverified")
        require_text(check.get("text"), "check text")
        require_text(check.get("evidence"), "check evidence or limitation")
    return page


def open_app(foreground=False):
    """Open Showwork, raising its window for an explicit Showwork command."""
    if os.environ.get("SHOWWORK_NO_APP") == "1" or sys.platform != "darwin":
        return "disabled"
    if os.environ.get("SHOWWORK_STORE"):
        return "disabled"  # the app reads only the default store, so a custom store needs the browser
    if not foreground:
        try:
            check = subprocess.run(["osascript", "-e", 'application id "dev.showwork.app" is running'],
                                   capture_output=True, text=True, timeout=10)
            if check.returncode == 0 and check.stdout.strip() == "true":
                return "opened"  # the running app's file watcher picks up the report
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        command = ["open", "-a", "Showwork"] if foreground else ["open", "-g", "-a", "Showwork", "--args", "--background"]
        result = subprocess.run(command,
                                capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "missing"
    return "opened" if result.returncode == 0 else "missing"


def publish(project, source, report_type=None, agent=None):
    report_type = report_type or "result"
    if report_type not in REPORT_TYPES:
        raise ValueError(f"type must be one of {', '.join(REPORT_TYPES)}")
    source = Path(source).resolve()
    if source.stat().st_size > MAX_BODY:
        raise ValueError("Page JSON must be at most 2 MiB; use image files for screenshots")
    page = validate(json.loads(source.read_text(encoding="utf-8")), report_type)
    # Validate all attachments before saving anything.
    images = []
    for item in page.get("sections", []) + page.get("options", []):
        if "image" not in item:
            continue
        image = (source.parent / item["image"]).resolve()
        if not image.is_file() or image.suffix.lower() not in IMAGE_TYPES:
            raise ValueError(f"Expected a PNG/JPEG/WebP/GIF image: {image}")
        with image.open("rb") as stream:
            name = hashlib.file_digest(stream, "sha256").hexdigest() + image.suffix.lower()
        images.append((image, "assets/" + name))
        item["image"] = "assets/" + name
    attach_code(project, page.get("files", []))
    page["version"] = secrets.token_hex(12)
    page["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = store.save_report(project, page, images, report_type, store.detect_agent(agent))
    return {**page, "report": meta}


def worktree_reports(project):
    worktree = store.worktree_key(project)
    return [meta for meta in store.list_reports(store.project_identity(project)["id"])
            if meta.get("worktree") == worktree]


class CompanionServer(HTTPServer):
    def __init__(self, project, port=0):
        self.project = Path(project).resolve()
        self.root = directory(project)
        self.root.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.cookie_name = f"showwork_key_{self.server_port}"
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.url = self.origin + "/?key=" + self.token


class Handler(BaseHTTPRequestHandler):
    # A bounded, single-threaded server serializes choices and avoids lost events.
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Do not print URLs containing the session key.

    def authorized(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            supplied = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
            if not supplied and self.server.cookie_name in cookie:
                supplied = cookie[self.server.cookie_name].value
            return secrets.compare_digest(supplied, self.server.token)
        except (ValueError, TypeError, CookieError):
            return False

    def respond(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self' about:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if code == 200:
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={self.server.token}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.authorized():
            self.respond(403, {"error": "Open the complete session URL"})
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/":
                self.respond(200, TEMPLATE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/view":
                meta = store.latest_report(self.server.project)
                page = json.loads((store.report_dir(meta) / "page.json").read_text(encoding="utf-8")) if meta else None
                self.respond(200, {"page": page, "report": meta["id"] if meta else None})
            elif path in ("/report-view.js", "/report-view.css"):
                asset = ASSETS / path[1:]
                if asset.is_file():
                    self.respond(200, asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                else:
                    self.respond(404, {"error": "Not found"})
            elif path.startswith("/assets/"):
                meta = store.latest_report(self.server.project)
                if not meta:
                    self.respond(404, {"error": "Image not found"})
                    return
                assets = (store.report_dir(meta) / "assets").resolve()
                asset = (assets / path.removeprefix("/assets/")).resolve()
                if not asset.is_relative_to(assets) or asset.suffix.lower() not in IMAGE_TYPES or not asset.is_file():
                    self.respond(404, {"error": "Image not found"})
                else:
                    self.respond(200, asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            else:
                self.respond(404, {"error": "Not found"})
        except (OSError, ValueError):
            self.respond(500, {"error": "Could not read the published page"})

    def do_POST(self):
        if not self.authorized() or self.headers.get("Origin") != self.server.origin:
            self.respond(403, {"error": "Unauthorized origin or session"})
            return
        if urlsplit(self.path).path != "/api/choice":
            self.respond(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("Invalid event size")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a choice object")
            meta = next((item for item in worktree_reports(self.server.project) if item.get("version") == data.get("version")), None)
            if meta is None:
                self.respond(409, {"error": "This page changed. Review the latest options."})
                return
            if meta["mode"] != "decision":
                raise ValueError("Not a current visual choice")
            if not store.is_open(meta):
                self.respond(409, {"error": "This question is closed. Review the latest report."})
                return
            page = json.loads((store.report_dir(meta) / "page.json").read_text(encoding="utf-8"))
            if data.get("choice") not in [item["id"] for item in page["options"]]:
                raise ValueError("Not a current visual choice")
            store.append_event(meta, data["choice"])
            delivery = store.deliver_decision(meta, page, data["choice"])
            self.respond(200, {"recorded": True, "choice": data["choice"], **delivery})
        except (OSError, ValueError, KeyError, TypeError):
            self.respond(400, {"error": "Invalid choice"})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    for name in ["path", "start", "progress", "stop", "serve", "publish", "events", "comments"]:
        command = sub.add_parser(name)
        command.add_argument("--project", required=True, type=Path)
        if name in ("start", "progress", "stop"):
            command.add_argument("--type", choices=REPORT_TYPES, default="result")
        if name == "progress":
            command.add_argument("--text", required=True)
        if name == "start":
            command.add_argument("--agent", choices=["claude", "codex"])
            command.add_argument("--title")
            command.add_argument("--require-app", action="store_true")
        if name == "serve":
            command.add_argument("--port", type=int, default=0)
            command.add_argument("--open", action="store_true")
        if name == "publish":
            command.add_argument("--file", required=True, type=Path)
            command.add_argument("--type", choices=REPORT_TYPES)
            command.add_argument("--agent", choices=["claude", "codex"])
            command.add_argument("--require-app", action="store_true")
        if name in ("events", "comments"):
            command.add_argument("--report")
    browser_cmd = sub.add_parser("browser")
    browser_sub = browser_cmd.add_subparsers(dest="browser_action", required=True)
    browser_open = browser_sub.add_parser("open")
    browser_open.add_argument("--project", required=True, type=Path)
    browser_open.add_argument("--url", required=True)
    browser_open.add_argument("--title")
    browser_open.add_argument("--width", type=int, default=1280)
    browser_open.add_argument("--height", type=int, default=800)
    browser_open.add_argument("--require-app", action="store_true")
    browser_close = browser_sub.add_parser("close")
    browser_close.add_argument("--project", required=True, type=Path)
    browser_close.add_argument("--session", required=True)
    simulator_cmd = sub.add_parser("simulator")
    simulator_sub = simulator_cmd.add_subparsers(dest="simulator_action", required=True)
    for action in ("open", "close"):
        command = simulator_sub.add_parser(action)
        command.add_argument("--project", required=True, type=Path)
        if action == "open":
            command.add_argument("--udid", required=True)
            command.add_argument("--title")
            command.add_argument("--require-app", action="store_true")
        else:
            command.add_argument("--session", required=True)
    args = cli.parse_args()
    try:
        if not args.project.is_dir():
            raise ValueError("Project must be an existing directory")
        if args.action == "path":
            root = directory(args.project)
            root.mkdir(exist_ok=True)
            print(root)
        elif args.action == "start":
            app = open_app(foreground=args.require_app)
            if args.require_app and app != "opened":
                raise ValueError("Showwork app is unavailable; an in-app task cannot start")
            store.cleanup_sessions(store.project_identity(args.project)["id"])
            root = directory(args.project)
            root.mkdir(exist_ok=True)
            run = store.start_run(args.project, args.type, store.detect_agent(args.agent), args.title)
            store.cleanup_sessions(store.project_identity(args.project)["id"])
            print(json.dumps({"directory": str(root), "run": run["id"], "type": run["type"], "app": app}))
        elif args.action == "stop":
            identity = store.project_identity(args.project)
            run_id = store.finish_run(identity["id"], store.worktree_key(args.project), args.type)
            store.cleanup_sessions(identity["id"], run_id)
            print(json.dumps({"stopped": args.type}))
        elif args.action == "progress":
            print(json.dumps(store.append_draft_text(args.project, args.type, args.text)))
        elif args.action == "simulator":
            if args.simulator_action == "open":
                if args.require_app and open_app(foreground=True) != "opened":
                    raise ValueError("Showwork app is unavailable; the simulator must appear in the app")
                session = ios_simulator.open_simulator(args.project, args.udid, args.title)
                print(json.dumps({"session": session["id"], "run": session["run"], "endpoint": f"http://127.0.0.1:{session['port']}"}))
            else:
                ios_simulator.close_simulator(store.project_identity(args.project)["id"], args.session)
                print(json.dumps({"closed": args.session}))
        elif args.action == "browser":
            if args.browser_action == "open":
                if args.require_app and open_app(foreground=True) != "opened":
                    raise ValueError("Showwork app is unavailable; the browser must appear in the app")
                session = browser.open_browser(args.project, args.url, args.title, args.width, args.height)
                print(json.dumps({"session": session["id"], "run": session["run"],
                                  "cdp": f"http://127.0.0.1:{session['port']}", "ws": session["ws"]}))
            else:
                identity = store.project_identity(args.project)
                browser.close_browser(identity["id"], args.session)
                print(json.dumps({"closed": args.session}))
        elif args.action == "publish":
            app = open_app(foreground=args.require_app)
            if args.require_app and app != "opened":
                raise ValueError("Showwork app is unavailable; the report must appear in the app")
            page = publish(args.project, args.file, args.type, args.agent)
            meta = page["report"]
            print(json.dumps({"published": page["version"], "mode": page["mode"], "report": meta["id"],
                              "project": meta["project_id"], "path": str(store.report_dir(meta)), "app": app}))
        elif args.action == "events":
            if args.report:
                meta = next((item for item in worktree_reports(args.project) if item["id"] == args.report), None)
            else:
                meta = store.latest_report(args.project, "decision")
            if meta is None:
                print(json.dumps({"report": None, "version": None, "open": False, "events": []}))
            else:
                current = [item for item in store.read_events(meta) if item.get("version") == meta["version"]]
                print(json.dumps({"report": meta["id"], "version": meta["version"], "open": store.is_open(meta), "events": current}, ensure_ascii=False))
        elif args.action == "comments":
            if args.report:
                meta = next((item for item in worktree_reports(args.project) if item["id"] == args.report), None)
            else:
                meta = next((item for item in reversed(worktree_reports(args.project))
                             if item.get("type") == "plan" and item.get("mode") == "handoff"), None)
            if meta is None:
                print(json.dumps({"report": None, "version": None, "note": None, "comments": []}))
            else:
                print(json.dumps({"report": meta["id"], "version": meta["version"],
                                  "note": store.read_plan_note(meta), "comments": store.read_comments(meta)}, ensure_ascii=False))
        else:
            with CompanionServer(args.project, args.port) as server:
                info = {"url": server.url, "pid": os.getpid(), "project": str(args.project.resolve()), "directory": str(server.root)}
                save_json(server.root / "server.json", info)
                print(json.dumps(info), flush=True)
                if args.open:
                    webbrowser.open(server.url)
                try:
                    server.serve_forever()
                finally:
                    info["stopped"] = True
                    save_json(server.root / "server.json", info)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"showwork companion: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
