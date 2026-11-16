"""Read-only project and SQLite explorer for the local Miyora workspace."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from app.core import database

EXCLUDE = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
MAX_DEPTH = 6
MAX_ENTRIES = 1500

def project_tree(root: Path) -> dict:
    root = root.resolve()
    seen = [0]
    def walk(path: Path, depth: int) -> dict:
        try:
            info = path.lstat()
        except OSError:
            return {"name": path.name, "type": "unavailable", "bytes": 0}
        if path.is_symlink():
            return {"name": path.name, "type": "link", "bytes": 0}
        if not path.is_dir():
            return {"name": path.name, "type": "file", "bytes": info.st_size}
        result = {"name": path.name, "type": "directory", "bytes": 0, "children": []}
        if depth >= MAX_DEPTH or seen[0] >= MAX_ENTRIES:
            result["truncated"] = True
            return result
        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            result["unavailable"] = True
            return result
        for child in children:
            if child.name in EXCLUDE or child.is_symlink():
                continue
            if seen[0] >= MAX_ENTRIES:
                result["truncated"] = True
                break
            seen[0] += 1
            entry = walk(child, depth + 1)
            result["children"].append(entry)
            result["bytes"] += entry["bytes"]
        return result
    result = walk(root, 0)
    result["scanned_entries"] = seen[0]
    return result

def overview(root: Path) -> dict:
    tree = project_tree(root)
    files = [database.DB_PATH, Path(str(database.DB_PATH) + "-wal"), Path(str(database.DB_PATH) + "-shm")]
    return {"project": tree, "database_files": {p.name: p.stat().st_size if p.is_file() else 0 for p in files},
            "database": database.stats()}

def tables() -> list[dict]:
    with database.connect() as db:
        names = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        output = []
        for name in names:
            escaped = '"' + name.replace('"', '""') + '"'
            fields = [dict(r) for r in db.execute("PRAGMA table_info(" + escaped + ")")]
            count = db.execute("SELECT count(*) FROM " + escaped).fetchone()[0]
            output.append({"name": name, "count": count, "fields": fields})
        return output

def table_rows(name: str, offset: int = 0, limit: int = 30) -> dict:
    if not isinstance(name, str) or len(name) > 128:
        raise ValueError("invalid table")
    with database.connect() as db:
        allowed = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if name not in allowed:
            raise ValueError("unknown table")
        quoted = '"' + name.replace('"', '""') + '"'
        limit = max(1, min(int(limit), 50))
        offset = max(0, min(int(offset), 1000000))
        cursor = db.execute("SELECT * FROM " + quoted + " LIMIT ? OFFSET ?", (limit, offset))
        columns = [c[0] for c in cursor.description]
        rows = [{key: (str(value)[:1000] if isinstance(value, bytes) else value) for key, value in zip(columns, row)}
                for row in cursor.fetchall()]
        return {"table": name, "columns": columns, "rows": rows, "offset": offset, "limit": limit}
