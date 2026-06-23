<!--
Source: converted (lossless, via pandoc) from To-AI/Requirement_Design_v1.docx on 2026-06-22.
This Markdown file now holds the full content of that .docx; the .docx can be deleted.
Status of the doc itself: historical design reference. Source code is authoritative for
implemented behaviour. The "Implementation Status — 22 June 2026" block below supersedes
any conflicting implementation claims in the historical sections that follow.
Original .docx metadata — Author note: "Maintained as a design/reference document; source
code is authoritative for implemented behaviour." · Original date: 28 April 2026.
-->

# UK AI Job Application Copilot - Requirement Design Document

**Implementation Status — 22 June 2026**

This page supersedes conflicting implementation claims in the historical design sections that follow.

• Architecture: deterministic Python controls scoring, decisions, safety gates, persistence, and reporting. LLMs are not a decision-making runtime dependency.

• Scoring: seven weighted components — required skills 35, preferred skills 5, experience 20, location 10, salary 10, domain 10, work mode 10. Confidence is low/medium/high, not a 0–1 float.

• Workflow: source-quality gating, ATS readiness scoring, safe canonical URL parsing, structured skills, decision overrides, and SQLite jobs/board APIs are implemented.

• Document generation: decision-gated POST /tailor and POST /cover-letter endpoints are implemented. Dedicated browser workspaces and DOCX/PDF export remain future UI/output work.

• State/output: local raw\_inputs/, reviewed\_jobs/, analyses/, and outcomes/ are kept separately; reports are JSON/CSV. The product never auto-submits applications.

• Entry points: CLI is python3 -m src.job\_hunt\_main; product UI is src/job\_hunt\_ui.py. The viewer/ folder is a separate project-document viewer.

**Historical design detail**

## 1\. Executive Summary

This document defines a new design direction for a UK-focused AI job application product. It combines the strongest ideas from two reference repositories:

1.  `santifer/career-ops` - useful as a mature job-search operating-system pattern.
2.  `GodsScion/Auto_job_applier_linkedIn` - useful only for selected tactical ideas such as answer banks, filters, applied history, and failure logging.

The target product is a **trusted AI Job Application Copilot**, not a mass auto-apply bot. The product should help users evaluate jobs, tailor truthful application materials, prepare reusable answers, track outcomes, and avoid wasting time on poor-fit, stale, or suspicious roles.

The product must not auto-submit applications, store LinkedIn credentials, use stealth browser automation, bypass anti-bot controls, or encourage mass application behaviour.

## 2\. Product Direction

### 2.1 Product Goal

Build a trusted AI job application copilot for UK job seekers.

The product should help users:

  - Find and evaluate suitable jobs.
  - Score job fit against their CV/profile.
  - Detect low-value, stale, suspicious, or poor-fit job posts.
  - Generate truthful tailored CVs and cover letters.
  - Prepare application form answers.
  - Track applications and outcomes.
  - Improve job-search strategy based on actual results.

### 2.2 Positioning

**Trusted AI Job Application Copilot**

Not:

**LinkedIn Auto Apply Bot**

### 2.3 Product Promise

Apply to fewer jobs, with better fit, stronger evidence, safer documents, and better follow-up.

### 2.4 Hard Boundary

The system may prepare, suggest, score, draft, and track. The system must not automatically submit applications or perform hidden LinkedIn automation.

Allowed:

  - Analyse pasted job descriptions.
  - Analyse job URLs where permitted.
  - Extract job requirements.
  - Score CV/job fit.
  - Detect red flags.
  - Generate tailored CV drafts.
  - Generate cover letter drafts.
  - Suggest application form answers.
  - Store approved answer bank entries.
  - Track application status.
  - Produce reports.
  - Remind the user to follow up.

Not allowed:

  - Auto-submit applications.
  - Store LinkedIn passwords.
  - Bypass bot detection.
  - Use stealth browser automation.
  - Mass apply to jobs.
  - Invent CV claims.
  - Answer legal/right-to-work questions without user confirmation.

## 3\. Design Ideas Absorbed from the Two Repositories

### 3.1 From `career-ops`

Borrow these patterns:

  - Pattern | Reason
  - Single pipeline workflow | One action should evaluate job, create documents, and update tracker.
  - Job operating-system design | Treat job search as a managed pipeline, not a one-off CV rewrite.
  - Human-in-the-loop design | User remains the final decision-maker.
  - Dashboard and tracker | Applications need persistent status, not just generated files.
  - Data contract | Separate user-owned files from system-owned files to prevent unsafe agent edits.
  - PDF/DOCX output | Users need exportable application material.
  - Batch analysis | Useful later for analysing multiple jobs, but not for auto-application.
  - Job legitimacy check | Helps avoid ghost jobs, stale jobs, and low-value applications.
  - Story bank | Supports interview preparation after application.

### 3.2 From `Auto_job_applier_linkedIn`

Borrow only the safe tactical ideas:

  - Pattern | Reason
  - Approved answer bank | Users repeatedly answer the same application form questions.
  - Skip filters | Avoid unsuitable jobs early.
  - Applied history | Avoid duplicate applications.
  - Failed application log | Learn why application preparation failed.
  - Pause before sensitive answers | Right-to-work, sponsorship, salary, clearance, and relocation answers need confirmation.
  - Form question assistant | Helpful when implemented as suggestion/copy-ready assistant, not auto-submit.

Reject these patterns:

  - Rejected Pattern | Reason
  - LinkedIn auto-apply | High platform, account, and terms-of-service risk.
  - Stealth mode | Anti-bot bypass risk.
  - Undetected ChromeDriver | Not suitable for a trust-first product.
  - Mass apply positioning | Conflicts with high-fit application strategy.
  - Storing LinkedIn credentials | Security and user-trust risk.

## 4\. Target Users

### 4.1 Primary User Group

UK job seekers applying for:

  - Business Analyst.
  - Product Owner.
  - Project Manager.
  - Delivery Manager.
  - Data Analyst.
  - BI Analyst.
  - QA/Test Analyst.
  - IT Support / Service Management.
  - Change Analyst.
  - Junior or mid-level Software, Cloud, or DevOps roles.

### 4.2 User Pain Points

  - Too many jobs to evaluate.
  - Unsure whether a job is worth applying to.
  - Generic CV does not match each role.
  - Repeated application questions waste time.
  - Hard to track which CV version was sent.
  - Unclear why applications get no response.
  - Risk of accidentally inventing CV claims using AI.
  - Fake, stale, or low-value job posts waste effort.

## 5\. Target Product Architecture

    Job Intake
      -> Job Normaliser
      -> Job Legitimacy Analyzer
      -> CV Evidence Extractor
      -> Match Engine
      -> Decision Engine
      -> Application Pack Generator
      -> Truth Guard
      -> User Review
      -> Tracker Update
      -> Outcome Learning Loop

## 6\. Required Modules

### 6.1 Job Intake Module

Purpose: accept job information from safe sources.

Input methods:

  - Paste job description.
  - Paste job URL.
  - Upload job spec as PDF, DOCX, or TXT.
  - Manual job entry.
  - Future safe portal import.

Requirements:

  - User can paste JD text directly.
  - User can paste job URL.
  - System must store original source.
  - System must not scrape restricted platforms at scale.
  - If URL parsing fails, user can paste JD manually.
  - LinkedIn job URLs should be treated as reference links only unless the user manually provides job text.

Output schema:

    {
      "job_id": "string",
      "source_type": "manual_text | url | upload",
      "source_url": "string | null",
      "raw_text": "string",
      "created_at": "datetime"
    }

### 6.2 Job Normaliser Module

Purpose: convert raw job text into structured job data.

Output schema:

    {
      "job_id": "string",
      "title": "string",
      "company": "string",
      "location": "string",
      "work_mode": "remote | hybrid | onsite | unknown",
      "salary_min": "number | null",
      "salary_max": "number | null",
      "contract_type": "permanent | contract | temporary | unknown",
      "seniority": "junior | mid | senior | lead | unknown",
      "required_skills": ["string"],
      "nice_to_have_skills": ["string"],
      "responsibilities": ["string"],
      "domain": "string | unknown",
      "application_url": "string | null",
      "posting_date": "date | null",
      "confidence": "high | medium | low"
    }

Rules:

  - Do not infer salary if not present.
  - Do not infer visa/sponsorship policy unless explicitly stated.
  - Mark missing fields as unknown or null.
  - Preserve raw job text for audit.

### 6.3 Job Legitimacy Analyzer

Purpose: identify whether the job is worth user time.

Signals to check (local-only in MVP):

  - Vague or generic job description language.
  - Missing company name or unclear company identity.
  - Missing salary or unrealistic salary range.
  - Commission-only or unpaid work signals.
  - Asks for money from the applicant.
  - Asks for sensitive personal data too early in the process (e.g., bank details, NI number before offer stage).
  - Unclear or missing responsibilities.
  - Unclear or missing required skills.
  - Duplicate job text detected in local database.
  - Do not implement web-assisted company/posting verification in MVP. Web-assisted legitimacy checking is a future phase (Phase 7) requiring browsing capability, domain allowlist, user consent, rate limits, and citation handling.
  - Apply link available.
  - Application page active.
  - Role appears closed.
  - Known company or unknown company.
  - Agency duplicate risk.
  - Hiring signal available.
  - Unpaid work.
  - Commission-only work.
  - Unrealistic salary.
  - Vague company identity.
  - Suspicious contact method.
  - Sensitive data requested too early.

Output schema:

    {
      "job_id": "string",
      "legitimacy_rating": "high_confidence | proceed_with_caution | suspicious | unknown",
      "positive_signals": ["string"],
      "concern_signals": ["string"],
      "recommended_action": "continue | review_manually | skip",
      "explanation": "string"
    }

Rule: the system must not accuse the employer of fraud. Use cautious wording, such as:

  - This post has weak verification signals.
  - This role may require manual checking before applying.
  - This appears stale or incomplete.

### 6.4 CV Evidence Extractor

Purpose: extract evidence from the user’s CV/profile so the AI does not invent claims.

Inputs:

  - Original CV.
  - User profile.
  - Work history.
  - Skills.
  - Achievements.
  - Certifications.
  - Approved answer bank.

Output schema:

    {
      "candidate_id": "string",
      "skills": [
        {
          "name": "SQL",
          "evidence": "Used SQL for monthly reporting in Data Analyst role",
          "source": "cv",
          "confidence": "high"
        }
      ],
      "achievements": [
        {
          "claim": "Improved reporting accuracy by 30%",
          "source": "cv",
          "confidence": "high"
        }
      ],
      "domains": ["finance", "retail"],
      "tools": ["Jira", "Confluence", "Excel", "Power BI"],
      "years_experience": {
        "business_analysis": 4,
        "sql": 3
      }
    }

Rule: no generated CV claim can be exported unless it maps to evidence or is explicitly confirmed by the user.

### 6.5 Match Engine

Purpose: score job fit using explainable logic.

Score model (current implementation):

  - Component | Max Points
  - Required skills | 35
  - Experience match | 20
  - Preferred skills | 5
  - Experience match | 20
  - Location, salary, domain, and work mode | 40 (10 each)
  - Source quality | Decision gate: \<40 skips; 40–69 forces review
  - Evidence confidence penalty | 0 to -10  
    Note: positive\_total = 100 (skill 35 + experience 20 + domain 15 + responsibility 15 + location/salary/workmode 15). Penalties are then subtracted. final\_score = clamp(positive\_score - red\_flag\_penalty - evidence\_confidence\_penalty, 0, 100).

Output schema:

    {
      "job_id": "string",
      "overall_score": 82,
      "decision": "apply | review | skip",
      "confidence": "high | medium | low",
      "breakdown": {
        "skill_match": 35,
        "experience_match": 20,
        "domain_match": 15,
        "responsibility_match": 15,
        "location_salary_workmode_match": 15,
        "red_flag_penalty": 0,
        "evidence_confidence_penalty": 0,
        "positive_total": 100
      },
      "matched_evidence": ["string"],
      "missing_skills": ["string"],
      "weak_evidence": ["string"],
      "explanation": "string"
    }

Decision thresholds:

  - Decision | Score | Condition
  - Apply | \>=80 | No critical red flags.
  - Review | 65-79 | Potential fit but needs user review.
  - Note: Watchlist decision is deferred beyond MVP.
  - Skip | \<65 | Poor fit, hard blocker, or suspicious job.

Important rule: do not call this “interview probability”. Use “Job Fit Score”, “Application Readiness Score”, or “CV Match Score”.

Reason: the system does not know applicant pool, recruiter behaviour, internal candidate status, employer urgency, or market competition.

### 6.6 Decision Engine

Purpose: convert score and risk signals into user action.

Output schema:

    {
      "job_id": "string",
      "decision": "apply | review | skip",
      "reason": "string",
      "required_user_actions": ["string"],
      "blocking_issues": ["string"],
      "next_step": "generate_application_pack | request_user_input | skip_and_archive"
    }

Logic:

  - If `legitimacy_rating` is suspicious, decision cannot be Apply.
  - If Truth Guard has unsupported claims, decision cannot be Ready to Apply.
  - If right-to-work or sponsorship answer is unknown, require user input.
  - If score \>=80 and no blocking issues, recommend Apply.
  - If score is 65-79, recommend Review.
  - If score is \<65, recommend Skip.  
    Confidence does not change the decision. Confidence only creates warning flags, explanation quality notes, or export-review requirements. Example: score 82 + low confidence = decision Apply with required user-review warning.

### 6.7 Application Pack Generator

Purpose: generate user-reviewable application materials.

Outputs:

  - Tailored CV draft.
  - Cover letter draft.
  - Application form answer suggestions.
  - Optional recruiter message.
  - Interview story suggestions.
  - Evidence report.

CV generation requirements:

  - UK CV style.
  - No photo by default.
  - Concise professional summary.
  - Achievement-led bullets.
  - Keyword alignment to JD.
  - No invented claims.
  - Each changed bullet must show evidence source.
  - Export to DOCX and PDF.

Cover letter requirements:

  - UK tone.
  - Concise.
  - Role-specific.
  - Company-specific where evidence exists.
  - No fake enthusiasm or invented company knowledge.
  - Mark weak company research as low confidence.

Application form answer requirements:

  - Suggest only.
  - Never auto-submit.
  - Show source.
  - Show confidence.
  - Require user confirmation for sensitive answers.

### 6.8 Approved Answer Bank

Purpose: store reusable answers to repeated application questions.

Example schema:

    {
      "answer_id": "string",
      "question_type": "right_to_work | sponsorship | notice_period | salary_expectation | relocation | clearance | work_mode | custom",
      "canonical_question": "Do you require visa sponsorship?",
      "approved_answer": "No",
      "source": "user_confirmed",
      "confidence": "confirmed",
      "last_confirmed_at": "datetime"
    }

Sensitive answer types:

  - Right to work.
  - Visa sponsorship.
  - Security clearance.
  - Criminal record.
  - Disability or health.
  - Salary expectation.
  - Relocation.
  - Notice period.

Rules:

  - Sensitive answers must be user-confirmed.
  - AI may suggest wording but cannot invent the fact.
  - If answer is unknown, ask user or mark as missing.
  - Do not export final pack until required sensitive answers are resolved.

### 6.9 Truth Guard

Purpose: prevent AI-generated false claims.

Claim statuses:

  - Status | Meaning
  - supported | Directly backed by CV/profile evidence.
  - partially\_supported | Based on real evidence but wording may be stronger than source.
  - inferred | Reasonable inference, but user confirmation required.
  - unsupported | No evidence found. Must not be exported.
  - user\_confirmed | User explicitly approved the claim.

Output schema:

    {
      "document_id": "string",
      "claims": [
        {
          "text": "Led requirements workshops with stakeholders",
          "status": "supported",
          "source": "CV: Business Analyst role, 2022-2024",
          "risk": "low"
        },
        {
          "text": "Expert in Salesforce",
          "status": "unsupported",
          "source": null,
          "risk": "high"
        }
      ],
      "export_allowed": false,
      "blocking_claims": ["Expert in Salesforce"]
    }

Export policy:

  - Claim Status | Export Behaviour
  - supported | Allowed.
  - user\_confirmed | Allowed.
  - partially\_supported | Warning.
  - inferred | Requires confirmation.
  - unsupported | Block export.

### 6.10 Tracker

Purpose: single source of truth for job applications.

Required statuses:

  - Discovered.
  - Analysed.
  - Skipped.
  - Skipped.
  - Review needed.
  - Application pack generated.
  - Applied.
  - Follow-up due.
  - Recruiter screen.
  - Interview.
  - Rejected.
  - Offer.
  - Withdrawn.

Tracker fields:

    {
      "application_id": "string",
      "job_id": "string",
      "company": "string",
      "title": "string",
      "score": 82,
      "decision": "apply",
      "status": "application_pack_generated",
      "cv_version_id": "string",
      "cover_letter_id": "string",
      "source_url": "string",
      "created_at": "datetime",
      "applied_at": "datetime | null",
      "follow_up_date": "date | null",
      "outcome": "string | null",
      "notes": "string"
    }

Rules:

  - Tracker is the source of truth.
  - Do not rely on Markdown tables as the main database.
  - Use SQLite for application state.
  - Current implementation stores tracker/index state locally and produces JSON/CSV reports. Tailored CV and cover-letter outputs are markdown/text; DOCX/PDF export is future work.
  - Every generated document must link back to `job_id` and `cv_version_id`.

### 6.11 Outcome Learning Loop

Purpose: improve recommendations based on real outcomes.

Inputs:

  - Application score.
  - CV version.
  - Application status.
  - Recruiter response.
  - Interview received.
  - Rejection reason if known.
  - Time to response.

Insights to produce:

  - High-score but no-response pattern.
  - Low-score but response pattern.
  - Strongest job titles.
  - Weakest missing skills.
  - Best CV version.
  - Best company type.
  - Salary range response pattern.

Example output:

    You applied to 12 jobs above 80 score.
    Only 1 produced recruiter response.
    Common issue: weak evidence for stakeholder management and SQL.
    Recommendation: strengthen CV evidence before applying to more BA/Data hybrid roles.

## 7\. Data Architecture

### 7.1 SQLite as System of Record

Required tables:

    users
    candidate_profiles
    cv_versions
    cv_evidence
    jobs
    job_normalised
    job_legitimacy
    job_scores
    applications
    application_events
    generated_documents
    document_claims
    answer_bank
    form_question_suggestions
    interview_stories
    outcome_metrics
    audit_log

### 7.2 File Outputs

    /output/cv/
      tailored_cv_{company}_{role}_{date}.docx
      tailored_cv_{company}_{role}_{date}.pdf
    
    /output/cover_letters/
      cover_letter_{company}_{role}_{date}.docx
      cover_letter_{company}_{role}_{date}.pdf
    
    /reports/
      job_analysis_{job_id}.md
      weekly_strategy_report.md

### 7.3 User Layer vs System Layer

User layer:

  - `data/cv/`
  - `data/profile/`
  - `data/jobs/`
  - `output/`
  - `reports/`
  - `user_approved_answers/`
  - `user_notes/`

System layer:

  - `src/`
  - `prompts/`
  - `templates/`
  - `tests/`
  - `docs/system/`
  - `config/defaults/`

OpenClaw rule:

    Agents may freely edit system_layer only when assigned to development tasks.
    Agents must not directly overwrite user_layer files.
    User_layer writes must go through approved application APIs.

## 8\. UI Flow Requirements

### 8.1 Main Dashboard

Show:

  - Jobs analysed today.
  - Applications ready for review.
  - Follow-ups due.
  - High-fit jobs.
  - Jobs skipped due to red flags.
  - Response rate.
  - Best performing CV version.

### 8.2 Analyse Job Flow

    User clicks: Analyse New Job
    -> Paste JD / URL / upload file
    -> System extracts structured job data
    -> System checks legitimacy
    -> System scores CV match
    -> System returns Apply / Review / Skip
    -> User can generate application pack

### 8.3 Job Result Page

Sections:

1.  Overall decision.
2.  Fit score.
3.  Score breakdown.
4.  Legitimacy warning.
5.  Matched evidence.
6.  Missing skills.
7.  CV changes recommended.
8.  Application question suggestions.
9.  Generate application pack button.
10. Add to tracker button.

### 8.4 CV Tailoring Review Page

Show side-by-side:

  - Original CV Bullet | Suggested Bullet | JD Keyword Covered | Evidence Source | Truth Guard Status | Action
  - Existing bullet | Improved bullet | Keyword | CV/profile source | supported / needs confirmation | Accept / Edit / Reject

### 8.5 Application Pack Page

Show:

  - Tailored CV.
  - Cover letter.
  - Suggested form answers.
  - Risk warnings.
  - Manual application link.
  - Tracker update.

Allowed CTAs:

  - Open Job Page.
  - Mark as Applied.
  - Schedule Follow-up.

Forbidden CTAs:

  - Auto Apply.
  - Submit Automatically.
  - Login to LinkedIn.

## 9\. Reference Agent Design (not the current runtime architecture)

The current application is deterministic Python first. Any future LLM use is limited to fallback parsing or generated drafting and must not alter scores or decisions.

  - Agent | Role | Model Guidance | Output
  - Orchestrator | Controls workflow and stage handoff. | Strong reasoning model. | Workflow state.
  - Job Intake Agent | Parse raw job input. | Cheap/local model allowed. | Raw job record.
  - Job Normaliser Agent | Convert job text to structured JSON. | Local or mid model. | Normalised job JSON.
  - Legitimacy Agent | Check stale/low-quality/suspicious job signals using local-only checks. Web-assisted verification is Phase 7. | Local model. | Legitimacy report.
  - CV Evidence Agent | Extract evidence from CV/profile. | Stronger model. | Evidence map.
  - Match Engine Agent | Calculate score and explain fit. | Deterministic Python only. Optional LLM explanation may be added later but must not change numeric score or decision. | Score JSON.
  - Decision Agent | Apply thresholds and safety rules. | Code-first. | Apply/Review/Skip.
  - Document Agent | Generate CV and cover letter drafts. | Strong writing model. | Draft documents.
  - Truth Guard Agent | Validate all generated claims against evidence. | Strong reviewer model. | Claim audit.
  - Application Answer Agent | Suggest form answers from approved answer bank. | Mid model. | Answer suggestions.
  - Tracker Agent | Update SQLite tracker. | Code-first. | Application status updates.
  - QA Agent | Review outputs and enforce rules. | Reviewer model. | Pass/fail report.

## 10\. Development Sequence

### Phase 1 - Safe MVP

Goal: manual JD -\> score -\> decision -\> tracker.

Build:

  - SQLite schema.
  - Job intake by paste/upload.
  - Job normaliser.
  - CV evidence extractor.
  - Match engine.
  - Decision engine.
  - Basic tracker.

Exclude:

  - LinkedIn automation.
  - Browser automation.
  - Auto-submit.

### Phase 2 - Application Pack

Goal: generate truthful tailored CV and cover letter.

Build:

  - CV tailoring engine.
  - Cover letter generator.
  - DOCX/PDF export.
  - Truth Guard.
  - Side-by-side review UI.

### Phase 3 - Answer Bank and Form Assistant

Goal: help with repeated application form questions.

Build:

  - Approved answer bank.
  - Sensitive answer rules.
  - Form question suggestion engine.
  - Copy-ready answers.

Hard rule: no auto-submit.

### Phase 4 - Job Legitimacy and Skip Filters

Goal: avoid wasted applications.

Build:

  - Job legitimacy analyzer.
  - Skip rules.
  - Stale job detection.
  - Red flag warnings.
  - Agency duplicate detection.

### Phase 5 - Outcome Learning

Goal: improve job-search strategy over time.

Build:

  - Outcome tracking.
  - Response rate dashboard.
  - CV version performance.
  - Weekly strategy report.

### Phase 6 - Optional Safe Integrations (and Phase 7 - Web-Assisted Legitimacy)

Goal: add integrations and advanced features without violating platform rules.  
Phase 6: Official API integrations where available, browser-open helper, manual copy/paste assistant, email/calendar reminders.  
Phase 7 (future): Web-assisted company/posting legitimacy verification with domain allowlist, user consent, rate limits, and citations. Requires browsing capability and is not part of MVP scope.

Build:

  - Official API integrations where available.
  - Browser-open helper.
  - Manual copy/paste assistant.
  - Email/calendar reminders.

Exclude:

  - Stealth automation.
  - Credential storage.
  - LinkedIn Easy Apply bot.

## 11\. OpenClaw Implementation Instruction

Copy this prompt into OpenClaw:

    OpenClaw Implementation Instruction
    
    You are implementing the UK AI Job Application Copilot (Job Seeking Tool).
    
    Design document: To-AI/Requirement_Design_v1.docx v2 (28 April 2026)
    
    CRITICAL RULES (non-negotiable):
    1. Scoring must be 100-point deterministic scoring.
       - skill_match = 35
       - experience_match = 20
       - domain_match = 15
       - responsibility_match = 15
       - location_salary_workmode_match = 15
       - positive_total = 100
       - red_flag_penalty = 0 to -20
       - evidence_confidence_penalty = 0 to -10
       - final_score = clamp(positive_score - penalties, 0, 100)
    2. Decision engine: apply/review/skip only. No watchlist in MVP.
       - score >= 80 = apply
       - 65 <= score < 80 = review
       - score < 65 = skip
    3. Confidence does NOT change decision. Confidence creates warning flags only.
    4. Match scoring is deterministic Python. Optional LLM explanation only — must not change numeric score.
    5. LinkedIn URLs: reference-only. No scraping, no login, no credential storage, no Easy Apply.
    6. URL ingestion: current 7-domain allowlist only. Unsupported URLs = reference + manual JD fallback.
    7. Job Legitimacy Analyzer: local-only checks in MVP. No web-assisted verification until Phase 7.
    
    Reference repos (design inspiration only):
    - santifer/career-ops: job operating system, human-in-the-loop, tracker, data contract
    - GodsScion/Auto_job_applier_linkedIn: answer bank, skip filters, applied history (reject auto-apply patterns)
    
    Product: Trusted AI Job Application Copilot for UK job seekers. NOT an auto-apply bot.
    
    MVP scope:
    1. Job intake by paste/upload/URL
    2. Job normaliser
    3. CV evidence extractor
    4. Match engine (100-point deterministic)
    5. Decision engine (apply/review/skip)
    6. Job legitimacy analyzer (local-only)
    7. Truth Guard
    8. Application pack generator (CV tailoring + cover letter + answer suggestions)
    9. Approved answer bank
    10. SQLite tracker
    11. Outcome learning
    
    NOT in scope:
    - Auto-submit applications
    - LinkedIn automation
    - Stealth browser mode
    - Mass apply logic
    - Web-assisted company verification (Phase 7)
    
    Scoring (existing src/job_hunt_scoring.py is source of truth — may need penalty clauses added).
    Decision (existing src/job_hunt_decision.py is source of truth — update if needed).
    Confidence is independent of score.
    
    Before coding any scoring/decision change: update design doc first.
    Before coding any new module: produce design doc update + diff plan.

## 12\. Risk Register

  - Risk | Severity | Control
  - LinkedIn automation violates platform rules | High | No LinkedIn auto-submit, no stealth, no credential storage.
  - AI invents CV claims | High | Truth Guard blocks unsupported claims.
  - User trusts score too much | Medium | Show confidence and evidence; do not show “interview probability”.
  - Bad job parsing | Medium | Preserve raw text and show extracted fields for review.
  - Sensitive form answers wrong | High | Require user-confirmed answer bank.
  - Tracker becomes inconsistent | Medium | SQLite as source of truth with audit log.
  - Agents overwrite user files | High | Data contract and approved write APIs.
  - Mass-apply product drift | High | Product rule: decision support only.
  - Scraping/job-board terms risk | High | Manual paste/upload first; official APIs only later.
  - Weak local model generates poor CV | Medium | Strong model for final writing and reviewer model for Truth Guard.

## 13\. Test Requirements

### 13.1 Scoring Tests

  - High-fit job with strong skill evidence should score \>=80.
  - Medium-fit job should score 65-79.
  - Low-fit job should score \<50.
  - Suspicious job should not produce Apply even with strong skill match.
  - Missing evidence should reduce confidence.

### 13.2 Truth Guard Tests

  - Supported claims are allowed.
  - Unsupported claims block export.
  - Inferred claims require confirmation.
  - Partially supported claims trigger warnings.
  - User-confirmed claims are allowed and stored with timestamp.

### 13.3 Answer Bank Tests

  - Confirmed right-to-work answer can be reused.
  - Unknown sponsorship answer must require user input.
  - Salary expectation must not be invented.
  - Sensitive answers must require confirmation before export.

### 13.4 Tracker Tests

  - New job creates tracker entry.
  - Duplicate job is detected.
  - Generated CV links to job and CV version.
  - Status transitions are logged.
  - Outcome updates affect learning report.

### 13.5 Data Contract Tests

  - Agent cannot directly overwrite user-layer files.
  - User-layer writes must go through approved APIs.
  - System-layer files can be edited only during development tasks.
  - Audit log records document generation and tracker updates.

## 14\. Final Product Shape

The combined design should become:

    career-ops-style job operating system
    +
    Auto_job_applier-style answer bank and application history
    -
    LinkedIn bot automation
    -
    stealth/bypass logic
    -
    mass apply behaviour
    +
    UK-specific scoring
    +
    Truth Guard
    +
    manual submit boundary
    +
    SQLite tracker
    +
    outcome learning

The key missing piece in the current product direction is not more agents. It is more trust control.

Specifically:

  - Evidence-linked CV tailoring.
  - Approved answer bank.
  - Job legitimacy check.
  - Manual submit boundary.
  - Outcome learning loop.

## 15\. Reference Notes

Reference repositories reviewed:

  - `santifer/career-ops`: mature job-search operating-system pattern with evaluation, document generation, tracking, and data contract concepts.
  - `GodsScion/Auto_job_applier_linkedIn`: useful tactical concepts such as answer bank, filtering, applied history, and failure logging, but high-risk as a direct product model because of LinkedIn automation and mass application behaviour.

Existing project basis:

  - The current AI Job Hunting Agent design already includes Job Fetcher, Job Analyzer, Decision Engine, CV Optimizer, Cover Letter Generator, and Orchestrator. This document upgrades that design with trust control, evidence mapping, answer bank, tracker, job legitimacy, and outcome learning.
