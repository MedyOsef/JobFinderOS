#!/usr/bin/env python3
"""A stand-in for the `opencode` binary so the test suite spends no tokens.

Point `OPENCODE_BIN` at this file and `JOBFINDEROS_HARNESS=opencode`. It accepts the flags
the runner passes (`run --format json --archived --auto [--agent X] [--model M] <prompt>`),
takes the prompt from the command line, and prints an NDJSON event stream shaped like the
real `opencode run --format json` (see tests/data/opencode_result_sample.ndjson).

How it decides what to answer, in order:
  1. FAKE_OPENCODE_MODE=error            -> one `error` event on stdout, exit 1
     FAKE_OPENCODE_MODE=exit:<n>         -> exit with code n, no output
     FAKE_OPENCODE_MODE=sleep:<seconds>  -> sleep, then answer normally (for timeout tests)
  2. FAKE_OPENCODE_RESPONSE (text)       -> used as the assistant text
  3. Otherwise: the text "ok".

Every invocation appends {"argv": [...], "prompt": "..."} to FAKE_OPENCODE_LOG (JSONL) when
that variable is set, so tests can assert on the flags the runner used.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid


def parse_args(argv: list[str]) -> dict:
    opts: dict = {"format": "default", "agent": None, "model": None, "positionals": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if a in ("--format", "--agent", "--model"):
            opts[a[2:]] = nxt
            i += 2
        elif a in ("--archived", "--auto", "--thinking"):
            i += 1
        elif a in ("run", "-p", "--prompt"):
            i += 1
        else:
            opts["positionals"].append(a)
            i += 1
    return opts


def main() -> int:
    argv = sys.argv[1:]
    opts = parse_args(argv)
    prompt = " ".join(opts["positionals"])

    log_path = os.environ.get("FAKE_OPENCODE_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "prompt": prompt}) + "\n")

    mode = os.environ.get("FAKE_OPENCODE_MODE", "")
    if mode.startswith("exit:"):
        return int(mode.split(":", 1)[1])
    if mode.startswith("sleep:"):
        time.sleep(float(mode.split(":", 1)[1]))

    started = time.time()
    is_error = mode == "error"
    text = "fake error" if is_error else os.environ.get("FAKE_OPENCODE_RESPONSE", "ok")

    session_id = f"ses_fake{uuid.uuid4().hex[:20]}"
    now = int(time.time() * 1000)

    if is_error:
        events = [
            {
                "type": "error",
                "timestamp": now,
                "sessionID": session_id,
                "error": {"type": "fake.error", "message": "fake error", "status": 500},
            }
        ]
        for event in events:
            sys.stdout.write(json.dumps(event) + "\n")
        return 1

    in_tok = max(1, len(prompt) // 4)
    out_tok = max(1, len(text) // 4)
    cost = round(in_tok * 3e-6 + out_tok * 1.5e-5, 6) + 0.005  # >0 so the run log shows a cost
    events = [
        {
            "type": "step_start",
            "timestamp": now,
            "sessionID": session_id,
            "part": {"id": "prt_1", "sessionID": session_id, "messageID": "msg_1", "type": "step-start"},
        },
        {
            "type": "text",
            "timestamp": now,
            "sessionID": session_id,
            "part": {
                "id": "prt_2",
                "sessionID": session_id,
                "messageID": "msg_1",
                "type": "text",
                "text": text,
                "time": {"start": now, "end": now + 1},
            },
        },
        {
            "type": "step_finish",
            "timestamp": now + int((time.time() - started) * 1000) + 5,
            "sessionID": session_id,
            "part": {
                "id": "prt_3",
                "sessionID": session_id,
                "messageID": "msg_1",
                "type": "step-finish",
                "reason": "stop",
                "cost": cost,
                "tokens": {"input": in_tok, "output": out_tok, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            },
        },
    ]
    for event in events:
        sys.stdout.write(json.dumps(event) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
