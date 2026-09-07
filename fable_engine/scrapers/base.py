"""
Base research scraper interfaces, structured result objects, and HTTP transport utilities.
Enforces standard TLS certificate verification, strict SSRF protection with IP pinning
(preventing DNS rebinding TOCTOU window), host rate limiting, retry/backoff, and response bounds.
"""

from __future__ import annotations

import datetime
import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fable-engine.scrapers.base")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 FableResearch/1.3.0"

_SSL_CONTEXT = ssl.create_default_context()


def is_safe_ip(ip_str: str) -> bool:
    """Verifies that an IP address is public and safe (not loopback, private, link-local, reserved)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
        # Cloud metadata service check (169.254.169.254)
        if str(ip) == "169.254.169.254":
            return False
        return True
    except ValueError:
        return False


def validate_safe_url(url: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates that a URL uses http/https scheme and its hostname resolves
    exclusively to safe, public IP addresses (SSRF prevention).
    Returns (is_safe, reason, first_resolved_safe_ip).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False, f"Invalid URL scheme '{parsed.scheme}'. Strictly http and https are permitted.", None

        hostname = parsed.hostname
        if not hostname:
            return False, "URL missing valid hostname.", None

        hostname_clean = hostname.strip().lower()

        # Reject explicit local hostnames
        if hostname_clean in ("localhost", "localhost.localdomain") or hostname_clean.endswith(".local"):
            return False, f"SSRF blocked: local hostname '{hostname_clean}' is not permitted.", None

        # Check if hostname is an explicit IP string
        try:
            ip_obj = ipaddress.ip_address(hostname_clean)
            if not is_safe_ip(str(ip_obj)):
                return False, f"SSRF blocked: target IP '{hostname_clean}' is private, loopback, or reserved.", None
            return True, "ok", str(ip_obj)
        except ValueError:
            pass  # Not an IP string, proceed to DNS resolution

        # Resolve hostname DNS records
        port = parsed.port or (443 if scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname_clean, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as e:
            return False, f"DNS resolution failed for host '{hostname_clean}': {e}", None

        if not addr_info:
            return False, f"Could not resolve IP addresses for host '{hostname_clean}'.", None

        safe_ips = []
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if not is_safe_ip(ip_str):
                return False, f"SSRF blocked: host '{hostname_clean}' resolved to restricted IP '{ip_str}'.", None
            safe_ips.append(ip_str)

        return True, "ok", safe_ips[0]
    except Exception as e:
        return False, f"URL validation error: {e}", None


class PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection connecting directly to a pre-validated safe IP address."""

    def __init__(self, host: str, resolved_ip: str, port: int = 80, **kwargs):
        super().__init__(host, port=port, **kwargs)
        self.resolved_ip = resolved_ip

    def connect(self):
        self.sock = socket.create_connection((self.resolved_ip, self.port), self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection connecting directly to a pre-validated safe IP address with TLS SNI."""

    def __init__(self, host: str, resolved_ip: str, port: int = 443, **kwargs):
        super().__init__(host, port=port, **kwargs)
        self.resolved_ip = resolved_ip

    def connect(self):
        sock = socket.create_connection((self.resolved_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class DomainRateLimiter:
    """Thread-safe outbound domain rate limiter ensuring minimum spacing between requests."""

    def __init__(self, min_interval_seconds: float = 0.3):
        self.min_interval = min_interval_seconds
        self._last_request: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait_if_needed(self, url: str):
        try:
            hostname = urllib.parse.urlparse(url).hostname or "default"
            domain = hostname.lower()
        except Exception:
            domain = "default"

        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
            else:
                sleep_time = 0.0
            self._last_request[domain] = now + sleep_time

        if sleep_time > 0:
            time.sleep(sleep_time)


GLOBAL_RATE_LIMITER = DomainRateLimiter(min_interval_seconds=0.3)


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
    Fetches raw string content from URL using pinned IP transport:
    1. Validates host & DNS records for SSRF safety
    2. Pins connection directly to validated IP (immune to DNS rebinding)
    3. Handles HTTP 301/302/303/307/308 redirects with re-validation on every redirect
    4. Applies domain rate limiting
    5. Standard TLS certificate verification & retries on 429/5xx status
    """
    current_url = url
    max_redirects = 5

    for redirect_count in range(max_redirects + 1):
        safe, reason, resolved_ip = validate_safe_url(current_url)
        if not safe or not resolved_ip:
            raise ValueError(f"SSRF validation failed for '{current_url}': {reason}")

        GLOBAL_RATE_LIMITER.wait_if_needed(current_url)

        parsed = urllib.parse.urlparse(current_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        req_headers = {"User-Agent": USER_AGENT, "Host": host}
        if headers:
            req_headers.update(headers)

        last_exc: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                if scheme == "https":
                    conn = PinnedHTTPSConnection(host, resolved_ip, port=port, context=_SSL_CONTEXT, timeout=timeout)
                else:
                    conn = PinnedHTTPConnection(host, resolved_ip, port=port, timeout=timeout)

                conn.request("GET", path, headers=req_headers)
                resp = conn.getresponse()

                # Handle HTTP redirects safely
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader("Location")
                    conn.close()
                    if not location:
                        raise urllib.error.HTTPError(current_url, resp.status, "Redirect missing Location header", resp.headers, None)
                    current_url = urllib.parse.urljoin(current_url, location)
                    break  # Break retry loop and execute next redirect iteration

                if resp.status in (429, 500, 502, 503, 504) and attempt < max_retries:
                    retry_after = resp.getheader("Retry-After")
                    conn.close()
                    sleep_time = float(retry_after) if retry_after and retry_after.isdigit() else (backoff_factor * (2 ** attempt))
                    time.sleep(sleep_time)
                    continue

                if resp.status >= 400:
                    conn.close()
                    raise urllib.error.HTTPError(current_url, resp.status, f"HTTP Error {resp.status}", resp.headers, None)

                raw_bytes = resp.read(max_bytes + 1)
                conn.close()
                if len(raw_bytes) > max_bytes:
                    raw_bytes = raw_bytes[:max_bytes]
                charset = resp.headers.get_param("charset") or "utf-8"
                return raw_bytes.decode(charset, errors="replace")

            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in (301, 302, 303, 307, 308):
                    raise exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue
                raise exc
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue
                raise exc

        # If loop exited due to redirect, continue outer redirect_count loop
        if 'resp' in locals() and resp.status in (301, 302, 303, 307, 308):
            continue

        if last_exc:
            raise last_exc

    raise RuntimeError(f"Maximum redirects ({max_redirects}) exceeded for {url}")


class SimpleHTMLTextExtractor(HTMLParser):
    """HTML parser converting web content to readable Markdown text."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.in_title = False
        self.in_script = False
        self.in_style = False
        self.chunks: List[str] = []
        self.links: List[Tuple[str, str]] = []
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
        cleaned = re.sub(r"\n\s*\n+", "\n\n", raw_text).strip()
        return cleaned


class ResearchSource:
    """Abstract base class for research scrapers."""
    source_type: str = "generic"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 12000) -> ResearchResult:
        raise NotImplementedError
