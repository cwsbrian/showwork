"""Verify that an ordinary prompt reaches the automatic routing adapter."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AutomaticTest(unittest.TestCase):
    def invoke(self, event, root=ROOT):
        return subprocess.run(
            [sys.executable, str(root / "scripts" / "automatic.py")],
            input=json.dumps(event), text=True, capture_output=True, timeout=5,
        )

    def test_plain_prompt_receives_context_without_command_or_prompt_echo(self):
        prompt = "HTML/CSS/JavaScript로 간단한 할 일 앱을 만들어줘."
        result = self.invoke({"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertNotIn("decision", output)
        context = output["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "UserPromptSubmit")
        self.assertNotIn(prompt, context["additionalContext"])
        self.assertNotIn("{{SKILLS_ROOT}}", context["additionalContext"])
        for name in ["showwork", "showwork-plan", "showwork-review", "showwork-verify", "showwork-adverial-review"]:
            self.assertIn(str(ROOT / "skills" / name / "SKILL.md"), context["additionalContext"])

    def test_ignores_unrelated_hook_events(self):
        result = self.invoke({"hook_event_name": "Stop"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_invalid_input_reports_failure_instead_of_success(self):
        result = self.invoke(["not an event object"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(os.name == "posix", "Exercise Claude's POSIX shell hook command")
    def test_registered_hook_runs_from_plugin_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="showwork plugin ") as temporary:
            root = Path(temporary)
            for name in ["scripts", "instructions", "skills", "hooks"]:
                shutil.copytree(ROOT / name, root / name)
            config = json.loads((root / "hooks" / "hooks.json").read_text())
            groups = config["hooks"]["UserPromptSubmit"]
            self.assertEqual(len(groups), 1)
            self.assertNotIn("matcher", groups[0])  # Every prompt reaches the model's triage.
            handler = groups[0]["hooks"][0]
            environment = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(root))
            result = subprocess.run(
                handler["command"], shell=True, env=environment,
                input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Build a todo app"}),
                text=True, capture_output=True, timeout=handler["timeout"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(str(root / "skills" / "showwork" / "SKILL.md"), context)


if __name__ == "__main__":
    unittest.main()
