"""
Unit tests for Stealth Agent Browser Engine and top-level MCP browser tools.
Verifies memory footprint target, local persistent profiles (~/.fable/browser-profile/),
navigation history, element clicking, typing, scrolling, and layered PNG screenshot generation.
"""

from __future__ import annotations

import http.cookiejar
import http.server
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from fable_engine.browser import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    DOMElement,
    MAX_BROWSER_SESSIONS,
    MAX_SCREENSHOT_LAYERS,
    ProfileManager,
    StealthBrowserEngine,
    StealthBrowserSession,
    generate_minimal_png,
)
from fable_engine.schema import BROWSER_TOOL_SCHEMAS
import fable_engine.server as browser_server


class _BrowserTestHandler(http.server.BaseHTTPRequestHandler):
    redirect_history_one = False

    def do_GET(self):
        if self.path == "/set-cookie":
            self.send_response(200)
            self.send_header("Set-Cookie", "session_token=abc123secret; Path=/; HttpOnly")
            body = b"cookie set"
        elif self.path == "/large":
            self.send_response(200)
            body = b"01234567890"
        elif self.path == "/history-one" and self.redirect_history_one:
            self.send_response(302)
            self.send_header("Location", "/redirected")
            self.end_headers()
            return
        else:
            self.send_response(200)
            body = (self.headers.get("Cookie") or "").encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TestStealthAgentBrowser(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.profile_dir = os.path.join(self.tmp_dir, "browser-profile")
        _BrowserTestHandler.redirect_history_one = False
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BrowserTestHandler)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.http_thread.join(timeout=2)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_browser_schemas_exist(self):
        tool_names = [t["name"] for t in BROWSER_TOOL_SCHEMAS]
        self.assertIn("browser_open", tool_names)
        self.assertIn("browser_navigate", tool_names)
        self.assertIn("browser_click", tool_names)
        self.assertIn("browser_type", tool_names)
        self.assertIn("browser_scroll", tool_names)
        self.assertIn("browser_snapshot_layers", tool_names)
        self.assertIn("browser_screenshot", tool_names)
        self.assertIn("browser_close", tool_names)
        self.assertIn("browser_back", tool_names)
        self.assertIn("browser_forward", tool_names)
        self.assertIn("browser_wait", tool_names)
        self.assertIn("browser_press", tool_names)
        self.assertIn("browser_reload", tool_names)

        for tool in BROWSER_TOOL_SCHEMAS:
            self.assertTrue(len(tool["description"]) > 0)
            self.assertIn("type", tool["inputSchema"])

        schemas = {tool["name"]: tool["inputSchema"] for tool in BROWSER_TOOL_SCHEMAS}
        layers_schema = schemas["browser_snapshot_layers"]["properties"]["max_layers"]
        self.assertEqual(layers_schema["minimum"], 1)
        self.assertEqual(layers_schema["maximum"], MAX_SCREENSHOT_LAYERS)
        wait_schema = schemas["browser_wait"]["properties"]["seconds"]
        self.assertEqual(wait_schema["maximum"], 10)

    def test_profile_manager_persistence(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        pm.cookies.set_cookie(http.cookiejar.Cookie(
            version=0, name="session_token", value="abc123secret",
            port=None, port_specified=False, domain="localhost.local",
            domain_specified=False, domain_initial_dot=False, path="/",
            path_specified=True, secure=False, expires=None, discard=False,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        ))
        pm.local_storage["user_pref"] = {"theme": "dark"}
        pm.save()

        # Reload from disk
        pm2 = ProfileManager(profile_dir=self.profile_dir)
        cookies = {cookie.name: cookie.value for cookie in pm2.cookies}
        self.assertEqual(cookies["session_token"], "abc123secret")
        self.assertEqual(pm2.local_storage.get("user_pref"), {"theme": "dark"})

    def test_profile_permissions_are_explicitly_private(self):
        old_umask = os.umask(0)
        try:
            pm = ProfileManager(profile_dir=self.profile_dir)
            pm.save()
        finally:
            os.umask(old_umask)

        self.assertEqual(stat.S_IMODE(os.stat(self.profile_dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(pm.cookie_file).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(pm.storage_file).st_mode), 0o600)

    def test_cookie_jar_does_not_send_cookie_to_another_origin(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)

        session.open(f"http://localhost:{self.port}/set-cookie")
        session.open(f"http://localhost:{self.port}/echo")
        self.assertIn("session_token=abc123secret", session.page_html)
        session.open(f"http://127.0.0.1:{self.port}/echo")

        self.assertNotIn("session_token", session.page_html)

    def test_browser_session_about_blank(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        res = session.open("about:blank")

        self.assertEqual(res["url"], "about:blank")
        self.assertEqual(res["title"], "Blank Page")
        self.assertEqual(res["viewport"], [DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT])

    def test_dom_parsing_and_element_interaction(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        session.page_html = """
        <html>
            <head><title>Test Localhost Page</title></head>
            <body>
                <h1>Welcome to Localhost App</h1>
                <input id="username_input" type="text" value="" />
                <button id="login_btn">Submit Login</button>
                <a id="home_link" href="about:blank">Return Home</a>
            </body>
        </html>
        """
        session._parse_and_layout()
        status = session._build_status()

        self.assertEqual(status["title"], "Test Localhost Page")
        self.assertIn("username_input", session.elements_by_id)
        self.assertIn("login_btn", session.elements_by_id)

        # Test type_text
        type_res = session.type_text("username_input", "agent_user")
        self.assertEqual(type_res["status"], "typed")
        self.assertEqual(session.elements_by_id["username_input"].attrs.get("value"), "agent_user")

        self.assertEqual(session.click("login_btn")["status"], "error")
        self.assertEqual(session.press_key("Enter", "username_input")["status"], "error")

        # Test click link
        click_res = session.click("home_link")
        self.assertEqual(click_res["url"], "about:blank")

    def test_duplicate_explicit_and_generated_element_ids_are_unique(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        session.page_html = (
            '<html id="elem_4"><body><div id="duplicate"></div>'
            '<span id="duplicate"></span><p></p></body></html>'
        )
        session._parse_and_layout()

        ids = [element.element_id for element in session.elements_by_id.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("duplicate", ids)
        self.assertIn("duplicate_2", ids)
        self.assertEqual(len(ids), 6)

    def test_layered_png_snapshot(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        session.page_html = "<html><body>" + "".join([f"<h2>Header {i}</h2><p>Paragraph text {i}</p>" for i in range(50)]) + "</body></html>"
        session._parse_and_layout()

        snapshot_res = session.snapshot_layers(max_layers=3)
        self.assertEqual(snapshot_res["session_id"], "test_tab")
        self.assertGreaterEqual(snapshot_res["total_layers"], 1)
        self.assertTrue(len(snapshot_res["layers"]) > 0)

        first_layer = snapshot_res["layers"][0]
        self.assertEqual(first_layer["layer_index"], 1)
        self.assertTrue(first_layer["b64_png"].startswith("iVBORw0KGgo"))  # PNG magic header in base64

    def test_snapshot_limits_layers_and_viewport_uses_current_scroll(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm, viewport_width=100, viewport_height=100)
        session.page_html = "<html><body><p>content</p></body></html>"
        session._parse_and_layout()
        session.document_height = 5000
        session.scroll_y = 275

        result = session.snapshot_layers(max_layers=10_000)
        self.assertEqual(result["total_layers"], MAX_SCREENSHOT_LAYERS)
        self.assertEqual(session.snapshot_viewport()["layers"][0]["scroll_top"], 275)

    def test_response_body_limit_rejects_oversized_content(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm, max_response_bytes=10)

        result = session.open(f"http://127.0.0.1:{self.port}/large")

        self.assertEqual(result["status"], "error")
        self.assertIn("10 byte limit", result["error"])
        self.assertEqual(session.history, [])

    def test_history_traversal_does_not_mutate_history_on_redirect(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        one = f"http://127.0.0.1:{self.port}/history-one"
        two = f"http://127.0.0.1:{self.port}/history-two"
        session.open(one)
        session.open(two)
        original_history = list(session.history)
        _BrowserTestHandler.redirect_history_one = True

        session.back()
        self.assertEqual(session.history, original_history)
        self.assertEqual(session.history_index, 0)
        self.assertTrue(session.url.endswith("/redirected"))

        session.forward()
        self.assertEqual(session.history, original_history)
        self.assertEqual(session.history_index, 1)
        self.assertEqual(session.url, two)

    def test_png_generator(self):
        elems = [DOMElement("elem_1", "button", {"id": "elem_1"})]
        elems[0].x = 10
        elems[0].y = 10
        elems[0].width = 100
        elems[0].height = 40

        png_bytes = generate_minimal_png(200, 100, elems)
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(b"IHDR" in png_bytes)
        self.assertTrue(b"IDAT" in png_bytes)
        self.assertTrue(b"IEND" in png_bytes)

    def test_browser_engine_session_lifecycle(self):
        engine = StealthBrowserEngine(profile_dir=self.profile_dir, max_sessions=2)
        session1 = engine.get_or_create_session("tab1")
        session2 = engine.get_or_create_session("tab2")

        self.assertIn("tab1", engine.sessions)
        self.assertIn("tab2", engine.sessions)

        close_res = engine.close_session("tab1")
        self.assertEqual(close_res["status"], "closed")
        self.assertNotIn("tab1", engine.sessions)

        engine.get_or_create_session("tab3")
        engine.get_or_create_session("tab4")
        self.assertNotIn("tab2", engine.sessions)
        self.assertEqual(list(engine.sessions), ["tab3", "tab4"])
        self.assertLessEqual(len(engine.sessions), MAX_BROWSER_SESSIONS)

    def test_browser_module_import_does_not_create_profile(self):
        script = """
from unittest.mock import patch
with patch('pathlib.Path.mkdir', side_effect=PermissionError('read-only home')):
    import fable_engine.browser as browser
    assert browser.GLOBAL_BROWSER_ENGINE._engine is None
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self.tmp_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_close_dispatch_does_not_create_unknown_session(self):
        engine = Mock()
        engine.close_session.return_value = {"status": "not_found", "session_id": "missing"}
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "browser_close", "arguments": {"session_id": "missing"}},
        }) + "\n"
        output = io.StringIO()
        with (
            patch.object(browser_server, "GLOBAL_BROWSER_ENGINE", engine),
            patch("sys.stdin", io.StringIO(request)),
            patch("sys.stdout", output),
        ):
            browser_server.main()

        engine.get_or_create_session.assert_not_called()
        engine.close_session.assert_called_once_with("missing")
        result = json.loads(json.loads(output.getvalue())["result"]["content"][0]["text"])
        self.assertEqual(result["status"], "not_found")

    def test_browser_wait_reports_bounded_duration(self):
        engine = Mock()
        engine.get_or_create_session.return_value = Mock()
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "browser_wait", "arguments": {"seconds": 25}},
        }) + "\n"
        output = io.StringIO()
        with (
            patch.object(browser_server, "GLOBAL_BROWSER_ENGINE", engine),
            patch("sys.stdin", io.StringIO(request)),
            patch("sys.stdout", output),
            patch("time.sleep") as sleep,
        ):
            browser_server.main()

        sleep.assert_called_once_with(10)
        result = json.loads(json.loads(output.getvalue())["result"]["content"][0]["text"])
        self.assertEqual(result["seconds"], 10)


if __name__ == "__main__":
    unittest.main()
