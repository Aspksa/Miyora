"""Persist conversations and messages in SQLite."""
from __future__ import annotations
from contextlib import closing
from app.core import database

def initialize():
    with closing(database.connect()) as db, db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS chat_threads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id,id);
        """)
def list_threads():
    with closing(database.connect()) as db:
        return [dict(r) for r in db.execute("SELECT * FROM chat_threads ORDER BY updated_at DESC,id DESC LIMIT 200")]
def create_thread(title="Новый чат"):
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 120: raise ValueError("invalid_title")
    with closing(database.connect()) as db, db:
        cur=db.execute("INSERT INTO chat_threads(title) VALUES (?)",(title.strip(),))
        return dict(db.execute("SELECT * FROM chat_threads WHERE id=?",(cur.lastrowid,)).fetchone())
def messages(thread_id):
    with closing(database.connect()) as db:
        if not db.execute("SELECT 1 FROM chat_threads WHERE id=?",(thread_id,)).fetchone(): return None
        return [dict(r) for r in db.execute("SELECT id,role,content,created_at FROM chat_messages WHERE thread_id=? ORDER BY id",(thread_id,))]
def rename(thread_id,title):
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 120: raise ValueError("invalid_title")
    with closing(database.connect()) as db, db:
        return db.execute("UPDATE chat_threads SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(title.strip(),thread_id)).rowcount>0
def delete(thread_id):
    with closing(database.connect()) as db, db:
        return db.execute("DELETE FROM chat_threads WHERE id=?",(thread_id,)).rowcount>0
def append(thread_id,role,content):
    if role not in ("user","assistant") or not isinstance(content,str) or not 1 <= len(content) <= 120000: raise ValueError("invalid_message")
    with closing(database.connect()) as db, db:
        if not db.execute("SELECT 1 FROM chat_threads WHERE id=?",(thread_id,)).fetchone(): raise ValueError("thread_not_found")
        db.execute("INSERT INTO chat_messages(thread_id,role,content) VALUES (?,?,?)",(thread_id,role,content))
        db.execute("UPDATE chat_threads SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(thread_id,))
