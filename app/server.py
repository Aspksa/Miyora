# -*- coding: utf-8 -*-
"""Miyora Core: lightweight local web application (Python standard library)."""
from __future__ import annotations

import json
import sqlite3
from app.core import database, explorer, file_search, cloudru, chat
import os
import socket
import sys
import webbrowser
import logging
import threading
import time
from urllib.request import urlopen
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

APP_NAME = "Miyora"
VERSION = "0.2.0"
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"

PAGE_PATH = Path(getattr(sys, "_MEIPASS", ROOT)) / "web" / "index.html"
FAVICON_PATH = PAGE_PATH.with_name("favicon.svg")
LOG_PATH = ROOT / "data" / "miyora.log"

def configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")

def open_browser(url: str) -> bool:
    """Prefer the Windows default browser; fall back to Python's browser module."""
    if sys.platform == "win32":
        try:
            os.startfile(url)
            return True
        except OSError:
            logging.exception("Windows default browser launch failed")
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        logging.exception("Python browser launch failed")
        return False


def verify_and_open(url: str) -> None:
    for _ in range(30):
        try:
            with urlopen(url + "api/health", timeout=1.5) as response:
                if response.status == 200 and json.load(response).get("status") == "ok":
                    logging.info("HTTP health check passed: %s", url)
                    print("[INFO] HTTP health check passed.", flush=True)
                    if open_browser(url):
                        print("[INFO] Browser open requested: " + url, flush=True)
                        return
                    print("[WARN] Open manually: " + url, flush=True)
                    logging.warning("Could not open browser: %s", url)
                    return
        except Exception:
            time.sleep(0.3)
    print("[ERROR] HTTP health check failed: " + url, flush=True)
    logging.error("HTTP health check failed: %s", url)


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
            try:
                self.send_bytes(200, PAGE_PATH.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                logging.exception("Web interface not found: %s", PAGE_PATH)
                self.send_json(503, {"error": "web_interface_unavailable"})
        elif route in ("/favicon.svg", "/favicon.ico"):
            try:
                self.send_bytes(200, FAVICON_PATH.read_bytes(), "image/svg+xml")
            except OSError:
                self.send_bytes(204, b"", "image/svg+xml")
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
        elif route == "/api/db/stats":
            self.send_json(200, database.stats())
        elif route == "/api/explorer/overview":
            try:
                self.send_json(200, explorer.overview(ROOT))
            except (OSError, sqlite3.Error):
                self.send_json(503, {"error": "explorer_unavailable"})
        elif route == "/api/explorer/tables":
            try:
                self.send_json(200, {"tables": explorer.tables()})
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        elif route == "/api/explorer/rows":
            try:
                params = parse_qs(urlsplit(self.path).query)
                self.send_json(200, explorer.table_rows(
                    params.get("table", [""])[0],
                    int(params.get("offset", ["0"])[0]),
                    int(params.get("limit", ["30"])[0])))
            except (ValueError, OverflowError):
                self.send_json(400, {"error": "invalid_table_or_pagination"})
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        elif route == "/api/explorer/file":
            try:
                params = parse_qs(urlsplit(self.path).query)
                self.send_json(200, file_search.preview(ROOT, params.get("path", [""])[0]))
            except file_search.InvalidFile as exc:
                self.send_json(400, {"error": str(exc)})
            except OSError:
                self.send_json(404, {"error": "file_unavailable"})
        elif route == "/api/search":
            try:
                params = parse_qs(urlsplit(self.path).query)
                self.send_json(200, file_search.search(ROOT, params.get("q", [""])[0],
                                                       int(params.get("limit", ["50"])[0])))
            except (ValueError, OverflowError):
                self.send_json(400, {"error": "invalid_search"})
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        elif route == "/api/status/connections":
            try:
                configured = cloudru.settings()
                self.send_json(200, {"system": "online", "api": "configured" if configured["has_key"] else "not_configured",
                                     "model": configured["model"]})
            except (cloudru.CloudError, sqlite3.Error, OSError):
                self.send_json(503, {"system": "online", "api": "error"})
        elif route == "/api/status/connections/check":
            try:
                configured = cloudru.settings()
                if not configured["has_key"]:
                    self.send_json(200, {"api": "not_configured"})
                else:
                    cloudru.models()
                    self.send_json(200, {"api": "connected", "model": configured["model"]})
            except cloudru.CloudError as exc:
                self.send_json(200, {"api": "disconnected", "reason": str(exc)})
            except (sqlite3.Error, OSError):
                self.send_json(503, {"api": "error"})
        elif route == "/api/settings/cloudru":
            try:
                self.send_json(200, cloudru.settings())
            except cloudru.CloudError as exc:
                self.send_json(503, {"error": str(exc)})
        elif route == "/api/settings/cloudru/models":
            try:
                self.send_json(200, cloudru.models())
            except cloudru.CloudError as exc:
                self.send_json(400, {"error": str(exc)})
        elif route == "/api/notes":
            try:
                params = parse_qs(urlsplit(self.path).query)
                self.send_json(200, {"notes": database.list_notes(search=params.get("search", [""])[0][:200], include_deleted=params.get("deleted", ["0"])[0] == "1")})
            except sqlite3.Error:
                self.send_json(503, {"error": "database_unavailable"})
        else:
            self.send_bytes(404, b'{"error":"not_found"}', "application/json; charset=utf-8")

    def send_json(self, status: int, data: dict) -> None:
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def _trusted_write(self) -> bool:
        host = self.headers.get("Host", "")
        allowed = {"127.0.0.1", "localhost"}
        if host.split(":")[0].lower() not in allowed:
            self.send_json(403, {"error": "invalid_host"})
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in allowed or parsed.netloc != host:
                self.send_json(403, {"error": "invalid_origin"})
                return False
        return True

    def do_POST(self) -> None:
        if not self._trusted_write():
            return
        if urlsplit(self.path).path == "/api/chat":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 400000:
                    self.send_json(413, {"error": "invalid_body_size"})
                    return
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict) or set(body) != {"messages"}:
                    raise ValueError("invalid_chat_request")
                self.send_json(200, chat.complete(body["messages"]))
            except (ValueError, UnicodeError, json.JSONDecodeError, cloudru.CloudError) as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if urlsplit(self.path).path == "/api/settings/cloudru":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("invalid_body_size")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict) or set(body) - {"api_key", "model", "clear_key"}:
                    raise ValueError("invalid_settings")
                if body.get("clear_key") is True:
                    cloudru.clear_key()
                if "api_key" in body and body["api_key"]:
                    cloudru.save_key(body["api_key"])
                if "model" in body:
                    cloudru.set_model(body["model"])
                self.send_json(200, cloudru.settings())
            except (ValueError, UnicodeError, json.JSONDecodeError, cloudru.CloudError):
                self.send_json(400, {"error": "invalid_cloudru_settings"})
            return
        if urlsplit(self.path).path == "/api/db/backup":
            try:
                self.send_json(201, {"backup": str(database.backup())})
            except (OSError, sqlite3.Error, ValueError):
                logging.exception("Backup failed")
                self.send_json(500, {"error": "backup_failed"})
            return
        if urlsplit(self.path).path.startswith("/api/notes/") and urlsplit(self.path).path.endswith("/restore"):
            try:
                note_id = int(urlsplit(self.path).path.split("/")[3])
                self.send_json(200, {"restored": database.restore_note(note_id)})
            except (ValueError, sqlite3.Error):
                self.send_json(400, {"error": "invalid_id"})
            return
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

    def do_PUT(self) -> None:
        if not self._trusted_write():
            return
        route = urlsplit(self.path).path
        if not route.startswith("/api/notes/"):
            self.send_json(404, {"error": "not_found"})
            return
        try:
            note_id = int(route.removeprefix("/api/notes/"))
            length = int(self.headers.get("Content-Length", "0"))
            if note_id <= 0 or not 0 < length <= 120000:
                raise ValueError("invalid request")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("expected JSON object")
            note = database.update_note(note_id, body.get("title"), body.get("content", ""))
            self.send_json(200 if note else 404, note or {"error": "not_found"})
        except (ValueError, UnicodeDecodeError, sqlite3.Error):
            self.send_json(400, {"error": "invalid_request"})

    def do_DELETE(self) -> None:
        if not self._trusted_write():
            return
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
        configure_logging()
        database.initialize()
        with ThreadingHTTPServer((HOST, port), MiyoraHandler) as server:
            server.daemon_threads = True
            actual_port = server.server_address[1]
            print(f"[INFO] Miyora Core {VERSION}", flush=True)
            print(f"[INFO] Project: {ROOT}", flush=True)
            print(f"[INFO] Open: http://{HOST}:{actual_port}/", flush=True)
            print("[INFO] Stop: Ctrl+C", flush=True)
            url = f"http://{HOST}:{actual_port}/"
            logging.info("Server started: %s", url)
            threading.Thread(target=verify_and_open, args=(url,), daemon=True).start()
            try:
                server.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                print("\n[INFO] Miyora stopped.", flush=True)
        return 0
    except (OSError, sqlite3.Error) as exc:
        logging.exception("Startup failed")
        print(f"[ERROR] Could not start local server: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        configure_logging()
        logging.exception("Unhandled error")
        raise
