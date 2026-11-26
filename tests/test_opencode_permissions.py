"""Token-free checks that the OpenCode layer keeps "never send" technical.

The doctrine in the agent files says drafts go to the clipboard and the vault;
these tests assert the harness-level denies in `opencode.json` still back it up.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "opencode.json"


class TestOpenCodePermissions(unittest.TestCase):
    def setUp(self):
        self.permissions = json.loads(CONFIG.read_text(encoding="utf-8"))["permissions"]

    def _denies(self, action):
        return [
            rule["resource"]
            for rule in self.permissions
            if rule["action"] == action and rule["effect"] == "deny"
        ]

    def test_instructions_load_claude_md(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertIn("CLAUDE.md", config["instructions"])

    def test_mail_senders_denied(self):
        denied = " ".join(self._denies("shell")).lower()
        for tool in (
            "sendmail",
            "send-mailmessage",
            "mailx",
            "mutt",
            "smtp",
            "send-email",
            "sendgrid",
            "mailgun",
            "nodemailer",
        ):
            self.assertIn(tool, denied, f"{tool} must be denied at the shell layer")

    def test_repo_writes_asked_globally_denied_for_agents(self):
        # The human clicks "Allow" in the TUI for the session's own commits,
        # but every persona frontmatter denies git outright: scheduled runs
        # pass --auto, which auto-approves asks and never touches a deny.
        effects = {
            (rule["action"], rule["resource"]): rule["effect"]
            for rule in self.permissions
        }
        for resource in ("git commit *", "git push *"):
            self.assertEqual(effects.get(("shell", resource)), "ask")
        for agent_file in sorted((ROOT / ".opencode" / "agents").glob("*.md")):
            frontmatter = agent_file.read_text(encoding="utf-8").split("---")[1]
            for resource in ("git commit *", "git push *"):
                match = re.search(
                    rf'- action: shell\s+resource: "{re.escape(resource)}"\s+effect: (\w+)',
                    frontmatter,
                )
                self.assertIsNotNone(
                    match, f"{agent_file.name} must deny {resource} for scheduled runs"
                )
                self.assertEqual(match.group(1), "deny")

    def test_mcp_send_tools_denied(self):
        actions = {rule["action"] for rule in self.permissions if rule["effect"] == "deny"}
        for pattern in ("*_send*", "*_draft*", "*_forward*", "*_reply*"):
            self.assertIn(pattern, actions, f"MCP tools matching {pattern} must be denied")

    def test_no_broad_allow_override(self):
        # Agent rules are appended after global rules and the last match wins
        # (OpenCode permissions doc): a permissive agent frontmatter would
        # silently cancel every deny above. Only deny rules belong there.
        for rule in self.permissions:
            if rule["effect"] == "allow":
                self.assertNotEqual(rule["action"], "*", "a blanket allow would void the denies")
        for agent_file in sorted((ROOT / ".opencode" / "agents").glob("*.md")):
            frontmatter = agent_file.read_text(encoding="utf-8").split("---")[1]
            self.assertNotIn(
                "effect: allow",
                frontmatter,
                f"{agent_file.name} must not grant permissions that override global denies",
            )

    def _gmail_server(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        return config["mcp"]["servers"]["gmail"]

    def test_gmail_server_is_official_and_readonly(self):
        # Phase 6: Google's own remote server (tool names match the skills'
        # search_threads / get_thread) requested with the read-only scope only,
        # so Google itself rejects any mutation even if a harness deny fails.
        gmail = self._gmail_server()
        self.assertEqual(gmail["type"], "remote")
        self.assertEqual(gmail["url"], "https://gmailmcp.googleapis.com/mcp/v1")
        scope = gmail["oauth"]["scope"]
        self.assertIn("gmail.readonly", scope)
        for forbidden in ("gmail.send", "gmail.compose", "gmail.modify", "mail.google.com"):
            self.assertNotIn(forbidden, scope)

    def test_gmail_credentials_come_from_env(self):
        # opencode.json is meant to be committed: no OAuth secret may live in it.
        oauth = self._gmail_server()["oauth"]
        for field in ("client_id", "client_secret"):
            value = oauth.get(field, "")
            self.assertTrue(
                value.startswith("{env:"),
                f"{field} must be an {{env:...}} placeholder, never a literal value",
            )

    def test_gmail_allowlist_is_read_only_and_ordered(self):
        # Last match wins: the three read tools must be allowed *after* the
        # blanket gmail_* deny; every other gmail tool stays denied.
        deny_index = next(
            i
            for i, rule in enumerate(self.permissions)
            if rule["action"] == "gmail_*" and rule["effect"] == "deny"
        )
        allows = [
            (i, rule["action"])
            for i, rule in enumerate(self.permissions)
            if rule["action"].startswith("gmail_") and rule["effect"] == "allow"
        ]
        self.assertEqual(
            {action for _, action in allows},
            {"gmail_search_threads", "gmail_get_thread", "gmail_get_message"},
        )
        for i, action in allows:
            self.assertGreater(i, deny_index, f"{action} must come after the gmail_* deny")


if __name__ == "__main__":
    unittest.main()
