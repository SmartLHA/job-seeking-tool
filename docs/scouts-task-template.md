# Scout Task Template — Combined (v8)

> Routing rule is for SilverHand (planner) only. Scout receives tasks that are already pre-scored and pre-routed.

---

## Part A — Task Routing (SilverHand only — DO NOT send to Scout)

Before assigning any task, SilverHand MUST:

### Step 1 — Score Complexity (6 factors)
+1 if multi-step logic required
+1 if external dependency exists
+1 if requirements are ambiguous
+1 if affects multiple files or system design
+1 if correctness is critical
+1 if involves async/concurrency/state

### Step 2 — Classify
- Score 0-2 → LOW → Gemma Dev OK
- Score 3 → MEDIUM → Gemma risky, Codex fallback
- Score 4-6 → HIGH → Codex Dev only

### Step 3 — Assign Dev Model
**Gemma Dev** ONLY if ALL true:
- Score ≤ 2
- Single function or small script
- No external systems (API, DB, auth, network)
- No async/concurrency/stateful logic
- Requirements clear and specific
- Output easy to verify

**Otherwise → Codex Dev**

### Step 4 — QA Always Uses Gemma
QA (Scout) always uses Gemma with strict 12-point checklist (Part E).
Fail on any uncertainty.

### Step 5 — Escalation
- If QA FAIL on Gemma Dev output → rerun Dev on Codex
- Codex output must still pass Gemma QA
- If Codex output still FAILS QA → escalate to Mic, stop automatic retries

### Routing notes
- Routing is internal planner policy only
- Do NOT send routing JSON/YAML instructions to Scout
- SilverHand applies routing, then sends Scout only the executable task

---

## Part B — Scout Task Execution

### CRITICAL RULES
1. Each step is INDEPENDENT — status of each step does NOT flow into the next
2. If ANY check command returns error or non-zero exit code → that step is FAIL
3. Report EXACT output of each command — not interpretation
4. Do NOT change commands. Do NOT skip steps.
5. Use python3.14 explicitly (not python3)
6. Code reviewer mindset: assume code is WRONG until proven correct
7. Actively try to find edge cases, logical errors, missing handling
8. If ANY doubt exists → FAIL. Do NOT be lenient.
9. All communication returns YAML only
10. Simple dev task and QA task results both return YAML only

---

## Part C — Task Types Scout Handles

### QA Task Format
```text
task_id: scout-qa-<name>
task_type: qa
focus: [what to verify]
checks:
- [exact command 1]
- [exact command 2]
```

### QA Report — EXACT YAML ONLY
```yaml
result: pass|fail
reason: short specific reason
failed_checks: []
checks:
  check_1: "EXACT output | FAIL"
  check_2: "EXACT output | FAIL"
```

### Simple Dev Task Format
```text
task_id: scout-dev-<name>
task_type: coding
goal: [what to implement]
steps:
1. [exact command]
2. [verify command]
3. [test command]
```

### Dev Report — EXACT YAML ONLY
```yaml
task_id: scout-dev-<name>
status: pass|fail
step_1: "EXACT output | FAIL"
step_2: "EXACT output | FAIL"
step_3: "EXACT output | FAIL"
changed_files: []
failures: []
```

---

## Part D — Code Reviewer Mindset (MUST apply to ALL tasks)

### Core principle
Assume the code is WRONG until proven correct.

### What Scout MUST actively check
- Edge cases: empty input, None, zero, negative values, very large values
- Logical errors: does the condition actually match what the comment says?
- Missing handling: what happens if X is None? If the list is empty?
- Off-by-one: boundary conditions, loop limits
- Type errors: wrong type passed, None passed where not allowed
- Exception paths: does the code handle the error case or just assume success?

### Automatic FAIL conditions
- A potential bug you cannot rule out
- Missing validation you cannot verify is unnecessary
- Ambiguous test output you cannot interpret
- A test that seems to pass but produces wrong-looking data
- ANY doubt about correctness
- Not 100% sure

### Do NOT
- Assume the original developer handled it
- Accept close enough as correct
- Explain away anomalous output
- Suggest fixes in the QA verdict

---

## Part E — QA Strict Checklist (12-point — apply to every QA task)

For every QA task, verify ALL 12 points:

1. REQUIREMENT MATCH — fail if any requirement missing, misinterpreted, or extra behaviour exists
2. LOGIC CORRECTNESS — fail if algorithms, branching, loops, or conditions produce wrong results
3. EDGE CASES — fail if empty, null, zero, negative, large, or unexpected inputs are unhandled
4. INPUT/OUTPUT VALIDATION — fail on type mismatch, missing validation, or wrong structure
5. EXECUTION SAFETY — fail if code can crash under normal use
6. STATE & SIDE EFFECTS — fail if output depends on hidden state or unintended mutation
7. ASYNC/CONCURRENCY — fail if await/race/state logic is misused when applicable
8. EXTERNAL DEPENDENCIES — fail if API/DB/network error handling is missing
9. CODE QUALITY — fail if confusing or unnecessarily complex for the task
10. SELF-CHECK — fail if not 100% confident
11. MENTAL TEST CASE SIMULATION — fail if expected output cannot be confidently predicted
12. FINAL DECISION — pass only if all above checks are clear

### QA Dual-Run Rule
- Ask Scout to run all required tests twice
- Use the same model with different seed or temperature between run 1 and run 2
- Pass only if both runs return pass
- If either run fails or runs disagree → FAIL

---

## Common Issues Fixed

### Issue: Scout returns prose instead of required format
Fix: All replies start with YAML keys immediately. Nothing else before it.

### Issue: Scout echoes template text instead of real output
Fix: Each step must show real command output. If template text appears → FAIL.

### Issue: Scout guesses instead of FAIL
Fix: If unsure → FAIL. Never guess.

### Issue: Scout self-investigates when it should just report
Fix: If check fails → report FAIL. Do NOT investigate. Do NOT suggest fixes.

### Issue: Scout uses wrong Python interpreter
Fix: Always use python3.14 explicitly.

### Issue: Scout invents file content
Fix: Verify file write with tail/cat commands. Report EXACT output.

### Issue: Scout is too lenient on borderline cases
Fix: Assume code is wrong until proven correct. If ANY doubt → FAIL.
