"""
Web page and search query scraper implementation.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, SimpleHTMLTextExtractor, fetch_url


class WebScraper(ResearchSource):
    source_type = "web"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 12000) -> ResearchResult:
        target = target.strip()
        if not target:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url="",
                error="Target URL or query string cannot be empty."
            )

        if target.startswith("http://") or target.startswith("https://"):
            try:
                html = fetch_url(target, timeout=timeout)
                parser = SimpleHTMLTextExtractor()
                parser.feed(html)
                title = parser.title.strip() or target
                content = parser.get_markdown()
                if len(content) > max_content_length:
                    content = content[:max_content_length] + "\n\n*(Content truncated for size)*"

                links_md = ""
                if parser.links:
                    seen = set()
                    link_lines = []
                    for text, href in parser.links[:15]:
                        full_url = urllib.parse.urljoin(target, href)
                        if full_url not in seen and text:
                            seen.add(full_url)
                            link_lines.append(f"- [{text}]({full_url})")
                    if link_lines:
                        links_md = "\n\n## Key Links\n" + "\n".join(link_lines)

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=target,
                    title=title,
                    content=f"## Web Page Content\n{content}{links_md}"
                )
            except Exception as e:
                return ResearchResult(
                    ok=False,
                    source_type=self.source_type,
                    canonical_url=target,
                    error=f"Web page fetch failed: {str(e)}"
                )
        else:
            # DuckDuckGo HTML Search
            try:
                query_enc = urllib.parse.quote(target)
                ddg_url = f"https://html.duckduckgo.com/html/?q={query_enc}"
                html = fetch_url(ddg_url, timeout=timeout)

                results = []
                result_blocks = re.findall(
                    r'<a class="result__url" href="([^"]+)".*?</a>.*?<a class="result__snippet[^"]*">(.*?)</a>',
                    html,
                    re.DOTALL
                )
                if not result_blocks:
                    urls = re.findall(r'class="result__a" href="([^"]+)">([^<]+)</a>', html)
                    snippets = re.findall(r'class="result__snippet[^"]*">(.*?)</span>', html)
                    for i in range(min(len(urls), 10)):
                        raw_url, title = urls[i]
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
                    parser = SimpleHTMLTextExtractor()
                    parser.feed(html)
                    content = parser.get_markdown()[:max_content_length]
                    return ResearchResult(
                        ok=True,
                        source_type=self.source_type,
                        canonical_url=ddg_url,
                        title=f"Web Search: '{target}'",
                        content=content
                    )

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=ddg_url,
                    title=f"Web Search Results for: '{target}'",
                    content="\n".join(results)
                )
            except Exception as e:
                return ResearchResult(
                    ok=False,
                    source_type=self.source_type,
                    canonical_url=f"https://duckduckgo.com/html/?q={urllib.parse.quote(target)}",
                    error=f"Web search failed: {str(e)}"
                )


def scrape_web(target: str, timeout: int = 15) -> ResearchResult:
    return WebScraper().fetch(target, timeout=timeout)
