# Job Seeking Tool — project CLAUDE.md (rewritten 2026-07-03; previous version in CLAUDE.md.bak-*)

Global rules live in ~/.claude/CLAUDE.md and apply here. Project-specific below.

## Read first
- `INDEX.md` — file map + Feature Map (feature → spec → functions → routes)
- `PROJECT_CONTEXT.md` — where things stand
Do NOT bulk-read src/ to orient; dispatch a scout (see ~/.claude/rules/dispatch.md).

## Skill routing — by surface
gstack: NOT installed. A reference source checkout exists at ~/gstack only. gstack is Claude Code-native (installable via its setup script into ~/.claude/skills/) — the earlier note that gstack is Cowork-only was incorrect. Do not run gstack's setup without Mike's explicit instruction. The design-council skill uses a built-in gstack-style fallback and does not require gstack. gstack skills, if ever installed, must comply with the Loop policy in dispatch.md.
In Cowork: route as listed. In CLI: these skills are absent — say so, then do
the work directly under ~/.claude/rules/ instead of hunting for the skill.
- Product ideas / "worth building?" → office-hours
- Bugs / errors / "why broken" → investigate
- Ship / deploy / PR → ship
- QA / test the site → qa
- Code review → review
- Docs after shipping → update-project-docs (Cowork; in CLI follow `docs/docs-update-checklist.md`)
- Architecture review → plan-eng-review; design review before code → design-council (design-council also works in Claude Code CLI — installed at ~/.claude/skills/)

## Project facts
- Run UI: `python3 src/job_hunt_ui.py` (main server; endpoints listed in INDEX.md)
- Tests: `pytest tests/` — run relevant subset before claiming done (judgment.md §2/§5)
- Reed API creds in `.env` — never print or commit
- Decision colours: Apply/Review/Skip with score thresholds — spec is
  `docs/product_spec.md`; per-feature design specs live in `docs/tasks/`
  (find the right one via the Feature Map table in `INDEX.md`). Score scales
  use RANGES, not single anchor points (Mike's standing rule)
- Fixtures/scratch: new test data under `tests/fixtures/`, scratch under
  `archive/` — nothing new at project root
