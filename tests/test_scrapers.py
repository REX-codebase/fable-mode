"""
Unit tests for Fable Engine Zero-Cost Research Scrapers and MCP Action Handlers.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from fable_engine.actions import handle_fable_session
from fable_engine.scrapers import (
    scrape_arxiv,
    scrape_github,
    scrape_reddit,
    scrape_web,
    scrape_x,
    scrape_youtube,
)
from fable_engine.session import FableSession, get_or_load_session


class TestResearchScrapers(unittest.TestCase):

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_web_url(self, mock_fetch):
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
        self.assertIn("# Web Page: Test Page", res)
        self.assertIn("Hello World", res)
        self.assertIn("This is a test paragraph", res)
        self.assertIn("[link](https://example.com/link)", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_web_search(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
            <body>
                <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org">Python Programming</a>
                <span class="result__snippet">Python is a programming language.</span>
            </body>
        </html>
        """
        res = scrape_web("python programming")
        self.assertIn("Web Search Results for: 'python programming'", res)
        self.assertIn("python.org", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_youtube_video(self, mock_fetch):
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
        self.assertIn("# YouTube Video: Test AI Video", res)
        self.assertIn("TechChannel", res)
        self.assertIn("Welcome to the video. Today we discuss AI agents.", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_reddit_thread(self, mock_fetch):
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
        self.assertIn("# Reddit Post: Fable Engine Released", res)
        self.assertIn("r/Python", res)
        self.assertIn("rex_dev", res)
        self.assertIn("Check out the new cognitive runtime.", res)
        self.assertIn("u/user1 (25 points)", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_x_tweet(self, mock_fetch):
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
        self.assertIn("# Tweet by @fable_mode (Fable Engine)", res)
        self.assertIn("Fable Mode is now 100% free with research scrapers!", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_github_repo(self, mock_fetch):
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
        self.assertIn("# GitHub Repository: REX-codebase/fable-mode", res)
        self.assertIn("Control plane for AI agents", res)
        self.assertIn("# Fable Mode\nStructured Deliberation for Agents.", res)

    @patch("fable_engine.scrapers._fetch_url")
    def test_scrape_arxiv_paper(self, mock_fetch):
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
        self.assertIn("Cognitive Deliberation in AI Agents", res)
        self.assertIn("Alice Smith, Bob Jones", res)
        self.assertIn("We propose Fable Mode for structured deliberation.", res)


class TestScraperActionsAndEpistemicLog(unittest.TestCase):

    @patch("fable_engine.actions.scrapers.scrape_arxiv")
    def test_mcp_action_dispatch(self, mock_scrape):
        mock_scrape.return_value = "# arXiv Paper\nTitle: AI Deliberation"
        resp = handle_fable_session({
            "action": "scrape_arxiv",
            "target": "2401.12345"
        })
        self.assertIn("AI Deliberation", resp)
        mock_scrape.assert_called_once_with("2401.12345")

    @patch("fable_engine.actions.scrapers.scrape_github")
    def test_auto_log_epistemic(self, mock_scrape):
        mock_scrape.return_value = "# GitHub Repo\nName: fable-mode"
        session_name = "test_scraper_session"

        # Create session first
        handle_fable_session({
            "action": "create_session",
            "session_name": session_name,
            "objective": "Test scraping auto-log",
            "time_budget_minutes": 2.0
        })

        # Run scrape_github with auto_log_epistemic: True
        resp = handle_fable_session({
            "action": "scrape_github",
            "session_name": session_name,
            "target": "REX-codebase/fable-mode",
            "auto_log_epistemic": True
        })
        self.assertIn("fable-mode", resp)

        # Check that epistemic ledger has the PROVEN item
        session = get_or_load_session(session_name)
        proven_items = [item for item in session.epistemic_ledger if item["tag"] == "PROVEN"]
        self.assertTrue(any("REX-codebase/fable-mode" in item["claim"] for item in proven_items))


if __name__ == "__main__":
    unittest.main()
