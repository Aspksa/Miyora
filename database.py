# -*- coding: utf-8 -*-
"""SQLite persistence for Miyora. No third-party dependencies."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MIYORA_DB_PATH") or ROOT / "data" / "miyora.db").expanduser()

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db

def initialize() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
            INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
        """)

def health() -> dict:
    with connect() as db:
        result = db.execute("PRAGMA quick_check").fetchone()[0]
        return {"status": "ok" if result == "ok" else "error", "engine": "sqlite",
                "schema_version": db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]}

def list_notes(limit: int = 100) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT id,title,content,created_at,updated_at FROM notes ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 100)),))]

def create_note(title: str, content: str = "") -> dict:
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValueError("title must be 1-200 characters")
    if not isinstance(content, str) or len(content) > 100000:
        raise ValueError("content must be a string of at most 100000 characters")
    with connect() as db:
        cursor = db.execute("INSERT INTO notes(title,content) VALUES (?,?)", (title.strip(), content))
        return dict(db.execute("SELECT * FROM notes WHERE id=?", (cursor.lastrowid,)).fetchone())

def delete_note(note_id: int) -> bool:
    with connect() as db:
        return db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount > 0
