"""
Fable Engine Research Scraping Action Handlers.
Exposes zero-cost scrapers for Web, YouTube, Reddit, X, GitHub, and arXiv as individual MCP actions.
Integrates retrieved evidence into Fable Session epistemic ledger as [HYPOTHESIS] candidate items.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fable_engine.scrapers import (
    ResearchResult,
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


def _auto_log_epistemic_if_requested(args: Dict[str, Any], action_name: str, target: str, res: ResearchResult):
    """
    Optionally logs scraped result as a [HYPOTHESIS] epistemic item if requested.
    Scraped raw web data MUST be tagged as [HYPOTHESIS] so agents are required to
    cross-check and verify evidence before promoting claims to [PROVEN].
    """
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
        claim = f"Retrieved {action_name} research candidate: '{target}' ({res.title or 'Untitled'})"
        evidence_content = res.to_markdown()
        evidence_snippet = evidence_content[:1500] if len(evidence_content) > 1500 else evidence_content
        # Log as HYPOTHESIS candidate evidence
        session.log_epistemic_item("HYPOTHESIS", claim, evidence_snippet)
    except Exception as e:
        logger.warning(f"Could not auto-log epistemic hypothesis for {action_name}: {e}")


def _handle_scrape_web(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'query' for scrape_web."
    res = scrape_web(target)
    _auto_log_epistemic_if_requested(args, "scrape_web", target, res)
    return res.to_markdown()


def _handle_scrape_youtube(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'video_id' for scrape_youtube."
    res = scrape_youtube(target)
    _auto_log_epistemic_if_requested(args, "scrape_youtube", target, res)
    return res.to_markdown()


def _handle_scrape_reddit(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'subreddit' for scrape_reddit."
    res = scrape_reddit(target)
    _auto_log_epistemic_if_requested(args, "scrape_reddit", target, res)
    return res.to_markdown()


def _handle_scrape_x(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'url' or 'handle' for scrape_x."
    res = scrape_x(target)
    _auto_log_epistemic_if_requested(args, "scrape_x", target, res)
    return res.to_markdown()


def _handle_scrape_github(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'repo' or 'query' for scrape_github."
    res = scrape_github(target)
    _auto_log_epistemic_if_requested(args, "scrape_github", target, res)
    return res.to_markdown()


def _handle_scrape_arxiv(args: Dict[str, Any]) -> str:
    target = _get_target_from_args(args)
    if not target:
        return "Error: Missing required parameter 'target' or 'paper_id' or 'query' for scrape_arxiv."
    res = scrape_arxiv(target)
    _auto_log_epistemic_if_requested(args, "scrape_arxiv", target, res)
    return res.to_markdown()
