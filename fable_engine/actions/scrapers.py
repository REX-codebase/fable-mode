"""
Fable Engine Research Scraping Action Handlers.
Exposes zero-cost scrapers for Web, YouTube, Reddit, X, GitHub, and arXiv as individual MCP actions.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict

from fable_engine.scrapers import (
    scrape_arxiv,
    scrape_github,
    scrape_reddit,
    scrape_web,
    scrape_x,
    scrape_youtube,
)
from fable_engine.session import ACTIVE_SESSIONS, get_or_load_session

logger = logging.getLogger("fable-engine.actions.scrapers")


def _get_target_from_args(args: Dict[str, Any]) -> str:
    """Extracts target string from args using common parameter keys."""
    target = args.get("target") or args.get("query") or args.get("url") or args.get("target_resource") or args.get("claim") or ""
    return str(target).strip()


def _format_evidence_for_epistemic(target: str, content: str) -> str:
    """Ensures evidence contains a valid URL reference for EpistemicEvidenceValidator."""
    content_snippet = content[:1500] if len(content) > 1500 else content
    if target.startswith("http://") or target.startswith("https://"):
        return f"{target}\n\n{content_snippet}"
    if "http://" in content_snippet or "https://" in content_snippet:
        return content_snippet
    # Fallback to web search URL reference
    encoded = urllib.parse.quote(target)
    return f"https://duckduckgo.com/html/?q={encoded}\n\n{content_snippet}"


def _auto_log_epistemic_if_requested(args: Dict[str, Any], action_name: str, target: str, content: str):
    """Optionally logs scraped result as a [PROVEN] epistemic item if requested."""
    auto_log = args.get("auto_log_epistemic") or args.get("auto_log")
    if not auto_log:
        return
    session_name = args.get("session_name", "").strip()
    if not session_name:
        if ACTIVE_SESSIONS:
            session_name = next(iter(ACTIVE_SESSIONS.keys()))
        else:
            return
    try:
        session = get_or_load_session(session_name)
        claim = f"Scraped {action_name} research target: '{target}'"
        evidence = _format_evidence_for_epistemic(target, content)
        session.log_epistemic_item("PROVEN", claim, evidence)
    except Exception as e:
        logger.warning(f"Could not auto-log epistemic item for {action_name}: {e}")


def _handle_scrape_web(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'query' for scrape_web."
    result = scrape_web(target)
    _auto_log_epistemic_if_requested(args, "scrape_web", target, result)
    return result


def _handle_scrape_youtube(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'video_id' for scrape_youtube."
    result = scrape_youtube(target)
    _auto_log_epistemic_if_requested(args, "scrape_youtube", target, result)
    return result


def _handle_scrape_reddit(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'subreddit' for scrape_reddit."
    result = scrape_reddit(target)
    _auto_log_epistemic_if_requested(args, "scrape_reddit", target, result)
    return result


def _handle_scrape_x(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'handle' for scrape_x."
    result = scrape_x(target)
    _auto_log_epistemic_if_requested(args, "scrape_x", target, result)
    return result


def _handle_scrape_github(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'repo' or 'query' for scrape_github."
    result = scrape_github(target)
    _auto_log_epistemic_if_requested(args, "scrape_github", target, result)
    return result


def _handle_scrape_arxiv(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'paper_id' or 'query' for scrape_arxiv."
    result = scrape_arxiv(target)
    _auto_log_epistemic_if_requested(args, "scrape_arxiv", target, result)
    return result
