"""Run with: python3 -m unittest discover -s tests -p 'test_install.py'."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("install_codex", ROOT / "scripts" / "install_codex.py")
INSTALLER = module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class InstallTest(unittest.TestCase):
    def test_adds_automatic_routing_preserving_existing_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            path = project / "AGENTS.md"
            original = b"# Project instructions\r\nKeep the public API stable.\r\n"
            path.write_bytes(original)
            INSTALLER.install(project)
            installed = path.read_bytes()
            self.assertTrue(installed.startswith(original))
            self.assertIn(b".agents/skills/showwork/SKILL.md", installed)
            self.assertNotIn(b"{{SKILLS_ROOT}}", installed)
            self.assertEqual(installed.count(INSTALLER.START.encode()), 1)
            INSTALLER.install(project)
            self.assertEqual(path.read_bytes(), installed)

    def test_upgrades_old_skill_only_install_without_recopying_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            INSTALLER.install(project)
            path = project / "AGENTS.md"
            path.unlink()  # Previous releases installed only skills.
            skill = project / ".agents" / "skills" / "showwork" / "SKILL.md"
            before = skill.stat().st_mtime_ns
            self.assertEqual(INSTALLER.install(project), 0)
            self.assertTrue(path.is_file())
            self.assertEqual(skill.stat().st_mtime_ns, before)

    def test_refreshes_only_managed_instruction_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            path = project / "AGENTS.md"
            prefix, suffix = "Keep before.\n", "\nKeep after.\n"
            path.write_text(prefix + INSTALLER.START + "\nOld rule\n" + INSTALLER.END + suffix)
            INSTALLER.install(project)
            updated = path.read_text()
            self.assertTrue(updated.startswith(prefix + INSTALLER.START))
            self.assertTrue(updated.endswith(INSTALLER.END + suffix))
            self.assertNotIn("Old rule", updated)

    def test_malformed_instruction_markers_prevent_partial_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            path = project / "AGENTS.md"
            original = INSTALLER.START + "\nUser text with no end marker."
            path.write_text(original)
            with self.assertRaisesRegex(ValueError, "Malformed Showwork markers"):
                INSTALLER.install(project)
            self.assertEqual(path.read_text(), original)
            self.assertFalse((project / ".agents").exists())

    def test_uses_override_when_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            ordinary = project / "AGENTS.md"
            override = project / "AGENTS.override.md"
            ordinary.write_text("Original project instructions.")
            override.write_text("Active override.")
            INSTALLER.install(project)
            self.assertEqual(ordinary.read_text(), "Original project instructions.")
            self.assertTrue(override.read_text().startswith("Active override."))
            self.assertIn(INSTALLER.START, override.read_text())

    def test_instruction_symlink_is_not_followed(self):
        for name in ["AGENTS.md", "AGENTS.override.md"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary) / "project"
                project.mkdir()
                external = Path(temporary) / "external.md"
                external.write_text("Untouched")
                (project / name).symlink_to(external)
                with self.assertRaisesRegex(ValueError, "Expected a real instruction file"):
                    INSTALLER.install(project)
                self.assertEqual(external.read_text(), "Untouched")
                self.assertFalse((project / ".agents").exists())

    def test_empty_override_does_not_hide_existing_project_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            ordinary = project / "AGENTS.md"
            override = project / "AGENTS.override.md"
            ordinary.write_text("Keep existing guidance.")
            override.touch()
            INSTALLER.install(project)
            self.assertEqual(override.read_bytes(), b"")
            self.assertTrue(ordinary.read_text().startswith("Keep existing guidance."))
            self.assertIn(INSTALLER.START, ordinary.read_text())

    def test_install_repeat_conflict_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.assertEqual(INSTALLER.install(project), 4)
            self.assertEqual(INSTALLER.install(project), 0)
            skills = project / ".agents" / "skills"
            for name in INSTALLER.SKILLS:
                self.assertEqual(INSTALLER.contents(skills / name), INSTALLER.contents(ROOT / "skills" / name))

            custom = skills / "showwork" / "personal-notes.md"
            custom.write_text("Keep this", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Existing install differs"):
                INSTALLER.install(project)
            self.assertEqual(custom.read_text(encoding="utf-8"), "Keep this")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            existing = project / ".agents" / "skills" / "showwork-verify"
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text("User version", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Existing install differs"):
                INSTALLER.install(project)
            self.assertFalse((existing.parent / "showwork").exists())
            self.assertFalse((project / "AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            external = Path(temporary) / "external"
            project.mkdir()
            external.mkdir()
            (project / ".agents").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Expected a real directory"):
                INSTALLER.install(project)
            self.assertEqual(list(external.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
