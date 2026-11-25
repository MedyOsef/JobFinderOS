"""The portable skill runner: no --dangerously-skip-permissions, JSON output, usage in the run log.
Logs are redirected to a temp dir (JOBFINDEROS_LOG_DIR) so the repo's logs and the vault mirror stay untouched.

One entrypoint, two harnesses, both token-free:
  JOBFINDEROS_HARNESS=claude    (default) drives tests/fake_claude.py via CLAUDE_BIN
  JOBFINDEROS_HARNESS=opencode            drives tests/fake_opencode.py via OPENCODE_BIN
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "jobfinderos_run_skill.py"
FAKE = REPO / "tests" / "fake_claude.py"
FAKE_OC = REPO / "tests" / "fake_opencode.py"
SAMPLE_OC = REPO / "tests" / "data" / "opencode_result_sample.ndjson"

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import jobfinderos_run_skill as runner_module  # noqa: E402  (scripts/ is on the path above)


def base_env(log_dir, extra_env=None):
    """The runner's environment without an ambient JOBFINDEROS_HARNESS: the harness under
    test is chosen by the test, never by the shell running the suite."""
    env = {k: v for k, v in os.environ.items() if k != "JOBFINDEROS_HARNESS"}
    env["JOBFINDEROS_LOG_DIR"] = str(log_dir)
    env.update(extra_env or {})
    return env


def invoke(log_dir, skill, extra_env=None):
    return subprocess.run(
        [sys.executable, str(RUNNER), "test-label", skill],
        cwd=REPO,
        env=base_env(log_dir, extra_env),
        capture_output=True,
        text=True,
        timeout=60,
    )


def log_tail(logs) -> str:
    return (logs / "launchd-runs.log").read_text(encoding="utf-8").splitlines()[-1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self._tmp.name) / "logs"

    def tearDown(self):
        self._tmp.cleanup()

    def run_runner(self, skill, extra_env=None):
        return invoke(self.logs, skill, {"CLAUDE_BIN": str(FAKE), **(extra_env or {})})

    def run_log_tail(self) -> str:
        return log_tail(self.logs)

    def test_missing_skill_exits_2_without_calling_claude(self):
        r = self.run_runner("no-such-skill")
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing skill file", r.stderr)

    def test_completed_run_logs_usage_and_uses_safe_flags(self):
        argv_log = Path(self._tmp.name) / "argv.log"
        r = self.run_runner("jobs-scout", {"FAKE_CLAUDE_LOG": str(argv_log)})
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads(argv_log.read_text().splitlines()[-1])["argv"]
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertIn("--output-format", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(argv[argv.index("-p") + 1], "/jobs-scout")
        self.assertIn("test-label — completed (est. $", self.run_log_tail())
        self.assertTrue(any(p.name.endswith("-test-label.txt") for p in (self.logs / "skills").iterdir()))

    def test_error_result_is_a_failure(self):
        r = self.run_runner("jobs-scout", {"FAKE_CLAUDE_MODE": "error"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("failed", self.run_log_tail())

    def test_unset_harness_keeps_the_claude_path(self):
        """Regression guard: the installed scheduler jobs never set JOBFINDEROS_HARNESS."""
        argv_log = Path(self._tmp.name) / "argv.log"
        r = self.run_runner("jobs-scout", {"FAKE_CLAUDE_LOG": str(argv_log)})
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads(argv_log.read_text().splitlines()[-1])["argv"]
        self.assertIn("-p", argv)
        self.assertNotIn("run", argv)


class OpenCodeRunnerTests(unittest.TestCase):
    """JOBFINDEROS_HARNESS=opencode: .opencode/commands/, `opencode run` flags, NDJSON result."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self._tmp.name) / "logs"

    def tearDown(self):
        self._tmp.cleanup()

    def run_opencode(self, skill, extra_env=None):
        env = {"OPENCODE_BIN": str(FAKE_OC), "JOBFINDEROS_HARNESS": "opencode", **(extra_env or {})}
        return invoke(self.logs, skill, env)

    def test_run_uses_command_body_agent_and_safe_flags(self):
        argv_log = Path(self._tmp.name) / "argv.log"
        r = self.run_opencode("jobs-scout", {"FAKE_OPENCODE_LOG": str(argv_log)})
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = json.loads(argv_log.read_text(encoding="utf-8").splitlines()[-1])
        argv = entry["argv"]
        self.assertEqual(argv[0], "run")
        self.assertEqual(argv[argv.index("--format") + 1], "json")
        self.assertIn("--archived", argv)
        self.assertIn("--auto", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[argv.index("--agent") + 1], "scout")
        prompt = entry["prompt"]
        # `opencode run` does not expand slash commands: the body (frontmatter stripped)
        # is the prompt, and it is the .opencode copy, not the .claude original.
        self.assertTrue(prompt.startswith("**Agent:**"), prompt[:80])
        self.assertIn(".opencode/commands/jobs-scout.md", prompt)
        self.assertIn("test-label — completed (est. $", log_tail(self.logs))
        self.assertTrue(any(p.name.endswith("-test-label.txt") for p in (self.logs / "skills").iterdir()))

    def test_skill_without_agent_omits_the_flag(self):
        argv_log = Path(self._tmp.name) / "argv.log"
        r = self.run_opencode("onboard", {"FAKE_OPENCODE_LOG": str(argv_log)})
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads(argv_log.read_text(encoding="utf-8").splitlines()[-1])["argv"]
        self.assertNotIn("--agent", argv)

    def test_error_event_is_a_failure(self):
        r = self.run_opencode("jobs-scout", {"FAKE_OPENCODE_MODE": "error"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("failed", log_tail(self.logs))

    def test_missing_skill_exits_2_without_calling_opencode(self):
        argv_log = Path(self._tmp.name) / "argv.log"
        r = self.run_opencode("no-such-skill", {"FAKE_OPENCODE_LOG": str(argv_log)})
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing skill file", r.stderr)
        self.assertFalse(argv_log.exists())

    def test_unknown_harness_exits_2(self):
        r = invoke(
            self.logs,
            "jobs-scout",
            {"JOBFINDEROS_HARNESS": "claude-code", "CLAUDE_BIN": str(FAKE), "OPENCODE_BIN": str(FAKE_OC)},
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("JOBFINDEROS_HARNESS", r.stderr)


class OpenCodeResultParsing(unittest.TestCase):
    """The NDJSON parser against the recorded sample and the error shape."""

    def test_parses_sample_stream(self):
        sample = SAMPLE_OC.read_text(encoding="utf-8")
        text, usage = runner_module.parse_opencode_stream(sample)
        self.assertIn("No entry clears the log threshold", text)
        self.assertFalse(usage["is_error"])
        self.assertEqual(usage["num_turns"], 2)
        self.assertEqual(usage["input_tokens"], 13102 + 512 + 189 + 13568)
        self.assertEqual(usage["output_tokens"], 44 + 63)
        self.assertAlmostEqual(usage["cost_usd"], 0.0059, places=6)
        self.assertIn("est. $", usage["summary"])

    def test_error_event_marks_failure(self):
        line = json.dumps({"type": "error", "error": {"type": "provider.quota", "message": "out of credits", "status": 402}})
        text, usage = runner_module.parse_opencode_stream(line)
        self.assertTrue(usage["is_error"])
        self.assertIn("out of credits", usage["error"])
        self.assertEqual(text, "")

    def test_raw_output_is_kept_when_nothing_parses(self):
        text, usage = runner_module.parse_opencode_stream("plain prose, not a stream\n")
        self.assertEqual(text, "plain prose, not a stream")
        self.assertFalse(usage["is_error"])

    def test_command_frontmatter_and_body(self):
        skill = REPO / ".opencode" / "commands" / "jobs-scout.md"
        meta = runner_module.command_frontmatter(skill)
        self.assertEqual(meta.get("agent"), "scout")
        self.assertEqual(meta.get("subagent"), "true")
        body = runner_module.command_body(skill)
        self.assertTrue(body.startswith("**Agent:**"), body[:80])
        self.assertNotIn("description:", body.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
