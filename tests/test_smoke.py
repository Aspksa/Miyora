"""Miyora smoke tests: python -m unittest discover -s tests -v"""
import json
from contextlib import closing
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

    def test_doctor_closes_sqlite_before_cleanup(self):
        import doctor
        import io
        from contextlib import redirect_stdout
        output = io.StringIO()
        with redirect_stdout(output):
            code = doctor.run()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0, result)
        self.assertTrue(result["checks"]["sqlite:write_read"])

    def test_modular_structure(self):
        import database
        import main
        self.assertIs(main.MiyoraHandler, self.app_server.MiyoraHandler)
        self.assertIs(database.initialize, self.core_database.initialize)
        self.assertEqual(self.app_server.PAGE_PATH.parent.name, 'web')
        self.assertTrue(self.app_server.PAGE_PATH.is_file())

    def test_explorer_api(self):
        from urllib.error import HTTPError
        with urlopen(self.base + "/api/explorer/overview") as response:
            overview = json.load(response)
        self.assertIn("project", overview)
        self.assertIn("database_files", overview)
        with urlopen(self.base + "/api/explorer/tables") as response:
            tables = json.load(response)["tables"]
        names = [item["name"] for item in tables]
        self.assertIn("notes", names)
        self.assertIn("settings", names)
        with urlopen(self.base + "/api/explorer/rows?table=notes&limit=2") as response:
            rows = json.load(response)
        self.assertIn("title", rows["columns"])
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/api/explorer/rows?table=sqlite_master")
        self.assertEqual(error.exception.code, 400)

    def test_explorer_rejects_symlink_traversal(self):
        from app.core.explorer import project_tree
        root = Path(self.temp.name) / "project"
        root.mkdir(exist_ok=True)
        (root / "visible.txt").write_text("hello", encoding="utf-8")
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = root / "escape"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pass
        result = project_tree(root)
        names = [x["name"] for x in result["children"]]
        self.assertIn("visible.txt", names)
        self.assertNotIn("escape", names)

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
        with closing(sqlite3.connect(str(target))) as backup_db:
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

    def test_knowledge_window_markup(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn('id="kb-open"', page)
        self.assertIn('id="kb-layer"', page)
        self.assertIn('role="dialog"', page)
        self.assertIn('aria-modal="true"', page)
        self.assertIn('id="kb-handle"', page)
        self.assertIn('resize:both', page)
        self.assertIn("setPointerCapture", page)
        self.assertIn("max-width:100vw", page)

    def test_database_moved_into_knowledge_window(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        homepage = page.split('<div id="kb-layer"', 1)[0]
        knowledge = page.split('<div id="kb-layer"', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('class="db-panel"', homepage)
        self.assertNotIn('id="db-form"', homepage)
        self.assertIn('id="db-form"', knowledge)
        self.assertIn('id="kb-tree"', knowledge)
        self.assertIn('id="kb-tables"', knowledge)
        self.assertIn('id="db-list"', knowledge)
        self.assertIn('id="kb-refresh-all"', knowledge)

    def test_file_preview_and_search(self):
        from app.core import file_search
        from urllib.error import HTTPError
        root = Path(self.temp.name) / "search-fixtures"
        root.mkdir(exist_ok=True)
        (root / "hello.py").write_text("def hello():\n    return 'УникальныйПоиск'\n", encoding="utf-8")
        (root / "secret.bin").write_bytes(b"\x00\x01")
        (root / ".env").write_text("УникальныйПоиск=secret", encoding="utf-8")
        result = file_search.preview(root, "hello.py")
        self.assertIn("УникальныйПоиск", result["content"])
        self.assertEqual(result["lines"], 3)
        with self.assertRaises(file_search.InvalidFile):
            file_search.preview(root, "../test.db")
        with self.assertRaises(file_search.InvalidFile):
            file_search.preview(root, ".env")
        with self.assertRaises(file_search.InvalidFile):
            file_search.preview(root, "secret.bin")
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("outside", encoding="utf-8")
        link = root / "escape.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(file_search.InvalidFile):
                file_search.preview(root, "escape.py")
        found = file_search.search(root, "УникальныйПоиск")
        self.assertTrue(any(r["type"] == "file" and r["path"] == "hello.py" for r in found["results"]))
        self.assertFalse(any(r.get("path") == ".env" for r in found["results"]))
        with patch.object(self.app_server, "ROOT", root):
            with urlopen(self.base + "/api/explorer/file?path=hello.py") as response:
                self.assertIn("УникальныйПоиск", json.load(response)["content"])
            with urlopen(self.base + "/api/search?q=%D0%A3%D0%BD%D0%B8%D0%BA%D0%B0%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9%D0%9F%D0%BE%D0%B8%D1%81%D0%BA") as response:
                self.assertTrue(json.load(response)["results"])
            with self.assertRaises(HTTPError) as err:
                urlopen(self.base + "/api/explorer/file?path=..%2Ftest.db")
            self.assertEqual(err.exception.code, 400)
            with self.assertRaises(HTTPError) as err:
                urlopen(self.base + "/api/search?q=a")
            self.assertEqual(err.exception.code, 400)

    def test_search_preview_markup(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        for element in ('id="kb-global-query"', 'id="kb-search-results"',
                        'id="kb-preview-code"', 'function kbHighlight',
                        'function kbOpenFile', 'function kbRunSearch'):
            self.assertIn(element, page)

    def test_minimal_knowledge_layout(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn('id="kb-advanced"', page)
        self.assertIn('<summary>Дополнительно', page)
        self.assertIn('id="kb-global-query"', page)
        self.assertIn('id="kb-preview-code"', page)
        workspace = page.split('<div class="kb-workspace">', 1)[1].split('<details class="kb-advanced"', 1)[0]
        self.assertIn('id="kb-tree"', workspace)
        self.assertIn('id="db-form"', workspace)
        self.assertNotIn('class="kb-data-section"', workspace)
        advanced = page.split('<details class="kb-advanced"', 1)[1]
        self.assertIn('id="kb-tables"', advanced)
        self.assertIn('id="kb-dbsize"', advanced)

    def test_homepage(self):
        with urlopen(self.base + "/") as response:
            self.assertIn(b"Miyora", response.read())

if __name__ == "__main__":
    unittest.main()
