# -*- coding: utf-8 -*-
"""SQLite persistence for Miyora. No third-party dependencies."""
from __future__ import annotations

import os
from datetime import datetime, timezone
import sqlite3
import sys
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
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
        columns = {row["name"] for row in db.execute("PRAGMA table_info(notes)")}
        if "deleted_at" not in columns:
            db.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at)")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")

def health() -> dict:
    with connect() as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        return {"status": "ok" if result == "ok" else "error", "engine": "sqlite",
                "schema_version": db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]}

def list_notes(limit: int = 100, search: str = "", include_deleted: bool = False) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT id,title,content,created_at,updated_at,deleted_at FROM notes "
            "WHERE (? OR deleted_at IS NULL) AND (title LIKE ? OR content LIKE ?) "
            "ORDER BY id DESC LIMIT ?",
            (int(include_deleted), "%" + search + "%", "%" + search + "%", max(1, min(limit, 500))))]

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
        return db.execute("UPDATE notes SET deleted_at=CURRENT_TIMESTAMP WHERE id=? AND deleted_at IS NULL", (note_id,)).rowcount > 0

def restore_note(note_id: int) -> bool:
    with connect() as db:
        return db.execute("UPDATE notes SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL", (note_id,)).rowcount > 0

def update_note(note_id: int, title: str, content: str = "") -> dict | None:
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValueError("title must be 1-200 characters")
    if not isinstance(content, str) or len(content) > 100000:
        raise ValueError("content must be a string of at most 100000 characters")
    with connect() as db:
        changed = db.execute("UPDATE notes SET title=?,content=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND deleted_at IS NULL",
                             (title.strip(), content, note_id)).rowcount
        return dict(db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()) if changed else None

def stats() -> dict:
    with connect() as db:
        return {"total": db.execute("SELECT count(*) FROM notes WHERE deleted_at IS NULL").fetchone()[0],
                "deleted": db.execute("SELECT count(*) FROM notes WHERE deleted_at IS NOT NULL").fetchone()[0],
                "bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
                "schema_version": db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]}

def backup(destination: str | Path | None = None) -> Path:
    """Online SQLite backup, preserving uncheckpointed WAL content."""
    initialize()
    folder = DB_PATH.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(destination) if destination is not None else folder / ("miyora-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".db")
    target = target.resolve()
    if target == DB_PATH.resolve():
        raise ValueError("Backup cannot overwrite the live database")
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with connect() as source, sqlite3.connect(str(target)) as output:
            source.backup(output)
            if output.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Backup integrity check failed")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target
