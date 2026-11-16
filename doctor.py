"""Miyora offline diagnostics. Run with the project's Python interpreter."""
from __future__ import annotations

import importlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parent

def run() -> int:
    checks = {}
    for name in ("main.py", "app/server.py", "app/core/database.py", "web/index.html"):
        checks["file:" + name] = (ROOT / name).is_file()
    for name in ("sqlite3", "http.server", "json", "app.server", "app.core.database"):
        try:
            importlib.import_module(name)
            checks["import:" + name] = True
        except Exception as exc:
            checks["import:" + name] = str(exc)
    try:
        with tempfile.TemporaryDirectory(prefix="miyora-doctor-") as tmp:
            with closing(sqlite3.connect(str(Path(tmp) / "test.db"))) as db:
                with db:
                    db.execute("CREATE TABLE checkup (value TEXT)")
                    db.execute("INSERT INTO checkup VALUES (?)", ("Привет",))
                checks["sqlite:write_read"] = db.execute("SELECT value FROM checkup").fetchone()[0] == "Привет"
    except Exception as exc:
        checks["sqlite:write_read"] = str(exc)
    try:
        data = ROOT / "data"
        data.mkdir(exist_ok=True)
        with tempfile.TemporaryFile(dir=data):
            pass
        checks["data:writable"] = True
    except Exception as exc:
        checks["data:writable"] = str(exc)
    checks["python:version"] = sys.version.split()[0]
    failures = [k for k,v in checks.items() if v is not True and k != "python:version"]
    print(json.dumps({"status":"ok" if not failures else "error", "checks":checks, "failed":failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(run())
