# -*- coding: utf-8 -*-
"""Miyora Core: lightweight local web application (Python standard library)."""
from __future__ import annotations

import json
import sqlite3
import database
import os
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP_NAME = "Miyora"
VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Miyora — Ядро</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;background:#0c1020;color:#eaf0ff;min-height:100vh;display:grid;place-items:center;padding:24px}
main{width:min(680px,100%);background:#171d31;border:1px solid #303b59;border-radius:20px;padding:32px;box-shadow:0 15px 55px #0005}
h1{font-size:clamp(32px,6vw,48px);margin:0 0 8px}p{line-height:1.6;color:#bac7e4}
.status{display:inline-flex;gap:9px;align-items:center;color:#9df5c6;font-weight:650}
.dot{width:10px;height:10px;border-radius:50%;background:#45dc93}
dl{display:grid;grid-template-columns:auto 1fr;gap:12px;margin:26px 0}
dt{color:#93a6ce}dd{margin:0;overflow-wrap:anywhere}
button{background:#6389ff;border:0;border-radius:10px;padding:12px 18px;color:#fff;font:inherit;cursor:pointer}
button:hover{background:#7a9bff}small{color:#91a0c1}
</style>
</head>
<body>
<main>
<div class="status"><span class="dot"></span><span id="state">Проверка ядра…</span></div>
<h1>Miyora</h1>
<p>Локальное ядро запущено. Сервер работает на вашем компьютере, а интерфейс поддерживает русский язык и UTF-8.</p>
<dl>
<dt>Версия</dt><dd id="version">—</dd>
<dt>Время UTC</dt><dd id="time">—</dd>
<dt>API</dt><dd><code>/api/health</code></dd>
</dl>
<button id="refresh">Обновить состояние</button>
<p><small>Базовое ядро · Python · HTTP API</small></p>
</main>
<script>
async function refresh(){
  try{
    const response=await fetch('/api/health',{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const data=await response.json();
    document.getElementById('state').textContent=data.status==='ok'?'Ядро работает':'Ошибка состояния';
    document.getElementById('version').textContent=data.version;
    document.getElementById('time').textContent=data.timestamp;
  }catch(error){document.getElementById('state').textContent='Нет связи с ядром';}
}
document.getElementById('refresh').addEventListener('click',refresh);
refresh();
</script>
</body>
</html>"""


class MiyoraHandler(BaseHTTPRequestHandler):
    server_version = "Miyora/" + VERSION

    def send_bytes(self, code: int, payload: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route in ("/", "/index.html"):
            self.send_bytes(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif route in ("/api/health", "/api/status"):
            result = {
                "name": APP_NAME,
                "version": VERSION,
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.send_bytes(200, json.dumps(result, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")
        elif route == "/api/db/health":
            try:
                self.send_json(200, database.health())
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        elif route == "/api/notes":
            try:
                self.send_json(200, {"notes": database.list_notes()})
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        else:
            self.send_bytes(404, b'{"error":"not_found"}', "application/json; charset=utf-8")

    def send_json(self, status: int, data: dict) -> None:
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/notes":
            self.send_json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 120000:
                self.send_json(413, {"error": "invalid_body_size"})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("expected JSON object")
            note = database.create_note(body.get("title"), body.get("content", ""))
            self.send_json(201, note)
        except (ValueError, UnicodeDecodeError) as exc:
            self.send_json(400, {"error": "invalid_request", "detail": str(exc)})
        except sqlite3.Error:
            self.send_json(503, {"error": "database_unavailable"})

    def do_DELETE(self) -> None:
        route = urlsplit(self.path).path
        if not route.startswith("/api/notes/"):
            self.send_json(404, {"error": "not_found"})
            return
        try:
            note_id = int(route.removeprefix("/api/notes/"))
            if note_id <= 0:
                raise ValueError("invalid id")
        except ValueError:
            self.send_json(400, {"error": "invalid_id"})
            return
        try:
            deleted = database.delete_note(note_id)
            self.send_json(200 if deleted else 404, {"deleted": deleted})
        except sqlite3.Error:
            self.send_json(503, {"error": "database_unavailable"})

    def log_message(self, fmt: str, *args: object) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)


def main() -> int:
    try:
        port = int(os.environ.get("PORT", "8000"))
        if not 0 <= port <= 65535:
            raise ValueError("Port outside allowed range")
    except ValueError:
        print("[ERROR] PORT must be an integer between 0 and 65535.", file=sys.stderr)
        return 2

    try:
        database.initialize()
        with ThreadingHTTPServer((HOST, port), MiyoraHandler) as server:
            server.daemon_threads = True
            actual_port = server.server_address[1]
            print(f"[INFO] Miyora Core {VERSION}", flush=True)
            print(f"[INFO] Project: {ROOT}", flush=True)
            print(f"[INFO] Open: http://{HOST}:{actual_port}/", flush=True)
            print("[INFO] Stop: Ctrl+C", flush=True)
            try:
                server.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                print("\n[INFO] Miyora stopped.", flush=True)
        return 0
    except (OSError, sqlite3.Error) as exc:
        print(f"[ERROR] Could not start local server: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
