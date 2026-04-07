# UI Flow Change — Paste Text + URL Input with Pre-Fill

**For: Handy**
**Status: Ready to hand off**
**Depends on: Mic approval, current UI scope in `docs/ui_scope.md` (updated)**

---

## Goal

Update UI to support two new input modes with AI pre-fill and a review step before evaluation.

---

## Scope

### IN
- URL fetch + webpage parsing → pre-fill job fields
- Paste job text + AI parsing → pre-fill job fields
- Review/edit step before evaluation
- Respect robots.txt for URL fetching
- Fallback: if parsing fails, show raw text → user fills manually

### OUT
- Auto-submit after parsing
- Multi-URL scraping
- Bulk import
- No browser automation beyond single URL fetch

---

## New Data Flow

```
1. User enters URL or pastes text
         ↓
2. If URL → fetch page, parse with src/parsing.py
   If pasted text → parse with src/parsing.py
         ↓
3. Pre-filled form shown to user for review/edit
         ↓
4. User clicks "Evaluate" → confirmed review step
         ↓
5. Evaluation runs → result screen
```

---

## Changes Required

### `src/ui.py`
- Add URL fetch handler (`/fetch` endpoint or integrated)
- Add text paste parsing handler
- Add review/edit step between input and evaluation
- Update screen flow: home → input → review → result
- Keep existing form flow as manual fallback

### `src/parsing.py` (new module)
```python
def parse_job_from_text(raw_text: str) -> dict:
    """Parse pasted job text into structured job fields.
    Uses deterministic extraction first, LLM fallback for field completion.
    Returns dict matching JobPosting shape."""

def parse_job_from_url(url: str) -> dict:
    """Fetch webpage, extract job posting text, pass to parse_job_from_text.
    Must respect robots.txt.
    Returns dict matching JobPosting shape on success, raises on failure."""
```

### `src/orchestrator.py`
- `submit_reviewed_job()` — already exists, works for parsed form submission

### `src/models.py`
- `JobPosting` fields already exist — no model changes needed

---

## Acceptance Criteria

1. User can paste job text → form pre-fills → user edits → clicks Evaluate → result shown
2. User can enter URL → page fetched → form pre-fills → user edits → clicks Evaluate → result shown
3. If URL fetch fails → error shown, manual paste offered
4. If parsing fails → raw text shown, user fills manually
5. Review/edit step always appears before Evaluate (user must confirm)
6. No auto-submit after parsing
7. Existing manual form flow still works as fallback
8. All new functions have tests

---

## Files to Change

| File | Change |
|------|--------|
| `src/parsing.py` | New module — parse from text, parse from URL |
| `src/ui.py` | Add URL/text input screen, review step, fetch handler |
| `tests/test_parsing.py` | New — text parsing, URL fetch (mocked), fallback behavior |
| `docs/ui_scope.md` | Updated v2 (done) |
| `docs/development_sequence.md` | Update UI scope entry |

---

## Test Command
```bash
python3 -m pytest tests/test_parsing.py tests/test_ui.py -v
```

---

## Notes

- robots.txt check: use `urllib.robotparser.RobotFileParser` before fetching
- URL fetch timeout: 10 seconds max
- Parsing fallback: if LLM unavailable, return empty fields and let user fill
- Do not store fetched webpage content — only the parsed structured data
