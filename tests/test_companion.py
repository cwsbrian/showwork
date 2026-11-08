import copy
from http.cookiejar import CookieJar
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "showwork" / "scripts" / "companion.py"
SPEC = spec_from_file_location("companion", SCRIPT)
COMPANION = module_from_spec(SPEC)
SPEC.loader.exec_module(COMPANION)
DECISION = {
    "mode": "decision", "title": "Choose a layout", "summary": "Visual alternatives", "question": "Which layout?",
    "options": [
        {"id": "list", "title": "List", "body": "Compact", "html": "<h2>Tasks</h2><p>One</p>"},
        {"id": "board", "title": "Board", "body": "Separate states", "html": "<h2>Pending | Done</h2>"},
    ],
}
HANDOFF = {
    "mode": "handoff", "title": "Result", "summary": "What changed",
    "sections": [{"kind": "explanation", "title": "Flow", "body": "An explanation, not a screenshot", "html": "<h2>Add → Save → Reload</h2>"}],
    "checks": [{"text": "Reload keeps tasks", "status": "unverified", "evidence": "Browser test not run"}],
}


class CompanionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="showwork companion ")
        self.project = Path(self.temp.name)
        self.store_dir = tempfile.TemporaryDirectory(prefix="showwork store ")
        self.addCleanup(self.store_dir.cleanup)
        env = patch.dict(os.environ, {"SHOWWORK_STORE": self.store_dir.name, "SHOWWORK_NO_APP": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.server = COMPANION.CompanionServer(self.project)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.opener.open(self.server.url, timeout=3).close()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        shutil.rmtree(self.server.root.parent)
        self.temp.cleanup()

    def test_temporary_path_is_stable_private_and_does_not_write_project(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'path', '--project', str(self.project)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.server.root)
        self.assertFalse(self.server.root.is_relative_to(self.project))
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertEqual(COMPANION.directory(self.project / '.'), self.server.root)
        if os.name == 'posix':
            self.assertTrue(self.server.root.is_relative_to(Path('/tmp').resolve()))
            self.assertEqual(self.server.root.parent.stat().st_mode & 0o777, 0o700)
        with tempfile.TemporaryDirectory() as other:
            other_root = COMPANION.directory(other)
            self.addCleanup(shutil.rmtree, other_root.parent)
            self.assertNotEqual(other_root, self.server.root)

    @unittest.skipUnless(os.name == 'posix', 'POSIX permissions and symlinks')
    def test_temporary_storage_refuses_symlink_or_public_root(self):
        import runtime
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / f'showwork-{os.getuid()}'
            with patch.object(runtime, 'temporary_root', return_value=base):
                root.symlink_to(self.project, target_is_directory=True)
                with self.assertRaises(ValueError):
                    COMPANION.directory(self.project)
                root.unlink()
                root.mkdir(mode=0o755)
                root.chmod(0o755)
                with self.assertRaises(ValueError):
                    COMPANION.directory(self.project)
        self.assertEqual(list(self.project.iterdir()), [])

    def publish(self, page):
        source = self.project / "page-source.json"
        source.write_text(json.dumps(page))
        return COMPANION.publish(self.project, source)

    def get(self, path):
        return self.opener.open(self.server.origin + path, timeout=3)

    def post(self, data, origin=None):
        request = Request(self.server.origin + "/api/choice", data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json", "Origin": origin or self.server.origin})
        return self.opener.open(request, timeout=3)

    def test_page_and_cookie_bootstrap(self):
        expected = self.publish(DECISION)
        with self.get("/api/view") as response:
            self.assertEqual(json.load(response)["page"], {k: v for k, v in expected.items() if k != "report"})
        with self.get("/") as response:
            self.assertIn(b"Showwork", response.read())
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_unauthorized_reader_cannot_see_page(self):
        self.publish(DECISION)
        with self.assertRaises(HTTPError) as failure:
            urlopen(self.server.origin + "/api/view", timeout=3)
        self.assertEqual(failure.exception.code, 403)

    def test_unknown_host_is_rejected_even_with_key(self):
        request = Request(self.server.url, headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as failure:
            urlopen(request, timeout=3)
        self.assertEqual(failure.exception.code, 403)

    def test_second_session_does_not_overwrite_first_session_cookie(self):
        self.publish(DECISION)
        other = COMPANION.CompanionServer(self.project)
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            self.opener.open(other.url, timeout=3).close()
            with self.get("/api/view") as response:
                self.assertEqual(json.load(response)["page"]["title"], DECISION["title"])
            with self.opener.open(other.origin + "/api/view", timeout=3) as response:
                self.assertEqual(response.status, 200)
        finally:
            other.shutdown()
            other.server_close()
            thread.join(timeout=3)

    def test_valid_selection_records_only_current_choice(self):
        page = self.publish(DECISION)
        with self.post({"version": page["version"], "choice": "board"}) as response:
            self.assertTrue(json.load(response)["recorded"])
        event = json.loads((COMPANION.store.report_dir(page["report"]) / "events.jsonl").read_text())
        self.assertEqual(event["version"], page["version"])
        self.assertEqual(event["choice"], "board")

    def test_stale_selection_cannot_answer_revised_question(self):
        old = self.publish(DECISION)
        self.publish(DECISION)
        with self.assertRaises(HTTPError) as failure:
            self.post({"version": old["version"], "choice": "board"})
        self.assertEqual(failure.exception.code, 409)
        self.assertFalse((COMPANION.store.report_dir(old["report"]) / "events.jsonl").exists())

    def test_cross_origin_choice_is_rejected(self):
        page = self.publish(DECISION)
        with self.assertRaises(HTTPError) as failure:
            self.post({"version": page["version"], "choice": "board"}, origin="http://attacker.example")
        self.assertEqual(failure.exception.code, 403)

    def test_handoff_has_no_approval_action(self):
        page = self.publish(HANDOFF)
        with self.assertRaises(HTTPError) as failure:
            self.post({"version": page["version"], "choice": "approve"})
        self.assertEqual(failure.exception.code, 400)

    def test_unknown_option_is_not_recorded(self):
        page = self.publish(DECISION)
        with self.assertRaises(HTTPError):
            self.post({"version": page["version"], "choice": "not-an-option"})
        self.assertFalse((COMPANION.store.report_dir(page["report"]) / "events.jsonl").exists())

    def test_attachment_is_copied_and_unrelated_files_are_not_served(self):
        image = self.project / "screen.png"
        image.write_bytes(b"captured-image")
        page = copy.deepcopy(HANDOFF)
        page["sections"][0].pop("html")
        page["sections"][0]["image"] = "screen.png"
        published = self.publish(page)
        image.write_bytes(b"changed")
        with self.get("/" + published["sections"][0]["image"]) as response:
            self.assertEqual(response.read(), b"captured-image")
        for path in ["/assets/../page.json", "/assets/%2e%2e/page.json", "/page-source.json"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as failure:
                self.get(path)
            self.assertEqual(failure.exception.code, 404)

    def test_invalid_publish_preserves_current_page(self):
        first = self.publish(DECISION)
        invalid = copy.deepcopy(HANDOFF)
        invalid["checks"][0]["status"] = "done"
        with self.assertRaises(ValueError):
            self.publish(invalid)
        with self.get("/api/view") as response:
            self.assertEqual(json.load(response)["page"]["version"], first["version"])

    def test_text_only_options_and_duplicate_ids_are_rejected(self):
        for kind in ["no-visual", "duplicate"]:
            invalid = copy.deepcopy(DECISION)
            if kind == "no-visual":
                invalid["options"][0].pop("html")
            else:
                invalid["options"][1]["id"] = "list"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.publish(invalid)

    def test_files_to_review_read_code_from_the_project(self):
        (self.project / "src").mkdir()
        (self.project / "src" / "store.ts").write_text("one\ntwo\nthree\nfour\n")
        page = copy.deepcopy(HANDOFF)
        page["files"] = [
            {"path": "src/store.ts", "why": "Saves tasks", "lines": [2, 3]},
            {"path": "src/store.ts", "why": "Whole file"},
            {"path": "api.py", "why": "Diff given by the author", "diff": True, "code": "@@ -1 +1 @@\n-a\n+b"},
        ]
        files = self.publish(page)["files"]
        self.assertEqual((files[0]["code"], files[0]["start_line"]), ("two\nthree", 2))
        self.assertNotIn("lines", files[0])
        self.assertEqual(files[1]["code"], "one\ntwo\nthree\nfour\n")
        self.assertEqual(files[2]["code"], "@@ -1 +1 @@\n-a\n+b")

    def test_files_to_review_stay_inside_the_project(self):
        outside = Path(self.temp.name).parent / "outside-showwork-test.txt"
        (self.project / ".env").write_text("SECRET=1")
        (self.project / ".ENV").write_text("SECRET=1")
        (self.project / ".Env.local").write_text("SECRET=1")
        (self.project / ".GIT").mkdir()
        (self.project / ".GIT" / "config").write_text("url = https://user:SECRET@example.com/r.git")
        (self.project / "blob.bin").write_bytes(b"\xff\xfe\x00")
        first = self.publish(HANDOFF)
        cases = {"outside": {"path": "../" + outside.name}, "missing": {"path": "nope.py"}, "env": {"path": ".env"},
                 "env upper": {"path": ".ENV"}, "env mixed": {"path": ".Env.local"}, "git upper": {"path": ".GIT/config"},
                 "binary": {"path": "blob.bin"}, "both": {"path": "x.py", "code": "x", "lines": [1, 1]},
                 "bad lines": {"path": "x.py", "lines": [3, 1]}, "no why": {"path": "x.py", "code": "x", "why": ""}}
        outside.write_text("private")
        try:
            for name, extra in cases.items():
                page = copy.deepcopy(HANDOFF)
                page["files"] = [{"why": "Reason", **extra}]
                with self.subTest(case=name), self.assertRaises(ValueError):
                    self.publish(page)
            decision = copy.deepcopy(DECISION)
            decision["files"] = [{"path": "x.py", "why": "Reason", "code": "x"}]
            with self.assertRaises(ValueError):
                self.publish(decision)
        finally:
            outside.unlink()
        with self.get("/api/view") as response:
            self.assertEqual(json.load(response)["page"]["version"], first["version"])

    def test_events_cli_filters_previous_page(self):
        old = self.publish(DECISION)
        self.post({"version": old["version"], "choice": "board"}).close()
        current = self.publish(DECISION)
        result = subprocess.run([sys.executable, str(SCRIPT), "events", "--project", str(self.project)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["report"], current["report"]["id"])
        self.assertEqual((out["version"], out["open"], out["events"]), (current["version"], True, []))

    def cli(self, *args, project=None):
        env = {**os.environ}
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--project", str(project or self.project)],
                              capture_output=True, text=True, timeout=10, env=env)

    def test_start_shows_a_working_marker_until_publish_or_stop(self):
        started = self.cli("start", "--type", "review", "--agent", "claude", "--title", "Login review")
        self.assertEqual(started.returncode, 0, started.stderr)
        out = json.loads(started.stdout)
        self.assertTrue(Path(out["directory"]).is_dir())
        self.assertEqual((out["type"], out["app"]), ("review", "disabled"))
        project_id = COMPANION.store.project_identity(self.project)["id"]
        running = Path(self.store_dir.name) / "projects" / project_id / "running"
        self.assertTrue((running.parent / "project.json").is_file())
        marker = json.loads((running / (out["run"] + ".json")).read_text())
        self.assertEqual((marker["type"], marker["title"], marker["agent"]), ("review", "Login review", "claude"))
        # starting the same type again replaces the marker instead of adding one
        again = json.loads(self.cli("start", "--type", "review").stdout)["run"]
        self.assertNotEqual(again, out["run"])
        self.assertEqual([p.stem for p in running.glob("*.json")], [again])
        self.cli("start", "--type", "plan")
        self.assertEqual(len(list(running.glob("*.json"))), 2)
        page = Path(out["directory"]) / "review.json"
        page.write_text(json.dumps({**HANDOFF, "checks": []}))
        published = self.cli("publish", "--file", str(page), "--type", "review")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse((running / (again + ".json")).exists())
        # a stopped run without a report leaves nothing behind
        self.assertEqual(self.cli("stop", "--type", "plan").returncode, 0)
        self.assertEqual(list(running.glob("*.json")), [])

    def test_each_publish_creates_a_new_report(self):
        a, b = self.publish(DECISION), self.publish(DECISION)
        self.assertNotEqual(a["report"]["id"], b["report"]["id"])
        self.assertEqual(len(COMPANION.store.list_reports(a["report"]["project_id"])), 2)

    def test_plan_and_review_may_omit_checks(self):
        page = copy.deepcopy(HANDOFF)
        page.pop("checks")
        source = self.project / "nochecks.json"
        source.write_text(json.dumps(page))
        for kind in ["plan", "review"]:
            COMPANION.publish(self.project, source, report_type=kind)
        with self.assertRaises(ValueError):
            COMPANION.publish(self.project, source, report_type="result")

    def test_type_and_agent_recorded(self):
        source = self.project / "d.json"
        source.write_text(json.dumps(DECISION))
        meta = COMPANION.publish(self.project, source, report_type="verify", agent="codex")["report"]
        self.assertEqual((meta["type"], meta["agent"]), ("verify", "codex"))
        self.assertEqual(COMPANION.publish(self.project, source)["report"]["type"], "result")

    def test_events_scoped_to_worktree(self):
        with tempfile.TemporaryDirectory(prefix="showwork repo ") as repo:
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
            wt = Path(repo).parent / (Path(repo).name + "-wt")
            subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "other", str(wt)], check=True)
            self.addCleanup(shutil.rmtree, wt, True)
            source = Path(self.project) / "scope.json"
            source.write_text(json.dumps(DECISION))
            page = COMPANION.publish(repo, source)
            server = COMPANION.CompanionServer(repo)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                opener.open(server.url, timeout=3).close()
                request = Request(server.origin + "/api/choice", data=json.dumps({"version": page["version"], "choice": "list"}).encode(),
                                  headers={"Content-Type": "application/json", "Origin": server.origin})
                opener.open(request, timeout=3).close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                shutil.rmtree(server.root.parent)
            self.assertEqual(json.loads(self.cli("events", project=repo).stdout)["events"][0]["choice"], "list")
            self.assertEqual(json.loads(self.cli("events", project=wt).stdout),
                             {"report": None, "version": None, "open": False, "events": []})

    def test_subfolder_shares_the_repository_worktree(self):
        with tempfile.TemporaryDirectory(prefix="showwork repo ") as repo:
            subprocess.run(["git", "init", "-q", repo], check=True)
            sub = Path(repo) / "sub"
            sub.mkdir()
            source = Path(self.project) / "sub.json"
            source.write_text(json.dumps(DECISION))
            decision = COMPANION.publish(repo, source)["report"]
            out = json.loads(self.cli("events", "--report", decision["id"], project=sub).stdout)
            self.assertEqual((out["report"], out["open"]), (decision["id"], True))
            source.write_text(json.dumps(HANDOFF))
            COMPANION.publish(sub, source)
            out = json.loads(self.cli("events", "--report", decision["id"], project=repo).stdout)
            self.assertEqual((out["report"], out["open"]), (decision["id"], False))

    def test_closed_decision_rejects_choice(self):
        decision = self.publish(DECISION)
        self.publish(HANDOFF)
        with self.assertRaises(HTTPError) as failure:
            self.post({"version": decision["version"], "choice": "list"})
        self.assertEqual(failure.exception.code, 409)
        self.assertFalse((COMPANION.store.report_dir(decision["report"]) / "events.jsonl").exists())

    def run_open_app(self, running, store=None):
        calls = []

        def fake(command, **kwargs):
            calls.append(command)
            out = ("true" if running else "false") + "\n" if command[0] == "osascript" else ""
            return subprocess.CompletedProcess(command, 0, out, "")

        with patch.dict(os.environ), patch.object(sys, "platform", "darwin"), patch.object(COMPANION.subprocess, "run", fake):
            os.environ.pop("SHOWWORK_NO_APP", None)
            os.environ.pop("SHOWWORK_STORE", None)
            if store:
                os.environ["SHOWWORK_STORE"] = store
            return COMPANION.open_app(), calls

    def test_open_app_disabled_for_custom_store(self):
        status, calls = self.run_open_app(True, store=self.store_dir.name)
        self.assertEqual(status, "disabled")
        self.assertEqual(calls, [])

    def test_open_app_does_not_reopen_running_app(self):
        status, calls = self.run_open_app(True)
        self.assertEqual(status, "opened")
        self.assertNotIn("open", [c[0] for c in calls])

    def test_open_app_launches_in_background_when_not_running(self):
        status, calls = self.run_open_app(False)
        self.assertEqual(status, "opened")
        self.assertIn(["open", "-g", "-a", "Showwork", "--args", "--background"], calls)

    def test_publish_never_writes_project(self):
        self.publish(DECISION)
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), ["page-source.json"])

    def test_publish_without_app_reports_disabled(self):
        source = self.project / "cli.json"
        source.write_text(json.dumps(DECISION))
        result = self.cli("publish", "--file", str(source), "--type", "plan", "--agent", "claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual((out["app"], out["mode"]), ("disabled", "decision"))
        self.assertTrue(Path(out["path"], "page.json").is_file())


class SimulatorCleanupTests(unittest.TestCase):
    def test_cleanup_attempts_both_owners_after_browser_failure(self):
        with patch.object(COMPANION.browser, 'close_run', side_effect=ValueError('browser failed')), \
             patch.object(COMPANION.browser, 'close_orphans') as browser_orphans, \
             patch.object(COMPANION.ios_simulator, 'close_run') as ios_run, \
             patch.object(COMPANION.ios_simulator, 'close_orphans') as ios_orphans:
            with self.assertRaisesRegex(ValueError, 'browser failed'):
                COMPANION.store.cleanup_sessions('project', 'run')
            browser_orphans.assert_called_once_with('project')
            ios_run.assert_called_once_with('project', 'run')
            ios_orphans.assert_called_once_with('project')

    def test_stop_completes_run_before_scanning_both_session_owners(self):
        from contextlib import redirect_stdout
        from io import StringIO
        events = []
        with tempfile.TemporaryDirectory() as project, \
             patch.object(sys, 'argv', ['companion.py','stop','--project',project]), \
             patch.object(COMPANION.store, 'project_identity', return_value={'id':'project'}), \
             patch.object(COMPANION.store, 'worktree_key', return_value='tree'), \
             patch.object(COMPANION.store, 'finish_run', side_effect=lambda *args: events.append('finish') or 'run'), \
             patch.object(COMPANION.store, 'cleanup_sessions', side_effect=lambda *args: events.append(('cleanup', args))), \
             redirect_stdout(StringIO()):
            self.assertEqual(COMPANION.main(), 0)
        self.assertEqual(events, ['finish', ('cleanup', ('project', 'run'))])


if __name__ == "__main__":
    unittest.main()
