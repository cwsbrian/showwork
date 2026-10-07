"""Run with: python3 -m unittest discover -s tests -p 'test_install.py'."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("install_codex", ROOT / "scripts" / "install_codex.py")
INSTALLER = module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class InstallTest(unittest.TestCase):
    def test_claude_user_install_update_preserves_settings_and_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            config = home / "claude profile"
            config.mkdir()
            instructions = config / "CLAUDE.md"
            instructions.write_bytes(b"My Claude rules.\r\n")
            settings = config / "settings.json"
            settings.write_text('{"hooks":{"custom":[]}}')
            with patch.object(INSTALLER.Path, "home", return_value=home), patch.object(INSTALLER.os, "environ", {"CLAUDE_CONFIG_DIR": str(config)}):
                self.assertEqual(INSTALLER.install(runtime="claude"), 4)
                self.assertTrue(instructions.read_bytes().startswith(b"My Claude rules.\r\n"))
                self.assertIn((config / "skills/showwork/SKILL.md").as_posix(), instructions.read_text())
                self.assertEqual(INSTALLER.install(runtime="claude"), 0)
                skill = config / "skills/showwork/SKILL.md"
                skill.write_text("Local Claude changes")
                self.assertEqual(INSTALLER.install(runtime="claude"), 1)
                backups = list((config / "showwork-backups").glob("update-*/showwork/SKILL.md"))
                self.assertEqual(backups[0].read_text(), "Local Claude changes")
            self.assertEqual(settings.read_text(), '{"hooks":{"custom":[]}}')
            self.assertFalse((home / ".agents").exists())
            self.assertFalse((home / ".codex").exists())

    def test_both_preflight_rejects_invalid_claude_before_codex_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".claude").mkdir()
            (project / ".claude/CLAUDE.md").write_text(INSTALLER.START)
            with patch("sys.argv", ["install_codex.py", "--target", str(project)]), self.assertRaises(SystemExit) as result:
                INSTALLER.main()
            self.assertEqual(result.exception.code, 1)
            self.assertFalse((project / ".agents").exists())
            (project / ".claude/CLAUDE.md").unlink()
            (project / ".claude/.showwork-install.lock").mkdir()
            with patch("sys.argv", ["install_codex.py", "--target", str(project)]), self.assertRaises(SystemExit):
                INSTALLER.main()
            self.assertFalse((project / ".agents").exists())

    def test_claude_symlink_refused_before_skills_and_failed_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".claude").mkdir()
            external = project / "external.md"
            external.write_text("Keep")
            instructions = project / ".claude/CLAUDE.md"
            instructions.symlink_to(external)
            with self.assertRaisesRegex(ValueError, "Expected a real instruction file"):
                INSTALLER.install(project, runtime="claude")
            instructions.unlink()
            with patch.object(INSTALLER, "write_instructions", side_effect=OSError("Write failed")), self.assertRaises(OSError):
                INSTALLER.install(project, runtime="claude")
            self.assertFalse(instructions.exists())
            self.assertEqual(list((project / ".claude/skills").iterdir()), [])
            self.assertEqual(external.read_text(), "Keep")

    def test_user_install_preserves_global_guidance_and_leaves_projects_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = home / "project"
            project.mkdir()
            with patch.object(INSTALLER.Path, "home", return_value=home), patch.object(INSTALLER.os, "environ", {}):
                self.assertEqual(INSTALLER.install(), 4)
                instructions = home / ".codex" / "AGENTS.md"
                self.assertIn((home / ".agents/skills/showwork/SKILL.md").as_posix(), instructions.read_text())
                instructions.write_text("My global rules.\n" + instructions.read_text())
                before = instructions.read_bytes()
                self.assertEqual(INSTALLER.install(), 0)
                self.assertEqual(instructions.read_bytes(), before)
                self.assertEqual(list(project.iterdir()), [])
                skill = home / ".agents/skills/showwork/SKILL.md"
                skill.write_text("My customized skill")
                self.assertEqual(INSTALLER.install(), 1)
                backups = list((home / ".agents/showwork-backups").glob("update-*/showwork/SKILL.md"))
                self.assertEqual(backups[-1].read_text(), "My customized skill")
                self.assertEqual(skill.read_bytes(), (ROOT / "skills/showwork/SKILL.md").read_bytes())
                self.assertEqual(instructions.read_bytes(), before)

    def test_user_install_respects_custom_codex_home_and_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            profile = home / "custom profile"
            profile.mkdir()
            (profile / "AGENTS.md").write_text("Keep inactive guidance")
            override = profile / "AGENTS.override.md"
            override.write_text("Active global rules\n")
            with patch.object(INSTALLER.Path, "home", return_value=home), patch.object(INSTALLER.os, "environ", {"CODEX_HOME": str(profile)}):
                INSTALLER.install()
            self.assertTrue(override.read_text().startswith("Active global rules\n"))
            self.assertIn((home / ".agents/skills").as_posix(), override.read_text())
            self.assertEqual((profile / "AGENTS.md").read_text(), "Keep inactive guidance")
            self.assertFalse((home / ".codex").exists())

    def test_user_instruction_conflict_prevents_skill_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".codex").mkdir()
            instructions = home / ".codex/AGENTS.md"
            instructions.write_text(INSTALLER.START)
            with patch.object(INSTALLER.Path, "home", return_value=home), patch.object(INSTALLER.os, "environ", {}):
                with self.assertRaisesRegex(ValueError, "Malformed Showwork markers"):
                    INSTALLER.install()
                instructions.unlink()
                (home / ".codex").rmdir()
                (home / ".codex").symlink_to(home, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "Expected a real directory"):
                    INSTALLER.install()
            self.assertFalse((home / ".agents").exists())

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
            self.assertEqual(INSTALLER.install(project), 1)
            backups = list((project / ".agents/showwork-backups").glob("update-*/showwork/personal-notes.md"))
            self.assertEqual(backups[-1].read_text(encoding="utf-8"), "Keep this")
            self.assertFalse(custom.exists())

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            existing = project / ".agents" / "skills" / "showwork-verify"
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text("User version", encoding="utf-8")
            self.assertEqual(INSTALLER.install(project), 4)
            backups = list((project / ".agents/showwork-backups").glob("update-*/showwork-verify/SKILL.md"))
            self.assertEqual(backups[-1].read_text(), "User version")
            self.assertTrue((project / "AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            external = Path(temporary) / "external"
            project.mkdir()
            external.mkdir()
            (project / ".agents").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Expected a real directory"):
                INSTALLER.install(project)
            self.assertEqual(list(external.iterdir()), [])

    def test_upgrade_replaces_changed_files_removes_retired_files_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            source = Path(temporary) / "release"
            shutil.copytree(ROOT / "skills", source)
            retired = source / "showwork/retired.md"
            retired.write_text("Old release file")
            INSTALLER.install(project, source)
            retired.unlink()
            (source / "showwork/SKILL.md").write_text("New release")
            self.assertEqual(INSTALLER.install(project, source), 1)
            installed = project / ".agents/skills/showwork"
            self.assertEqual((installed / "SKILL.md").read_text(), "New release")
            self.assertFalse((installed / "retired.md").exists())
            backups = list((project / ".agents/showwork-backups").iterdir())
            self.assertEqual((backups[0] / "showwork/retired.md").read_text(), "Old release file")
            self.assertEqual(INSTALLER.install(project, source), 0)
            self.assertEqual(list((project / ".agents/showwork-backups").iterdir()), backups)

    def test_failed_update_restores_all_skills_and_instructions(self):
        for failure in ("replace", "move_after", "instructions", "instructions_after", "staging"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary) / "project"
                project.mkdir()
                INSTALLER.install(project)
                skills = project / ".agents/skills"
                before = INSTALLER.contents(skills)
                instructions = project / "AGENTS.md"
                instructions.write_text("User prefix\n" + INSTALLER.START + "\nOld instructions\n" + INSTALLER.END)
                original = instructions.read_bytes()
                source = Path(temporary) / "release"
                shutil.copytree(ROOT / "skills", source)
                for name in INSTALLER.SKILLS:
                    (source / name / "SKILL.md").write_text("New release")
                replace = INSTALLER.os.replace
                write_instructions = INSTALLER.write_instructions
                def fail_replace(src, dest):
                    if failure == "replace" and ".showwork-stage-" in str(src) and Path(src).name == "showwork-review":
                        raise OSError("Simulated failure")
                    result = replace(src, dest)
                    if failure == "move_after" and Path(src) == skills / "showwork-review":
                        raise KeyboardInterrupt("Simulated failure")
                    return result
                def fail_instructions(path, content):
                    write_instructions(path, content)
                    raise KeyboardInterrupt("Simulated failure")
                if failure in ("replace", "move_after"):
                    mock = patch.object(INSTALLER.os, "replace", side_effect=fail_replace)
                elif failure == "instructions":
                    mock = patch.object(INSTALLER, "write_instructions", side_effect=OSError("Simulated failure"))
                elif failure == "instructions_after":
                    mock = patch.object(INSTALLER, "write_instructions", side_effect=fail_instructions)
                else:
                    mock = patch.object(INSTALLER.shutil, "copytree", side_effect=OSError("Simulated failure"))
                with mock, self.assertRaisesRegex((OSError, KeyboardInterrupt), "Simulated failure"):
                    INSTALLER.install(project, source)
                self.assertEqual(INSTALLER.contents(skills), before)
                self.assertEqual(instructions.read_bytes(), original)
                self.assertFalse((project / ".agents/.showwork-install.lock").exists())

    def test_update_refuses_existing_lock_and_symlinked_backup_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            INSTALLER.install(project)
            skill = project / ".agents/skills/showwork/SKILL.md"
            skill.write_text("Local edits")
            lock = project / ".agents/.showwork-install.lock"
            lock.mkdir()
            with self.assertRaisesRegex(ValueError, "Another install is active"):
                INSTALLER.install(project)
            lock.rmdir()
            (project / ".agents/showwork-backups").symlink_to(project, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Expected a real backup directory"):
                INSTALLER.install(project)
            self.assertEqual(skill.read_text(), "Local edits")


if __name__ == "__main__":
    unittest.main()
