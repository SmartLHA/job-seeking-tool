# Autonomous Skill Creation — Design Spec v3

**Status:** Draft v3 — revised after Wiser review
**Version:** 3.0
**Created:** 2026-04-11
**Changes from v2:** Override scoped to require complexity signal, evidence in-session metadata only, deduplication rules operationalized, REVISE loop defined, schema validation added

---

## Core Principle

**Approval required before any persistence.** Drafts in-memory only. Nothing on disk until Mic approves. Evidence is ephemeral in-session metadata only. No silent skill creation — ever.

---

## Trigger Conditions

**Deterministic rule:** Both conditions must be true:

### Condition 1: Complexity Signal (≥1 of)
- >10 minutes elapsed time
- ≥3 tool calls across different phases (not retries)
- External dependencies (API, file I/O, network calls)
- Non-obvious decision points or error recovery
- User explicitly flagged the approach as worth remembering

### Condition 2: Reusability Signal (≥1 of)
- Same or similar task class encountered ≥2 times (logged evidence required)
- Approach is generalizable — not purely project-specific
- Contains a stable, repeatable procedure with verification
- User said "remember this" or "this worked well"

### Override (user-initiated)
If Mic explicitly says "create a skill for this":
- Skip reusability check
- **But still require at least one complexity signal** from the list above
- One-off user-specific tasks still filtered by complexity threshold
- User-specificity filter applies: if task is purely user-private data, mark as USER-SPECIFIC and skip

**Logged evidence for "same class"** — stored as ephemeral in-session metadata only:
```yaml
task_class_evidence:
  pattern: "<description>"
  occurrences: <count>
  examples: ["<brief example 1>", "<brief example 2>"]
  # No raw task content stored — just pattern + count
```

---

## Evidence and Privacy Rules

| Data | Allowed? | Where |
|------|----------|-------|
| Task pattern description | ✅ Yes | In-session metadata only |
| Example summaries (no raw content) | ✅ Yes | In-session metadata only |
| Raw task input/output | ❌ Never | Not stored before approval |
| User-private data | ❌ Never | Excluded from all logs |

Evidence logging must not capture raw command output, file contents, or user messages.

---

## Draft Creation (In-Memory Only)

- Draft exists **only in subagent memory** during creation
- Never written to `skills/`, `tmp/`, or any persistent location
- If subagent interrupted → draft lost (intentional)
- Passed back as structured payload to main session
- Payload schema validated before presentation

### Schema Validation (before approval UI)
Before showing the approval request, validate:
- `title` present and ≤60 chars
- `category` is a known category
- `body.when_to_use` non-empty
- `body.procedure` non-empty
- `body.verification` non-empty
- No fields missing from required schema

If validation fails → do not propose, log as failed attempt silently.

---

## Approval Flow

```
Task completes
  ↓
Self-reflection checks: both complexity + reusability signals true?
  ↓No ──→ Skip silently, no notification
  ↓Yes
Override check: user said "create a skill"?
  ↓Yes ──→ Require ≥1 complexity signal, otherwise skip
  ↓No
Isolated subagent writes draft IN MEMORY only
  ↓
Schema validation of payload
  ↓Fail ──→ Discard draft silently, log failure
  ↓Pass
Subagent returns structured payload
  ↓
SilverHand formats approval request for Mic:
  ┌─────────────────────────────────────────────┐
  │ Skill proposed: <title>                    │
  │ Category: <category>                        │
  │ Triggered by: <conditions met>              │
  │ Confidence: LOW | MEDIUM | HIGH             │
  │ Reusability: <why worth saving>             │
  │ Provenance: source_task, timestamp           │
  │                                             │
  │ [Full draft preview]                       │
  │                                             │
  │ [APPROVE] [REVISE] [REJECT]                 │
  └─────────────────────────────────────────────┘
  ↓
Mic APPROVES → SilverHand writes to skills/autonomous/<category>/
Mic REVISE   → Mic edits inline or returns changes
              → Revisions stay in-memory
              → Mic approves revised → write
              → Mic rejects → discard, no trace
Mic REJECT   → Draft discarded, no trace
```

### REVISE Loop Rules
- Revisions remain **in-memory only** until final approval
- Each revision round resets any prior suppressions on that task class
- After 3 REVISE rounds without approval → auto-reject, suggest manual creation instead
- Rejection does not create disk artifacts

---

## Structured Approval Payload

```yaml
draft_proposal:
  title: "<skill title>"           # ≤60 chars
  category: "<category>"           # known category
  confidence: LOW | MEDIUM | HIGH
  privacy: GENERALIZABLE | USER-SPECIFIC  # auto-classified

  trigger_rationale:
    complexity_signal: "<which complexity condition met>"
    reusability_signal: "<which reusability condition met>"
    evidence: "<brief evidence summary, no raw content>"

  draft:
    name: <slug>                   # auto-generated from title
    description: <one-line>       # ≤120 chars
    version: "0.1.0"
    draft: true
    provenance:
      created: <ISO timestamp>
      source_task: <brief description>
      trigger_signals: [<list of met conditions>]
    body:
      when_to_use: <...>
      procedure: <...>
      pitfalls: <...>
      verification: <...>
```

---

## Skill Format (on disk after approval)

```yaml
---
name: <slug-name>
description: <one-line when-to-use>
version: 0.1.0
draft: false
provenance:
  created: <ISO timestamp>
  source_task: <brief description>
  trigger_signals: [<list>]
  confidence: LOW | MEDIUM | HIGH
  privacy: GENERALIZABLE | USER-SPECIFIC
  approved_by: mic
---
# <Skill Title>

## When to Use
## Procedure
## Pitfalls
## Verification
```

---

## Namespace Isolation

| Location | Purpose | Written by |
|----------|---------|-----------|
| `skills/autonomous/<category>/` | Only after explicit approval | SilverHand |
| `skills/curated/<category>/` | Manually maintained skills | Mic or Handy |
| `skills/drafts/` | **Never used** | N/A |

- Collision check before write: if exists → increment version, do not overwrite
- `privacy: USER-SPECIFIC` skills never go to `skills/autonomous/` — stored in `skills/user-specific/` only
- Autonomous skills have `draft: false` on save
- Cannot overwrite or modify `skills/curated/`

---

## Deduplication Rules (Operationalized)

**Same-class detection** — defined as both:
- Same category AND
- Either title similarity ≥70% (Levenshtein) OR procedure overlap ≥50%

**Suppression windows:**
- After approval: same class suppressed 7 days
- After rejection: same class suppressed 30 days
- After 3 REVISE rounds: auto-reject, suppressed 7 days

**Uncertain = suppress.** If same-class determination is ambiguous, default to proposing (Mic can reject).

**Near-duplicate check** before proposing:
1. Load all existing autonomous skills in same category
2. Compare title similarity + procedure overlap
3. If ≥70% title similarity OR ≥50% procedure overlap → suppress with note "near-duplicate found"

---

## Audit Event (on approval or rejection)

After verdict, write one-line metadata to ephemeral audit log only:
```
<timestamp> | <verdict> | <title> | <category> | <confidence>
```
Not stored to disk after session ends — used only for trigger quality tuning if reviewed.

---

## What Is NOT Attempted

- Automatically improving existing skills
- Writing drafts to disk before approval
- Storing raw task content as evidence
- Single data point skill creation (even under override)
- Code-level tool creation (SKILL.md only)
- Silent saves

---

## Open Questions (all resolved in v3)

- [x] Override requires complexity signal — resolved
- [x] Evidence in-session metadata only, no raw content — resolved
- [x] Operationalized same-class/near-duplicate rules — resolved
- [x] REVISE loop defined — resolved
- [x] Schema validation before approval UI — resolved
- [x] USER-SPECIFIC filter — resolved
- [x] Audit metadata on verdict — resolved
