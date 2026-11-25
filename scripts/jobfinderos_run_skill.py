#!/usr/bin/env python3
"""Run a JobFinderOS skill locally, on either harness.

JOBFINDEROS_HARNESS picks the CLI (default `claude`, so the installed scheduler jobs keep
running exactly as before):

  claude    `claude -p /<skill> --output-format json --allowedTools …`
  opencode  `opencode run --format json --archived --auto`, sending the command's own body
            as the prompt (`opencode run` does not expand slash commands) and selecting the
            persona with `--agent` from the command's frontmatter.

Both write the same run log; only the result parsing differs (Claude's single JSON object
vs OpenCode's NDJSON event stream).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_TIMEOUT_SEC = 1800
DEFAULT_ALLOWED_TOOLS = "Agent,Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch"
HARNESSES = ("claude", "opencode")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def append_run_log(root: Path, label: str, phase: str) -> None:
    line = (
        f"- {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
        f" — {label} — {phase}\n"
    )

    log = log_dir(root) / "launchd-runs.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as file:
        file.write(line)

    if os.environ.get("JOBFINDEROS_LOG_DIR"):
        return      # a redirected log (tests, ad-hoc runs) never touches the vault mirror
    vault_log = root / "vault" / "Automation" / "JobFinderOS — Schedule & Run Log.md"
    try:
        with open(vault_log, "a", encoding="utf-8") as file:
            file.write(line)
    except OSError:
        pass


def log_dir(root: Path) -> Path:
    """logs/ under the repo, or $JOBFINDEROS_LOG_DIR when set."""
    configured = os.environ.get("JOBFINDEROS_LOG_DIR")
    return Path(configured).expanduser() if configured else root / "logs"


def record_result(root: Path, label: str, stdout: str, stderr: str, harness: str = "claude") -> dict:
    """Save the skill's text to logs/skills/ and pull tokens + estimated cost out of the
    CLI's result (Claude: tests/data/claude_result_sample.json; OpenCode:
    tests/data/opencode_result_sample.ndjson)."""
    import json

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = log_dir(root) / "skills"
    out_dir.mkdir(parents=True, exist_ok=True)
    usage: dict = {}

    if harness == "opencode":
        text, usage = parse_opencode_stream(stdout)
    else:
        text = stdout or ""
        try:
            payload = json.loads(text.strip() or "{}")
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and "result" in payload:
            text = str(payload.get("result") or "")
            u = payload.get("usage") or {}
            usage = {
                "is_error": bool(payload.get("is_error")),
                "error": str(payload.get("terminal_reason") or "") if payload.get("is_error") else "",
                "cost_usd": float(payload.get("total_cost_usd") or 0.0),
                "input_tokens": int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
                "output_tokens": int(u.get("output_tokens") or 0),
                "num_turns": int(payload.get("num_turns") or 0),
            }
            usage["summary"] = (f"est. ${usage['cost_usd']:.2f}, {usage['input_tokens']} in / {usage['output_tokens']} out tokens, "
                                f"{usage['num_turns']} turns")
    with open(out_dir / f"{stamp}-{label}.txt", "w", encoding="utf-8") as fh:
        fh.write(text)
        if stderr:
            fh.write("\n\n--- stderr ---\n" + stderr)
    return usage


def parse_opencode_stream(stdout: str) -> tuple[str, dict]:
    """`opencode run --format json` prints one JSON event per line (NDJSON): assistant text
    arrives as `text` events, token totals and cost on every `step_finish`, and a failure as
    a single `error` event (shape reference: tests/data/opencode_result_sample.ndjson).
    Non-JSON lines are ignored; with no recognized event the raw output is kept as text."""
    import json

    chunks: list[str] = []
    cost_usd = 0.0
    input_tokens = output_tokens = 0
    turns = 0
    error = ""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "text":
            chunks.append(str((event.get("part") or {}).get("text") or ""))
        elif kind == "step_finish":
            part = event.get("part") or {}
            tokens = part.get("tokens") or {}
            cost_usd += float(part.get("cost") or 0.0)
            input_tokens += int(tokens.get("input") or 0) + int((tokens.get("cache") or {}).get("read") or 0)
            output_tokens += int(tokens.get("output") or 0)
            turns += 1
        elif kind == "error":
            err = event.get("error") or {}
            error = str(err.get("message") or err.get("type") or "unknown error")

    text = "\n".join(chunk for chunk in chunks if chunk)
    if not chunks and (stdout or "").strip() and not error:
        text = stdout.strip()

    usage = {
        "is_error": bool(error),
        "error": error,
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "num_turns": turns,
    }
    if turns or cost_usd:
        usage["summary"] = (
            f"est. ${cost_usd:.2f}, {input_tokens} in / {output_tokens} out tokens, {turns} turns"
        )
    return text, usage


def find_claude() -> str | None:
    configured = os.environ.get("CLAUDE_BIN")
    if configured:
        return configured

    return shutil.which("claude")


def find_opencode() -> str | None:
    configured = os.environ.get("OPENCODE_BIN")
    if configured:
        return configured

    return shutil.which("opencode")


def cli_argv(binary: str) -> list[str]:
    """A `.py` target runs under the current interpreter: the token-free fakes in tests/
    point CLAUDE_BIN / OPENCODE_BIN at a script, which is not executable as-is on Windows.
    The real CLIs never end in `.py` and are invoked unchanged."""
    if binary.endswith(".py"):
        return [sys.executable, binary]
    return [binary]


def command_frontmatter(path: Path) -> dict:
    """Flat `key: value` frontmatter of a skill file. No YAML dependency: the command
    files only carry top-level scalars, so indented continuation lines are skipped."""
    match = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", path.read_text(encoding="utf-8"), re.S)
    if not match:
        return {}
    meta: dict = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t", "#")):
            meta[key.strip()] = value.strip()
    return meta


def command_body(path: Path) -> str:
    """The prompt template: the skill file minus its frontmatter (what OpenCode submits)."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---[ \t]*\r?\n.*?\r?\n---[ \t]*\r?\n?", text, re.S)
    return (text[match.end():] if match else text).strip()


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: jobfinderos_run_skill.py <log-label> <skill-name>",
            file=sys.stderr,
        )
        return 2

    label = sys.argv[1]
    skill = sys.argv[2]
    root = project_root()

    harness = os.environ.get("JOBFINDEROS_HARNESS", "").strip().lower() or "claude"
    if harness not in HARNESSES:
        print(
            "JobFinderOS_run_skill: JOBFINDEROS_HARNESS must be one of "
            + ", ".join(HARNESSES),
            file=sys.stderr,
        )
        return 2

    command_file = (
        root
        / (".opencode" if harness == "opencode" else ".claude")
        / "commands"
        / f"{skill}.md"
    )
    if not command_file.is_file():
        print(
            f"JobFinderOS_run_skill: missing skill file: {command_file}",
            file=sys.stderr,
        )
        return 2

    if harness == "opencode":
        cli_bin = find_opencode()
        missing_cli = "JobFinderOS_run_skill: opencode CLI not found (set OPENCODE_BIN)"
    else:
        cli_bin = find_claude()
        missing_cli = "JobFinderOS_run_skill: claude CLI not found (set CLAUDE_BIN)"
    if not cli_bin:
        print(missing_cli, file=sys.stderr)
        return 127

    try:
        timeout_sec = int(
            os.environ.get(
                "JOBFINDEROS_SKILL_TIMEOUT_SEC",
                str(DEFAULT_TIMEOUT_SEC),
            )
        )
    except ValueError:
        print(
            "JOBFINDEROS_SKILL_TIMEOUT_SEC must be an integer",
            file=sys.stderr,
        )
        return 2

    allowed_tools = os.environ.get(
        "JOBFINDEROS_SKILL_ALLOWED_TOOLS",
        DEFAULT_ALLOWED_TOOLS,
    )

    env = os.environ.copy()

    path_entries = [
        str(root / ".venv" / ("Scripts" if os.name == "nt" else "bin")),
    ]

    if os.name != "nt":
        path_entries.append(str(Path.home() / ".local" / "bin"))

    path_entries.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(path_entries)

    # Explicit tools and a permission mode instead of --dangerously-skip-permissions: a
    # scheduled run reads untrusted web pages and email with nobody watching. acceptEdits
    # lets the skill write the vault; anything outside the allowed tools is refused.
    if harness == "opencode":
        # `opencode run` submits a prompt; it does not expand `/skill` (verified), so the
        # command's own body is the prompt and `--agent` selects the persona the command's
        # frontmatter names. `--auto` approves what the deny rules in opencode.json do not
        # forbid, which is the acceptEdits / allowedTools counterpart.
        tail = ["run", "--format", "json", "--archived", "--auto"]
        agent = command_frontmatter(command_file).get("agent")
        if agent:
            tail += ["--agent", agent]
        model = os.environ.get("JOBFINDEROS_OPENCODE_MODEL")
        if model:
            tail += ["--model", model]
        tail.append(command_body(command_file))
    else:
        tail = [
            "-p",
            f"/{skill}",
            "--output-format",
            "json",
            "--allowedTools",
            allowed_tools,
            "--permission-mode",
            os.environ.get("JOBFINDEROS_PERMISSION_MODE", "acceptEdits"),
            "--permission-prompts",
            "none",
            "--no-session-persistence",
        ]
    command = cli_argv(cli_bin) + tail

    append_run_log(root, label, "start")

    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        append_run_log(root, label, f"failed (timeout {timeout_sec}s)")
        return 124
    except OSError as exc:
        append_run_log(root, label, f"failed ({exc})")
        print(f"JobFinderOS_run_skill: {exc}", file=sys.stderr)
        return 127

    usage = record_result(root, label, result.stdout, result.stderr, harness)

    if result.returncode != 0 or usage.get("is_error"):
        append_run_log(
            root,
            label,
            f"failed (exit {result.returncode}{', ' + usage['error'] if usage.get('error') else ''})",
        )
        return result.returncode or 1

    append_run_log(root, label, f"completed ({usage.get('summary', 'no usage data')})")

    fixer = root / "scripts" / "jobfinderos_fix_backslash_paths.py"
    subprocess.run(
        [sys.executable, str(fixer)],
        cwd=root,
        env=env,
        check=False,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
