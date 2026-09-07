"""
Fable Engine Research Scrapers.
Zero-cost, standard-library based scraping utilities for Web, YouTube, Reddit, X (Twitter), GitHub, and arXiv.
All routines return clean, structured Markdown output suitable for LLM context and epistemic evidence logging.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 FableResearch/1.3.0"

_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def _fetch_url(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> str:
    """Helper to fetch raw string content from URL using urllib."""
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


class _SimpleHTMLTextExtractor(HTMLParser):
    """Simple HTML parser to convert web pages to readable Markdown."""

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
            self.chunks.append(f"\n\n### ")
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
        # Clean up excess whitespace/newlines
        cleaned = re.sub(r"\n\s*\n+", "\n\n", raw_text).strip()
        return cleaned


def scrape_web(target: str) -> str:
    """
    Scrapes a web page URL or performs a DuckDuckGo HTML web search query.
    Returns clean Markdown text.
    """
    target = target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        try:
            html = _fetch_url(target)
            parser = _SimpleHTMLTextExtractor()
            parser.feed(html)
            title = parser.title.strip() or target
            content = parser.get_markdown()
            # Truncate content if massive
            if len(content) > 12000:
                content = content[:12000] + "\n\n*(Content truncated for context size)*"

            md = [f"# Web Page: {title}", f"**URL**: {target}\n"]
            if content:
                md.append("## Content\n" + content)
            if parser.links:
                md.append("\n## Key Links")
                seen = set()
                count = 0
                for text, href in parser.links:
                    if count >= 15:
                        break
                    full_url = urllib.parse.urljoin(target, href)
                    if full_url not in seen and text:
                        seen.add(full_url)
                        md.append(f"- [{text}]({full_url})")
                        count += 1
            return "\n".join(md)
        except Exception as e:
            return f"# Web Scrape Error\n**Target**: {target}\n**Error**: {str(e)}"
    else:
        # Perform DuckDuckGo HTML Search
        try:
            query_enc = urllib.parse.quote(target)
            ddg_url = f"https://html.duckduckgo.com/html/?q={query_enc}"
            html = _fetch_url(ddg_url)

            # Extract search results from HTML
            results = []
            # Find result snippets in DuckDuckGo HTML
            result_blocks = re.findall(r'<a class="result__url" href="([^"]+)".*?</a>.*?<a class="result__snippet[^"]*">(.*?)</a>', html, re.DOTALL)
            if not result_blocks:
                # Alternate regex for DDG html
                urls = re.findall(r'class="result__a" href="([^"]+)">([^<]+)</a>', html)
                snippets = re.findall(r'class="result__snippet[^"]*">(.*?)</span>', html)
                for i in range(min(len(urls), 10)):
                    raw_url, title = urls[i]
                    # DDG url unwrapping
                    parsed_url = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query).get("uddg", [raw_url])[0]
                    snip = snippets[i] if i < len(snippets) else ""
                    snip_clean = re.sub(r"<[^>]+>", "", snip).strip()
                    title_clean = re.sub(r"<[^>]+>", "", title).strip()
                    results.append(f"### [{title_clean}]({parsed_url})\n**Snippet**: {snip_clean}\n")
            else:
                for raw_url, snip in result_blocks[:10]:
                    snip_clean = re.sub(r"<[^>]+>", "", snip).strip()
                    results.append(f"### [Result]({raw_url})\n**Snippet**: {snip_clean}\n")

            if not results:
                # Fallback: simple link extraction
                parser = _SimpleHTMLTextExtractor()
                parser.feed(html)
                content = parser.get_markdown()
                return f"# Web Search Results: '{target}'\n\n{content[:4000]}"

            md = [f"# Web Search Results for: '{target}'\n"]
            md.extend(results)
            return "\n".join(md)
        except Exception as e:
            return f"# Web Search Error\n**Query**: {target}\n**Error**: {str(e)}"


def scrape_youtube(target: str) -> str:
    """
    Scrapes YouTube video metadata and captions/transcripts.
    Accepts YouTube URL or 11-character video ID.
    """
    target = target.strip()
    video_id = None
    if "youtube.com" in target or "youtu.be" in target:
        parsed = urllib.parse.urlparse(target)
        if "youtu.be" in target:
            video_id = parsed.path.lstrip("/")
        else:
            qs = urllib.parse.parse_qs(parsed.query)
            video_id = qs.get("v", [None])[0]
    elif len(target) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", target):
        video_id = target

    if not video_id:
        # Search query fallback
        query_enc = urllib.parse.quote(target)
        search_url = f"https://www.youtube.com/results?search_query={query_enc}"
        try:
            html = _fetch_url(search_url)
            vids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
            titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}', html)
            if vids:
                video_id = vids[0]
            else:
                return f"# YouTube Scrape Error\nCould not resolve video ID or search results for target: '{target}'"
        except Exception as e:
            return f"# YouTube Scrape Error\n**Target**: {target}\n**Error**: {str(e)}"

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        html = _fetch_url(watch_url)

        # Extract title and description metadata
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(r'"title":"([^"]+)"', html)
        title = title_match.group(1) if title_match else f"YouTube Video ({video_id})"
        title = re.sub(r'\\u0026', '&', title)

        channel_match = re.search(r'<link itemprop="name" content="([^"]+)"', html) or re.search(r'"author":"([^"]+)"', html)
        channel = channel_match.group(1) if channel_match else "Unknown Channel"

        desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
        description = desc_match.group(1) if desc_match else ""

        # Attempt transcript extraction via playerCaptionsTracklistRenderer
        transcript_text = ""
        captions_match = re.search(r'"captionTracks":\[(.*?)\]', html)
        if captions_match:
            try:
                tracks_json = json.loads(f"[{captions_match.group(1)}]")
                if tracks_json and "baseUrl" in tracks_json[0]:
                    caption_url = tracks_json[0]["baseUrl"]
                    caption_xml = _fetch_url(caption_url)
                    # Parse caption XML <text start="..." dur="...">text</text>
                    root = ET.fromstring(caption_xml)
                    lines = []
                    for child in root.findall("text"):
                        txt = child.text or ""
                        txt_clean = re.sub(r"&amp;", "&", txt)
                        txt_clean = re.sub(r"&#39;", "'", txt_clean)
                        txt_clean = re.sub(r"&quot;", '"', txt_clean)
                        if txt_clean.strip():
                            lines.append(txt_clean.strip())
                    transcript_text = " ".join(lines)
            except Exception:
                pass

        md = [
            f"# YouTube Video: {title}",
            f"**URL**: https://www.youtube.com/watch?v={video_id}",
            f"**Channel**: {channel}\n",
        ]
        if description:
            md.append(f"## Description\n{description[:1000]}\n")
        if transcript_text:
            if len(transcript_text) > 8000:
                transcript_text = transcript_text[:8000] + "...\n*(Transcript truncated)*"
            md.append(f"## Transcript / Captions\n{transcript_text}")
        else:
            md.append("*(No automated transcript available for this video)*")

        return "\n".join(md)
    except Exception as e:
        return f"# YouTube Scrape Error\n**Video ID**: {video_id}\n**Error**: {str(e)}"


def scrape_reddit(target: str) -> str:
    """
    Scrapes Reddit thread or subreddit using Reddit's public JSON interface (`.json`).
    Accepts Reddit URL, subreddit path (e.g. `r/python`), or query.
    """
    target = target.strip()
    url = ""
    if target.startswith("http://") or target.startswith("https://"):
        url = target.split("?")[0].rstrip("/") + ".json"
    elif target.startswith("r/"):
        url = f"https://www.reddit.com/{target.rstrip('/')}/hot.json?limit=10"
    else:
        query_enc = urllib.parse.quote(target)
        url = f"https://www.reddit.com/search.json?q={query_enc}&limit=10"

    try:
        json_str = _fetch_url(url, headers={"User-Agent": USER_AGENT})
        data = json.loads(json_str)

        # Handle post thread response (list of 2 listings)
        if isinstance(data, list) and len(data) >= 1:
            post_data = data[0]["data"]["children"][0]["data"]
            title = post_data.get("title", "Reddit Post")
            subreddit = post_data.get("subreddit", "")
            author = post_data.get("author", "[deleted]")
            score = post_data.get("score", 0)
            selftext = post_data.get("selftext", "")
            post_url = f"https://www.reddit.com{post_data.get('permalink', '')}"

            md = [
                f"# Reddit Post: {title}",
                f"**Subreddit**: r/{subreddit} | **Author**: u/{author} | **Score**: {score}",
                f"**URL**: {post_url}\n",
            ]
            if selftext:
                md.append(f"## Post Text\n{selftext}\n")

            # Extract top comments
            if len(data) >= 2 and "data" in data[1]:
                comments = data[1]["data"]["children"]
                md.append("## Top Comments\n")
                comment_count = 0
                for c in comments:
                    if comment_count >= 10:
                        break
                    cdata = c.get("data", {})
                    c_author = cdata.get("author", "")
                    c_body = cdata.get("body", "")
                    c_score = cdata.get("score", 0)
                    if c_body:
                        md.append(f"### u/{c_author} ({c_score} points)")
                        md.append(f"{c_body}\n")
                        comment_count += 1
            return "\n".join(md)

        # Handle subreddit / search listing (single dict response)
        elif isinstance(data, dict) and "data" in data:
            children = data["data"].get("children", [])
            md = [f"# Reddit Listing for: '{target}'\n"]
            for child in children[:10]:
                p = child.get("data", {})
                p_title = p.get("title", "")
                p_sub = p.get("subreddit", "")
                p_author = p.get("author", "")
                p_score = p.get("score", 0)
                p_num_comments = p.get("num_comments", 0)
                p_permalink = f"https://www.reddit.com{p.get('permalink', '')}"
                p_text = p.get("selftext", "")[:300]
                if p_text:
                    p_text = f"\n  _{p_text.strip()}..._"
                md.append(f"- **[{p_title}]({p_permalink})**")
                md.append(f"  *r/{p_sub} | u/{p_author} | Score: {p_score} | Comments: {p_num_comments}*{p_text}\n")
            return "\n".join(md)

        return f"# Reddit Scrape\nUnexpected response format for target: {target}"
    except Exception as e:
        return f"# Reddit Scrape Error\n**Target**: {target}\n**Error**: {str(e)}"


def scrape_x(target: str) -> str:
    """
    Scrapes X (Twitter) tweets or profiles using Twitter syndication API & embed fallbacks.
    Accepts Tweet URL, handle (e.g. `@openai`), or query.
    """
    target = target.strip()
    tweet_id = None

    # Check for tweet ID in URL
    tweet_id_match = re.search(r"status(?:es)?/(\d+)", target)
    if tweet_id_match:
        tweet_id = tweet_id_match.group(1)

    if tweet_id:
        # Use CDN syndication endpoint (free public JSON endpoint)
        synd_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
        try:
            json_str = _fetch_url(synd_url)
            data = json.loads(json_str)

            text = data.get("text", "")
            user = data.get("user", {})
            name = user.get("name", "User")
            screen_name = user.get("screen_name", "unknown")
            created_at = data.get("created_at", "")
            likes = data.get("favorite_count", 0)
            retweets = data.get("retweet_count", 0)

            md = [
                f"# Tweet by @{screen_name} ({name})",
                f"**Date**: {created_at} | **Likes**: {likes} | **Retweets**: {retweets}",
                f"**URL**: https://x.com/{screen_name}/status/{tweet_id}\n",
                f"## Content\n{text}\n"
            ]
            return "\n".join(md)
        except Exception as e:
            # Fallback to web oembed API
            try:
                oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tweet_id}"
                json_str = _fetch_url(oembed_url)
                data = json.loads(json_str)
                author = data.get("author_name", "User")
                html_embed = data.get("html", "")
                parser = _SimpleHTMLTextExtractor()
                parser.feed(html_embed)
                text = parser.get_markdown()
                return f"# Tweet by {author}\n**URL**: https://x.com/i/status/{tweet_id}\n\n## Content\n{text}"
            except Exception:
                return f"# X / Twitter Scrape Error\n**Tweet ID**: {tweet_id}\n**Error**: {str(e)}"

    # Handle handle or query via Twitter oembed search or Nitter RSS / web fallback
    handle = target.lstrip("@")
    try:
        # Attempt free public embed query
        oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/{handle}"
        json_str = _fetch_url(oembed_url)
        data = json.loads(json_str)
        author = data.get("author_name", handle)
        html_embed = data.get("html", "")
        parser = _SimpleHTMLTextExtractor()
        parser.feed(html_embed)
        text = parser.get_markdown()
        return f"# X Profile / Query: @{handle}\n**Author**: {author}\n**URL**: https://x.com/{handle}\n\n## Summary\n{text}"
    except Exception as e:
        return f"# X / Twitter Scrape Error\n**Target**: {target}\n**Note**: For exact tweet scraping, provide full Tweet URL. Error: {str(e)}"


def scrape_github(target: str) -> str:
    """
    Scrapes GitHub repository details, README content, issues/PRs, or code search using GitHub REST API.
    Accepts repo string `owner/repo`, GitHub URL, or search query.
    """
    target = target.strip()
    repo_path = None

    if "github.com/" in target:
        parsed = urllib.parse.urlparse(target)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) >= 2:
            repo_path = f"{parts[0]}/{parts[1]}"
    elif re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", target):
        repo_path = target

    if repo_path:
        api_url = f"https://api.github.com/repos/{repo_path}"
        try:
            repo_json = _fetch_url(api_url, headers={"Accept": "application/vnd.github.v3+json"})
            data = json.loads(repo_json)

            name = data.get("full_name", repo_path)
            description = data.get("description", "No description provided.")
            stars = data.get("stargazers_count", 0)
            forks = data.get("forks_count", 0)
            language = data.get("language", "Unknown")
            default_branch = data.get("default_branch", "main")
            html_url = data.get("html_url", f"https://github.com/{repo_path}")

            md = [
                f"# GitHub Repository: {name}",
                f"**Stars**: {stars} | **Forks**: {forks} | **Language**: {language} | **Branch**: {default_branch}",
                f"**URL**: {html_url}\n",
                f"**Description**: {description}\n"
            ]

            # Fetch README raw content
            readme_url = f"https://raw.githubusercontent.com/{repo_path}/{default_branch}/README.md"
            try:
                readme_text = _fetch_url(readme_url)
                if len(readme_text) > 8000:
                    readme_text = readme_text[:8000] + "\n\n*(README truncated for size)*"
                md.append(f"## README.md\n{readme_text}")
            except Exception:
                md.append("*(README.md could not be retrieved automatically)*")

            return "\n".join(md)
        except Exception as e:
            return f"# GitHub Scrape Error\n**Repo**: {repo_path}\n**Error**: {str(e)}"

    # Search query fallback
    query_enc = urllib.parse.quote(target)
    search_url = f"https://api.github.com/search/repositories?q={query_enc}&per_page=10"
    try:
        search_json = _fetch_url(search_url, headers={"Accept": "application/vnd.github.v3+json"})
        data = json.loads(search_json)
        items = data.get("items", [])

        md = [f"# GitHub Repository Search Results for: '{target}'\n"]
        for item in items[:10]:
            full_name = item.get("full_name", "")
            desc = item.get("description", "") or "No description"
            stars = item.get("stargazers_count", 0)
            lang = item.get("language", "N/A")
            url = item.get("html_url", "")
            md.append(f"### [{full_name}]({url})")
            md.append(f"**Stars**: {stars} | **Language**: {lang}\n**Description**: {desc}\n")

        return "\n".join(md)
    except Exception as e:
        return f"# GitHub Search Error\n**Query**: {target}\n**Error**: {str(e)}"


def scrape_arxiv(target: str) -> str:
    """
    Scrapes arXiv academic research papers using arXiv public API.
    Accepts arXiv paper ID (e.g. `2301.12345`), URL, or search query string.
    """
    target = target.strip()
    paper_id = None

    if "arxiv.org/" in target:
        id_match = re.search(r"(?:abs|pdf)/([0-9]+\.[0-9]+(?:v[0-9]+)?)", target)
        if id_match:
            paper_id = id_match.group(1)
    elif re.match(r"^[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?$", target):
        paper_id = target

    if paper_id:
        api_url = f"https://export.arxiv.org/api/query?id_list={paper_id}"
    else:
        query_enc = urllib.parse.quote(target)
        api_url = f"https://export.arxiv.org/api/query?search_query=all:{query_enc}&max_results=5"

    try:
        xml_str = _fetch_url(api_url)
        root = ET.fromstring(xml_str)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        entries = root.findall("atom:entry", ns)
        if not entries:
            return f"# arXiv Search Results\nNo papers found for target: '{target}'"

        md = [f"# arXiv Papers for: '{target}'\n"]
        for entry in entries:
            title_elem = entry.find("atom:title", ns)
            title = re.sub(r"\s+", " ", title_elem.text).strip() if title_elem is not None and title_elem.text else "Untitled"

            id_elem = entry.find("atom:id", ns)
            entry_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""

            published_elem = entry.find("atom:published", ns)
            published = published_elem.text[:10] if published_elem is not None and published_elem.text else ""

            summary_elem = entry.find("atom:summary", ns)
            summary = re.sub(r"\s+", " ", summary_elem.text).strip() if summary_elem is not None and summary_elem.text else ""

            authors = []
            for author_elem in entry.findall("atom:author", ns):
                name_elem = author_elem.find("atom:name", ns)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            pdf_link = entry_id.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in entry_id else entry_id

            md.append(f"## {title}")
            md.append(f"**Authors**: {', '.join(authors)}")
            md.append(f"**Published**: {published} | **arXiv Link**: [{entry_id}]({entry_id}) | **PDF**: [{pdf_link}]({pdf_link})\n")
            md.append(f"### Abstract\n{summary}\n")

        return "\n".join(md)
    except Exception as e:
        return f"# arXiv Scrape Error\n**Target**: {target}\n**Error**: {str(e)}"
