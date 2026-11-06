from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "showwork" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = spec_from_file_location("store", SCRIPTS / "store.py")
STORE = module_from_spec(SPEC)
SPEC.loader.exec_module(STORE)


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def page(title="T", mode="handoff", version=1):
    return {"mode": mode, "title": title, "version": version, "published_at": "2026-01-01T00:00:00+00:00"}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        patcher = patch.dict(os.environ, {"SHOWWORK_STORE": str(self.tmp / "store")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        git("init", cwd=repo)
        git("commit", "--allow-empty", "-m", "i", cwd=repo)
        return repo

    def test_bare_repo_layouts_are_named_after_the_repository(self):
        for layout, expected in (("Frendy-App/.bare", "Frendy-App"), ("plain.git", "plain")):
            bare = self.tmp / layout
            bare.mkdir(parents=True)
            git("init", "--bare", cwd=bare)
            wt = self.tmp / ("wt-" + expected)
            git("worktree", "add", "--orphan", "-b", "main-" + expected, str(wt), cwd=bare)
            self.assertEqual(STORE.project_identity(wt)["name"], expected)

    def test_worktrees_share_one_project(self):
        repo = self.repo()
        wt = self.tmp / "wt"
        git("worktree", "add", str(wt), "-b", "feature/x", cwd=repo)
        a, b = STORE.project_identity(repo), STORE.project_identity(wt)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["name"], "repo")
        m1 = STORE.save_report(repo, page(), [], "handoff", "claude")
        m2 = STORE.save_report(wt, page(), [], "handoff", "claude")
        self.assertIn(m1["branch"], ("main", "master"))
        self.assertEqual(m2["branch"], "feature/x")
        self.assertEqual(m1["project_id"], m2["project_id"])

    def test_detached_and_non_git(self):
        repo = self.repo()
        git("checkout", "--detach", cwd=repo)
        self.assertTrue(STORE.git_state(repo)["branch"].startswith("detached@"))
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(STORE.git_state(plain), {"branch": None, "commit": None})
        self.assertEqual(STORE.project_identity(plain)["id"],
                         hashlib.sha256(os.path.realpath(plain).encode()).hexdigest()[:16])

    def test_reports_are_never_overwritten(self):
        plain = self.tmp / "p"
        plain.mkdir()
        a = STORE.save_report(plain, page("A"), [], "handoff", "x")
        b = STORE.save_report(plain, page("B"), [], "handoff", "x")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual([m["id"] for m in STORE.list_reports(a["project_id"])], sorted([a["id"], b["id"]]))
        self.assertEqual(STORE.list_reports(a["project_id"])[0]["title"], "A")

    def test_concurrent_publish_keeps_both(self):
        plain = self.tmp / "p"
        plain.mkdir()
        metas = []
        threads = [threading.Thread(target=lambda: metas.append(STORE.save_report(plain, page(), [], "handoff", "x")))
                   for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len({m["id"] for m in metas}), 8)
        pid = metas[0]["project_id"]
        self.assertEqual(len(STORE.list_reports(pid)), 8)
        self.assertEqual(list((STORE.store_root() / "projects" / pid / "reports").glob(".pending-*")), [])

    def test_project_json_exists_before_report_appears(self):
        plain = self.tmp / "p"
        plain.mkdir()
        project_json = STORE.store_root() / "projects" / STORE.project_identity(plain)["id"] / "project.json"
        real_rename, seen = os.rename, []

        def checked_rename(src, dst):
            seen.append(project_json.is_file())
            return real_rename(src, dst)

        with patch.object(STORE.os, "rename", checked_rename):
            STORE.save_report(plain, page(), [], "handoff", "x")
        self.assertEqual(seen, [True])

    def test_broken_entries_are_skipped(self):
        plain = self.tmp / "p"
        plain.mkdir()
        good = STORE.save_report(plain, page(), [], "handoff", "x")
        reports = STORE.report_dir(good).parent
        (reports / ".pending-x").mkdir()
        (reports / "bad").mkdir()
        (reports / "bad" / "meta.json").write_text("{")
        (reports / "note.txt").write_text("hi")
        self.assertEqual([m["id"] for m in STORE.list_reports(good["project_id"])], [good["id"]])

    def test_store_is_private(self):
        root = STORE.store_root()
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((root / "projects").stat().st_mode & 0o777, 0o700)

    def test_decision_open_until_newer_report_from_same_worktree(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir(), b.mkdir()
        d = STORE.save_report(a, page(mode="decision"), [], "decision", "x")
        self.assertTrue(STORE.is_open(d))
        STORE.save_report(b, page(), [], "handoff", "x")
        self.assertTrue(STORE.is_open(d))
        STORE.save_report(a, page(), [], "handoff", "x")
        self.assertFalse(STORE.is_open(d))

    def test_worktree_is_git_top_level(self):
        repo = self.repo()
        sub = repo / "sub"
        sub.mkdir()
        d = STORE.save_report(repo, page(mode="decision"), [], "decision", "x")
        h = STORE.save_report(sub, page(), [], "handoff", "x")
        self.assertEqual(d["worktree"], os.path.realpath(repo))
        self.assertEqual(h["worktree"], d["worktree"])
        self.assertFalse(STORE.is_open(d))
        self.assertEqual(STORE.latest_report(repo)["id"], h["id"])
        self.assertEqual(STORE.latest_report(sub, "decision")["id"], d["id"])
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(STORE.worktree_key(plain), os.path.realpath(plain))

    def test_deleting_newer_report_keeps_decision_closed(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir(), b.mkdir()
        d = STORE.save_report(a, page(mode="decision"), [], "decision", "x")
        elsewhere = STORE.save_report(b, page(mode="decision"), [], "decision", "x")
        h = STORE.save_report(a, page(), [], "handoff", "x")
        marker = __import__("json").loads((STORE.report_dir(d) / "closed.json").read_text())
        self.assertEqual(marker["by"], h["id"])
        self.assertIn("time", marker)
        self.assertFalse((STORE.report_dir(elsewhere) / "closed.json").exists())
        self.assertFalse((STORE.report_dir(h) / "closed.json").exists())
        __import__("shutil").rmtree(STORE.report_dir(h))
        self.assertFalse(STORE.is_open(d))
        self.assertTrue(STORE.is_open(elsewhere))
        # A later report keeps the first closer instead of rewriting the marker.
        STORE.save_report(a, page(), [], "handoff", "x")
        self.assertEqual(__import__("json").loads((STORE.report_dir(d) / "closed.json").read_text())["by"], h["id"])

    def test_closed_marker_failure_does_not_fail_publish(self):
        plain = self.tmp / "p"
        plain.mkdir()
        d = STORE.save_report(plain, page(mode="decision"), [], "decision", "x")
        real = STORE.write_json

        def failing(path, value):
            if path.name == "closed.json":
                raise OSError("disk full")
            return real(path, value)

        with patch.object(STORE, "write_json", failing):
            h = STORE.save_report(plain, page(), [], "handoff", "x")
        self.assertTrue((STORE.report_dir(h) / "meta.json").is_file())
        self.assertFalse(STORE.is_open(d))

    def test_credential_stripping_never_raises(self):
        self.assertEqual(STORE.strip_credentials("https://[YOUR_TOKEN]@github.com/o/r.git"), "https://github.com/o/r.git")
        out = STORE.strip_credentials("https://user:pa[ss@github.com/o/r.git")
        self.assertEqual(out, "https://github.com/o/r.git")
        self.assertNotIn("pa[ss", out or "")
        for secret in ("to#k", "to?k", "to#k?x"):
            self.assertEqual(STORE.strip_credentials("https://u:%s@host/r" % secret), "https://host/r")
        self.assertEqual(STORE.strip_credentials("ssh://git@host/r"), "ssh://git@host/r")
        self.assertEqual(STORE.strip_credentials("ssh://git:pw#x@host/r"), "ssh://git@host/r")
        self.assertEqual(STORE.strip_credentials("hg::https://u:TOK@host/r"), "hg::https://host/r")
        self.assertEqual(STORE.strip_credentials("persistent-https://TOKEN@host/r"), "persistent-https://host/r")

    def test_older_decision_with_incomplete_meta_does_not_fail_publish(self):
        plain = self.tmp / "p"
        plain.mkdir()
        d = STORE.save_report(plain, page(mode="decision"), [], "decision", "x")
        path = STORE.report_dir(d) / "meta.json"
        meta = __import__("json").loads(path.read_text())
        del meta["project_id"]
        path.write_text(__import__("json").dumps(meta))
        h = STORE.save_report(plain, page(), [], "handoff", "x")
        self.assertTrue((STORE.report_dir(h) / "meta.json").is_file())

    def test_remote_credentials_are_not_stored(self):
        self.assertEqual(STORE.strip_credentials("https://user:TOKEN@example.com:8443/r.git"), "https://example.com:8443/r.git")
        self.assertEqual(STORE.strip_credentials("https://TOKEN@github.com/o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(STORE.strip_credentials("https://github.com/o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(STORE.strip_credentials("git@github.com:o/r.git"), "git@github.com:o/r.git")
        self.assertIsNone(STORE.strip_credentials(None))
        repo = self.repo()
        git("remote", "add", "origin", "https://user:SECRETTOKEN@example.com/r.git", cwd=repo)
        meta = STORE.save_report(repo, page(), [], "handoff", "x")
        saved = (STORE.store_root() / "projects" / meta["project_id"] / "project.json").read_text()
        self.assertNotIn("SECRETTOKEN", saved)
        self.assertEqual(STORE.project_identity(repo)["remote"], "https://example.com/r.git")

    def test_read_events_skips_torn_and_non_object_lines(self):
        plain = self.tmp / "p"
        plain.mkdir()
        m = STORE.save_report(plain, page(mode="decision"), [], "decision", "x")
        e = STORE.append_event(m, "list")
        with open(STORE.report_dir(m) / "events.jsonl", "a", encoding="utf-8") as stream:
            stream.write('[1]\n"text"\n{"version": 1, "cho')
        self.assertEqual(STORE.read_events(m), [e])

    def test_ids_with_trailing_newline_are_rejected(self):
        self.assertIsNone(STORE.ID_PATTERN.match("abc\n"))
        self.assertEqual(STORE.list_reports("p\n"), [])
        with self.assertRaises(ValueError):
            STORE.report_dir({"project_id": "p\n", "id": "r"})
        with self.assertRaises(ValueError):
            STORE.report_dir({"project_id": "p", "id": "r\n"})

    def test_images_events_and_latest(self):
        plain = self.tmp / "p"
        plain.mkdir()
        img = self.tmp / "i.png"
        img.write_bytes(b"png")
        m = STORE.save_report(plain, page(mode="decision"), [(img, "assets/abc.png")], "decision", "x")
        self.assertEqual((STORE.report_dir(m) / "assets" / "abc.png").read_bytes(), b"png")
        self.assertEqual(STORE.latest_report(plain, "decision")["id"], m["id"])
        self.assertIsNone(STORE.latest_report(plain, "handoff"))
        e = STORE.append_event(m, "list")
        self.assertEqual(STORE.read_events(m), [e])
        self.assertEqual(set(e), {"version", "title", "choice", "time"})

    def test_agent_detection(self):
        self.assertEqual(STORE.detect_agent("codex"), "codex")
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            self.assertEqual(STORE.detect_agent(None), "claude")
        with patch.dict(os.environ, {"CODEX_SANDBOX": "1"}, clear=True):
            self.assertEqual(STORE.detect_agent(None), "codex")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(STORE.detect_agent(None), "unknown")


if __name__ == "__main__":
    unittest.main()
