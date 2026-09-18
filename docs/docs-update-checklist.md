# Docs Update Checklist (manual version of the Cowork `update-project-docs` skill)
Run at the end of every session that changed code. Document only what actually
happened this session — never invent changes. (2026-07-03)

1. **Gather**: list what was built/fixed this session; skim `src/job_hunt_ui.py`
   for the `_PAGE_UPDATED` dict (~lines 55–65); note any new `src/*.py` files.
2. **PROJECT_LOG.md**: entries grouped by `## YYYY-MM-DD` (prepend new date block
   at top if today's absent). Per change:
   `### [title]` + Status ✅ + Motivation (1 line) + Changes (file — what) + Key facts.
3. **PROJECT_TODO.md**: mark completed items in place:
   `**Status:** ✅ Done YYYY-MM-DD — [n] tests green` (omit test note if none ran).
   Never delete items. Add newly found tasks as `⬜ Pending`. Bump `**Last updated:**`.
4. **INDEX.md**: update stale rows only (esp. `src/job_hunt_ui.py` description:
   line count + endpoints). Update the `## Feature Map` table if a feature,
   function, route, or design spec changed:
   `| Feature | Design spec (docs/tasks/) | Key functions | Routes | UI page |`
5. **docs/function_list.md**: grep current signatures
   (`grep -n "^def \|^    def \|^class " src/*.py`), add new / fix changed /
   mark deleted (don't silently remove). Update the HTTP routes table if present.
6. **Design spec status headers**: via the Feature Map, open each affected
   `docs/tasks/*.md`; update the `<!-- STATUS -->` block after the first `#`:
   Implementation status ✅/⚠️ + date, divergences, key functions, routes.
   Only ✅ when fully done; partial = ⚠️ with a note.
7. **PROJECT_CONTEXT.md / docs/product_spec.md / README.md**: update only the
   parts this session made stale (state narrative / intended behaviour /
   user-facing setup, respectively).
8. **Syntax check**: `python3 -c "import ast; ast.parse(open('src/job_hunt_ui.py').read()); print('OK')"`
   — report failure, never skip silently.
9. **Report** (≤10 lines): files updated, spec headers touched, any changed
   function with no Feature Map row (needs one), syntax check result.
