"""
Fable Engine Research Scrapers Package.
Exporting zero-cost, standard-library based scrapers for Web, YouTube, Reddit, X, GitHub, and arXiv.
"""

from __future__ import annotations

from fable_engine.scrapers.arxiv import ArxivScraper, scrape_arxiv
from fable_engine.scrapers.base import ResearchResult, ResearchSource, fetch_url
from fable_engine.scrapers.github import GitHubScraper, scrape_github
from fable_engine.scrapers.reddit import RedditScraper, scrape_reddit
from fable_engine.scrapers.web import WebScraper, scrape_web
from fable_engine.scrapers.x import XScraper, scrape_x
from fable_engine.scrapers.youtube import YouTubeScraper, scrape_youtube

__all__ = [
    "ResearchResult",
    "ResearchSource",
    "fetch_url",
    "WebScraper",
    "scrape_web",
    "YouTubeScraper",
    "scrape_youtube",
    "RedditScraper",
    "scrape_reddit",
    "XScraper",
    "scrape_x",
    "GitHubScraper",
    "scrape_github",
    "ArxivScraper",
    "scrape_arxiv",
]
