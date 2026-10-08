import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "showwork.py"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="showwork test ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        result = self.cli("init", "checkout", "--title", "Checkout", "--criterion", "A purchase succeeds")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.run = Path(result.stdout.splitlines()[0])
        self.addCleanup(shutil.rmtree, self.run.parent.parent)

    def test_records_stay_outside_project_and_project_root_override_is_rejected(self):
        self.assertFalse(self.run.is_relative_to(self.project))
        self.assertEqual(list(self.project.iterdir()), [])
        if os.name == 'posix':
            self.assertTrue(self.run.is_relative_to(Path('/tmp').resolve()))
        result = self.cli('init', 'bad', '--title', 'Bad', '--criterion', 'Test', '--root', self.project / '.showwork')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_legacy_project_run_is_rejected_before_writing_logs(self):
        legacy = self.project / '.showwork' / 'runs' / 'checkout'
        shutil.copytree(self.run, legacy)
        result = self.cli('check', legacy, '--criterion', 'C1', '--', sys.executable, '-c', 'print("no")')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(list((legacy / 'evidence').iterdir()), [])

    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)], cwd=self.project,
            capture_output=True, text=True, timeout=15,
        )

    def check(self, source, *options):
        return self.cli("check", self.run, "--criterion", "C1", *options,
                        "--", sys.executable, "-c", source)

    def manifest(self):
        return json.loads((self.run / "run.json").read_text())

    def test_init_requires_nonempty_criteria_and_safe_unique_slug(self):
        original = (self.run / "run.json").read_bytes()
        for slug, criterion in [("../escape", "Behavior"), ("valid", " "), ("checkout", "New")]:
            with self.subTest(slug=slug):
                self.assertNotEqual(self.cli("init", slug, "--title", "Task", "--criterion", criterion).returncode, 0)
        self.assertEqual((self.run / "run.json").read_bytes(), original)

    def test_missing_evidence_is_incomplete(self):
        self.assertEqual(self.cli("status", self.run).returncode, 1)

    def test_check_captures_output_argv_and_cwd(self):
        result = self.check("import sys; print('runtime output'); print('stderr output', file=sys.stderr)")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.manifest()["evidence"][0]
        self.assertEqual(evidence["cwd"], str(self.project))
        self.assertEqual(evidence["exit_code"], 0)
        self.assertEqual(evidence["command"][0], sys.executable)
        output = (self.run / evidence["path"]).read_text()
        self.assertIn("runtime output", output)
        self.assertIn("stderr output", output)
        self.assertEqual(self.cli("status", self.run).returncode, 0)

    def test_arguments_are_not_interpreted_by_a_shell(self):
        literal = "$(touch owned); echo hello"
        result = self.cli("check", self.run, "--criterion", "C1", "--", sys.executable,
                          "-c", "import sys; print(sys.argv[1])", literal)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.manifest()["evidence"][0]
        self.assertEqual((self.run / record["path"]).read_text().strip(), literal)
        self.assertFalse((self.project / "owned").exists())

    def test_failure_is_preserved_and_later_pass_supersedes_it(self):
        self.assertEqual(self.check("raise SystemExit(7)").returncode, 7)
        self.assertEqual(self.cli("status", self.run).returncode, 1)
        self.assertEqual(self.check("print('fixed')").returncode, 0)
        records = self.manifest()["evidence"]
        self.assertEqual([record["result"] for record in records], ["failed", "passed"])
        self.assertEqual(self.cli("status", self.run).returncode, 0)

    def test_later_failure_invalidates_earlier_pass(self):
        self.check("print('ok')")
        self.check("raise SystemExit(1)")
        self.assertEqual(self.cli("status", self.run).returncode, 1)

    def test_timeout_records_partial_output(self):
        result = self.check("import time; print('started', flush=True); time.sleep(10)", "--timeout", "0.2")
        self.assertEqual(result.returncode, 124, result.stderr)
        record = self.manifest()["evidence"][0]
        self.assertEqual(record["result"], "timeout")
        self.assertIn("started", (self.run / record["path"]).read_text())
        self.assertEqual(self.cli("status", self.run).returncode, 1)

    def test_invalid_timeout_or_criterion_does_not_execute(self):
        for timeout in ["0", "-1", "nan", "inf"]:
            self.assertEqual(self.check("open('owned', 'w').close()", "--timeout", timeout).returncode, 2)
        result = self.cli("check", self.run, "--criterion", "C99", "--", sys.executable,
                          "-c", "open('owned', 'w').close()")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.project / "owned").exists())
        self.assertEqual(self.manifest()["evidence"], [])

    def test_missing_executable_records_error(self):
        result = self.cli("check", self.run, "--criterion", "C1", "--", str(self.project / "absent"))
        self.assertEqual(result.returncode, 127)
        self.assertEqual(self.manifest()["evidence"][0]["result"], "error")

    def test_attachment_is_snapshot_not_claim_of_success(self):
        source = self.project / "observation.txt"
        source.write_text("Observed output")
        result = self.cli("attach", self.run, "--criterion", "C1", "--kind", "manual",
                          "--path", source, "--note", "Observed locally")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.manifest()["evidence"][0]
        source.write_text("changed")
        self.assertEqual((self.run / record["path"]).read_text(), "Observed output")
        self.assertEqual(record["result"], "recorded")
        self.assertNotIn("accepted", self.manifest())

    def test_attachment_cannot_hide_failed_check(self):
        self.check("raise SystemExit(1)")
        source = self.project / "notes.txt"
        source.write_text("Looks good")
        self.cli("attach", self.run, "--criterion", "C1", "--kind", "manual",
                 "--path", source, "--note", "Supporting notes")
        self.assertEqual(self.cli("status", self.run).returncode, 1)

    def test_changed_or_missing_evidence_fails_integrity(self):
        self.check("print('ok')")
        path = self.run / self.manifest()["evidence"][0]["path"]
        path.write_text("changed")
        self.assertEqual(self.cli("status", self.run).returncode, 1)
        path.unlink()
        self.assertEqual(self.cli("status", self.run).returncode, 1)

    def test_concurrent_check_and_attachment_are_both_retained(self):
        marker = self.project / "started"
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "check", str(self.run), "--criterion", "C1", "--",
             sys.executable, "-c", "import pathlib, time; pathlib.Path('started').touch(); time.sleep(0.5)"],
            cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            source = self.project / "notes.txt"
            source.write_text("Concurrent observation")
            result = self.cli("attach", self.run, "--criterion", "C1", "--kind", "manual",
                              "--path", source, "--note", "Recorded while the check runs")
            self.assertEqual(result.returncode, 0, result.stderr)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertCountEqual([item["kind"] for item in self.manifest()["evidence"]], ["check", "manual"])

    def test_malformed_manifest_returns_a_useful_failure(self):
        (self.run / "run.json").write_text('{"schema_version": 99}')
        result = self.cli("status", self.run)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX termination and process groups")
    def test_termination_stops_check_and_records_interruption(self):
        marker = self.project / "heartbeat"
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "check", str(self.run), "--criterion", "C1", "--",
             sys.executable, "-c",
             "import pathlib, time\np = pathlib.Path('heartbeat')\nwhile True:\n p.write_text(str(time.time()))\n time.sleep(0.03)"],
            cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            process.terminate()
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
            heartbeat = marker.read_text()
            time.sleep(0.1)
            self.assertEqual(marker.read_text(), heartbeat)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(self.manifest()["evidence"][0]["result"], "interrupted")
        self.assertEqual(self.cli("status", self.run).returncode, 1)


if __name__ == "__main__":
    unittest.main()
