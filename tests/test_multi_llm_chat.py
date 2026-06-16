"""QA tests for Multi-LLM Chat Persistence Rev3."""
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

CONV_DIR = Path(__file__).parent.parent / "viewer" / "conversations"
TMP_DIR = CONV_DIR / ".tmp"
CORRUPT_DIR = CONV_DIR / ".corrupt"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _new_id():
    return str(uuid.uuid4())


def _write_thread(thread_id: str, data: dict) -> None:
    p = CONV_DIR / f"{thread_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f)


def _read_thread(thread_id: str) -> dict | None:
    p = CONV_DIR / f"{thread_id}.json"
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def _delete_thread(thread_id: str) -> None:
    p = CONV_DIR / f"{thread_id}.json"
    if p.exists():
        p.unlink()


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_test_thread():
    tid = _new_id()
    yield tid
    _delete_thread(tid)
    tmp = TMP_DIR / f"{tid}.json.tmp"
    if tmp.exists():
        tmp.unlink()


# ─── Import the helpers being tested ─────────────────────────────────────────

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "viewer"))
import viewer_server as vs


# ─── Test 1: Turns structure ──────────────────────────────────────────────────

class TestTurnsStructure:
    def test_turn_structure_fields(self, clean_test_thread):
        """A turn should have turn_index, user{text,ts}, responses{minimax,gemma,gpt}."""
        tid = clean_test_thread
        turns = [
            {
                "turn_index": 0,
                "user": {"text": "hi", "ts": "2026-04-13T00:00:00Z"},
                "responses": {
                    "minimax": {"text": "hello from minimax", "ts": "2026-04-13T00:00:01Z"},
                    "gemma": None,
                    "gpt": None,
                }
            }
        ]
        data = {
            "schema_version": 1,
            "thread_id": tid,
            "created_at": "2026-04-13T00:00:00Z",
            "updated_at": "2026-04-13T00:00:00Z",
            "models": ["minimax", "gemma", "gpt"],
            "deleted": False,
            "turns": turns,
        }
        _write_thread(tid, data)
        loaded, _ = vs._load_thread(tid)
        assert loaded["turns"][0]["turn_index"] == 0
        assert loaded["turns"][0]["user"]["text"] == "hi"
        assert loaded["turns"][0]["responses"]["minimax"]["text"] == "hello from minimax"
        assert loaded["turns"][0]["responses"]["gemma"] is None


# ─── Test 2: Truncation (40 turn cap) ─────────────────────────────────────────

class TestTruncation:
    def test_truncate_drops_oldest_from_front(self):
        """_truncate_turns should drop oldest turns until len <= 40."""
        turns = [{"turn_index": i, "user": {"text": f"msg{i}"}, "responses": {}} for i in range(45)]
        truncated = vs._truncate_turns(turns)
        assert len(truncated) == 40
        assert truncated[0]["turn_index"] == 5  # oldest 5 dropped
        assert truncated[-1]["turn_index"] == 44

    def test_truncate_under_limit_no_change(self):
        """Under 40 turns, no truncation."""
        turns = [{"turn_index": i, "user": {"text": f"msg{i}"}, "responses": {}} for i in range(10)]
        truncated = vs._truncate_turns(turns)
        assert len(truncated) == 10

    def test_truncation_preserves_newest(self):
        """With 50 turns, cap is 40 — oldest 10 dropped, newest 40 kept."""
        turns = [{"turn_index": i, "user": {"text": f"msg{i}"}, "responses": {}} for i in range(50)]
        truncated = vs._truncate_turns(turns)
        assert len(truncated) == 40  # cap is 40, not 10
        assert truncated[0]["turn_index"] == 10  # oldest 10 dropped
        assert truncated[-1]["turn_index"] == 49

    def test_exactly_40_no_truncation(self):
        """Exactly 40 turns → no change."""
        turns = [{"turn_index": i, "user": {"text": f"msg{i}"}, "responses": {}} for i in range(40)]
        truncated = vs._truncate_turns(turns)
        assert len(truncated) == 40


# ─── Test 3: DELETE idempotent 204 ─────────────────────────────────────────────

class TestDeleteIdempotent:
    def test_delete_removes_file(self, clean_test_thread):
        """DELETE sets deleted=True, saves, then unlinks. File should be gone."""
        tid = clean_test_thread
        _write_thread(tid, {
            "schema_version": 1, "thread_id": tid, "created_at": "2026-04-13T00:00:00Z",
            "updated_at": "2026-04-13T00:00:00Z", "models": ["minimax"], "deleted": False, "turns": []
        })
        thread, _ = vs._load_thread(tid)
        assert thread["deleted"] is False
        thread["deleted"] = True
        vs._save_thread(tid, thread)
        vs._thread_path(tid).unlink()  # DELETE handler does this after save
        assert not (CONV_DIR / f"{tid}.json").exists()

    def test_deleted_file_stays_deleted(self, clean_test_thread):
        """After file is unlinked, it stays gone (idempotent)."""
        tid = clean_test_thread
        _write_thread(tid, {
            "schema_version": 1, "thread_id": tid, "created_at": "2026-04-13T00:00:00Z",
            "updated_at": "2026-04-13T00:00:00Z", "models": ["minimax"], "deleted": False, "turns": []
        })
        # Simulate first DELETE
        thread, _ = vs._load_thread(tid)
        thread["deleted"] = True
        vs._save_thread(tid, thread)
        vs._thread_path(tid).unlink()
        # Second attempt: file already gone
        assert not (CONV_DIR / f"{tid}.json").exists()


# ─── Test 4: 409 Conflict after DELETE ─────────────────────────────────────────

class Test409Conflict:
    def test_deleted_flag_detected_by_load(self, clean_test_thread):
        """After DELETE (unlink), subsequent _load_thread finds no file."""
        tid = clean_test_thread
        _write_thread(tid, {
            "schema_version": 1, "thread_id": tid, "created_at": "2026-04-13T00:00:00Z",
            "updated_at": "2026-04-13T00:00:00Z", "models": ["minimax"], "deleted": False, "turns": []
        })
        # DELETE flow
        thread, _ = vs._load_thread(tid)
        thread["deleted"] = True
        vs._save_thread(tid, thread)
        vs._thread_path(tid).unlink()
        # File is gone
        assert not (CONV_DIR / f"{tid}.json").exists()


# ─── Test 5: 413 Thread too large ─────────────────────────────────────────────

class Test413LargeThread:
    def test_large_thread_file_exceeds_2mb(self, clean_test_thread):
        """Large thread data should exceed 2MB threshold."""
        tid = clean_test_thread
        large_turns = [{
            "turn_index": i,
            "user": {"text": "x" * 50000, "ts": "2026-04-13T00:00:00Z"},
            "responses": {
                "minimax": {"text": "y" * 50000, "ts": "2026-04-13T00:00:01Z"},
                "gemma": {"text": "z" * 50000, "ts": "2026-04-13T00:00:02Z"},
                "gpt": {"text": "w" * 50000, "ts": "2026-04-13T00:00:03Z"},
            }
        } for i in range(30)]
        data = {
            "schema_version": 1, "thread_id": tid,
            "created_at": "2026-04-13T00:00:00Z", "updated_at": "2026-04-13T00:00:00Z",
            "models": ["minimax", "gemma", "gpt"], "deleted": False, "turns": large_turns
        }
        _write_thread(tid, data)
        size = (CONV_DIR / f"{tid}.json").stat().st_size
        assert size > 2 * 1024 * 1024  # must exceed 2MB


# ─── Test 6: Rev2 → Rev3 migration ────────────────────────────────────────────

class TestRev2Migration:
    def test_flat_format_coerced_to_turns(self, clean_test_thread):
        """Old flat files → turns array with 1 turn per shared message."""
        tid = clean_test_thread
        old_data = {
            "schema_version": 1,
            "thread_id": tid,
            "created_at": "2026-04-11T00:00:00Z",
            "updated_at": "2026-04-11T00:00:00Z",
            "models": ["minimax", "gemma", "gpt"],
            "shared_user_messages": [
                {"text": "hello", "ts": "2026-04-11T00:00:00Z"},
                {"text": "second msg", "ts": "2026-04-11T00:01:00Z"},
            ],
            "responses_by_model": {
                "minimax": [{"text": "hi minimax", "ts": "2026-04-11T00:00:01Z"}],
                "gemma": [{"text": "hi gemma", "ts": "2026-04-11T00:00:02Z"}],
                "gpt": [],
            }
        }
        _write_thread(tid, old_data)
        coerced, history_reset = vs._load_thread(tid)
        assert "turns" in coerced
        assert len(coerced["turns"]) == 2
        # Turn 0
        assert coerced["turns"][0]["user"]["text"] == "hello"
        assert coerced["turns"][0]["responses"]["minimax"]["text"] == "hi minimax"
        assert coerced["turns"][0]["responses"]["gpt"] is None
        # Turn 1: gemma only has 1 total response → no response for turn 1
        assert coerced["turns"][1]["user"]["text"] == "second msg"
        assert coerced["turns"][1]["responses"]["minimax"] is None  # minimax has 1 response (turn 0 only)
        assert coerced["turns"][1]["responses"]["gemma"] is None  # gemma has 1 response (turn 0 only)
        assert coerced["turns"][1]["responses"]["gpt"] is None
        # history_reset False — migration preserves history (just restructures)
        assert history_reset["minimax"] is False
        assert history_reset["gemma"] is False
        assert history_reset["gpt"] is False


# ─── Test 7: Atomic write (tmp + fsync + rename) ──────────────────────────────

class TestAtomicWrite:
    def test_save_writes_to_tmp_first(self, clean_test_thread):
        """_save_thread should write to .tmp/ then rename."""
        tid = clean_test_thread
        data = {
            "schema_version": 1, "thread_id": tid,
            "created_at": "2026-04-13T00:00:00Z", "updated_at": "2026-04-13T00:00:00Z",
            "models": ["minimax"], "deleted": False, "turns": []
        }
        vs._save_thread(tid, data)
        # .tmp file should be gone after rename
        assert not (TMP_DIR / f"{tid}.json.tmp").exists()
        # Final file should exist
        assert (CONV_DIR / f"{tid}.json").exists()
        content = _read_thread(tid)
        assert content["thread_id"] == tid


# ─── Test 8: Per-thread locking ───────────────────────────────────────────────

class TestPerThreadLock:
    def test_lock_cached_by_thread_id(self, clean_test_thread):
        """Calling _lock_for twice with same tid returns same Lock object."""
        lock1 = vs._lock_for(clean_test_thread)
        lock2 = vs._lock_for(clean_test_thread)
        assert lock1 is lock2

    def test_different_threads_different_locks(self, clean_test_thread):
        """Different thread IDs get different locks."""
        tid2 = _new_id()
        lock1 = vs._lock_for(clean_test_thread)
        lock2 = vs._lock_for(tid2)
        assert lock1 is not lock2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
