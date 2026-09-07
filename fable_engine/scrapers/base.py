"""
Base research scraper interfaces, structured result objects, and HTTP transport utilities.
Enforces standard TLS certificate verification, retry/backoff, and response bounds.
"""

from __future__ import annotations

import datetime
import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fable-engine.scrapers.base")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 FableResearch/1.3.0"

# Standard TLS context enforcing certificate verification
_SSL_CONTEXT = ssl.create_default_context()


@dataclass
class ResearchResult:
    """Structured research retrieval result."""
    ok: bool
    source_type: str
    canonical_url: str
    title: str = ""
    author: str = ""
    content: str = ""
    error: Optional[str] = None
    retrieved_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Formats the structured research result as readable Markdown."""
        if not self.ok:
            return (
                f"# Research Retrieval Failed: {self.source_type.title()}\n"
                f"**Canonical URL**: {self.canonical_url or 'N/A'}\n"
                f"**Retrieved At**: {self.retrieved_at}\n"
                f"**Error**: {self.error or 'Unknown error'}\n"
            )
        md = [
            f"# {self.source_type.title()}: {self.title or 'Untitled'}",
            f"**Canonical URL**: {self.canonical_url}",
        ]
        if self.author:
            md.append(f"**Author**: {self.author}")
        md.append(f"**Retrieved At**: {self.retrieved_at}\n")
        if self.content:
            md.append(self.content)
        return "\n".join(md)


def fetch_url(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
    max_bytes: int = 5 * 1024 * 1024,
    max_retries: int = 2,
    backoff_factor: float = 0.5,
) -> str:
    """
    Fetches raw string content from URL using urllib with standard TLS verification,
    exponential backoff retries on rate limits (429) or server errors (5xx), and size caps.
    """
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                raw_bytes = resp.read(max_bytes + 1)
                if len(raw_bytes) > max_bytes:
                    raw_bytes = raw_bytes[:max_bytes]
                return raw_bytes.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # Retry on rate limits (429) or transient server errors (500, 502, 503, 504)
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After")
                sleep_time = float(retry_after) if retry_after and retry_after.isdigit() else (backoff_factor * (2 ** attempt))
                time.sleep(sleep_time)
                continue
            raise exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            raise exc

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url}")


class SimpleHTMLTextExtractor(HTMLParser):
    """HTML parser converting web content to readable Markdown text."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.in_title = False
        self.in_script = False
        self.in_style = False
        self.chunks: List[str] = []
        self.links: List[Tuple[str, str]] = []  # (text, href)
        self._current_href: Optional[str] = None
        self._current_link_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "svg"):
            self.in_script = True
        elif tag == "title":
            self.in_title = True
        elif tag == "a":
            attr_dict = dict(attrs)
            self._current_href = attr_dict.get("href")
            self._current_link_text = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.chunks.append("\n\n### ")
        elif tag in ("p", "div", "section", "article", "li", "tr"):
            self.chunks.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "svg"):
            self.in_script = False
        elif tag == "title":
            self.in_title = False
        elif tag == "a":
            if self._current_href:
                link_str = "".join(self._current_link_text).strip()
                if link_str and not self._current_href.startswith("javascript:"):
                    self.links.append((link_str, self._current_href))
            self._current_href = None
            self._current_link_text = []

    def handle_data(self, data: str):
        if self.in_script or self.in_style:
            return
        if self.in_title:
            self.title += data
            return
        text = data.strip()
        if text:
            if self._current_href is not None:
                self._current_link_text.append(text)
            self.chunks.append(text + " ")

    def get_markdown(self) -> str:
        raw_text = "".join(self.chunks)
        import re
        cleaned = re.sub(r"\n\s*\n+", "\n\n", raw_text).strip()
        return cleaned


class ResearchSource:
    """Abstract base class for research scrapers."""
    source_type: str = "generic"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 12000) -> ResearchResult:
        raise NotImplementedError
