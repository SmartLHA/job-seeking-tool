# Scout Task Template — Improved

## Core Rules

1. **EXACT output format** — reply MUST be valid YAML matching the specified structure
2. **Write to file first** — run all checks, write results to `/tmp/scout_<task>.txt`, then `cat` the file
3. **If unsure → FAIL** — don't guess. If a check errors, report as FAIL
4. **Exact commands only** — no prose, no explanation, no "I think"

---

## Standard Scout Task Template

```
## Scout QA — <Task Name>

task_id: scout-<short-name>

### Constraints
- Do NOT modify source or config
- Run from: /Users/lhaclaw/.openclaw/workspace/Job Seeking Tool
- Use python3.14 explicitly (not python3)
- result_first, bullet_or_yaml_only, max 1 line per item

### Checks
Run these EXACT commands. Write ALL output to /tmp/scout_<task>.txt

```bash
cd "/Users/lhaclaw/.openclaw/workspace/Job Seeking Tool"
echo "=== CHECK NAME ===" > /tmp/scout_<task>.txt
<exact command> >> /tmp/scout_<task>.txt 2>&1
# repeat for each check
cat /tmp/scout_<task>.txt
```

### Self-Diagnosis (if check fails)
If a check fails, DO NOT investigate further. Just report FAIL.
If ALL checks pass, status = pass.
If ANY check fails, status = partial or fail.

### Reply — EXACT YAML format
```yaml
task_id: scout-<short-name>
status: pass | partial | fail
check_1: "EXACT output from file" | "FAIL"
check_2: "EXACT output from file" | "FAIL"
check_3: "EXACT output from file" | "FAIL"
gaps: []
failures: []
actions: []
confidence: high | medium | low
```

## Common Issues Fixed

### Issue: Scout returns prose instead of YAML
Fix: Start reply with `task_id:` line. Nothing else before it.

### Issue: Scout guesses instead of FAIL
Fix: Rule: "If unsure → FAIL. Never guess."

### Issue: Scout doesn't follow exact grep commands
Fix: Give exact `grep -E "pattern1|pattern2"` commands, not "check if X"

### Issue: Scout ignores write-to-file convention
Fix: Always `> /tmp/scout_xxx.txt` then `cat`. Never pipe directly to reply.

### Issue: Scout self-investigates when it should just report
Fix: "If check fails → report FAIL. Do NOT investigate. Do NOT suggest fixes."
