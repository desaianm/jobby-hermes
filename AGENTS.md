# Contributions

This standalone export contains `personal_jobby` and seven synthetic test modules.
Keep changes scoped to the requested work; preserve deterministic, source-backed
facts and the external Hermes browser boundary. For CLI or guard changes, read
[the CLI contract](personal_jobby/CLI.md) and
[operator skill](personal_jobby/skills/hermes-jobby-daily/SKILL.md) first.

Use Codex for coding-agent work here. Do not invoke Claude Code, alternate coding
agents, delegated agents or billable model APIs. External Hermes is the runtime
browser operator, not a contribution/testing agent.

Test with the ignored checkout `.venv` and synthetic temporary workspaces. Set
`JOBBY_ROOT` to a fresh absolute temporary directory before CLI smoke checks.
Never read real candidate state, perform live search/submit, enable schedules or
change services as part of development verification. Keep private data and
credentials out of repository files, test output and diagnostics.

Run all seven test modules and relevant syntax checks using the commands in
[README verification](README.md#verification). Check launcher help and parse
`status --brief` JSON from another working directory with temporary state.
Report actual results and blockers; do not invent receipts or visual QA.
Before sharing changes, inspect the changed files for private data and verify
`.gitignore` still excludes databases, profiles and `.venv`. Commit, push or
publish only when the user explicitly authorizes that action.
