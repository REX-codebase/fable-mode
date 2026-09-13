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
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from unittest.mock import Mock, patch

from fable_engine.browser import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    DOMElement,
    MAX_BROWSER_OPEN_TIMEOUT_SECONDS,
    MAX_BROWSER_SESSIONS,
    MAX_DOM_NODES,
    MAX_HISTORY_ENTRIES,
    MAX_RETAINED_PAGE_HTML_BYTES,
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
        elif self.path == "/oversized-dom":
            self.send_response(200)
            body = ("<input>" * (MAX_DOM_NODES + 1)).encode("utf-8")
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
        open_timeout_schema = schemas["browser_open"]["properties"]["timeout"]
        navigate_timeout_schema = schemas["browser_navigate"]["properties"]["timeout"]
        self.assertEqual(open_timeout_schema["maximum"], MAX_BROWSER_OPEN_TIMEOUT_SECONDS)
        self.assertEqual(open_timeout_schema["default"], 15.0)
        self.assertEqual(navigate_timeout_schema["maximum"], MAX_BROWSER_OPEN_TIMEOUT_SECONDS)
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

        if os.name != "nt":
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
                <input id="remember_me" type="checkbox" />
                <textarea id="notes"></textarea>
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
        self.assertEqual(session.type_text("notes", "editable")["status"], "typed")
        self.assertIn(
            "notes",
            {element["element_id"] for element in status["interactive_elements"]},
        )

        self.assertEqual(session.type_text("login_btn", "nope")["status"], "error")
        self.assertEqual(session.type_text("home_link", "nope")["status"], "error")
        self.assertEqual(session.type_text("remember_me", "nope")["status"], "error")

        self.assertEqual(session.click("login_btn")["status"], "error")
        self.assertEqual(session.press_key("!", "username_input")["status"], "pressed")
        self.assertEqual(
            session.elements_by_id["username_input"].attrs["value"], "agent_user!"
        )
        self.assertEqual(session.press_key("Backspace")["status"], "pressed")
        self.assertEqual(
            session.elements_by_id["username_input"].attrs["value"], "agent_user"
        )
        self.assertEqual(session.press_key("Tab", "username_input")["element_id"], "remember_me")

        # Test click link
        click_res = session.click("home_link")
        self.assertEqual(click_res["url"], "about:blank")

    def test_password_values_are_redacted_without_mutating_dom(self):
        password = DOMElement(
            "password", "input", {"type": "PASSWORD", "value": "secret", "name": "password"}
        )
        regular = DOMElement("username", "input", {"type": "text", "value": "agent"})

        self.assertEqual(password.to_dict()["attrs"]["value"], "[REDACTED]")
        self.assertEqual(password.to_dict()["attrs"]["name"], "password")
        self.assertEqual(password.attrs["value"], "secret")
        self.assertEqual(regular.to_dict()["attrs"]["value"], "agent")

    def test_oversized_dom_returns_an_explicit_error(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)

        result = session.open(f"http://127.0.0.1:{self.port}/oversized-dom")

        self.assertEqual(result["status"], "error")
        self.assertIn(f"{MAX_DOM_NODES} DOM node limit", result["error"])
        self.assertLess(len(session.elements_by_id), MAX_DOM_NODES)

    def test_navigation_resets_scroll_before_layout(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        session.scroll_y = 275

        session.open("about:blank")
        self.assertEqual(session.scroll_y, 0)

        session.scroll_y = 275
        session.open(f"http://127.0.0.1:{self.port}/echo")
        self.assertEqual(session.scroll_y, 0)

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

    def test_history_is_bounded_and_remains_consistent_after_branching(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        urls = [f"about:page-{index}" for index in range(MAX_HISTORY_ENTRIES + 5)]

        for url in urls:
            session._record_history(url)

        self.assertEqual(session.history, urls[-MAX_HISTORY_ENTRIES:])
        self.assertEqual(session.history_index, MAX_HISTORY_ENTRIES - 1)

        session.back()
        session.open("about:branched")
        session.open("about:branched")

        self.assertEqual(len(session.history), MAX_HISTORY_ENTRIES)
        self.assertEqual(session.history[-1], "about:branched")
        self.assertEqual(session.history_index, len(session.history) - 1)
        self.assertEqual(session.forward()["url"], "about:branched")

    def test_url_scheme_checks_are_case_insensitive_without_rewriting_url(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)

        about_url = "AbOuT:blank"
        self.assertEqual(session.open(about_url)["url"], about_url)

        session.opener = Mock()
        session.opener.open.side_effect = OSError("stop before network access")
        with patch("fable_engine.browser.urllib.request.Request") as request:
            session.open("HtTp://Example.test/Path")

        request.assert_called_once_with("HtTp://Example.test/Path")

    def test_layout_walk_handles_deep_dom_in_preorder(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        session.page_html = "".join(
            f'<div id="node-{index}">' for index in range(1_500)
        ) + "</div>" * 1_500

        session._parse_and_layout()

        ids = list(session.elements_by_id)
        self.assertEqual(ids[:4], ["elem_0", "node-0", "node-1", "node-2"])
        self.assertEqual(ids[-1], "node-1499")

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

    def test_png_background_scanlines_preserve_rgb_layout(self):
        bg_color = (1, 127, 255)
        png_bytes = generate_minimal_png(137, 103, [], bg_color=bg_color)
        offset = 8
        compressed = bytearray()
        while offset < len(png_bytes):
            chunk_length = struct.unpack(">I", png_bytes[offset:offset + 4])[0]
            chunk_type = png_bytes[offset + 4:offset + 8]
            chunk_data = png_bytes[offset + 8:offset + 8 + chunk_length]
            if chunk_type == b"IDAT":
                compressed.extend(chunk_data)
            offset += 12 + chunk_length

        expected_scanline = b"\x00" + bytes(bg_color) * 137
        self.assertEqual(zlib.decompress(compressed), expected_scanline * 103)

    def test_browser_engine_session_lifecycle(self):
        engine = StealthBrowserEngine(profile_dir=self.profile_dir, max_sessions=2)
        session1 = engine.get_or_create_session("tab1")
        session2 = engine.get_or_create_session("tab2")

        self.assertIn("tab1", engine.sessions)
        self.assertIn("tab2", engine.sessions)
        self.assertIs(engine.get_or_create_session("tab1"), session1)
        self.assertEqual(list(engine.sessions), ["tab1", "tab2"])

        close_res = engine.close_session("tab1")
        self.assertEqual(close_res["status"], "closed")
        self.assertNotIn("tab1", engine.sessions)

        session2.page_html = "retained page"
        session2.opener.close = Mock()
        engine.get_or_create_session("tab3")
        engine.get_or_create_session("tab4")
        self.assertNotIn("tab2", engine.sessions)
        self.assertEqual(list(engine.sessions), ["tab3", "tab4"])
        self.assertLessEqual(len(engine.sessions), MAX_BROWSER_SESSIONS)
        session2.opener.close.assert_called_once_with()
        self.assertEqual(session2.page_html, "")

    def test_default_session_page_retention_has_a_safe_aggregate_limit(self):
        self.assertEqual(
            DEFAULT_MAX_RESPONSE_BYTES * MAX_BROWSER_SESSIONS,
            MAX_RETAINED_PAGE_HTML_BYTES,
        )
        self.assertLess(MAX_RETAINED_PAGE_HTML_BYTES, 160 * 1024 * 1024)

    def test_browser_module_import_does_not_create_profile(self):
        script = """
from unittest.mock import patch
with patch('pathlib.Path.mkdir', side_effect=PermissionError('read-only home')):
    import fable_engine.browser as browser
    assert browser.GLOBAL_BROWSER_ENGINE._engine is None
"""
        env = os.environ.copy()
        repo_root = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self.tmp_dir,
            env=env,
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
            patch.object(browser_server, "AutoUpdater") as auto_updater,
            patch("sys.stdin", io.StringIO(request)),
            patch("sys.stdout", output),
        ):
            auto_updater.return_value.trigger_silent_background_update.return_value = None
            browser_server.main()

        engine.get_or_create_session.assert_not_called()
        engine.close_session.assert_called_once_with("missing")
        result = json.loads(json.loads(output.getvalue())["result"]["content"][0]["text"])
        self.assertEqual(result["status"], "not_found")

    def test_unknown_browser_tool_does_not_create_session(self):
        engine = Mock()
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "browser_typo", "arguments": {"session_id": "unused"}},
        }) + "\n"
        output = io.StringIO()
        with (
            patch.object(browser_server, "GLOBAL_BROWSER_ENGINE", engine),
            patch.object(browser_server, "AutoUpdater") as auto_updater,
            patch("sys.stdin", io.StringIO(request)),
            patch("sys.stdout", output),
        ):
            auto_updater.return_value.trigger_silent_background_update.return_value = None
            browser_server.main()

        engine.get_or_create_session.assert_not_called()
        engine.close_session.assert_not_called()
        response = json.loads(output.getvalue())
        self.assertEqual(response["error"]["code"], -32601)

    def test_browser_open_timeout_is_bounded_and_must_be_finite(self):
        engine = Mock()
        session = engine.get_or_create_session.return_value
        session.open.return_value = {"status": "opened"}
        requests = "".join([
            json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": "browser_open",
                    "arguments": {"url": "about:blank", "timeout": 10_000},
                },
            }) + "\n",
            json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "browser_open",
                    "arguments": {"url": "about:blank", "timeout": float("nan")},
                },
            }) + "\n",
        ])
        output = io.StringIO()
        with (
            patch.object(browser_server, "GLOBAL_BROWSER_ENGINE", engine),
            patch.object(browser_server, "AutoUpdater") as auto_updater,
            patch("sys.stdin", io.StringIO(requests)),
            patch("sys.stdout", output),
        ):
            auto_updater.return_value.trigger_silent_background_update.return_value = None
            browser_server.main()

        session.open.assert_called_once_with(
            "about:blank", timeout=MAX_BROWSER_OPEN_TIMEOUT_SECONDS
        )
        engine.get_or_create_session.assert_called_once_with(None)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(responses[0]["result"]["isError"])
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertIn("must be finite", responses[1]["result"]["content"][0]["text"])

    def test_browser_operation_error_results_set_mcp_error_flag(self):
        engine = Mock()
        session = engine.get_or_create_session.return_value
        session.open.side_effect = [
            {"status": "error", "error": "navigation failed"},
            {"status": "opened", "url": "about:blank"},
        ]
        session.click.return_value = {"error": "missing element"}
        session.type_text.return_value = {
            "status": "error",
            "error": "not editable",
        }
        requests = "".join(
            json.dumps({
                "jsonrpc": "2.0",
                "id": index,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }) + "\n"
            for index, (name, arguments) in enumerate((
                ("browser_open", {"url": "bad.test"}),
                ("browser_click", {"element_id": "missing"}),
                ("browser_type", {"element_id": "readonly", "text": "value"}),
                ("browser_open", {"url": "about:blank"}),
            ), start=1)
        )
        output = io.StringIO()
        with (
            patch.object(browser_server, "GLOBAL_BROWSER_ENGINE", engine),
            patch.object(browser_server, "AutoUpdater") as auto_updater,
            patch("sys.stdin", io.StringIO(requests)),
            patch("sys.stdout", output),
        ):
            auto_updater.return_value.trigger_silent_background_update.return_value = None
            browser_server.main()

        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [response["result"]["isError"] for response in responses],
            [True, True, True, False],
        )

    def test_browser_open_enforces_one_deadline_across_reads(self):
        class FakeSocket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, timeout):
                self.timeouts.append(timeout)

        class FakeResponse:
            def __init__(self):
                fake_raw = type("FakeRaw", (), {"_sock": FakeSocket()})()
                self.fp = type("FakeFP", (), {"raw": fake_raw})()
                self.chunks = iter((b"partial", b"response", b""))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read1(self, _size):
                return next(self.chunks)

            def read(self, _size):
                return next(self.chunks)

        pm = ProfileManager(profile_dir=self.profile_dir)
        session = StealthBrowserSession("test_tab", pm)
        response = FakeResponse()
        session.opener = Mock()
        session.opener.open.return_value = response

        with patch(
            "fable_engine.browser.time.monotonic",
            side_effect=(100.0, 100.1, 100.2, 101.1),
        ):
            result = session.open("example.test", timeout=1.0)

        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["error"])
        self.assertAlmostEqual(session.opener.open.call_args.kwargs["timeout"], 0.9)
        self.assertEqual(len(response.fp.raw._sock.timeouts), 1)

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
            patch.object(browser_server, "AutoUpdater") as auto_updater,
            patch("sys.stdin", io.StringIO(request)),
            patch("sys.stdout", output),
            patch("time.sleep") as sleep,
        ):
            auto_updater.return_value.trigger_silent_background_update.return_value = None
            browser_server.main()

        sleep.assert_called_once_with(10)
        result = json.loads(json.loads(output.getvalue())["result"]["content"][0]["text"])
        self.assertEqual(result["seconds"], 10)


if __name__ == "__main__":
    unittest.main()
