"""Miyora smoke tests: python -m unittest discover -s tests -v"""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

class MiyoraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["MIYORA_DB_PATH"] = str(Path(cls.temp.name) / "test.db")
        import database
        import main
        from app.core import database as core_database
        from app import server as app_server
        cls.core_database = core_database
        cls.app_server = app_server
        cls.database = database
        cls.database.initialize()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), main.MiyoraHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%s" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def test_modular_structure(self):
        import database
        import main
        self.assertIs(main.MiyoraHandler, self.app_server.MiyoraHandler)
        self.assertIs(database.initialize, self.core_database.initialize)
        self.assertEqual(self.app_server.PAGE_PATH.parent.name, 'web')
        self.assertTrue(self.app_server.PAGE_PATH.is_file())

    def test_health(self):
        with urlopen(self.base + "/api/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")

    def test_database(self):
        with urlopen(self.base + "/api/db/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")

    def test_notes_lifecycle_unicode(self):
        body = json.dumps({"title": "Привет", "content": "Тест"}).encode("utf-8")
        request = Request(self.base + "/api/notes", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            note = json.load(response)
        self.assertEqual(note["title"], "Привет")
        with urlopen(self.base + "/api/notes") as response:
            notes = json.load(response)["notes"]
        self.assertTrue(any(n["id"] == note["id"] for n in notes))
        request = Request(self.base + "/api/notes/" + str(note["id"]), method="DELETE")
        with urlopen(request) as response:
            self.assertTrue(json.load(response)["deleted"])

    def test_database_backup_and_trash(self):
        from app.core import database as db
        note = db.create_note("Резервная", "содержимое")
        self.assertGreaterEqual(db.stats()["total"], 1)
        self.assertTrue(db.delete_note(note["id"]))
        self.assertFalse(any(n["id"] == note["id"] for n in db.list_notes()))
        self.assertTrue(any(n["id"] == note["id"] for n in db.list_notes(include_deleted=True)))
        self.assertTrue(db.restore_note(note["id"]))
        self.assertEqual(db.update_note(note["id"], "Обновлено")["title"], "Обновлено")
        target = db.backup()
        self.assertTrue(target.is_file())
        import sqlite3
        with sqlite3.connect(str(target)) as backup_db:
            self.assertEqual(backup_db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup_db.execute("SELECT title FROM notes WHERE id=?", (note["id"],)).fetchone()[0], "Обновлено")

    def test_database_api_stats_and_search(self):
        with urlopen(self.base + "/api/db/stats") as response:
            self.assertIn("schema_version", json.load(response))
        with urlopen(self.base + "/api/notes?search=does-not-exist-123456") as response:
            self.assertEqual(json.load(response)["notes"], [])

    def test_cross_origin_write_blocked(self):
        from urllib.error import HTTPError
        request = Request(self.base + "/api/db/backup", data=b"",
                          headers={"Origin": "https://evil.example"}, method="POST")
        with self.assertRaises(HTTPError) as exc:
            urlopen(request)
        self.assertEqual(exc.exception.code, 403)

    def test_browser_fallback(self):
        from app import server as app_server
        with patch.object(app_server.sys, "platform", "win32"):
            with patch.object(app_server.os, "startfile", create=True, side_effect=OSError("blocked")):
                with patch.object(app_server.webbrowser, "open", return_value=True) as fallback:
                    self.assertTrue(app_server.open_browser("http://127.0.0.1:8000/"))
                    fallback.assert_called_once()

    def test_browser_windows_default(self):
        from app import server as app_server
        with patch.object(app_server.sys, "platform", "win32"):
            with patch.object(app_server.os, "startfile", create=True) as start:
                with patch.object(app_server.webbrowser, "open") as fallback:
                    self.assertTrue(app_server.open_browser("http://127.0.0.1:8000/"))
                    start.assert_called_once()
                    fallback.assert_not_called()

    def test_favicon(self):
        with urlopen(self.base + "/favicon.svg") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("image/svg+xml", response.headers["Content-Type"])
            self.assertIn(b"<svg", response.read())
        with urlopen(self.base + "/favicon.ico") as response:
            self.assertEqual(response.status, 200)

    def test_homepage(self):
        with urlopen(self.base + "/") as response:
            self.assertIn(b"Miyora", response.read())

if __name__ == "__main__":
    unittest.main()
