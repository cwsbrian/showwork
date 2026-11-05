"""Run with: python3 -m unittest discover -s tests -p 'test_obsidian.py'."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "showwork" / "scripts"
HELPER = SCRIPTS / "obsidian_memory.py"
SPEC = spec_from_file_location("obsidian_mcp", SCRIPTS / "obsidian_mcp.py")
MCP = module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)


class ObsidianTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name).resolve()
        self.vault = base / "vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        projects = self.vault / "Work" / "03 Projects"
        for name in ("MindShift", "Janus Health"):
            (projects / name).mkdir(parents=True)
        (projects / "MindShift" / "Subscription meeting.md").write_text(
            "We will not use RevenueCat for subscriptions.\n", encoding="utf-8")
        (projects / "Janus Health" / "Billing.md").write_text(
            "Janus Health subscriptions use RevenueCat.\n", encoding="utf-8")
        # A same-named folder outside 03 Projects must never receive notes.
        (self.vault / "Archive" / "MindShift").mkdir(parents=True)
        self.config = base / "config" / "obsidian.json"
        self.selection = base / "config" / "project-selection.json"
        self.patches = [patch.object(MCP, "CONFIG", self.config), patch.object(MCP, "SELECTION", self.selection)]
        for item in self.patches:
            item.start()
        self.helper("location", str(self.vault))

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temporary.cleanup()

    def helper(self, *args, stdin="", check=True):
        result = subprocess.run([sys.executable, str(HELPER), "--config", str(self.config), *args],
                                input=stdin, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def select(self, *projects):
        self.selection.write_text(json.dumps({"mode": "manual" if projects else "auto", "projects": list(projects)}), encoding="utf-8")

    def test_save_uses_the_search_tool_project_folder_and_area(self):
        path = Path(self.helper("save", "--title", "No RevenueCat", "--project", "mindshift", "--area", "backend",
                                stdin="Decision: use store billing directly.").stdout.strip())
        self.assertEqual(path.parent, self.vault / "Work/03 Projects/MindShift/Architecture/Decisions/backend")
        text = path.read_text(encoding="utf-8")
        self.assertIn("type: showwork-decision", text)
        self.assertIn("status: confirmed", text)
        self.assertFalse(any((self.vault / "Archive/MindShift").iterdir()))
        found = MCP.search_notes({"project": "MindShift", "query": "store billing"})
        self.assertIn("Architecture/Decisions/backend", found)

    def test_project_without_location_saves_to_searchable_default_folder(self):
        result = self.helper("save", "--title", "First", "--project", "New App", "--area", "frontend", stdin="Use React.")
        path = Path(result.stdout.strip())
        self.assertEqual(path.parent, self.vault / "Showwork/New App/Architecture/Decisions/frontend")
        self.assertIn("default folder", result.stderr)
        self.assertIn("New App: Showwork/New App", MCP.list_projects({}))
        self.assertIn("Use React", MCP.search_notes({"project": "New App", "query": "React"}))

    def test_ambiguous_project_is_still_refused(self):
        projects = self.vault / "Work" / "03 Projects"
        (projects / "Alpha One").mkdir()
        (projects / "Alpha Two").mkdir()
        result = self.helper("save", "--title", "x", "--project", "Alpha", stdin="x", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("showwork-set-location", result.stderr)
        self.assertFalse((self.vault / "Showwork").exists())

    def test_no_vault_set_saves_under_documents(self):
        home = Path(self.temporary.name).resolve() / "home"
        home.mkdir()
        result = subprocess.run([sys.executable, str(HELPER), "--config", str(home / "missing.json"), "save",
                                 "--title", "x", "--project", "Solo"], input="x", capture_output=True, text=True,
                                env={"HOME": str(home), "PATH": "/usr/bin:/bin"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(result.stdout.strip()).is_relative_to(home / "Documents/Showwork/Solo/Architecture/Decisions/shared"))
        self.assertIn("no vault is set", result.stderr)

    def test_location_mapping_and_alias_are_shared_with_search(self):
        docs = self.vault / "Docs" / "Mobile app"
        docs.mkdir(parents=True)
        self.helper("location", "--project", "Mobile app", "--path", "Docs/Mobile app")
        self.helper("location", "--project", "Mobile app", "--alias", "mobi")
        listing = json.loads(self.helper("location").stdout)
        self.assertEqual(listing["discovered"]["Mobile app"], "Docs/Mobile app")
        path = Path(self.helper("save", "--title", "Push", "--project", "mobi", "--area", "mobile", stdin="x").stdout.strip())
        self.assertTrue(path.is_relative_to(docs))
        self.assertIn("Mobile app", MCP.list_projects({}))

    def test_current_summary_requires_replace_and_keeps_backup(self):
        args = ("save", "--kind", "current", "--title", "Backend", "--project", "MindShift", "--area", "backend")
        current = Path(self.helper(*args, stdin="v1").stdout.strip())
        self.assertEqual(current.name, "Current.md")
        self.assertNotEqual(self.helper(*args, stdin="v2", check=False).returncode, 0)
        self.helper(*args, "--replace", stdin="v2")
        self.assertIn("v2", current.read_text(encoding="utf-8"))
        self.assertEqual(len(list(current.parent.glob(".Current-*.md.bak"))), 1)

    def test_answer_context_honors_manual_selection_and_flags_unselected_project(self):
        self.select("MindShift")
        text = MCP.answer_context({"question": "Does Janus Health use RevenueCat?", "query": "RevenueCat"})
        self.assertIn("projects=['MindShift']", text)
        self.assertIn("NOT SELECTED", text)
        self.assertNotIn("Billing.md", text)
        quiet = MCP.answer_context({"question": "Do we use RevenueCat?", "recent": "Janus Health came up earlier", "query": "RevenueCat"})
        self.assertNotIn("NOT SELECTED", quiet)

    def test_answer_context_searches_every_selected_project_and_auto(self):
        self.select("MindShift", "Janus Health")
        both = MCP.answer_context({"question": "Who uses RevenueCat?", "query": "RevenueCat"})
        self.assertIn("Billing.md", both)
        self.assertIn("Subscription meeting.md", both)
        self.select()
        auto = MCP.answer_context({"question": "Does MindShift use RevenueCat?", "query": "RevenueCat"})
        self.assertIn("confidence=high", auto)
        self.assertNotIn("Billing.md", auto)
        named = MCP.answer_context({"question": "Do Janus Health and MindShift use RevenueCat?", "query": "RevenueCat"})
        self.assertIn("confidence=named", named)
        self.assertIn("Billing.md", named)
        self.assertIn("Subscription meeting.md", named)
        unclear = json.loads(MCP.answer_context({"question": "Do we use RevenueCat?"}))
        self.assertIn(unclear["status"], {"suggested", "unresolved"})


if __name__ == "__main__":
    unittest.main()
