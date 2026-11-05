"""Offline acceptance coverage for saved-search salary filtering and attempts."""
import json
from unittest.mock import Mock

import pytest
import requests

import src.job_hunt_scheduler as scheduler
from src.job_sources import source_registry as registry
from src.job_sources.reed_source import normalize_reed_search_params, reed_filter_notes
from src.job_sources.adzuna_source import normalize_adzuna_search_params
from src.job_sources.linkedin_source import normalize_search_params as normalize_linkedin
from src.job_sources.reed_client import fetch_reed_jobs
from test_digest_pipeline import _setup, _search, _profile, _result
from src.job_hunt_index import is_already_indexed, upsert_job


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    before = dict(registry._REGISTRY)
    skills = Mock(return_value=(["python", "sql"], ["excel"], None))
    monkeypatch.setattr(scheduler, "extract_skills_from_text", skills)
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("No network")))
    yield skills
    registry._REGISTRY.clear()
    registry._REGISTRY.update(before)


def install(results, source="reed", normalize=normalize_reed_search_params):
    calls = []
    def fetch(params):
        calls.append(dict(params))
        return list(results)[:int(params.get("resultsToTake", params.get("results_to_take", 25)))]
    registry.register(registry.JobSource(source, source, lambda: True, normalize, fetch,
                      lambda *a: {}, lambda *a: "", lambda *a: ""))
    return calls


def run(tmp_path, results, params=None, profile=None, source="reed", normalize=normalize_reed_search_params):
    config, db = _setup(tmp_path)
    calls = install(results, source, normalize)
    result = scheduler.run_digest_pipeline(config=config, db_path=db, profile=profile or _profile(),
                    saved_searches=[_search(source, {"minimumSalary": "65000"} if params is None else params)])
    return result, calls, db


def count_sum(result, save_failures=0):
    assert result.jobs_fetched == (result.jobs_new + result.jobs_already_seen + result.jobs_skipped
                                 + result.jobs_below_floor + result.jobs_held_over + save_failures)


def test_ac1_drop_before_extraction_and_log(tmp_path, offline):
    r, _, db = run(tmp_path, [_result(salary_min_gbp="38,000", salary_max_gbp="45000.0")])
    assert r.jobs_below_floor == 1 and not is_already_indexed(db, "reed", "100")
    offline.assert_not_called()
    lines = [json.loads(line) for p in (tmp_path / "logs").glob("*.jsonl") for line in p.read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["reason"] == "below_salary_floor"
    count_sum(r)


@pytest.mark.parametrize("low,high,kept", [(60000,70000,True),(65000,None,True),(None,70000,True),
                                            (50000,None,False),(12000,None,False)])
def test_ac2_ranges(tmp_path, low, high, kept):
    r, _, _ = run(tmp_path, [_result(salary_min_gbp=low, salary_max_gbp=high)])
    assert (r.jobs_new, r.jobs_below_floor) == (int(kept), int(not kept))
    count_sum(r)


@pytest.mark.parametrize("low,high,floor", [(None,None,65000),("abc",None,65000),(0,0,65000),
                                            (500,700,65000),(500,700,8000)])
def test_ac3_unknown(tmp_path, low, high, floor):
    r, _, _ = run(tmp_path, [_result(salary_min_gbp=low, salary_max_gbp=high)], {"minimumSalary":str(floor)})
    assert (r.jobs_new, r.jobs_salary_unknown, r.jobs_below_floor) == (1,1,0)
    count_sum(r)


@pytest.mark.parametrize("params", [{"minimumSalary":""},{"minimumSalary":"abc"},{"minimumSalary":"0"},{}])
def test_ac4_disabled_floor(tmp_path, params):
    r, calls, _ = run(tmp_path, [_result()], params)
    assert r.jobs_new == 1 and r.jobs_below_floor == r.jobs_salary_unknown == 0
    assert calls[0]["resultsToTake"] == "10"


@pytest.mark.parametrize("maximum,saved,expected", [(50,None,50),(17,None,17),(50,"7",7)])
def test_ac5_fetch(tmp_path, maximum, saved, expected):
    params = {"minimumSalary":"65000"}
    if saved is not None:
        params["resultsToTake"] = saved
    _, calls, _ = run(tmp_path, [], params, _profile(digest_max_per_source=maximum))
    assert int(calls[0]["resultsToTake"]) == expected


def test_ac5_no_api_floor(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"results": []}
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    fetch_reed_jobs("analyst", "London", 50, save_raw=False)
    assert "minimumSalary" not in get.call_args.kwargs["params"]


def test_ac6_seen_before_floor(tmp_path, offline):
    config, db = _setup(tmp_path)
    upsert_job(db, {"job_id":"reed-100", "source":"reed", "source_job_id":"100"})
    install([_result()])
    r = scheduler.run_digest_pipeline(config=config, db_path=db, profile=_profile(), saved_searches=[_search("reed",{"minimumSalary":"65000"})])
    assert (r.jobs_already_seen,r.jobs_below_floor) == (1,0)
    offline.assert_not_called()


def test_ac7_real_normalizers(tmp_path):
    r, calls, _ = run(tmp_path / "adzuna", [_result()], source="adzuna", normalize=normalize_adzuna_search_params)
    assert r.jobs_below_floor == 1 and calls[0]["resultsToTake"] == "50"
    r, calls, _ = run(tmp_path / "linkedin", [_result()], source="linkedin", normalize=normalize_linkedin)
    assert r.jobs_new == 1 and r.jobs_below_floor == r.jobs_salary_unknown == 0
    assert calls[0]["results_to_take"] == 25 and "resultsToTake" not in calls[0]
    assert scheduler._salary_floor(calls[0]) is None


def test_ac8_note():
    assert reed_filter_notes({}, {"minimumSalary":"65000"})[0] == "Minimum salary is not applied on this page. It only filters saved-search runs."


def test_ac8a_budget_then_catch_up(tmp_path, offline):
    config, db = _setup(tmp_path)
    install([_result(str(n), salary_min_gbp=70000, salary_max_gbp=80000) for n in range(15)] + [_result(str(n)) for n in range(15,50)])
    kwargs = dict(config=config, db_path=db, profile=_profile(), saved_searches=[_search("reed",{"minimumSalary":"65000"})])
    first = scheduler.run_digest_pipeline(**kwargs)
    assert (first.jobs_fetched,first.jobs_new,first.jobs_held_over,first.jobs_below_floor) == (50,10,5,35)
    assert offline.call_count == 10
    count_sum(first)
    offline.reset_mock()
    second = scheduler.run_digest_pipeline(**kwargs)
    assert (second.jobs_new,second.jobs_already_seen,second.jobs_held_over) == (5,10,0)
    assert offline.call_count == 5
    count_sum(second)


def test_ac8b_order_and_failed_attempts(tmp_path, monkeypatch, offline):
    config, db = _setup(tmp_path)
    upsert_job(db, {"job_id":"reed-seen", "source":"reed", "source_job_id":"seen"})
    passing = lambda name: _result(name, salary_min_gbp=70000, salary_max_gbp=80000)
    results = [None, _result(""), _result("seen"), _result("below",description_raw=""), passing("blank")]
    results[-1]["description_raw"] = ""
    results += [passing(str(n)) for n in range(11)]
    install(results)
    conversion = Mock(wraps=scheduler.reviewed_job_payload_from_ui_result)
    monkeypatch.setattr(scheduler, "reviewed_job_payload_from_ui_result", conversion)
    original_eval = scheduler.evaluate_reviewed_job
    def evaluate(profile, job, **kwargs):
        if job.job_id == "reed-0":
            raise ValueError("synthetic eval")
        return original_eval(profile, job, **kwargs)
    monkeypatch.setattr(scheduler, "evaluate_reviewed_job", evaluate)
    original_save = scheduler.save_reviewed_job
    def save(job, root):
        if job.job_id == "reed-1":
            raise ValueError("synthetic save")
        return original_save(job, root)
    monkeypatch.setattr(scheduler, "save_reviewed_job", save)
    r = scheduler.run_digest_pipeline(config=config, db_path=db, profile=_profile(), saved_searches=[_search("reed",{"minimumSalary":"65000"})])
    assert (r.jobs_new,r.jobs_already_seen,r.jobs_below_floor,r.jobs_skipped,r.jobs_held_over) == (8,1,1,4,1)
    assert len(r.errors) == 2 and offline.call_count == conversion.call_count == 10
    count_sum(r,save_failures=1)


def test_ac8b_repeated_errors_hold_following_job(tmp_path, monkeypatch, offline):
    config, db = _setup(tmp_path)
    install([_result(str(n),salary_min_gbp=70000,salary_max_gbp=80000) for n in range(11)])
    monkeypatch.setattr(scheduler,"evaluate_reviewed_job",Mock(side_effect=ValueError("synthetic evaluation")))
    conversion = Mock(wraps=scheduler.reviewed_job_payload_from_ui_result)
    monkeypatch.setattr(scheduler,"reviewed_job_payload_from_ui_result",conversion)
    for _ in range(2):
        offline.reset_mock(); conversion.reset_mock()
        r = scheduler.run_digest_pipeline(config=config, db_path=db, profile=_profile(), saved_searches=[_search("reed",{"minimumSalary":"65000"})])
        assert len(r.errors) == 10 and r.jobs_held_over == 1 and r.jobs_new == 0
        assert offline.call_count == conversion.call_count == 10
        count_sum(r)


def test_ac8c_shared_queue_and_unfiltered_search(tmp_path, offline):
    config, db = _setup(tmp_path)
    calls = install([_result(str(n),salary_min_gbp=70000,salary_max_gbp=80000) for n in range(20)])
    other = install([_result(str(n)) for n in range(20)], source="adzuna",normalize=normalize_adzuna_search_params)
    profile = _profile()
    assert profile.digest_max_llm_per_run == 10
    r = scheduler.run_digest_pipeline(config=config,db_path=db,profile=profile,saved_searches=[_search("reed",{"minimumSalary":"65000"}),_search("adzuna",sid="s2")])
    assert (r.jobs_new,r.jobs_llm_queued,r.jobs_held_over) == (20,10,10)
    assert calls[0]["resultsToTake"] == "50" and other[0]["resultsToTake"] == "10"
    assert offline.call_count == 20
    count_sum(r)


def test_result_roundtrip():
    r = scheduler.DigestRunResult("start","finish",0,0,0,0,0,0,0)
    assert scheduler.DigestRunResult(**r.to_dict()) == r
    old = r.to_dict()
    for key in ("jobs_below_floor","jobs_salary_unknown","jobs_held_over"):
        del old[key]
    assert scheduler.DigestRunResult(**old) == r


@pytest.mark.parametrize("value,expected", [(65000,65000),("65,000",65000),("65000.0",65000),
                                            ("",None),(None,None),("abc",None),(0,None)])
def test_salary_number_formats(value, expected):
    assert scheduler._salary_number(value) == expected


def test_explicit_fetch_has_no_attempt_budget(tmp_path, offline):
    r, calls, _ = run(tmp_path, [_result(str(n),salary_min_gbp=70000,salary_max_gbp=80000) for n in range(15)],
                      {"minimumSalary":"65000","resultsToTake":"15"})
    assert r.jobs_new == offline.call_count == 15 and r.jobs_held_over == 0
    assert calls[0]["resultsToTake"] == "15"
    count_sum(r)


def test_floor_requires_both_normalized_keys():
    assert scheduler._salary_floor({"minimumSalary":"65000"}) is None
    assert scheduler._salary_floor({"resultsToTake":"50"}) is None


def test_ac8_reed_floor_page_paging_server(tmp_path, monkeypatch):
    """Socket regression for the orchestrator; excluded from producer offline run."""
    from src.job_sources import reed_source
    from test_ui import _running_ui_server, _http_get
    from urllib.parse import urlencode
    # Earlier test modules can leave a stub registered under "reed"; this test needs the real one.
    reed_source._register()
    calls = []
    def fake_fetch(keyword, location, max_results, *, skip=0, save_raw=True):
        calls.append((max_results, skip, save_raw))
        # Distinct titles and employers: the search page collapses identical cards.
        return [{"jobId": 1000 + n, "jobTitle": f"Analyst {n}", "employerName": f"Acme {n}",
                 "locationName": "London", "minimumSalary":38000,"maximumSalary":45000,
                 "jobUrl":f"https://reed.example/jobs/{1000+n}","jobDescription":"<p>Work</p>"}
                for n in range(skip, skip + max_results)]
    monkeypatch.setattr("src.job_sources.reed_source.fetch_reed_jobs", fake_fetch)
    query = urlencode({"keywords":"analyst","minimumSalary":"65000","resultsToTake":"10"})
    with _running_ui_server(tmp_path) as (base_url, _config):
        status, body = _http_get(f"{base_url}/search/reed?{query}")
        assert status == 200
        assert "Minimum salary is not applied on this page. It only filters saved-search runs." in body
        next_url = body.split('data-next-url="',1)[1].split('"',1)[0].replace("&amp;","&")
        status, body = _http_get(base_url + next_url)
    data = json.loads(body)
    assert status == 200 and data["count"] == 10 and data["has_more"] is True
    assert 'data-jst-sjid="1010"' in data["cards_html"]
    assert "resultsSkip=20" in data["next_url"]
    assert calls == [(10,0,False),(10,10,False)]
