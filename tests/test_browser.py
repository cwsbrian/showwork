import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "showwork" / "scripts"
SCRIPT = SCRIPTS / "companion.py"
sys.path.insert(0, str(SCRIPTS))


STORE = importlib.import_module("store")
BROWSER = importlib.import_module("browser")
CHROME = os.environ.get("SHOWWORK_CHROMIUM") or next((p for p in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium") if os.path.exists(p)), None)


def page():
    return {"mode": "handoff", "title": "T", "version": 1, "published_at": "2026-01-01T00:00:00+00:00"}


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True  # alive and not our child
    except OSError:
        return False


def wait_until(fn, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return fn()


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


@unittest.skipUnless(CHROME, "Chrome not found")
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = self.tmp / "repo"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        patcher = patch.dict(os.environ, {"SHOWWORK_STORE": str(self.tmp / "store"), "SHOWWORK_NO_APP": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.close_all)

    def close_all(self):
        pid = STORE.project_identity(self.project)["id"]
        for s in STORE.list_sessions(pid):
            if s["ended_at"] is None:
                BROWSER.close_browser(pid, s["id"])

    def test_open_requires_a_started_task(self):
        with self.assertRaisesRegex(ValueError, "start first"):
            BROWSER.open_browser(self.project, "about:blank")

    def test_open_starts_headless_chrome_and_close_ends_it(self):
        run = STORE.start_run(self.project, "result", "claude")
        s = BROWSER.open_browser(self.project, "data:text/html,<h1>hi</h1>", width=800, height=600)
        self.assertEqual((s["kind"], s["run"], s["width"], s["height"], s["ended_at"]), ("browser", run["id"], 800, 600, None))
        self.assertTrue(s["ws"].startswith(f"ws://127.0.0.1:{s['port']}/devtools/page/"))
        urlopen(f"http://127.0.0.1:{s['port']}/json/version", timeout=3).close()
        self.assertEqual([x["id"] for x in STORE.list_sessions(s["project_id"], run["id"])], [s["id"]])
        ended = BROWSER.close_browser(s["project_id"], s["id"])
        self.assertIsNotNone(ended["ended_at"])
        self.assertFalse(Path(s["profile"]).exists())
        self.assertTrue(wait_until(lambda: not pid_alive(s["pid"]), 5))
        self.assertEqual(BROWSER.close_browser(s["project_id"], s["id"]), ended)
        with self.assertRaises(ValueError):
            BROWSER.close_browser(s["project_id"], "nope")

    def test_publish_and_stop_close_the_tasks_browsers(self):
        STORE.start_run(self.project, "review", "claude")
        a = BROWSER.open_browser(self.project, "about:blank")
        STORE.save_report(self.project, page(), [], "review", "claude")
        self.assertIsNotNone(STORE.list_sessions(a["project_id"])[0]["ended_at"])
        STORE.start_run(self.project, "plan", "claude")
        b = BROWSER.open_browser(self.project, "about:blank")
        self.assertEqual(cli("stop", "--project", str(self.project), "--type", "plan").returncode, 0)
        self.assertTrue(wait_until(lambda: not pid_alive(b["pid"]), 5))

    def test_start_closes_orphaned_browsers(self):
        run = STORE.start_run(self.project, "review", "claude")
        s = BROWSER.open_browser(self.project, "about:blank")
        (STORE.store_root() / "projects" / s["project_id"] / "running" / f"{run['id']}.json").unlink()  # agent died
        self.assertEqual(cli("start", "--project", str(self.project), "--type", "plan").returncode, 0)
        self.assertTrue(wait_until(lambda: not pid_alive(s["pid"]), 5))
        self.assertIsNotNone(STORE.list_sessions(s["project_id"])[0]["ended_at"])

    def test_open_fails_cleanly_without_chrome(self):
        STORE.start_run(self.project, "result", "claude")
        with patch.dict(os.environ, {"SHOWWORK_CHROMIUM": "/nonexistent/chrome"}):
            with self.assertRaises(ValueError):
                BROWSER.open_browser(self.project, "about:blank")
        self.assertEqual(STORE.list_sessions(STORE.project_identity(self.project)["id"]), [])

    def test_cli_open_prints_the_cdp_endpoint(self):
        cli("start", "--project", str(self.project), "--type", "result")
        out = json.loads(cli("browser", "open", "--project", str(self.project), "--url", "about:blank").stdout)
        self.assertTrue(out["cdp"].startswith("http://127.0.0.1:"))
        self.assertEqual(json.loads(cli("browser", "close", "--project", str(self.project), "--session", out["session"]).stdout), {"closed": out["session"]})


class RunMarkerTests(unittest.TestCase):
    def test_a_newer_start_is_not_deleted_by_an_older_concurrent_start(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        with patch.dict(os.environ, {"SHOWWORK_STORE": str(tmp / "store")}):
            newer = "99990101-000000-000000-ffff"
            running = STORE.store_root() / "projects" / STORE.project_identity(repo)["id"] / "running"
            running.mkdir(parents=True)
            (running / f"{newer}.json").write_text(json.dumps({
                "id": newer, "type": "review", "worktree": STORE.worktree_key(repo)}))
            STORE.start_run(repo, "review", "claude")
            self.assertTrue((running / f"{newer}.json").exists())


if __name__ == "__main__":
    unittest.main()
