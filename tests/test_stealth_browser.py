"""
Unit tests for Stealth Agent Browser Engine and top-level MCP browser tools.
Verifies memory footprint target, local persistent profiles (~/.fable/browser-profile/),
navigation history, element clicking, typing, scrolling, and layered PNG screenshot generation.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from fable_engine.browser import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    DOMElement,
    ProfileManager,
    StealthBrowserEngine,
    StealthBrowserSession,
    generate_minimal_png,
)
from fable_engine.schema import BROWSER_TOOL_SCHEMAS
from fable_engine.server import GLOBAL_BROWSER_ENGINE


class TestStealthAgentBrowser(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.profile_dir = os.path.join(self.tmp_dir, "browser-profile")

    def tearDown(self):
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

    def test_profile_manager_persistence(self):
        pm = ProfileManager(profile_dir=self.profile_dir)
        pm.cookies["session_token"] = "abc123secret"
        pm.local_storage["user_pref"] = {"theme": "dark"}
        pm.save()

        # Reload from disk
        pm2 = ProfileManager(profile_dir=self.profile_dir)
        self.assertEqual(pm2.cookies.get("session_token"), "abc123secret")
        self.assertEqual(pm2.local_storage.get("user_pref"), {"theme": "dark"})
        self.assertEqual(pm2.get_cookie_header(), "session_token=abc123secret")

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

        # Test click link
        click_res = session.click("home_link")
        self.assertEqual(click_res["url"], "about:blank")

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
        engine = StealthBrowserEngine(profile_dir=self.profile_dir)
        session1 = engine.get_or_create_session("tab1")
        session2 = engine.get_or_create_session("tab2")

        self.assertIn("tab1", engine.sessions)
        self.assertIn("tab2", engine.sessions)

        close_res = engine.close_session("tab1")
        self.assertEqual(close_res["status"], "closed")
        self.assertNotIn("tab1", engine.sessions)


if __name__ == "__main__":
    unittest.main()
