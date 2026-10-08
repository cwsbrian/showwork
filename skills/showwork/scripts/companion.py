#!/usr/bin/env python3
"""Local browser companion for design choices and evidence-backed handoffs."""

import argparse
from datetime import datetime, timezone
import hashlib
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import workspace

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "companion.html"
MAX_BODY = 2 * 1024 * 1024
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


def validate(page):
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
    if page["mode"] == "handoff" and (not sections or not checks):
        raise ValueError("A handoff needs visual sections and verification results")
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


def publish(project, source):
    source = Path(source).resolve()
    if source.stat().st_size > MAX_BODY:
        raise ValueError("Page JSON must be at most 2 MiB; use image files for screenshots")
    page = validate(json.loads(source.read_text(encoding="utf-8")))
    root = directory(project)
    # Validate all attachments before changing the current page.
    copies = []
    for item in page.get("sections", []) + page.get("options", []):
        if "image" not in item:
            continue
        image = (source.parent / item["image"]).resolve()
        if not image.is_file() or image.suffix.lower() not in IMAGE_TYPES:
            raise ValueError(f"Expected a PNG/JPEG/WebP/GIF image: {image}")
        with image.open("rb") as stream:
            name = hashlib.file_digest(stream, "sha256").hexdigest() + image.suffix.lower()
        copies.append((image, root / "assets" / name))
        item["image"] = "/assets/" + name
    for image, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, destination)
    page["version"] = secrets.token_hex(12)
    page["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(root / "page.json", page)
    return page


class CompanionServer(HTTPServer):
    def __init__(self, project, port=0):
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
                page_path = self.server.root / "page.json"
                page = json.loads(page_path.read_text(encoding="utf-8")) if page_path.exists() else None
                self.respond(200, {"page": page})
            elif path.startswith("/assets/"):
                assets = (self.server.root / "assets").resolve()
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
            page = json.loads((self.server.root / "page.json").read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected a choice object")
            if data.get("version") != page["version"]:
                self.respond(409, {"error": "This page changed. Review the latest options."})
                return
            if page["mode"] != "decision" or data.get("choice") not in [item["id"] for item in page["options"]]:
                raise ValueError("Not a current visual choice")
            event = {
                "version": page["version"], "title": page["title"],
                "choice": data["choice"], "time": datetime.now(timezone.utc).isoformat(),
            }
            with (self.server.root / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.respond(200, {"recorded": True, "choice": data["choice"]})
        except (OSError, ValueError, KeyError, TypeError):
            self.respond(400, {"error": "Invalid choice"})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    for name in ["path", "serve", "publish", "events"]:
        command = sub.add_parser(name)
        command.add_argument("--project", required=True, type=Path)
        if name == "serve":
            command.add_argument("--port", type=int, default=0)
            command.add_argument("--open", action="store_true")
        if name == "publish":
            command.add_argument("--file", required=True, type=Path)
    args = cli.parse_args()
    try:
        if not args.project.is_dir():
            raise ValueError("Project must be an existing directory")
        if args.action == "path":
            root = directory(args.project)
            root.mkdir(exist_ok=True)
            print(root)
        elif args.action == "publish":
            page = publish(args.project, args.file)
            print(json.dumps({"published": page["version"], "mode": page["mode"]}))
        elif args.action == "events":
            root = directory(args.project)
            current = json.loads((root / "page.json").read_text(encoding="utf-8"))
            path = root / "events.jsonl"
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
            print(json.dumps({"version": current["version"], "events": [item for item in events if item["version"] == current["version"]]}, ensure_ascii=False))
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
