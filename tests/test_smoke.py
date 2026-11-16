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

    def test_cloudru_settings_and_secret_not_exposed(self):
        from app.core import cloudru
        from urllib.error import HTTPError
        cloudru.clear_key()
        with urlopen(self.base + "/api/settings/cloudru") as response:
            settings = json.load(response)
        self.assertFalse(settings["has_key"])
        self.assertEqual(settings["base_url"], cloudru.BASE_URL)
        secret = "test-secret-cloudru-key-123"
        body = json.dumps({"api_key": secret, "model": "ai-sage/GigaChat3-10B-A1.8B"}).encode()
        request = Request(self.base + "/api/settings/cloudru", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            saved = json.load(response)
        self.assertTrue(saved["has_key"])
        self.assertEqual(saved["model"], "ai-sage/GigaChat3-10B-A1.8B")
        self.assertNotIn(secret, json.dumps(saved))
        self.assertEqual(cloudru._read_key(), secret)
        from urllib.error import HTTPError as UpstreamHTTPError
        with patch.object(cloudru, "urlopen", side_effect=UpstreamHTTPError(cloudru.BASE_URL, 401, "unauthorized", {}, None)):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base + "/api/settings/cloudru/models")
        self.assertEqual(error.exception.code, 400)
        request = Request(self.base + "/api/settings/cloudru", data=b'{"clear_key":true}',
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            self.assertFalse(json.load(response)["has_key"])
        self.assertFalse(cloudru._secret_path().exists())

    def test_cloudru_model_catalog(self):
        from app.core import cloudru
        from unittest.mock import MagicMock
        cloudru.save_key("test-cloudru-key")
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return b'{"data":[{"id":"provider/model-a"},{"id":"provider/model-b"}]}'
        with patch.object(cloudru, "urlopen", return_value=FakeResponse()) as mocked:
            data = cloudru.models()
            self.assertEqual(data["models"], ["provider/model-a", "provider/model-b"])
            request = mocked.call_args.args[0]
            self.assertEqual(request.full_url, cloudru.BASE_URL + "/models")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-cloudru-key")
        cloudru.clear_key()

    def test_cloudru_settings_markup(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        for token in ('id="settings-open"', 'id="settings-layer"',
                      'id="cloudru-key"', 'id="cloudru-model"',
                      'id="cloudru-load-models"', 'id="cloudru-save"'):
            self.assertIn(token, page)

    def test_home_connection_status(self):
        from app.core import cloudru
        cloudru.clear_key()
        with urlopen(self.base + "/api/status/connections") as response:
            data = json.load(response)
        self.assertEqual(data["system"], "online")
        self.assertEqual(data["api"], "not_configured")
        with urlopen(self.base + "/api/status/connections/check") as response:
            self.assertEqual(json.load(response)["api"], "not_configured")
        cloudru.save_key("test-status-cloudru-key")
        try:
            with patch.object(cloudru, "models", return_value={"models": ["test/model"]}):
                with urlopen(self.base + "/api/status/connections/check") as response:
                    self.assertEqual(json.load(response)["api"], "connected")
            with patch.object(cloudru, "models", side_effect=cloudru.CloudError("cloudru_auth_failed")):
                with urlopen(self.base + "/api/status/connections/check") as response:
                    self.assertEqual(json.load(response)["api"], "disconnected")
        finally:
            cloudru.clear_key()

    def test_header_controls_share_geometry(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn("One baseline and consistent control geometry across the header.", page)
        self.assertIn("height:42px;min-height:42px", page)
        self.assertIn("header .right .home-status", page)
        self.assertIn("@media(max-width:690px)", page)

    def test_home_status_icons(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn('id="system-status"', page)
        self.assertIn('id="api-status"', page)
        self.assertIn('/api/status/connections/check', page)
        self.assertIn('Cloud.ru API', page)

    def test_chat_ui(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        for token in ('id="chat-app"', 'id="chat-form"', 'id="chat-input"',
                      'id="chat-new"', 'id="chat-messages"', '/api/chat'):
            self.assertIn(token, page)

    def test_chat_endpoint_validation_and_completion(self):
        from app.core import cloudru, chat
        from urllib.error import HTTPError
        def post(messages):
            data = json.dumps({"messages": messages}).encode("utf-8")
            request = Request(self.base + "/api/chat", data=data,
                              headers={"Content-Type": "application/json"})
            return urlopen(request)
        with self.assertRaises(HTTPError) as error:
            post([{"role": "system", "content": "bad"}])
        self.assertEqual(error.exception.code, 400)
        cloudru.clear_key()
        with self.assertRaises(HTTPError) as error:
            post([{"role": "user", "content": "Hello"}])
        self.assertEqual(error.exception.code, 400)
        cloudru.save_key("test-chat-api-key")
        cloudru.set_model("test-chat-model")
        try:
            class FakeResponse:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, *_): return b'{"choices":[{"message":{"content":"Hello from model"}}]}'
            with patch.object(chat, "urlopen", return_value=FakeResponse()) as mocked:
                with post([{"role": "user", "content": "Hello"}]) as response:
                    result = json.load(response)
                self.assertEqual(result["message"], "Hello from model")
                self.assertEqual(result["model"], "test-chat-model")
                upstream = mocked.call_args.args[0]
                self.assertEqual(upstream.full_url, cloudru.BASE_URL + "/chat/completions")
                self.assertEqual(upstream.get_header("Authorization"), "Bearer test-chat-api-key")
        finally:
            cloudru.clear_key()
            cloudru.set_model("")

    def test_persistent_chat_store(self):
        from app.core import chat_store
        chat_store.initialize()
        thread=chat_store.create_thread("Test chat")
        self.assertIn(thread["id"],[t["id"] for t in chat_store.list_threads()])
        chat_store.append(thread["id"],"user","Question")
        chat_store.append(thread["id"],"assistant","Answer")
        self.assertEqual([m["content"] for m in chat_store.messages(thread["id"])],["Question","Answer"])
        self.assertTrue(chat_store.rename(thread["id"],"Renamed"))
        self.assertTrue(chat_store.delete(thread["id"]))
        self.assertIsNone(chat_store.messages(thread["id"]))

    def test_chat_history_api(self):
        def request(path,method="GET",body=None):
            req=Request(self.base+path,method=method,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={"Content-Type":"application/json"})
            with urlopen(req) as response: return json.load(response)
        created=request("/api/chats","POST",{"title":"API test"})
        thread_id=created["id"]
        self.assertTrue(any(t["id"]==thread_id for t in request("/api/chats")["threads"]))
        self.assertEqual(request("/api/chats/"+str(thread_id))["messages"],[])
        self.assertTrue(request("/api/chats/"+str(thread_id),"PUT",{"title":"Updated"})["updated"])
        self.assertTrue(request("/api/chats/"+str(thread_id),"DELETE")["deleted"])

    def test_neural_graph_from_sqlite(self):
        from app.core import chat_store
        chat_store.initialize()
        thread = chat_store.create_thread("Neural graph")
        tid = thread["id"]
        self.assertEqual(chat_store.graph(tid)["nodes"], [])
        chat_store.append(tid, "user", "First question")
        chat_store.append(tid, "assistant", "First answer")
        chat_store.append(tid, "user", "Follow-up")
        data = chat_store.graph(tid)
        self.assertEqual(data["source"], "sqlite_messages")
        self.assertEqual([n["role"] for n in data["nodes"]], ["user", "assistant", "user"])
        self.assertEqual([n["label"] for n in data["nodes"]], ["First question", "First answer", "Follow-up"])
        self.assertEqual(len(data["edges"]), 2)
        self.assertEqual(data["edges"][0]["source"], data["nodes"][0]["id"])
        self.assertEqual(data["edges"][0]["target"], data["nodes"][1]["id"])
        self.assertEqual(len(chat_store.graph(tid, limit=2)["nodes"]), 2)
        self.assertIsNone(chat_store.graph(99999999))
        self.assertTrue(chat_store.delete(tid))
        self.assertIsNone(chat_store.graph(tid))

    def test_neural_graph_api(self):
        from urllib.error import HTTPError
        from app.core import chat_store
        chat_store.initialize()
        tid = chat_store.create_thread("Graph API")["id"]
        chat_store.append(tid, "user", "Persistent node")
        with urlopen(self.base + "/api/chats/%s/graph" % tid) as response:
            data = json.load(response)
        self.assertEqual(data["nodes"][0]["label"], "Persistent node")
        self.assertEqual(data["thread_id"], tid)
        for invalid, code in [("/api/chats/999999999/graph", 404),
                              ("/api/chats/invalid/graph", 400)]:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base + invalid)
            self.assertEqual(error.exception.code, code)
        chat_store.delete(tid)

    def test_neural_workspace_markup(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for marker in ('id="neural-canvas"', 'id="neural-viewport"',
                       'id="neural-zoom-in"', 'id="neural-zoom-out"',
                       'id="neural-reset"', 'id="neural-node-list"',
                       'grid-template-columns:minmax(0,3fr) minmax(340px,2fr)',
                       'miyora:focus-message', 'miyora:thread',
                       'miyora:activity', 'ResizeObserver',
                       'pointerdown', 'pointermove', 'wheel',
                       '@media(max-width:690px)'):
            self.assertIn(marker, html)

    def test_neural_visualization_modes(self):
        from app.core import chat_store
        chat_store.initialize()
        tid = chat_store.create_thread("Modes")["id"]
        chat_store.append(tid, "user", "inspectable " + "x" * 4500)
        result = chat_store.graph(tid)
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(len(result["nodes"][0]["content"]), 4000)
        self.assertTrue(result["nodes"][0]["content"].startswith("inspectable"))
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for marker in ('data-neural-mode="radial"', 'data-neural-mode="links"',
                       'data-neural-mode="hex"', 'data-neural-mode="overview"',
                       'id="neural-inspector"', 'id="neural-inspector-open"',
                       "function hexagon(", "function zoomAt(",
                       "prefers-reduced-motion: reduce", "stage:'подготовка'",
                       "stage:'запрос'", "stage:'ответ'",
                       "aria-pressed", "miyora:focus-message"):
            self.assertIn(marker, html)
        self.assertTrue(chat_store.delete(tid))

    def test_neural_knowledge_clusters_and_links(self):
        from app.core import chat_store
        chat_store.initialize()
        tid = chat_store.create_thread("Knowledge graph")["id"]
        try:
            chat_store.append(tid, "user", "sqlite graph visual connections")
            chat_store.append(tid, "assistant", "sqlite graph persistence connections")
            chat_store.append(tid, "user", "unrelated weather forecast")
            graph = chat_store.graph(tid)
            self.assertEqual(graph["relation_method"], "chronology_and_shared_lexical_terms")
            self.assertEqual(len(graph["clusters"]), 2)
            self.assertEqual(len(graph["nodes"]), 3)
            self.assertEqual(len([e for e in graph["edges"] if e["type"] == "sequence"]), 2)
            lexical = [e for e in graph["edges"] if e["type"] == "shared_terms"]
            self.assertTrue(lexical)
            self.assertIn("sqlite", lexical[0]["terms"])
            self.assertIn("graph", lexical[0]["terms"])
            self.assertEqual(sum(len(group["node_ids"]) for group in graph["clusters"]), 3)
            with urlopen(self.base + "/") as response:
                html = response.read().decode("utf-8")
            for marker in ("Hierarchical rings", "graph.clusters", "transition={from:before",
                           "shared_terms", "stage:'синхронизация'"):
                self.assertIn(marker, html)
        finally:
            chat_store.delete(tid)

    def test_mizuyori_brain_layout_port(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for marker in ('data-neural-mode="radial"', 'data-neural-mode="hex"',
                       'data-neural-mode="circle"', 'data-neural-mode="board"',
                       'data-neural-mode="hud"', 'function sections()',
                       'function layout()', 'Mizuyori mizuyori/static/brain.js',
                       'section.sector', 'section.hex', 'section.board',
                       'section.hud', 'Math.sqrt(s.nodes.length)',
                       'if(!reduced)', 'miyora:focus-message'):
            self.assertIn(marker, html)

    def test_mizuyori_visual_design(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for token in ('id="neural-theme"', 'data-mz-theme="dark"',
                      'value="gold"', 'value="amber"', 'value="jade"',
                      'miyora-neural-theme', 'allowedThemes',
                      '--mz-accent', 'backdrop-filter:blur(14px)',
                      'prefers-reduced-motion:reduce',
                      'grid-template-columns:minmax(0,3fr) minmax(340px,2fr)'):
            self.assertIn(token, html)

    def test_mizuyori_motion_and_floating_controls(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for token in ('id="mz-panel-toggle"', 'id="mz-floating-panel"',
                      'id="mz-camera-speed"', 'id="mz-signals"',
                      'id="mz-center"', 'targetCamera', 'cameraSpeed',
                      'signalsEnabled', 'const smooth=reduced?1:cameraSpeed',
                      'aria-expanded', 'prefers-reduced-motion:reduce'):
            self.assertIn(token, html)

    def test_neural_graph_intelligence(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        for token in ('id="mz-graph-search"', 'id="mz-physics"',
                      'id="mz-context-filter"', 'id="mz-context-note"',
                      'function neighborhood(id)', 'function springStep(dt)',
                      'function updateSearch()', 'function focusNode(p)',
                      'const aggregate=zoom<.48', 'const faded=id=>',
                      'ctx.globalAlpha=.14', 'physicsMoving'):
            self.assertIn(token, html)

    def test_streaming_provider(self):
        from app.core import cloudru,chat
        cloudru.save_key("test-stream-key")
        cloudru.set_model("stream-model")
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def __iter__(self):
                return iter([b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n',
                             b'data: {"choices":[{"delta":{"content":"!"}}]}\n',
                             b'data: [DONE]\n'])
        try:
            with patch.object(chat,"urlopen",return_value=FakeResponse()) as mocked:
                self.assertEqual("".join(chat.stream([{"role":"user","content":"Hello"}])),"Hi!")
                self.assertTrue(json.loads(mocked.call_args.args[0].data)["stream"])
        finally:
            cloudru.clear_key()
            cloudru.set_model("")

    def test_chat_markdown_ui(self):
        with urlopen(self.base+"/") as response:
            page=response.read().decode()
        for marker in ("renderMarkdown(", "chat-copy-code", "chat-token-keyword",
                       "chat-thread-action", "getReader()", "Остановить генерацию"):
            self.assertIn(marker,page)

    def test_homepage(self):
        with urlopen(self.base + "/") as response:
            self.assertIn(b"Miyora", response.read())

if __name__ == "__main__":
    unittest.main()
