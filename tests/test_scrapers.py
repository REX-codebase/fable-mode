"""
Unit tests for Fable Engine Zero-Cost Research Scrapers, SSRF protection,
redirect validation, IP pinning, error handling, and MCP Action Handlers.
"""

import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from fable_engine.actions import handle_fable_session
from fable_engine.scrapers import (
    ArxivScraper,
    GitHubScraper,
    RedditScraper,
    ResearchResult,
    WebScraper,
    XScraper,
    YouTubeScraper,
    fetch_url,
    scrape_arxiv,
    scrape_github,
    scrape_reddit,
    scrape_web,
    scrape_x,
    scrape_youtube,
)
from fable_engine.scrapers.base import PinnedHTTPSConnection, validate_safe_url
from fable_engine.session import get_or_load_session


class TestSSRFProtectionAndRateLimiting(unittest.TestCase):

    def test_ssrf_validation_blocks_unsafe_hosts(self):
        unsafe_urls = [
            "http://localhost:8080/admin",
            "http://127.0.0.1/secret",
            "http://127.0.0.255/",
            "http://10.0.0.1/internal",
            "http://172.16.0.1/status",
            "http://192.168.1.1/router",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "gopher://localhost:70",
            "ftp://ftp.local/data",
        ]
        for url in unsafe_urls:
            safe, reason, resolved_ip = validate_safe_url(url)
            self.assertFalse(safe, f"Expected '{url}' to be blocked by SSRF validation, but it passed.")

    def test_ssrf_validation_allows_public_urls(self):
        safe_urls = [
            "https://arxiv.org/abs/2401.12345",
            "https://api.github.com/repos/REX-codebase/fable-mode",
            "https://www.reddit.com/r/Python/hot.json",
        ]
        for url in safe_urls:
            safe, reason, resolved_ip = validate_safe_url(url)
            self.assertTrue(safe, f"Expected public URL '{url}' to pass SSRF validation, failed: {reason}")
            self.assertTrue(resolved_ip is not None)

    def test_fetch_url_raises_value_error_on_ssrf_target(self):
        with self.assertRaises(ValueError) as ctx:
            fetch_url("http://127.0.0.1:8000/keys")
        self.assertIn("SSRF validation failed", str(ctx.exception))

    @patch("fable_engine.scrapers.base.validate_safe_url")
    def test_ssrf_redirect_to_private_ip_is_blocked(self, mock_validate):
        # Initial URL is safe, redirect location is blocked
        mock_validate.side_effect = [
            (True, "ok", "93.184.216.34"),  # example.com (public)
            (False, "SSRF blocked: target IP '127.0.0.1' is private, loopback, or reserved.", None)
        ]

        with patch("fable_engine.scrapers.base.PinnedHTTPSConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_resp_redirect = MagicMock()
            mock_resp_redirect.status = 302
            mock_resp_redirect.getheader.side_effect = lambda h: "http://127.0.0.1/secret" if h == "Location" else None
            mock_conn.getresponse.return_value = mock_resp_redirect
            mock_conn_cls.return_value = mock_conn

            with self.assertRaises(ValueError) as ctx:
                fetch_url("https://example.com/redirect-me")
            self.assertIn("SSRF validation failed", str(ctx.exception))
            self.assertIn("127.0.0.1", str(ctx.exception))


class TestResearchScrapers(unittest.TestCase):

    @patch("fable_engine.scrapers.web.fetch_url")
    def test_scrape_web_url_success(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Hello World</h1>
                <p>This is a test paragraph with a <a href="https://example.com/link">link</a>.</p>
            </body>
        </html>
        """
        res = scrape_web("https://example.com/page")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "web")
        self.assertEqual(res.canonical_url, "https://example.com/page")
        self.assertIn("Test Page", res.title)
        md = res.to_markdown()
        self.assertIn("Hello World", md)
        self.assertIn("[link](https://example.com/link)", md)

    @patch("fable_engine.scrapers.web.fetch_url")
    def test_scrape_web_http_error_handling(self, mock_fetch):
        mock_fetch.side_effect = urllib.error.HTTPError("https://example.com/forbidden", 403, "Forbidden", {}, None)
        res = scrape_web("https://example.com/forbidden")
        self.assertFalse(res.ok)
        self.assertIn("403", res.error)
        md = res.to_markdown()
        self.assertIn("Research Retrieval Failed", md)

    @patch("fable_engine.scrapers.youtube.fetch_url")
    def test_scrape_youtube_video_success(self, mock_fetch):
        def side_effect(url, *args, **kwargs):
            if "watch?v=" in url:
                return """
                <html>
                    <meta property="og:title" content="Test AI Video">
                    <meta property="og:description" content="A great video about AI.">
                    <link itemprop="name" content="TechChannel">
                    "captionTracks":[{"baseUrl":"https://youtube.com/api/timedtext"}]
                </html>
                """
            elif "timedtext" in url:
                return """<?xml version="1.0" encoding="utf-8" ?>
                <transcript>
                    <text start="0" dur="2">Welcome to the video.</text>
                    <text start="2" dur="3">Today we discuss AI agents.</text>
                </transcript>
                """
            return ""

        mock_fetch.side_effect = side_effect
        res = scrape_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "youtube")
        self.assertEqual(res.canonical_url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIn("Test AI Video", res.title)
        self.assertIn("Welcome to the video. Today we discuss AI agents.", res.content)

    @patch("fable_engine.scrapers.youtube.fetch_url")
    def test_scrape_youtube_missing_transcript_fallback(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
            <meta property="og:title" content="No Captions Video">
            <link itemprop="name" content="TechChannel">
        </html>
        """
        res = scrape_youtube("dQw4w9WgXcQ")
        self.assertTrue(res.ok)
        self.assertIn("Best-effort automated transcript track status", res.content)

    @patch("fable_engine.scrapers.reddit.fetch_url")
    def test_scrape_reddit_thread_success(self, mock_fetch):
        mock_response = [
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "title": "Fable Engine Released",
                                "subreddit": "Python",
                                "author": "rex_dev",
                                "score": 150,
                                "selftext": "Check out the new cognitive runtime.",
                                "permalink": "/r/Python/comments/123/fable/"
                            }
                        }
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "author": "user1",
                                "body": "Looks amazing!",
                                "score": 25
                            }
                        }
                    ]
                }
            }
        ]
        mock_fetch.return_value = json.dumps(mock_response)
        res = scrape_reddit("https://www.reddit.com/r/Python/comments/123/fable/")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "reddit")
        self.assertIn("Fable Engine Released", res.title)
        self.assertIn("Check out the new cognitive runtime.", res.content)
        self.assertIn("u/user1 (25 points)", res.content)

    @patch("fable_engine.scrapers.reddit.fetch_url")
    def test_scrape_reddit_empty_structure_handling(self, mock_fetch):
        mock_fetch.return_value = json.dumps([])
        res = scrape_reddit("r/empty_sub")
        self.assertFalse(res.ok)
        self.assertTrue(res.error is not None)

    @patch("fable_engine.scrapers.x.fetch_url")
    def test_scrape_x_tweet_success(self, mock_fetch):
        mock_tweet = {
            "text": "Fable Mode is now 100% free with research scrapers!",
            "user": {
                "name": "Fable Engine",
                "screen_name": "fable_mode"
            },
            "created_at": "Mon Mar 03 12:00:00 +0000 2025",
            "favorite_count": 42,
            "retweet_count": 10
        }
        mock_fetch.return_value = json.dumps(mock_tweet)
        res = scrape_x("https://x.com/fable_mode/status/1234567890")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "x")
        self.assertIn("Fable Engine", res.title)
        self.assertIn("100% free", res.content)

    @patch("fable_engine.scrapers.github.fetch_url")
    def test_scrape_github_repo_success(self, mock_fetch):
        def side_effect(url, *args, **kwargs):
            if "api.github.com/repos" in url:
                return json.dumps({
                    "full_name": "REX-codebase/fable-mode",
                    "description": "Control plane for AI agents",
                    "stargazers_count": 100,
                    "forks_count": 12,
                    "language": "Python",
                    "default_branch": "main",
                    "html_url": "https://github.com/REX-codebase/fable-mode"
                })
            elif "raw.githubusercontent.com" in url:
                return "# Fable Mode\nStructured Deliberation for Agents."
            return ""

        mock_fetch.side_effect = side_effect
        res = scrape_github("REX-codebase/fable-mode")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "github")
        self.assertIn("REX-codebase/fable-mode", res.title)
        self.assertIn("Control plane for AI agents", res.content)

    @patch("fable_engine.scrapers.arxiv.fetch_url")
    def test_scrape_arxiv_paper_success(self, mock_fetch):
        mock_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <id>http://arxiv.org/abs/2401.12345v1</id>
                <published>2024-01-20T10:00:00Z</published>
                <title>Cognitive Deliberation in AI Agents</title>
                <summary>We propose Fable Mode for structured deliberation.</summary>
                <author><name>Alice Smith</name></author>
                <author><name>Bob Jones</name></author>
            </entry>
        </feed>
        """
        mock_fetch.return_value = mock_xml
        res = scrape_arxiv("2401.12345")
        self.assertTrue(res.ok)
        self.assertEqual(res.source_type, "arxiv")
        self.assertIn("Cognitive Deliberation in AI Agents", res.content)


class TestScraperActionsAndEpistemicLog(unittest.TestCase):

    @patch("fable_engine.actions.scrapers.scrape_arxiv")
    def test_mcp_action_dispatch(self, mock_scrape):
        mock_scrape.return_value = ResearchResult(
            ok=True,
            source_type="arxiv",
            canonical_url="https://arxiv.org/abs/2401.12345",
            title="AI Deliberation",
            content="Paper abstract."
        )
        resp = handle_fable_session({
            "action": "scrape_arxiv",
            "target": "2401.12345"
        })
        self.assertIn("AI Deliberation", resp)
        mock_scrape.assert_called_once_with("2401.12345")

    @patch("fable_engine.actions.scrapers.scrape_github")
    def test_auto_log_epistemic_hypothesis_success_only(self, mock_scrape):
        session_name = "test_scraper_session"

        handle_fable_session({
            "action": "create_session",
            "session_name": session_name,
            "objective": "Test scraping auto-log as HYPOTHESIS",
            "time_budget_minutes": 2.0
        })

        # 1. Test failed result (ok=False) -> MUST NOT log hypothesis
        mock_scrape.return_value = ResearchResult(
            ok=False,
            source_type="github",
            canonical_url="https://github.com/invalid/repo",
            error="404 Not Found"
        )
        handle_fable_session({
            "action": "scrape_github",
            "session_name": session_name,
            "target": "invalid/repo",
            "auto_log_epistemic": True
        })

        session = get_or_load_session(session_name)
        self.assertEqual(len(session.epistemic_ledger), 0)

        # 2. Test successful result (ok=True) -> MUST log hypothesis
        mock_scrape.return_value = ResearchResult(
            ok=True,
            source_type="github",
            canonical_url="https://github.com/REX-codebase/fable-mode",
            title="REX-codebase/fable-mode",
            content="# GitHub Repo\nName: fable-mode"
        )
        handle_fable_session({
            "action": "scrape_github",
            "session_name": session_name,
            "target": "REX-codebase/fable-mode",
            "auto_log_epistemic": True
        })

        session = get_or_load_session(session_name)
        hypothesis_items = [item for item in session.epistemic_ledger if item["tag"] == "HYPOTHESIS"]
        self.assertEqual(len(hypothesis_items), 1)
        self.assertIn("REX-codebase/fable-mode", hypothesis_items[0]["claim"])


if __name__ == "__main__":
    unittest.main()
