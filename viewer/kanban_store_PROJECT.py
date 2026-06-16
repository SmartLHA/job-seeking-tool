"""
Kanban data store — thread-safe JSON persistence with atomic writes.
"""
from __future__ import annotations
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

VIEWER_DIR = Path(__file__).parent.resolve()
DATA_FILE = VIEWER_DIR / "kanban_data.json"

# Thread-safe lock for write operations
_LOCK = threading.Lock()

# Default board structure
DEFAULT_BOARD = {
    "columns": [
        {"id": "backlog", "title": "📥 Backlog", "cards": []},
        {"id": "in-progress", "title": "🔄 In Progress", "cards": []},
        {"id": "blocked", "title": "🚫 Blocked", "cards": []},
        {"id": "done", "title": "✅ Done", "cards": []},
    ],
    "version": 1,
    "updated_at": None,
}


def _load_board() -> dict:
    """Load board from JSON file, return default if missing/corrupt."""
    if not DATA_FILE.exists():
        return dict(DEFAULT_BOARD)
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        # Ensure all columns exist
        column_ids = {c["id"] for c in data.get("columns", [])}
        for default_col in DEFAULT_BOARD["columns"]:
            if default_col["id"] not in column_ids:
                data["columns"].append(default_col)
        return data
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_BOARD)


def _save_board(board: dict) -> None:
    """Atomically save board: write to temp file, then rename."""
    board["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tmp_path = DATA_FILE.with_suffix(".json.tmp")
    try:
        encoded = json.dumps(board, ensure_ascii=False, indent=2).encode("utf-8")
        with open(tmp_path, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, DATA_FILE)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _new_card_id() -> str:
    return f"card-{uuid.uuid4().hex[:8]}"


# ─── Public API ──────────────────────────────────────────────────────────────

def get_board() -> dict:
    """Return full board (columns + cards)."""
    with _LOCK:
        return _load_board()


def upsert_card(column_id: str, card_data: dict) -> dict:
    """
    Create or update a card.
    
    If card_data["id"] is provided and exists → update.
    If card_data["id"] is provided but not found → treat as new card.
    If no id → generate new card.
    
    Returns the card object.
    """
    with _LOCK:
        board = _load_board()
        
        card_id = card_data.get("id")
        title = card_data.get("title", "").strip()
        if not title:
            raise ValueError("Card title is required")
        
        # Find target column
        target_col = None
        for col in board["columns"]:
            if col["id"] == column_id:
                target_col = col
                break
        if not target_col:
            raise ValueError(f"Column not found: {column_id}")
        
        # Prepare card object
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if card_id:
            # Check if card exists in any column
            for col in board["columns"]:
                for i, c in enumerate(col["cards"]):
                    if c["id"] == card_id:
                        # Update existing card
                        col["cards"][i] = {
                            **c,
                            **card_data,
                            "id": card_id,
                            "updated_at": now,
                        }
                        _save_board(board)
                        return col["cards"][i]
            # Card ID provided but not found → create new with this ID
            new_card = {
                "id": card_id,
                "title": title,
                "description": card_data.get("description", ""),
                "priority": card_data.get("priority", "medium"),
                "tags": card_data.get("tags", []),
                "link": card_data.get("link", ""),
                "created_at": now,
                "updated_at": now,
            }
            target_col["cards"].append(new_card)
            _save_board(board)
            return new_card
        else:
            # New card with generated ID
            new_card = {
                "id": _new_card_id(),
                "title": title,
                "description": card_data.get("description", ""),
                "priority": card_data.get("priority", "medium"),
                "tags": card_data.get("tags", []),
                "link": card_data.get("link", ""),
                "created_at": now,
                "updated_at": now,
            }
            target_col["cards"].append(new_card)
            _save_board(board)
            return new_card


def move_card(card_id: str, to_column_id: str, to_index: int | None = None) -> dict:
    """
    Move a card to a different column (and optionally reorder within it).
    
    to_index: position in target column (default = append to end)
    """
    with _LOCK:
        board = _load_board()
        
        # Find and remove card from current column
        card = None
        from_col = None
        for col in board["columns"]:
            for i, c in enumerate(col["cards"]):
                if c["id"] == card_id:
                    card = col["cards"].pop(i)
                    from_col = col
                    break
            if card:
                break
        
        if not card:
            raise ValueError(f"Card not found: {card_id}")
        
        # Find target column
        to_col = None
        for col in board["columns"]:
            if col["id"] == to_column_id:
                to_col = col
                break
        if not to_col:
            # Invalid column → put card back
            from_col["cards"].append(card)
            raise ValueError(f"Column not found: {to_column_id}")
        
        # Insert at position (default = end)
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        card["updated_at"] = now
        if to_index is None or to_index >= len(to_col["cards"]):
            to_col["cards"].append(card)
        else:
            to_col["cards"].insert(max(0, to_index), card)
        
        _save_board(board)
        return card


def delete_card(card_id: str) -> bool:
    """Delete a card by ID."""
    with _LOCK:
        board = _load_board()
        for col in board["columns"]:
            for i, c in enumerate(col["cards"]):
                if c["id"] == card_id:
                    col["cards"].pop(i)
                    _save_board(board)
                    return True
        return False


def reorder_column(column_ids: list[str]) -> dict:
    """Reorder columns by a list of column IDs."""
    with _LOCK:
        board = _load_board()
        id_to_col = {c["id"]: c for c in board["columns"]}
        new_columns = []
        for cid in column_ids:
            if cid in id_to_col:
                new_columns.append(id_to_col[cid])
        # Add any columns not in the list (shouldn't happen but safety)
        for col in board["columns"]:
            if col["id"] not in [c["id"] for c in new_columns]:
                new_columns.append(col)
        board["columns"] = new_columns
        _save_board(board)
        return board
