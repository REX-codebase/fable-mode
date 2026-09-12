"""
Stealth Agent Browser Engine for Fable Engine.
A lightweight, agent-first browser engine designed for low memory footprint (<= 20 MB RSS target),
persistent local logins/profiles (~/.fable/browser-profile/), localhost support across any language server,
element indexing, navigation, and layered PNG screenshot generation.
"""

from __future__ import annotations

import base64
import html
from html.parser import HTMLParser
import json
import logging
import os
import pathlib
import re
import struct
import sys
import time
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fable-engine.browser")

DEFAULT_PROFILE_DIR = pathlib.Path.home() / ".fable" / "browser-profile"
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 800


class DOMElement:
    """Represents a node in the rendered DOM tree with stable element ID and layout box."""

    def __init__(
        self,
        element_id: str,
        tag: str,
        attrs: Dict[str, str],
        text: str = "",
        children: Optional[List[DOMElement]] = None,
    ):
        self.element_id = element_id
        self.tag = tag.lower()
        self.attrs = attrs
        self.text = text
        self.children = children or []
        self.parent: Optional[DOMElement] = None
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "tag": self.tag,
            "attrs": self.attrs,
            "text": self.text.strip(),
            "bbox": [self.x, self.y, self.width, self.height],
            "children_count": len(self.children),
        }


class SimpleDOMParser(HTMLParser):
    """HTML parser that constructs a clean DOM tree with stable element IDs."""

    def __init__(self):
        super().__init__()
        self.root = DOMElement("elem_0", "root", {})
        self.stack: List[DOMElement] = [self.root]
        self.counter = 1

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: (v or "") for k, v in attrs}
        elem_id = attr_dict.get("id") or f"elem_{self.counter}"
        self.counter += 1
        elem = DOMElement(elem_id, tag, attr_dict)
        elem.parent = self.stack[-1]
        self.stack[-1].children.append(elem)
        if tag.lower() not in ("img", "br", "hr", "input", "meta", "link"):
            self.stack.append(elem)

    def handle_endtag(self, tag: str):
        if len(self.stack) > 1 and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_data(self, data: str):
        if self.stack:
            clean_text = data.strip()
            if clean_text:
                if self.stack[-1].text:
                    self.stack[-1].text += " " + clean_text
                else:
                    self.stack[-1].text = clean_text


def generate_minimal_png(width: int, height: int, elements: List[DOMElement], bg_color: Tuple[int, int, int] = (245, 247, 250)) -> bytes:
    """
    Generates a valid 24-bit RGB PNG image buffer without external image dependencies (pure stdlib struct + zlib).
    Renders background canvas and simple color-coded layout boxes for DOM elements.
    """
    # Clamp maximum raster dimensions to avoid excessive memory during snapshot
    w = min(max(width, 100), 1280)
    h = min(max(height, 100), 2400)

    # 3 bytes per pixel RGB
    row_bytes = w * 3
    # Allocate bytearray for raw uncompressed bitmap + scanline filter byte (0x00 None filter per row)
    raw_data = bytearray((row_bytes + 1) * h)

    bg_r, bg_g, bg_b = bg_color
    for y in range(h):
        row_offset = y * (row_bytes + 1)
        raw_data[row_offset] = 0  # Filter type 0
        for x in range(w):
            px = row_offset + 1 + x * 3
            raw_data[px] = bg_r
            raw_data[px + 1] = bg_g
            raw_data[px + 2] = bg_b

    # Simple element box rasterization
    for elem in elements:
        if elem.width <= 0 or elem.height <= 0:
            continue
        # Color coding by tag
        if elem.tag in ("a", "button", "input"):
            box_r, box_g, box_b = (59, 130, 246)  # Blue
        elif elem.tag in ("h1", "h2", "h3", "header"):
            box_r, box_g, box_b = (30, 41, 59)   # Dark Slate
        else:
            box_r, box_g, box_b = (203, 213, 225) # Light Slate Border

        x1 = max(0, min(elem.x, w - 1))
        y1 = max(0, min(elem.y, h - 1))
        x2 = max(0, min(elem.x + elem.width, w - 1))
        y2 = max(0, min(elem.y + elem.height, h - 1))

        # Fill/Border
        for py in range(y1, y2 + 1):
            row_offset = py * (row_bytes + 1)
            for px_x in range(x1, x2 + 1):
                is_border = (px_x == x1 or px_x == x2 or py == y1 or py == y2)
                if is_border or elem.tag in ("button", "input"):
                    idx = row_offset + 1 + px_x * 3
                    raw_data[idx] = box_r
                    raw_data[idx + 1] = box_g
                    raw_data[idx + 2] = box_b

    compressed = zlib.compress(bytes(raw_data), level=6)

    # Build PNG chunks
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    idat_len = len(compressed)
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat_chunk = struct.pack(">I", idat_len) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND")
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    png_header = b"\x89PNG\r\n\x1a\n"
    return png_header + ihdr_chunk + idat_chunk + iend_chunk


class ProfileManager:
    """Manages persistent cookies, session data, and login state on local user machine."""

    def __init__(self, profile_dir: Optional[pathlib.Path | str] = None):
        if profile_dir is None:
            self.profile_dir = DEFAULT_PROFILE_DIR
        else:
            self.profile_dir = pathlib.Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_file = self.profile_dir / "cookies.json"
        self.storage_file = self.profile_dir / "local_storage.json"
        self.cookies: Dict[str, str] = {}
        self.local_storage: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    self.cookies = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load cookies from {self.cookie_file}: {e}")
                self.cookies = {}
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    self.local_storage = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load local_storage from {self.storage_file}: {e}")
                self.local_storage = {}

    def save(self):
        try:
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(self.cookies, f, indent=2)
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(self.local_storage, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save profile state: {e}")

    def get_cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def update_cookies_from_headers(self, headers: List[Tuple[str, str]]):
        for key, val in headers:
            if key.lower() == "set-cookie":
                parts = val.split(";")[0].split("=", 1)
                if len(parts) == 2:
                    self.cookies[parts[0].strip()] = parts[1].strip()
        self.save()


class StealthBrowserSession:
    """
    Active browser tab session.
    Parses HTML, layouts elements into coordinates, handles inputs, and captures layered PNG screenshots.
    """

    def __init__(
        self,
        session_id: str,
        profile_manager: ProfileManager,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    ):
        self.session_id = session_id
        self.profile_manager = profile_manager
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.url = "about:blank"
        self.history: List[str] = []
        self.history_index = -1
        self.dom_root: Optional[DOMElement] = None
        self.elements_by_id: Dict[str, DOMElement] = {}
        self.scroll_y = 0
        self.document_height = DEFAULT_VIEWPORT_HEIGHT
        self.page_title = ""
        self.page_html = ""

    def open(self, url: str, timeout: float = 15.0) -> Dict[str, Any]:
        """Opens a URL (including localhost) using urllib with persistent cookies and standard headers."""
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = "http://" + url

        if url.startswith("about:"):
            self.url = url
            self.page_title = "Blank Page"
            self.page_html = "<html><head><title>Blank Page</title></head><body><h1>Blank Page</h1></body></html>"
            self._parse_and_layout()
            self._record_history(url)
            return self._build_status()

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "en-US,en;q=0.9")

        cookie_str = self.profile_manager.get_cookie_header()
        if cookie_str:
            req.add_header("Cookie", cookie_str)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                headers = resp.getheaders()
                self.profile_manager.update_cookies_from_headers(headers)
                body = resp.read().decode("utf-8", errors="replace")
                self.url = resp.geturl()
                self.page_html = body
                self._record_history(self.url)
                self._parse_and_layout()
                return self._build_status()
        except Exception as e:
            logger.error(f"Browser navigation error to {url}: {e}")
            self.page_html = f"<html><body><h1>Navigation Error</h1><p>{html.escape(str(e))}</p></body></html>"
            self._parse_and_layout()
            return {"status": "error", "error": str(e), "url": url}

    def _record_history(self, url: str):
        if self.history_index >= 0 and self.history_index < len(self.history):
            if self.history[self.history_index] == url:
                return
            self.history = self.history[: self.history_index + 1]
        self.history.append(url)
        self.history_index = len(self.history) - 1

    def back(self) -> Dict[str, Any]:
        if self.history_index > 0:
            self.history_index -= 1
            return self.open(self.history[self.history_index])
        return self._build_status()

    def forward(self) -> Dict[str, Any]:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            return self.open(self.history[self.history_index])
        return self._build_status()

    def reload(self) -> Dict[str, Any]:
        if self.url and not self.url.startswith("about:"):
            return self.open(self.url)
        return self._build_status()

    def _parse_and_layout(self):
        parser = SimpleDOMParser()
        try:
            parser.feed(self.page_html)
        except Exception:
            pass

        self.dom_root = parser.root
        self.elements_by_id.clear()

        # Extract title
        title_match = re.search(r"<title>(.*?)</title>", self.page_html, re.IGNORECASE | re.DOTALL)
        self.page_title = title_match.group(1).strip() if title_match else self.url

        # Compute layout boxes
        current_y = 20
        all_elems: List[DOMElement] = []

        def traverse(node: DOMElement):
            nonlocal current_y
            self.elements_by_id[node.element_id] = node
            all_elems.append(node)

            if node.tag in ("h1", "h2", "h3", "p", "div", "button", "input", "a", "section"):
                node.x = 40
                node.y = current_y
                node.width = self.viewport_width - 80
                node.height = 36 if node.tag in ("button", "input") else 24
                current_y += node.height + 12

            for child in node.children:
                traverse(child)

        traverse(self.dom_root)
        self.document_height = max(self.viewport_height, current_y + 40)

    def scroll(self, delta_y: int) -> Dict[str, Any]:
        self.scroll_y = max(0, min(self.scroll_y + delta_y, self.document_height - self.viewport_height))
        return self._build_status()

    def click(self, element_id: str) -> Dict[str, Any]:
        elem = self.elements_by_id.get(element_id)
        if not elem:
            return {"error": f"Element '{element_id}' not found"}
        href = elem.attrs.get("href")
        if href:
            target_url = urllib.parse.urljoin(self.url, href)
            return self.open(target_url)
        return {"status": "clicked", "element_id": element_id}

    def type_text(self, element_id: str, text: str) -> Dict[str, Any]:
        elem = self.elements_by_id.get(element_id)
        if not elem:
            return {"error": f"Element '{element_id}' not found"}
        elem.attrs["value"] = text
        return {"status": "typed", "element_id": element_id, "text": text}

    def press_key(self, key: str, element_id: Optional[str] = None) -> Dict[str, Any]:
        return {"status": "key_pressed", "key": key, "element_id": element_id}

    def snapshot_layers(self, max_layers: int = 3) -> Dict[str, Any]:
        """Captures N viewport-sized sequential screenshots (1 layer = 1 viewport height)."""
        layers = []
        all_elements = list(self.elements_by_id.values())

        total_layers = max(1, min(max_layers, (self.document_height + self.viewport_height - 1) // self.viewport_height))

        for layer_idx in range(total_layers):
            layer_top = layer_idx * self.viewport_height

            visible_elements = [
                e for e in all_elements
                if e.y + e.height >= layer_top and e.y <= layer_top + self.viewport_height
            ]

            layer_elements = []
            for e in visible_elements:
                adjusted = DOMElement(e.element_id, e.tag, e.attrs, e.text)
                adjusted.x = e.x
                adjusted.y = e.y - layer_top
                adjusted.width = e.width
                adjusted.height = e.height
                layer_elements.append(adjusted)

            png_bytes = generate_minimal_png(self.viewport_width, self.viewport_height, layer_elements)
            b64_png = base64.b64encode(png_bytes).decode("ascii")

            layers.append({
                "layer_index": layer_idx + 1,
                "viewport": [self.viewport_width, self.viewport_height],
                "scroll_top": layer_top,
                "b64_png": b64_png,
                "elements_count": len(visible_elements),
            })

        return {
            "session_id": self.session_id,
            "url": self.url,
            "title": self.page_title,
            "total_layers": len(layers),
            "layers": layers,
        }

    def _build_status(self) -> Dict[str, Any]:
        elements_summary = [
            elem.to_dict() for elem in self.elements_by_id.values()
            if elem.tag in ("a", "button", "input", "h1", "h2", "h3", "form")
        ]
        return {
            "session_id": self.session_id,
            "url": self.url,
            "title": self.page_title,
            "viewport": [self.viewport_width, self.viewport_height],
            "scroll_y": self.scroll_y,
            "document_height": self.document_height,
            "interactive_elements": elements_summary[:50],
        }


class StealthBrowserEngine:
    """Master Stealth Browser Manager managing active tab sessions and profiles."""

    def __init__(self, profile_dir: Optional[pathlib.Path] = None):
        self.profile_manager = ProfileManager(profile_dir)
        self.sessions: Dict[str, StealthBrowserSession] = {}
        self.active_session_id: Optional[str] = None

    def get_or_create_session(self, session_id: Optional[str] = None) -> StealthBrowserSession:
        sid = session_id or self.active_session_id or "default_session"
        if sid not in self.sessions:
            self.sessions[sid] = StealthBrowserSession(sid, self.profile_manager)
        self.active_session_id = sid
        return self.sessions[sid]

    def close_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        sid = session_id or self.active_session_id
        if sid and sid in self.sessions:
            del self.sessions[sid]
            if self.active_session_id == sid:
                self.active_session_id = next(iter(self.sessions.keys())) if self.sessions else None
            return {"status": "closed", "session_id": sid}
        return {"status": "not_found", "session_id": sid}


GLOBAL_BROWSER_ENGINE = StealthBrowserEngine()
