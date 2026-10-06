import copy
from http.cookiejar import CookieJar
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
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
        self.server = COMPANION.CompanionServer(self.project)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.opener.open(self.server.url, timeout=3).close()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

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
            self.assertEqual(json.load(response)["page"], expected)
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
        event = json.loads((self.server.root / "events.jsonl").read_text())
        self.assertEqual(event["version"], page["version"])
        self.assertEqual(event["choice"], "board")

    def test_stale_selection_cannot_answer_revised_question(self):
        old = self.publish(DECISION)
        self.publish(DECISION)
        with self.assertRaises(HTTPError) as failure:
            self.post({"version": old["version"], "choice": "board"})
        self.assertEqual(failure.exception.code, 409)
        self.assertFalse((self.server.root / "events.jsonl").exists())

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
        self.assertFalse((self.server.root / "events.jsonl").exists())

    def test_attachment_is_copied_and_unrelated_files_are_not_served(self):
        image = self.project / "screen.png"
        image.write_bytes(b"captured-image")
        page = copy.deepcopy(HANDOFF)
        page["sections"][0].pop("html")
        page["sections"][0]["image"] = "screen.png"
        published = self.publish(page)
        image.write_bytes(b"changed")
        with self.get(published["sections"][0]["image"]) as response:
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

    def test_events_cli_filters_previous_page(self):
        old = self.publish(DECISION)
        self.post({"version": old["version"], "choice": "board"}).close()
        current = self.publish(DECISION)
        result = subprocess.run([sys.executable, str(SCRIPT), "events", "--project", str(self.project)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"version": current["version"], "events": []})


if __name__ == "__main__":
    unittest.main()
