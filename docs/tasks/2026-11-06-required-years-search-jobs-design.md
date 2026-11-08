# Required years for search-source jobs — design

Status: r2 approved by Mike on 2026-11-07 ("Approve as recommended"). Step 0 then met its
stop rule (section 17). Mike then chose the paste-and-URL fix only ("Fix paste and URL only"),
specified in section 18. The rest of this design is not built. Section 18 was built in
`153196a`; its blind test (B2) missed the limits and Mike chose to keep it (section 19).
Date: 2026-11-06. Line numbers are from `main` at `6579980`.

## 1. Read this first: what the feature will and will not do for you

**For a candidate with many years of experience, this feature will rarely change the score.** A missing
requirement already gives full experience marks, and meeting a requirement gives the
same full marks. The score drops only when an advert asks for more than the candidate's configured years.

**Its largest side effect is on decisions, and that effect is not a gain.** Missing
years costs 20 confidence points today (`src/job_hunt_config.py:45`). Low confidence is
the guard that holds thin-data jobs at Review instead of Apply
(`src/job_hunt_decision.py:44-47`). Because unknown fields score neutrally, these
thin-data jobs can score about 90. A found number gives no real fit information at the
configured years, but it would lift confidence enough to remove that guard.

Measured with the real `evaluate_reviewed_job` on synthetic jobs, candidate with the configured years,
balanced preset (working files are kept locally and are not in git):

| Job data | No value today | Advert asks 5 years, value counts for confidence | Advert asks 20 years, value counts for confidence |
|---|---|---|---|
| All known except domain | 93.5, medium, Apply | 93.5, high, Apply | 83.5, high, Apply |
| No required skills | 90, low, **Review** | 90, medium, **Apply** | 80, medium, **Apply** |
| No salary, no work mode | 87.5, low, **Review** | 87.5, medium, **Apply** | 77.5, medium, Review |
| No location, no work mode | 87.5, low, **Review** | 87.5, medium, **Apply** | 77.5, medium, Review |
| No skills, no salary | 90, low, **Review** | 90, medium, **Apply** | 80, medium, **Apply** |

The digest never sets `domain` (`src/ui_utils.py:44-58`), so those 8 points are always lost.

**Recommendation: an extracted number does not count for confidence** (section 5). No job
then moves up to Apply because of this feature. What remains:
- **The configured years count** on the rare adverts that ask for more than you have.
- **You see what the advert asked for**, with the sentence it came from.
- The code is correct if your years ever change.

That is a small benefit, so this design recommends a small build (section 6) and a
check on your real jobs before any code is written (section 12, Step 0).

## 2. How jobs reach the scorer today

`_score_experience` (`src/job_hunt_scoring.py:157-170`) reads
`job.required_years_experience`. Search jobs never set it.

| Path | Built at | Text available | Required years today |
|---|---|---|---|
| Digest, all sources | `src/job_hunt_scheduler.py:260` via `reviewed_job_payload_from_ui_result` (`src/ui_utils.py:19-58`) | Reed and Adzuna: 500-character preview. LinkedIn: full text (`src/job_sources/linkedin_source.py:390`) | Key absent |
| Select and batch evaluate, Reed | `src/job_sources/reed_source.py:111-193` | Full text; one detail call at `:144` already happens | `""`, becomes None |
| Select and batch evaluate, Adzuna | `src/job_sources/adzuna_source.py:279-332` | Snippet only | `""`, becomes None |
| Select and batch evaluate, LinkedIn | `src/job_sources/linkedin_source.py:414-495` | Full text | `""`, becomes None |
| Paste and URL | `src/job_hunt_parsing.py:268`, stored at `:299` | Full text | `_extract_years` |
| Reed CLI flow | `src/job_hunt_orchestrator.py:317` | Preview | Hard-coded None |

Corrections to the brief:
- `_extract_years` is at `src/job_hunt_parsing.py:511`, called once at `:268`.
- `src/job_hunt_orchestrator.py:317` is **not** the live path. `run_reed_evaluation_flow`
  is called only from `tests/test_orchestrator.py` (shell-checked 2026-11-06). This
  design leaves it alone.
- Batch evaluate reuses the select handlers (`src/ui_handlers.py:1992`). The digest does not.

## 3. Is `_extract_years` accurate enough to reuse? No.

It takes the first "number + years" anywhere in the text (`src/job_hunt_parsing.py:512`).

**Blind measurement.** 80 synthetic UK adverts, labelled by a separate agent that had not
seen any extractor. A strict prototype was frozen first (SHA-256 `f081f433…`) and run once.

| Blind set, 80 adverts | Current `_extract_years` | Strict prototype |
|---|---|---|
| No requirement stated (39): wrongly gave a number | **27 of 39 (69%)** | **1 of 39 (2.6%)** |
| Requirement stated (41): correct lower bound | 18 of 41 (44%) | 37 of 41 (90%) |
| Requirement stated: wrong value | 15 | 1 |
| Requirement stated: missed (stays neutral) | 8 | 3 |
| Would lower the score of a candidate at the configured years | 8 | 1 |

The probe scripts and saved output are kept locally and are not in git.

**Limits. Read these before trusting the numbers.**
- All text is synthetic, and 30 of 80 are deliberate traps. These are rates on known
  patterns, not rates on real adverts. **Real-advert accuracy is UNVERIFIED.**
- 1 of 39 is a small sample: the 95% upper bound is 13.5%.
- Labels were written by one agent and not reviewed by a second.
- The set is no longer blind, because its failures have been read. The build must
  measure on a new blind set (AC2).
- **The blind set's line breaks do not match production text.** LinkedIn text is fully
  flattened (`src/job_sources/linkedin_source.py:383`), and Reed's `strip_html` removes
  `<li>` with no separator (`src/job_sources/normalize.py:57-60`). In those two shapes
  the prototype found 4 of 6 requirements in the 10 full adverts, not 5 of 6, with no
  false match (working files kept locally, not in git). The real
  HTML that Reed sends is UNVERIFIED.

**Known false matches the prototype still makes** (run on 2026-11-06):
- "With over 18 years' experience in the recruitment industry, Acme Recruitment is proud
  to offer this role." gives 18, because the sentence names the company instead of "we".
- "Essential SQL skills Desirable 18 years' experience in banking" gives 18, because a
  flattened list joins the two words into one sentence.
- "Strong SQL5+ years experience" gives nothing (a miss, from joined list items).

**False-match risk at the configured years.** Today a false 30 from "established 30 years ago" takes
experience marks to 0 (-15 or -20), because the configured years are below 60% of 30. With the design:
- A false number above the configured years, up to 20, takes half marks (-7.5 on salary_focused, -10 on balanced)
  and can drop a job below the threshold, which clears its pending AI review
  (`src/job_hunt_scheduler.py:500-503`). This is the remaining harm.
- A false number at or below the configured years changes nothing, if section 5 is accepted.
- A false number above 20 is ignored.

**Decision: replace it with a strict extractor on every path,** so that one advert never
gives two answers. Paste and URL reuse is safe: a person reviews that form before saving.
A number counts only if all of these hold, each tested on a **short window around the
number**, not on the whole "sentence", which may be a whole flattened advert:
1. An experience cue is next to it ("experience", "working as", "as a", and similar).
2. The words around it are not a trap (age, company history, contract or programme
   length, service awards, retention, UK residency for clearance, "within 2 years").
3. A company boast ("we", "our", "established", "with over N years ... industry") needs
   a candidate cue ("you", "must", "required", "minimum", "looking for").
4. It is not desirable-only. "Desirable: 10 years" gives no requirement.
5. The lower bound is 20 or less. Above that it is treated as not stated, so "15-25
   years" gives 15, and "25 years" gives nothing.

If several numbers pass, use the highest lower bound. No number gives null, as the
existing rules require (`docs/tasks/url-ingestion-design.md:162`,
`docs/data_contract.md:24-25`).

For extraction only, `</li>` becomes a line break. Stored text does not change.

Other failures to fix: "ten or more years", "seven (7) years", "18 years or older and
have 2-3 years' experience" (crossed into the next number), "ideally" later in a line
marking the whole line as desirable, "4 year degree apprenticeship in software", and
number words 13, 14 and 16 to 19.

Known limits: the 20 cap means a true 21 scores better than a true 20, and the job page
shows "Not stated" for it. Months ("18 months' experience") and vague text ("several
years") stay neutral. The trap list will grow as real false matches appear.

## 4. Score scale, as ranges

The bands below are ranges, as your standing rule asks. Candidate years are compared
with the **lower bound** of the advert's requirement, so "3-5 years" no longer becomes a
single 5 (today a 4-year candidate would get half marks on it). The formula and the 0.6
ratio do not change (`src/job_hunt_config.py:59`).

| Candidate years, against the advert's lower bound | Band | Share of weight | Balanced (20) | salary_focused or skills_focused (15) |
|---|---|---|---|---|
| Requirement not stated | Unknown | 100% | 20 | 15 |
| 100% or more (inside or above the range) | Meets | 100% | 20 | 15 |
| 60% up to, not including, 100% | Partly meets | 50% | 10 | 7.5 |
| Below 60% | Below | 0% | 0 | 0 |

Only the lower bound is stored; the source sentence shows the full range. A job far below
your level (many years against "2-3 years") stays in Meets, with no penalty. Your salary
floor already catches many such jobs. A penalty would need the upper bound stored, so it
is left for later (section 8).

## 5. Confidence rule

**Rule: a value extracted from an advert does not count for confidence.** The 20-point
penalty stays until a person has given the number. Only the check in `_derive_confidence`
changes (`src/job_hunt_scoring.py:260`).

- **Effect:** no job moves up to Apply because of this feature. With your profile's years
  set, a false number at or below the configured years has no effect on score or decision. (If a profile has
  no years, any set value gives half marks, `src/job_hunt_scoring.py:164-165`.) Confidence
  stays as it is today.
- **Score note:** the "did not include explicit required years" note
  (`src/job_hunt_scoring.py:293`) changes for these jobs, to say the number came from the
  advert and is not confirmed, so it still explains the lost confidence points.
- **How it knows:** the job's `notes` holds the source sentence (section 8). If the stored
  number equals the number in that sentence, it is treated as extracted.
- **How to confirm a number yourself:** on the Evaluate form, type a different number or
  delete the note line. The number then counts, as a typed number does today.
- **Paste and URL are not affected:** they add no note, because a person reviews the form
  before saving. They behave as today apart from the stricter extractor.

The alternative is Q2 in section 15: the number counts, and the Apply jobs in the table in
section 1 appear. Step 0 will count how many of your jobs that would be.

## 6. Scope: small build first, Reed digest only if the check supports it

**Phase A, the recommended build. No new API calls.**
- Strict extractor on paste and URL.
- Select and batch evaluate on all three sources. Reed uses the full text it already
  fetches at `src/job_sources/reed_source.py:144`. If that fetch fails, nothing is
  extracted from the preview.
- Digest: LinkedIn (full text) and Adzuna (snippet), set inside
  `reviewed_job_payload_from_ui_result`, whose only `src/` caller is the digest. So
  `src/job_hunt_scheduler.py` does not change.
- Backfill of saved text (section 7).

**The gap in Phase A: Reed digest jobs stay neutral until you select them.** The Reed
preview is not used, because it would disagree with the full text: the requirement was in
the first 500 characters in 0 of 6 synthetic full adverts, and a stored real job's preview was much shorter than its full text (from a read-only check
of the owner's saved jobs; figures kept locally, not published). Adzuna snippets are also
short, so expect mostly "Not stated" there.

**Phase B, Reed digest full text. Not approved by this document.** Build it only if Step 0
supports it, and ask again with the real numbers. It costs one detail call per job:
- Call only for a new job with no preview extraction, whose first score is at or above
  `min(digest_threshold, apply_threshold)`. A found value can only keep or lower a score.
- At most 30 calls per run, 1 second between calls, stop at the first 429. This needs
  `fetch_reed_job_detail` to expose the status code, because today it returns None for
  404, 429 and network errors alike (`src/job_sources/reed_client.py:98-119`).
- No retry: a job over the limit stays neutral until a re-runnable backfill reaches it.
- It needs a helper call of about 3 lines at the digest seam, so build it after
  PR SmartLHA/job-seeking-tool#5 has merged.

**API cost.** Reed publishes no rate limit or daily quota for this API
(https://www.reed.co.uk/developers/jobseeker, seen 2026-11-06). One unofficial report says
a limit exists but is undocumented
(https://pub.towardsai.net/how-to-automate-job-searches-with-python-9a1b04b33036; UNVERIFIED,
the page refused a second fetch). The
2,000-per-hour figure on Reed's site is for its Recruiter API
(https://www.reed.co.uk/developers/Recruiter). The client has no call counter. Calls today:
one search per saved search, one detail per selected job, and one detail per job the LLM
worker claims (default at most 10 per run, `src/job_hunt_profile.py:227`).

Adzuna has no sanctioned route to full text. Its docs say search gives a snippet and show
no detail endpoint (https://developer.adzuna.com/docs/search). Fetching `redirect_url` may
breach its terms (https://developer.adzuna.com/docs/terms_of_service; my reading, not
confirmed). Do not fetch it. Neither API has a structured experience field.

## 7. Saved jobs

**Re-score does not change.** `_reevaluate_digest_jobs_locked` reads the stored JSON, never
writes it, and promises no fetch and no Gemini call of its own
(`src/job_hunt_scheduler.py:369-371`). It uses whatever value is stored. Without a
backfill, old jobs stay neutral.

**Backfill is a separate one-off step.** `scripts/backfill_required_years.py`, which I run
for you with your consent:
- covers digest jobs whose `required_years_experience` is null, on LinkedIn and Adzuna;
- the default is a dry run that writes nothing and prints counts per source;
- `--apply` copies each file to a timestamped backup, then writes;
- never overwrites an existing number, and a second run changes nothing unless you have
  cleared a value. Reed stays null in Phase A.

You then press the existing Re-score button.

**What a Re-score press does.** A score can only stay or fall because of this feature. But
any press today also marks as unread, and queues for AI, each job at or above the threshold
that was never queued (`src/job_hunt_scheduler.py:486-497`), up to `digest_max_llm_per_run`.
Each queued job costs one Gemini call and one Reed detail call. This is existing, tested
behaviour (`tests/test_digest_reeval.py:132-142`), not caused by this feature. The dry run
prints that count so you know before you press.

## 8. Data changes: no new keys

The value goes in the existing `required_years_experience`, and the source sentence in the
existing `notes`: `Required years, from the advert: "…"`, up to 160 characters cut around
the number. It is appended, so your own notes stay. `notes` is not sent to the LLM.

**Why no new keys.** `reviewed_job_from_dict` rejects unknown keys
(`src/job_hunt_reviewed_input.py:57-61`), and that error is not a `StorageError`. Under
older code a job holding a new key does not count as `missing`. It stops the whole Re-score
at that job (`src/job_hunt_scheduler.py:400-404`), and it fails the LLM batch and the job
page too. A stale copy of the app ran until 2026-11-05, so this can happen in practice.
With no new keys, any version of the code can read the files.

**What this gives up:** the upper bound is not stored as a number, so the range is shown
only in the sentence. If a penalty for being far above the range is wanted later, first
make those loaders tolerate unknown keys, and only then add the key.

Job page (`src/ui_render.py:2641`): "Required experience: 5 years", with the source sentence
below it, or "Not stated". The sentence is third-party text and must be escaped.

On the Evaluate form, your typed number always wins. Nothing overwrites a number you typed.
Existing values from `_extract_years` stay as they are, with no note and no label.

## 9. Which branch to build on

**Build Phase A on the PR SmartLHA/job-seeking-tool#4 tip,
`fix/main-test-regressions-2026-11-05` (`174772b`), or on `main` if PR #4 has merged.**

- **Why not `main` as it stands:** it has 46 known failing tests, all in UI, digest, search
  and form test files such as `tests/test_ui.py` (11), `tests/test_digest_e2e.py` (4) and
  `tests/test_digest_ui.py` (3). A new defect in a test that already fails cannot be seen.
  PR #4 fixes them: its body reports 2766 passed, 17 skipped, 0 failed at `e3bc283`, and
  its CI is green.
- **Why not PR #5:** Phase A does not need it. PR #5 and the three branches on top of it
  change `src/job_hunt_scheduler.py`, which Phase A does not touch. In
  `src/job_sources/reed_source.py` they change `:395` and `:289-299`; Phase A changes
  `:166-190`. In `src/ui_render.py` they change `render_profile_page`; Phase A changes `:2641`.
- PR #4 merges with PR #5 and each of the three branches with no conflict
  (`git merge-tree`, 2026-11-06).

No unmerged branch touches `src/job_hunt_parsing.py`, `src/job_hunt_scoring.py`,
`src/ui_utils.py`, `src/job_sources/adzuna_source.py` or `src/job_sources/linkedin_source.py`.

## 10. Alternatives rejected

| Option | Why not |
|---|---|
| Reuse `_extract_years` | 69% false matches on the blind set |
| Ask Gemini, by extending the skill prompt | Costs quota per job, not repeatable, and needs full text anyway. Reconsider only if Step 0 shows the regex misses too much |
| Take years from the LLM worker's Reed fetch | Covers only queued jobs, does nothing when LLM is off, adds a write path |
| New keys for upper bound and evidence | Older code stops on them (section 8), and they need form logic |
| Store Reed full text and use it for skills too | Likely useful, but shifts every new job's skill score. A separate decision |
| Lower the "not stated" share below 100% | Moves all scores. Not asked for |

## 11. Non-goals

Gemini extraction; fetching Adzuna redirect pages; storing Reed full text; the Reed CLI flow;
manual bookmarks; `nice_to_have_years_experience`; months; a penalty for being above the
range; changing weights, presets or the 0.6 ratio; Phase B unless approved later.

## 12. Build steps, each committed after its checks pass

0. **Real-data check, before any code** (needs consent, Q3). Run the frozen prototype on
   the owner's saved jobs, read-only, plus at most 10 live detail calls on saved Reed jobs,
   stopping after 3 empty replies in a row. The output stays in the session scratchpad, not
   in git:
   - source split of the saved jobs;
   - per job: source, value, sentence;
   - sentences holding "N years" that the extractor rejected, so that misses can be seen;
   - per job: score, confidence and decision today, and under each confidence rule;
   - how many adverts ask for more than the configured years.

   **Stop and re-plan if** more than 1 in 10 found values is wrong by your reading, or a
   value is found on under 20% of the Reed full texts. With fewer than 10 found values
   there is not enough to judge: I report that and you decide.
1. Strict extractor, tests, and the switch for paste and URL.
2. Confidence rule, note format, job page.
3. Reed, Adzuna and LinkedIn select handlers.
4. Digest payload for LinkedIn and Adzuna.
5. Backfill script. Run dry, then apply with your consent. You press Re-score.
6. Docs per `docs/docs-update-checklist.md`, the new blind set, full suite, trial merges,
   fresh verifier.

Builder: routed by `~/.claude/rules/dispatch.md` when the build starts.

## 13. Acceptance criteria

- **AC1 Extractor.** `tests/test_required_years.py` passes on the development cases, the old
  blind set, and every failure and false match named in section 3.
  `tests/test_parsing.py:17,30` still gives 5.0, and `:146-148` still gives None.
- **AC2 New blind set.** A new agent writes at least 100 labelled adverts. Its prompt is saved
  with the set, and forbids reading `src/` and the probe files. At least half are full-length,
  named-company boasts are included, and all text goes through the real `strip_html` and
  whitespace squash. The final extractor, run once:
  - at most 5% false matches on no-requirement adverts;
  - at least 80% correct on requirement adverts;
  - report the count of false values above the configured years, which are the ones that lower the score.

  **If it misses, stop and report. Do not tune against that set.**
- **AC3 Boundaries.** "3-5 years" stores 3. "15-25 years" stores 15. "25 years" stores null.
  "0-2 years" stores 0, and the note is written.
- **AC4 Bands.** Tests cover all four bands at weights 20 and 15. No test covers the Partly
  meets or Below band today.
- **AC5 Decisions, the main effect.** The cases in `decision_check.py` become tests. With an
  extracted note: confidence and decision equal the no-value result, and the score falls only
  above the configured years. With a typed number or a deleted note: the number counts for confidence. The score
  note says the number is unconfirmed. If Mike answers Q2 the other way, these tests follow
  his answer.
- **AC6 Digest.** LinkedIn and Adzuna payloads carry value and note, with network calls
  patched to raise. Reed payloads carry neither. `src/job_hunt_scheduler.py` has no diff. A
  pipeline-level test shows the stored score and the AI-queue flag use the value.
- **AC7 Select and batch.** All three sources fill value and note, and batch evaluate stores
  them. Reed extracts from full text, and from nothing when the detail fetch fails. Existing
  notes are kept, and selecting twice does not duplicate the note.
- **AC8 Storage and page.** `OPTIONAL_REVIEWED_JOB_FIELDS` has no diff. The job page shows the
  value and sentence, or "Not stated". A `<script>` in the sentence is escaped.
- **AC9 Re-score.** Uses the stored value, makes no new network call of its own, and leaves
  the reviewed-job file's modified time unchanged.
- **AC10 Backfill.** A dry run leaves every modified time unchanged and prints the count of
  never-queued jobs at or above the threshold. Apply makes a backup first, fills only null
  values, leaves Reed alone, and a second run changes nothing.
- **AC11 Tests.** Failing test ids are recorded on the base branch before the first change and
  compared afterwards with `comm`: 0 new failures. The digest and form tests
  (`test_full_digest_journey`, `test_evaluate_form_prefills_saved_job_and_round_trips`) must
  pass on the base, or the build stops and reports. Latest stated `main` baseline: 46 failed,
  3002 passed, 20 skipped (`PROJECT_LOG.md:9`). The real baseline is the one recorded on the base.
- **AC12 Merge.** `git merge-tree` against PR #5 and the three branches on top of it shows no
  conflict in `src/`. Any conflict is reported to Mike before the work is called done.
- **AC13 Review.** A fresh verifier re-runs the tests and checks each AC.

No live Gemini call. Reed is called live only under the consent in Q3. Tests use synthetic
data and fake clients.

## 14. Stop and ask Mike if

- Step 0 or AC2 misses its limit.
- The stored JSON fails to load after a change.
- The build needs to touch `.env`, a new reviewed-job key, or any write under `data/` outside
  the approved backfill.
- Phase A turns out to need a change to `src/job_hunt_scheduler.py`.

## 15. Questions for Mike

- **Q1. Scope, knowing section 1.** Recommended: Step 0, then Phase A if the check passes, and
  Phase B only if the check finds Reed adverts asking for more than the configured years, or you still want
  the sentence on Reed digest jobs. Other choices: Step 0 only, then decide; or do not build.
- **Q2. May an extracted number alone lift a job to Apply?** Recommended: no (section 5). If
  yes, the Apply jobs in section 1 appear, and a false number at or below the configured years can also cause them.
- **Q3. Consent for Step 0:** read saved jobs under `data/` (read-only) and make at most 10 live
  Reed detail calls.
- **Q4. Saved jobs:** backfill saved text for LinkedIn and Adzuna (recommended), or new jobs only.
- **Q5. PR #4:** merge it to `main` before the build (recommended, gives one clean base), or I
  build on its branch and it stays unmerged.

## 16. Review record

- **Independent review:** Judge-tier reviewer, 2026-11-06. 3 HIGH, 7 MED, 1 LOW. All three HIGH
  items changed this draft: the Apply effect (sections 1 and 5), the false rollback claim
  (section 8), and the production text shape (section 3). Its two main code claims were then
  confirmed by running them (`decision-check-1.txt`, and a class check showing the two errors
  are siblings).
- **Codex review: unavailable.** The call stopped at a usage limit, with a retry time of 23:58 on
  2026-11-06. Not retried. Under `~/.claude/rules/dispatch.md` section 6, one second opinion is enough.
- **Gemini pre-check: not run.** This session has no consent for a live Gemini call.
- **gstack: not installed.**

## 17. Step 0 result, 2026-11-07

A read-only check on the owner's own saved jobs was run, with a small number of live detail
calls, and it met the stop rule of section 12. Its figures and the per-job report are kept
locally and are not published; the working files are kept locally and are not in git. The
conclusion, without numbers: the saved jobs all come from one source, so Phase A's
digest change and backfill would cover none of them; the strict extractor found a value on
only a small share of the full adverts, mostly because most adverts do not state a
requirement in that form; the current extractor gave some wrong or false values on the saved
previews, while the strict prototype gave none; and no score or decision changed on the
saved jobs. The sample was small, so this is a pointer, not a measurement.

## 18. Build spec: paste and URL only

Mike chose this on 2026-11-07 ("Fix paste and URL only"), after section 17. PR #4 was merged to
`main` first (`d83a7b3`), as he had agreed, and this branch was brought up to date (`5f32d3d`).
Sections 5 to 8 and the digest, select, note, confidence, form, page and backfill parts of
section 13 are **not** built.

**Change.** Replace the body of `_extract_years` in `src/job_hunt_parsing.py` (`:511`) with the
strict rules in section 3. Keep its signature: it returns the lower bound as a float, or None.
Its only caller stays `:268`, which serves paste and URL. Nothing else in `src/` changes.

**Rules,** from section 3, each tested on a short window around the number:
experience cue next to the number; trap words; company boasts need a candidate cue;
desirable-only gives nothing; a lower bound above 20 gives nothing; several passing numbers
give the highest lower bound; ranges give their lower bound; `0` is a valid lower bound.

**Cases that must pass,** besides `tests/test_parsing.py`, which must stay unchanged:
- the development cases (working files kept locally, not in git);
- all 80 entries of `tests/fixtures/required_years_holdout.json`;
- the failures and false matches named in section 3, and the cases drawn from the
  section 17 check, which are written as invented sentences in the test file (contract
  length, company age, a range, a company boast, a screening question, a months-only gap).

**Acceptance criteria:**
- **B1.** `tests/test_required_years.py` covers all the cases above and passes, with
  `tests/test_parsing.py`.
- **B2.** `tests/fixtures/required_years_blind2.json` (at least 100 entries, half of them full
  adverts) is written by a fresh agent that sees neither `src/` nor the probe files. Its exact prompt is
  saved in `tests/fixtures/required_years_blind2_prompt.md`. The finished extractor is run once
  through `parse_job_from_text`, in two shapes: as written, and with all whitespace squashed.
  In each shape:
  - at most 5% false matches on the no-requirement entries;
  - at least 80% correct lower bound on the requirement entries;
  - the count of false values above the configured years is reported.

  **If it misses, stop and report. Do not tune against this set.**
- **B3.** The full suite has 0 new failing test ids against the baseline recorded at `5f32d3d`.
- **B4.** `git merge-tree` against PR SmartLHA/job-seeking-tool#5 and the three branches on top
  of it shows no conflict in `src/`.
- **B5.** Docs are updated per `docs/docs-update-checklist.md`.
- **B6.** A fresh verifier re-runs B1 to B4 and reads the diff.

## 19. Build result and decision (2026-11-08)

Commit `153196a` builds section 18: `_extract_years` in `src/job_hunt_parsing.py` now uses the strict
rules, with helpers `_years_value`, `_years_matches`, `_years_window_passes` and `_is_years_header`.
Its signature and its only caller (`parse_job_from_text`, paste and URL) are unchanged.
Tests are in `tests/test_required_years.py`.

**Results against the acceptance criteria of section 18**

| Point | Result |
|---|---|
| B1 | `pytest tests/test_required_years.py tests/test_parsing.py` gave 216 passed. |
| B2 | **MISSED in both shapes.** Run once, on `tests/fixtures/required_years_blind2.json` (100 entries: 43 with no requirement, 57 with a requirement). Limits: at most 5% false matches, at least 80% correct in each shape. |
| B3 | Full suite 2950 passed, 16 skipped, 0 failed. Baseline at `5f32d3d`: 2767 passed, 16 skipped, 0 failed. |
| B4 | `git merge-tree` against `claude/agitated-sinoussi-7cc5be` (PR #5), `claude/keen-jones-b93b9a`, `claude/cool-faraday-76ed62` and `claude/upbeat-mendeleev-6981ed` showed no conflicts. |
| B5 | Docs updated per `docs/docs-update-checklist.md` (this section and the files named there). |

**B2 numbers** (working files kept locally, not in git)

| Shape | False matches (limit 5%) | Correct lower bound (limit 80%) | Missed | False values above the configured years |
|---|---|---|---|---|
| As written | 5 of 43 (11.6%) | 27 of 57 (47.4%) | 30 | 3 |
| Whitespace squashed | 5 of 43 (11.6%) | 30 of 57 (52.6%) | 27 | 3 |

Wrong value: 0 in both shapes.

**Comparison on the same set** (working files kept locally, not in git)

| Extractor | False matches | Correct | Wrong value | False values above the configured years |
|---|---|---|---|---|
| Old `_extract_years` | 28/43 | 21/57 | 24 | 20 |
| Frozen prototype | 6/43 | 24/57 | 0 | 3 |
| New `_extract_years` | 5/43 | 27/57 | 0 | 3 |

**Why it misses.** Some requirements have no "experience" word, for example "6+ years of commercial
Java development", "minimum of 8 years delivering" and "7-10 years in security architecture". A miss
returns None, so the job's experience score stays neutral.

**Why it false-matches.** A named company or agency describes its own history without "we" or "our",
for example "Keldmoor Advisory has over 15 years of experience". A false value only hurts when it is
above the candidate's configured years (3 of the 43).

**Overfitting.** The development and holdout tuning overfitted. The blind set
`required_years_blind2.json` has now been seen, so any future rule change needs a new, third blind
set and must not be tuned against this one.

**Known limit.** `_years_matches` is quadratic on pathological input (about 3.6 s for 100,000
characters of repeated "5 years "). Real adverts are far smaller.

**Decision.** Mike, 2026-11-08: "Keep it", relayed by the parent session, in answer to "Keep the new
years extractor despite missing the targets?". It covers keeping commit `153196a` and writing its
limits into the docs. It gives no approval to push, open a PR or merge.

**What did not change.** Search-source jobs (Reed, LinkedIn, Adzuna) are unchanged and stay neutral
on experience. Nobody should assume they now have required years, or that B2 passed.
