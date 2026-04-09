# Scout Certification Protocol

## Purpose

Define and enforce which roles Scout can reliably perform. Scout is certified per role based on demonstrated performance, not assumed capability.

---

## Role Definitions

### Role: Scout-QA
**Description:** Verify code correctness using strict 12-point checklist and dual-run agreement.
**Always allowed:** Yes.

### Role: Scout-LowDev
**Description:** Execute low-complexity single-file dev tasks that score ≤ 2 on routing complexity scale.
**Allowed:** Only for tasks that pass routing gate.
**Always denied:** Multi-file, external dependencies, ambiguous bug fixes, architecture work.

### Role: Scout-Reject
**Description:** Tasks that Scout should refuse and escalate back to SilverHand.
**Always denied:** Anything above low complexity or outside the defined allowed scope.

---

## Certification Requirements

### Certification thresholds
- Scout is **certified** for a role after **5 consecutive successful completions** with no fabrication or format errors.
- Scout is **decertified** if it fails, fabricates output, or returns wrong format **even once**.
- Decertification resets the counter and requires 5 fresh successes to recertify.

### What counts as a success
- QA: returns valid YAML, both dual-runs agree, all checklist items verified YES
- LowDev: returns valid YAML, file written correctly, tests pass

### What counts as a failure
- Returns fabricated or invented content
- Returns wrong output format (not YAML/JSON where required)
- QA: dual-runs disagree
- Dev: file not written, or written incorrectly
- Any instruction to guess or assume rather than fail

---

## Scout Task Log

Location: `~/.openclaw/workspace/memory/scout-task-log.md`

### Fields
```yaml
task_id: <string>
task_type: qa | lowdev
routed_role: scout-qa | scout-lowdev
focus: <short description>
complexity_score: 0-6
result: pass | fail
fabrication: true | false
format_error: true | false
dual_run_agree: true | false | na
escalation_needed: true | false
escalation_outcome: none | codex-dev | micromanual
notes: <short free text>
date: YYYY-MM-DD
```

### Log review trigger
Review log after **every 10 tasks**. If any decertification event occurs, review immediately.

### Review actions
- If certification threshold broken → mark decertified, notify Mic
- If trend shows consistent failure in one role → restrict that role
- If reliable across 20 tasks → consider permanently certifying

---

## Scout Prompt Wrappers

### Scout-QA prompt
```
You are Scout-QA. Your role is strict code verification.
[Apply Part E 12-point checklist]
[Apply dual-run rule]
[Return YAML only]
```

### Scout-LowDev prompt
```
You are Scout-LowDev. Your role is simple single-file dev.
[Pre-routed low complexity task]
[Exact commands only]
[Verify file write]
[Return YAML only]
```

### Scout-Reject prompt
```
You are Scout-Reject. Your role is routing gatekeeper.
If this task exceeds low complexity → FAIL and escalate to SilverHand.
```

---

## Hard Guardrails for SilverHand (Planner)

Before sending ANY task to Scout, SilverHand MUST:
1. Score complexity (6 factors)
2. Apply routing gate — deny if > 2 or any hard violation
3. Choose correct role wrapper
4. Verify commands before handing to Scout
5. Log the routing decision before sending

---

## Escalation Path

```
Task received → SilverHand scores complexity → Routes to correct role
                                                           ↓
                                     Scout-LowDev → QA verify after
                                                           ↓
                                     Scout-QA → Strict checklist
                                                           ↓
                                     Pass → Done
                                     Fail → Re-run on Codex Dev
                                                           ↓
                                     Codex + QA still fail → Escalate to Mic
                                                           ↓
                                     Mic reviews summary → Decision
```

---

## Certification Status

| Role | Status | Certified Since | Consecutive Passes |
|------|--------|-----------------|-------------------|
| Scout-QA | TBD | — | 0 |
| Scout-LowDev | TBD | — | 0 |

Update status after each task log review.
