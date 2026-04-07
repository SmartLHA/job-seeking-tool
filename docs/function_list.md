# Function List

## Planned Core Modules and Responsibilities

### profile.py
- load_candidate_profile()
- save_candidate_profile(profile)
- validate_candidate_profile(profile)
- load_cv_master()
- save_cv_master(cv_text)

### ingestion.py
- ingest_job_from_text(raw_text)
- ingest_job_from_json(job_data)
- ingest_job_from_url(url)
- normalize_raw_job(raw_job)
- deduplicate_job(job, existing_jobs)

### parsing.py
- parse_job(raw_job)
- extract_required_skills(description)
- extract_preferred_skills(description)
- extract_salary_range(description)
- extract_work_mode(description)
- extract_experience_requirement(description)
- extract_domain(description)
- validate_job_schema(job)

### eligibility.py
- check_hard_blockers(profile, job)
- is_salary_acceptable(profile, job)
- is_location_acceptable(profile, job)
- is_work_authorization_compatible(profile, job)
- is_seniority_reasonable(profile, job)

### scoring.py
- calculate_skill_score(profile, job)
- calculate_experience_score(profile, job)
- calculate_domain_score(profile, job)
- calculate_location_score(profile, job)
- calculate_salary_score(profile, job)
- calculate_match_score(profile, job)
- generate_score_breakdown(profile, job)
- analyze_job(profile, job)

### decision.py
- decide_application(analysis)
- apply_decision_rules(score, blockers, risks)
- assign_confidence_level(analysis)
- requires_manual_review(analysis)

### tailoring.py
- select_relevant_cv_evidence(profile, cv_text, job)
- optimize_cv(cv_text, profile, job)
- validate_cv_truthfulness(original_cv, optimized_cv, profile)
- save_tailored_cv(job_id, cv_text)

### cover_letter.py
- build_cover_letter_highlights(profile, analysis)
- generate_cover_letter(profile, job, evidence_points)
- validate_cover_letter_truthfulness(letter, profile, job)
- save_cover_letter(job_id, text)

### reporting.py
- build_daily_report(results)
- summarize_job_pipeline(results)
- export_report_markdown(report)
- export_report_json(report)
- list_top_jobs(results)

### outcomes.py
- record_application(job_id, applied_at, cv_version, letter_version)
- record_outcome(job_id, status, notes)
- update_application_status(job_id, status)
- get_interview_conversion_metrics()
- get_score_to_outcome_analysis()

### storage.py
- load_jobs()
- save_job(job)
- load_applications()
- save_analysis(analysis)
- save_generated_file(metadata)
- load_outcomes()

### config.py
- load_config()
- get_scoring_weights()
- get_decision_thresholds()
- get_blocker_rules()

### orchestrator.py
- run_daily_pipeline()
- process_single_job(raw_job)
- retry_failed_step(step_name, payload)
- skip_duplicate_jobs()
- schedule_pipeline_run()
