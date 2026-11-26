# Changelog

User-facing changes, newest first. Release notes on GitHub are copied from here.

## 1.1.0 (2026-11-25)

JobFinderOS now also runs on [OpenCode](https://opencode.ai), alongside Claude Code. Nothing moved out of `.claude/`: the runner still defaults to `claude`, and both harnesses share one repository.

**An additive OpenCode harness.** `.opencode/` carries the same three agents and all 25 skills, with the frontmatter translated (`mode`, `agent`, `subagent`) and only mechanical rewrites in the bodies. `opencode.json` wires `CLAUDE.md` through `instructions`, because OpenCode would otherwise load the developer `AGENTS.md` at the root instead of the project instructions. `scripts/jobfinderos_run_skill.py` gains `JOBFINDEROS_HARNESS=opencode` (default `claude`): it sends the command body rather than a slash command, because `opencode run` does not expand them, and parses the NDJSON event stream. `roadmap.md` documents the port phase by phase.

**The never-send rule gained a technical lock.** On OpenCode, `opencode.json` denies the shell mail senders (`sendmail`, `Send-MailMessage`, `mailx`, `mutt`, `swaks`, SMTP, `mailto:`, `send-email`, `sendgrid`, `mailgun`, `nodemailer`), `git commit`, `git push`, and MCP tools whose names betray a send (`*_send*`, `*_draft*`, `*_forward*`, `*_reply*`). A deny is not an ask: `echo sendmail` fails with `Permission denied: shell` even under `--auto`. The Claude Code path is unchanged and still rests on doctrine alone.

**Gmail on OpenCode is read-only by construction.** The official Google Gmail MCP server is requested with the `gmail.readonly` scope alone, then denied wholesale (`gmail_*`) and allowed back only for the three read tools the skills call (`search_threads`, `get_thread`, `get_message`). Credentials are read from environment variables; the repository stores none. Sign-in is yours to complete, and without it every other skill still runs.

**Tests.** 95 token-free tests, up from 78: the OpenCode runner path, the NDJSON parser, and permission guards in `tests/test_opencode_permissions.py`, with `tests/fake_opencode.py` standing in for the CLI.

## Upgrading from 1.0.0

Nothing to migrate. `JOBFINDEROS_HARNESS` defaults to `claude`, so existing installs behave exactly as before. To take the OpenCode path: install [OpenCode](https://opencode.ai), run `opencode` in the repository, and export `JOBFINDEROS_HARNESS=opencode` for scheduled runs (`JOBFINDEROS_OPENCODE_MODEL` if you want a specific model). If you maintain a fork, port new skills to both `.claude/commands/` and `.opencode/commands/`.

## 1.0.0 (2026-10-31)

JobFinderOS 1.0.0 is the first tagged release. It is the system as it stands after the discovery rebuild: three agents (a recruiter, a crawler, a market analyst) on Claude Code, writing to an Obsidian vault, with job discovery now done by deterministic code instead of a model reading careers pages.

## What changed in this release

**Discovery is a graph, not a crawl.** `scripts/jobfinderos_discover.py` fetches every registered Greenhouse, Ashby and Lever board directly, finds boards for companies you only named (in your profile, in Mark's handoff, or in a web sweep), applies your seniority, location and comp rules, reads the descriptions of titles your search terms would miss, scores what survives against your rubric, and appends today's block to `vault/Market Intel/ATS Inbox.md`. The scout writes opportunity notes from that block. It no longer fetches anything.

**Measured, not asserted.** On a frozen snapshot of 8,188 live postings across 29 real boards, labeled for two fictional candidates:

| | Original LLM scout | New discovery graph |
|---|---|---|
| Labeled-fit roles found, profile 1 | 14% (mean of 6 runs, best 24%) | 82% |
| Labeled-fit roles found, profile 2 | 10% (mean of 5 runs, best 48%) | 93% |
| Precision on act-now roles | 1.00 | 1.00 |
| Agreement between two runs on the same day | 18% | 100% on the fit set |
| Estimated cost per run | about $0.70 | about $0.30 to $1.20 |

Method, gates and per-node funnels: `docs/discovery-benchmark.md`. Protocol to reproduce it on your own profile: `sim/README.md`.

**Three things the measurement changed.** A posted salary range now has to top out below your floor to be dropped (the old midpoint rule hid most of the misses). A posting that passes the seniority rule but not your title vocabulary gets its description read; confirmed matches teach the search terms after two companies. Mark's signals (funding, a new function leader, a rename) score each company and promote hot ones to tier 1 so their postings surface the day they land; `--weekly` writes an "About to Hire" note.

**Safer unattended runs.** Both skill runners pass explicit tools and `--permission-mode acceptEdits` instead of `--dangerously-skip-permissions`, and every run logs tokens and estimated cost. The retention pruner commits locally and pushes only with `--push`. Nothing in the repo sends email or pushes on its own.

**Human review as a checkbox.** An ambiguous board match or a learned title term lands in `vault/Market Intel/Discovery Review.md`; tick the box and the next run picks it up.

**Tests.** `python3 -m unittest discover -s tests -t .` runs 78 tests with no tokens spent (`tests/fake_claude.py` stands in for the CLI).

## Upgrading from an earlier clone

1. `cp config/discovery.example.yaml config/discovery.yaml` (graph preset, thresholds, classifier, signals).
2. Make sure `config/ats_boards.yaml` lists your boards and filters. If you only have the ATS URL table in `config/profile.md`, the first discovery run reads it and fills the registry.
3. Optional: `python3 scripts/jobfinderos_ats_poll.py --seed` once if you do not want the current backlog surfaced.
4. State moved under `$JOBFINDEROS_STATE_DIR` (default `~/.jobfinderos`); the old seen-set file migrates on first read.
5. If you installed the helper launchd jobs, re-run `scripts/JobFinderOS_install_helpers.sh`: the morning job now runs the discovery graph.

`/jobs-daily` runs discovery before the scout. The scout and the priority watch read the inbox and no longer crawl; if discovery failed, the orchestrator says so instead of skipping it.

## Known limits

- Boards on Workday, iCIMS and SmartRecruiters are not auto-discovered (SmartRecruiters can be registered by hand).
- Scoring is an LLM call and moves a few borderline postings across the thresholds between runs; the fit set is stable, the margin is not.
- Windows: the scheduler runs (PR #3), but the priority watch and daily guard still shell out to the bash runner. Tracked in #5.

## Thanks

@jonathanpperry for the Windows Task Scheduler support (#3). @pws-d2d for the unattended-run security analysis and the Windows fixes on their fork (#5). @Souheil-Yazji and @curanderacyber for the Codex and Hermes ports (#6). @krishna408 for asking the question that became the pluggable-client tracker (#2).

Versioning from here: `1.0.x` for fixes, `1.x.0` for additions that leave your config alone, `2.0.0` the day `ats_boards.yaml` or `discovery.yaml` changes shape or a skill is renamed.
