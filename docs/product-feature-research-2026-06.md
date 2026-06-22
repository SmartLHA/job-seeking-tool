# Product Feature Research & Recommendations — June 2026

**Author:** Claude (acting PO) · **For:** Mic
**Method:** market scan of 2025/26 AI job-search tools (Teal, Huntr, Jobscan,
Simplify, Sonara, Apply IQ, AIApply, Adzuna) + mapping to this product's existing
architecture and strengths.

---

## 1. Market context — the strategic signal

The AI job-search market has **split into two camps**, and one is clearly losing:

- **Spray-and-pray auto-apply (declining / risky).** Wonsulting, an early
  auto-apply pioneer, **shut down its bulk-send feature in August 2025** after
  clients averaged ~1 interview per 50 applications (~2% hit rate). LinkedIn's
  User Agreement forbids automated activity and **stepped up detection in 2026** —
  bulk-appliers get flagged/shadowbanned. Quality beats volume. [scale.jobs], [jobapplyai]
- **Targeted, quality, human-in-the-loop (winning).** The smartest 2025/26 tools
  (Sonara, Apply IQ, Jobscan Auto Apply) **score each posting against skills,
  salary and location before applying, never auto-submit, and don't blindly
  rewrite your CV.** [scale.jobs], [jobscan]

**Where this product sits:** it is *already* built on the winning model —
transparent, deterministic, weighted scoring per job; local-first; no spray; a
human reviews every evaluation. That's a genuine differentiator. **The
recommendations below double down on "quality + targeting", not auto-apply.**

### Demand signals worth knowing
- Recruiters **commonly use ATS filters and keyword search**, so keyword-mismatched
  CVs get ranked lower or missed; a per-job *match rate* is among the most-cited
  résumé-optimisation features (Jobscan's core). [jobscan-keywords]
  *(Caution: the viral "~75% of résumés are auto-rejected by ATS" figure is
  **contested** — no published methodology, traced to a defunct vendor — so it is
  **not** used here. [davron], [coversentry])*
- **29.3% of job seekers used AI to write/customise a CV or cover letter in 2025**
  (up from 17.3% in 2024) — fast-growing behaviour this product already supports. [resumegenius]
- Candidates who **combined CV optimisation with active follow-up/networking got
  interviews 3.2× more often** than optimisation alone. [stemgenic / jobscan]

---

## 2. Recommended features (ranked)

### ⭐ F1 — Per-job ATS **Match Rate** + keyword-gap (against the actual job description)
**Problem/evidence:** recruiters commonly filter/search by ATS keywords, so
keyword-mismatched CVs lose visibility (the "75% auto-rejected" stat is contested
and avoided — see Demand signals). This product's **current `ats_scorer`
only checks CV *format/sections*, not the match against a specific job.** That's
the biggest gap vs. the market leader (Jobscan).
**Build:** for a selected job, compute a 0–100 **match rate** comparing the
(tailored) CV text to the job's required/preferred skills + JD keywords, and show
a **missing-keywords list** ("present / missing / weak"). Surface it on the job
page next to the existing match score.
**Fit:** the data already exists — JD skills (`required_skills`/`preferred_skills`),
the CV text, and a deterministic scoring engine. It's an extension, not a new
subsystem.
**Risk / missing piece:** this *invites keyword-stuffing*, which modern ATS now
flag (repeating a phrase >3–4×, white-text, "keyword bank" sections). The feature
must **recommend natural integration and warn against stuffing**, or it actively
hurts users. [theinterviewguys]
**Effort:** M.

### ⭐ F2 — Tailored **Interview Prep pack** (per job)
**Problem/evidence:** interview prep is a top premium feature across the market
(AIApply, Jobscan), and it's the natural next step *after* "Apply" — a stage this
product currently drops the user at.
**Build:** from the JD + the existing fit/risk/gap analysis, generate a prep sheet:
likely **behavioural + technical + competency questions**, the **gap/risk
questions to rehearse** (drawn from the already-computed `risk_flags` /
`missing_required_skills`), and **STAR answer scaffolds grounded in the user's own
CV/achievements**.
**Fit:** the AI analysis already returns `{fit, risk, action}` and the tailoring
layer already enforces **truth-validation** (no invented claims) — reuse that to
keep answers grounded.
**Risk:** generic/hallucinated Q&A. Mitigation: ground every answer in real CV
facts via the existing tailoring truth-check; mark anything unsupported.
**Effort:** M.

### ⭐ F3 — **Follow-up reminders & nudges** (activate the tracker)
**Problem/evidence:** Teal/Huntr's retention engine is follow-up reminders, and
optimisation **+ active follow-up → 3.2× more interviews.** This product *tracks*
outcomes on a board but never *nudges*.
**Build:** time-based nudges off the outcome timestamps — "Applied 8 days ago, no
reply → send a follow-up?" (with a generated, factual follow-up note),
"Interview tomorrow → open your prep pack (F2)", "Job saved 14 days ago, never
applied → still interested?".
**Fit:** outcomes already carry `status` + `updated_at`; the **Daily Digest
scheduler (backlog D5)** is the delivery mechanism — this rides on work already
designed.
**Risk:** nudge fatigue. Keep cadence configurable and gentle; default off-by-one
reminders only.
**Effort:** S–M (leans on existing outcomes + the planned scheduler).

### F4 — **Application Package export** (control-first, explicitly NOT auto-apply)
**Problem/evidence:** the winning pattern is "draft everything, human submits"
(Jobscan Auto Apply, Simplify autofill). Auto-submit is a trap (ToS bans, ~2% hit
rate). The friction users actually feel is *assembling* each application.
**Build:** for an "Apply" job, one click bundles the **tailored CV + cover letter
(both already exist) + a pre-filled common-questions sheet** (right-to-work,
salary expectation, notice period, "why this role" — from profile + JD) + the F1
match summary, exported as a ready-to-submit folder/zip.
**Fit:** local-first export suits the product; tailor + cover letter already done.
**Risk:** scope creep toward a browser bot — **stay an export, never an
auto-submitter.** Keep the human in the loop (the product's whole ethos).
**Effort:** M.

### F5 — **Multi-source + salary/market benchmarking** (Adzuna)
**Problem/evidence:** Sonara/Apply IQ score salary & location before recommending;
salary transparency is a 2025/26 expectation. Reed alone narrows the funnel; for a
**UK** IT BA/PM, Adzuna adds breadth *and* salary data. [adzuna]
**Build:** wire the already-backlogged **Adzuna source (P5-1)** — the registry
pattern makes it a one-file adapter — and use Adzuna's salary endpoints to show a
**market salary benchmark** for the role/location vs. the user's floor, feeding the
deterministic salary score with real data instead of a single number.
**Fit:** `adzuna_client.py` exists; the post-refactor source registry was *built*
for exactly this ("add a source = one file"). Salary data deepens existing scoring.
**Risk:** API key/quota; UK-centric salary coverage. Effort: M.

---

## 3. What NOT to build (and why)
- **Auto-submit / LinkedIn auto-apply bots.** Against LinkedIn ToS (account bans),
  ~2% interview rate, and it contradicts the product's transparent, human-reviewed
  ethos. The market is *moving away* from this. [jobapplyai], [scale.jobs]
- **A "keyword bank" / stuffing helper.** Modern ATS flag it; it would hurt users.

## 4. Suggested roadmap order
1. **F1 (ATS match rate)** — biggest market gap, highest perceived value, reuses
   existing data.
2. **F3 (follow-up nudges)** — cheap, high-retention, rides the planned scheduler.
3. **F2 (interview prep)** — natural post-apply step, strong differentiator.
4. **F5 (Adzuna + salary)** — already scoped (P5-1); broadens the funnel.
5. **F4 (application package)** — convenience capstone once F1/F2 exist.

> A through-line: every recommendation strengthens **"help me apply to the *right*
> jobs *well*"**, which is where the market — and this product's architecture —
> are both heading. None of them push toward volume/automation, which is the part
> of the market that's collapsing.

---

## Sources
- [scale.jobs — AI job search tools / auto-apply 2026](https://scale.jobs/blog/best-ai-job-search-tools-land-dream-job-2026) and [auto-applier comparison](https://scale.jobs/blog/auto-job-applier-tools-compared-which-actually-works)
- [jobscan-keywords] [Jobscan — top resume keywords / recruiters use ATS filters & search](https://www.jobscan.co/blog/top-resume-keywords-boost-resume/)
- [jobscan] [Jobscan — Best AI job search tools / keyword-gap & ATS compatibility](https://www.jobscan.co/blog/ai-job-search-tools/)
- [The Interview Guys — ATS resume optimization (stuffing red flags)](https://blog.theinterviewguys.com/ats-resume-optimization/)
- [davron] [DAVRON — the "75% ATS rejection" stat lacks empirical support](https://www.davron.net/ats-systems-explained-75-percent-resumes-rejected/)
- [coversentry] [CoverSentry — the viral 75% ATS-rejection figure is unsubstantiated](https://www.coversentry.com/ats-statistics)
- [Resume Genius — AI job search tools 2025 (29.3% AI CV stat)](https://resumegenius.com/blog/job-hunting/ai-job-search)
- [STEMGenic — AI job search optimization 2025 (optimisation + networking 3.2×)](https://stemgenicglobal.com/ai-job-search-optimization-2025/)
- [JobApplyAI — Is auto-applying to LinkedIn against ToS?](https://jobapplyai.in/blog/is-auto-applying-linkedin-jobs-against-tos/)
- [Adzuna UK — AI job search tools](https://www.adzuna.co.uk/blog/best-ai-job-search-tools-to-streamline-your-job-hunt/)
