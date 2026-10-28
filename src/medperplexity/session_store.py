"""SQLite persistence for patient-bound MedPerplexity conversations.

Stores conversation metadata, a compact extractive memory, pending task state,
and the visible message history. A conversation ID is permanently bound to one
patient ID; callers must use a new conversation ID when switching patients.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


class PatientConversationMismatch(ValueError):
    """Raised when a conversation is opened for a different patient."""


class SessionStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        default = os.environ.get("MEDPERPLEXITY_SESSION_DB", "data/medperplexity_sessions.sqlite3")
        self.db_path = str(db_path or default)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                memory_json TEXT NOT NULL DEFAULT '[]',
                pending_task_json TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_messages ON conversation_messages(conversation_id, id)")

    def load(self, conversation_id: str, patient_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
            if row is None:
                return {"memory": [], "summary": "", "pending_task": None}
            if row["patient_id"] != patient_id:
                raise PatientConversationMismatch(
                    f"Conversation '{conversation_id}' belongs to patient '{row['patient_id']}', not '{patient_id}'. "
                    "Use a different conversation ID for the selected patient."
                )
            return {
                "memory": json.loads(row["memory_json"] or "[]"),
                "summary": "",
                "pending_task": json.loads(row["pending_task_json"]) if row["pending_task_json"] else None,
            }

    def save(self, conversation_id: str, patient_id: str, state: Dict[str, Any],
             user_message: str, assistant_message: str) -> None:
        memory = json.dumps(state.get("memory") or [], ensure_ascii=False)
        pending = state.get("pending_task")
        pending_json = json.dumps(pending, ensure_ascii=False) if pending else None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT patient_id FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
            if row is not None and row["patient_id"] != patient_id:
                raise PatientConversationMismatch(
                    f"Conversation '{conversation_id}' belongs to patient '{row['patient_id']}', not '{patient_id}'. "
                    "Use a different conversation ID for the selected patient."
                )
            conn.execute("""INSERT INTO conversations(conversation_id, patient_id, memory_json, pending_task_json)
                VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET
                memory_json=excluded.memory_json, pending_task_json=excluded.pending_task_json,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                (conversation_id, patient_id, memory, pending_json))
            conn.execute("INSERT INTO conversation_messages(conversation_id,patient_id,role,content) VALUES(?,?,?,?)",
                         (conversation_id, patient_id, "user", user_message))
            conn.execute("INSERT INTO conversation_messages(conversation_id,patient_id,role,content) VALUES(?,?,?,?)",
                         (conversation_id, patient_id, "assistant", assistant_message))
            conn.commit()

    def history(self, conversation_id: str, patient_id: str, limit: int = 100) -> list[Dict[str, str]]:
        """Return messages only after verifying the conversation's patient binding."""
        with self._connect() as conn:
            row = conn.execute("SELECT patient_id FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
            if row is None:
                return []
            if row["patient_id"] != patient_id:
                raise PatientConversationMismatch("This conversation does not belong to the selected patient.")
            rows = conn.execute("""SELECT role, content, created_at FROM conversation_messages
                WHERE conversation_id=? AND patient_id=? ORDER BY id DESC LIMIT ?""",
                (conversation_id, patient_id, max(1, min(int(limit), 500)))).fetchall()
            return [dict(r) for r in reversed(rows)]
