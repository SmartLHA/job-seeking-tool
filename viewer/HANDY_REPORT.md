# Multi-LLM Chat Persistence — Rev3 Implementation

## What Changed

### viewer_server.py

**New constants:**
- `MAX_TURNS = 40` (replaced `MAX_SHARED_USER_MESSAGES` and `MAX_RESPONSES_PER_MODEL`)
- Removed `_THREAD_DELETED` in-memory set (replaced by durable `deleted` flag in file)

**New helpers added:**

1. `_truncate_turns(turns)` — enforces max 40 turns by dropping oldest from front; replaces the old flat-array `_truncate_thread()`
2. `_materialize_model_history(model, turns)` — iterates `turns` array, collects `user.text` + model `response.text` (skip null) for curl history; replaces old flat-array materialization
3. `_load_thread(thread_id)` — atomic read with schema version check and corrupt rename to `.corrupt/`
4. `_save_thread(thread_id, data)` — atomic write via `.tmp/` + `fsync` + rename
5. `_lock_for(thread_id)` — per-thread `threading.Lock` cached in `_THREAD_LOCKS` dict

**Schema changes:**
- File now uses `turns` array instead of flat `shared_user_messages` + `responses_by_model`
- Each turn: `{ turn_index, user: {text, ts}, responses: {minimax, gemma, gpt} }` — model responses can be `null`
- `deleted: false` tombstone field added (replaces in-memory `_THREAD_DELETED` set)
- `request_cache` removed (request_id cached per-turn instead)

**Migration:**
- `_coerce_thread_data_v1()` migrates old Rev2 flat files to new `turns` structure on read
- Unknown schema versions rename file to `.corrupt/` instead of `.bak`

**API changes:**
- `POST /api/multi-chat`: uses turns structure + per-thread lock; checks `deleted` flag after lock; checks request_id in turns; returns `history_reset` flags
- `GET /api/multi-chat/<thread_id>`: validates UUID, checks `deleted` flag
- `DELETE /api/multi-chat/<thread_id>`: idempotent 204, durable tombstone + file remove
- 413 now includes `{"error": "Thread too large", "current_size_bytes": N}`

**Removed:**
- `_truncate_thread()`, `_coerce_thread_data()`, old flat-array materialization
- In-memory `_THREAD_DELETED` set (replaced by file-based tombstone)

### multi_llm_chat.html (client)

- Already had `localStorage` thread_id persistence, 409 handling, 413 handling, `history_reset` notice, DELETE on Clear, and thread_id footer
- No HTML changes needed — all Rev3 client requirements were already implemented

## Notes

- No new Python dependencies added
- All existing curl timeouts unchanged
- `.tmp/` and `.corrupt/` subdirectories created automatically
- Existing conversation files are migrated on first read via `_coerce_thread_data_v1()`