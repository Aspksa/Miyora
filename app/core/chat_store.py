"""Persist conversations and messages in SQLite."""
from __future__ import annotations
from contextlib import closing
import re
from collections import defaultdict
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

def graph(thread_id: int, limit: int = 160) -> dict | None:
    """Derive an observable conversation graph from persisted SQLite messages.

    Nodes represent actual messages; edges are chronological message links,
    not the model's hidden reasoning or inferred semantic relationships.
    """
    if not isinstance(thread_id, int) or isinstance(thread_id, bool) or thread_id < 1:
        raise ValueError("invalid_thread")
    with closing(database.connect()) as db:
        thread = db.execute(
            "SELECT id,title FROM chat_threads WHERE id=?", (thread_id,)
        ).fetchone()
        if thread is None:
            return None
        rows = db.execute(
            "SELECT id,role,content,created_at FROM chat_messages "
            "WHERE thread_id=? ORDER BY id DESC LIMIT ?",
            (thread_id, max(1, min(limit, 300))),
        ).fetchall()
    rows = list(reversed(rows))
    nodes = [
        {"id": "message-" + str(row["id"]), "message_id": row["id"],
         "role": row["role"], "label": row["content"][:100],
         "content": row["content"][:4000],
         "created_at": row["created_at"]}
        for row in rows
    ]
    edges = [
        {"source": nodes[i - 1]["id"], "target": nodes[i]["id"],
         "type": "sequence"}
        for i in range(1, len(nodes))
    ]
    # Transparent lexical connections, not model-inferred knowledge or hidden reasoning.
    stopwords = {"это", "как", "что", "для", "или", "при", "the", "and", "with", "from", "you", "are", "мне", "могу", "нужно", "будет", "есть", "привет"}
    def terms(content):
        return {term for term in re.findall(r"[^\W_]{4,}", content.lower(), re.UNICODE)
                if term not in stopwords}
    groups = defaultdict(list)
    for node in nodes:
        node_terms = terms(node["content"])
        node["terms"] = sorted(node_terms)[:12]
        for term in node_terms:
            groups[term].append(node["id"])
    shared = []
    # Cap pair generation to avoid quadratic expansion for frequent words.
    for term, members in sorted(groups.items()):
        if 2 <= len(members) <= 16:
            shared.append((term, members))
    pair_terms = defaultdict(list)
    for term, members in shared:
        for i, source in enumerate(members):
            for target in members[i + 1:]:
                if len(pair_terms[(source, target)]) < 4:
                    pair_terms[(source, target)].append(term)
    knowledge_edges = [
        {"source": source, "target": target, "type": "shared_terms",
         "terms": matches}
        for (source, target), matches in pair_terms.items() if len(matches) >= 2
    ][:240]
    clusters = [
        {"id": "role-user", "label": "Сообщения пользователя",
         "kind": "role", "node_ids": [n["id"] for n in nodes if n["role"] == "user"]},
        {"id": "role-assistant", "label": "Ответы Miyora",
         "kind": "role", "node_ids": [n["id"] for n in nodes if n["role"] == "assistant"]},
    ]
    return {"thread_id": thread["id"], "title": thread["title"],
            "nodes": nodes, "edges": edges + knowledge_edges,
            "clusters": clusters, "source": "sqlite_messages",
            "relation_method": "chronology_and_shared_lexical_terms"}
