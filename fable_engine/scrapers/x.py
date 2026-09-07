"""
X (Twitter) tweet syndication and oembed lookup scraper implementation.
Exact Tweet URLs utilize Twitter syndication API; handles/profiles use oEmbed embed summaries.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, SimpleHTMLTextExtractor, fetch_url


class XScraper(ResearchSource):
    source_type = "x"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 8000) -> ResearchResult:
        target = target.strip()
        if not target:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url="",
                error="Target Tweet URL or handle cannot be empty."
            )

        tweet_id = None
        tweet_id_match = re.search(r"status(?:es)?/(\d+)", target)
        if tweet_id_match:
            tweet_id = tweet_id_match.group(1)

        if tweet_id:
            # Use Twitter Syndication JSON API (free endpoint for individual tweets)
            synd_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
            canonical_url = f"https://x.com/i/status/{tweet_id}"
            try:
                json_str = fetch_url(synd_url, timeout=timeout)
                data = json.loads(json_str)

                text = data.get("text", "")
                user = data.get("user", {})
                name = user.get("name", "User")
                screen_name = user.get("screen_name", "unknown")
                created_at = data.get("created_at", "")
                likes = data.get("favorite_count", 0)
                retweets = data.get("retweet_count", 0)
                full_url = f"https://x.com/{screen_name}/status/{tweet_id}"

                content = (
                    f"**Date**: {created_at} | **Likes**: {likes} | **Retweets**: {retweets}\n\n"
                    f"## Tweet\n{text}"
                )

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=full_url,
                    title=f"Tweet by @{screen_name} ({name})",
                    author=f"@{screen_name}",
                    content=content,
                    metadata={"tweet_id": tweet_id, "likes": likes, "retweets": retweets}
                )
            except Exception as e:
                # Fallback to Twitter oEmbed API
                try:
                    oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tweet_id}"
                    json_str = fetch_url(oembed_url, timeout=timeout)
                    data = json.loads(json_str)
                    author = data.get("author_name", "User")
                    html_embed = data.get("html", "")
                    parser = SimpleHTMLTextExtractor()
                    parser.feed(html_embed)
                    text = parser.get_markdown()
                    return ResearchResult(
                        ok=True,
                        source_type=self.source_type,
                        canonical_url=canonical_url,
                        title=f"Tweet by {author}",
                        author=author,
                        content=f"## Content\n{text}"
                    )
                except Exception:
                    return ResearchResult(
                        ok=False,
                        source_type=self.source_type,
                        canonical_url=canonical_url,
                        error=f"X/Twitter tweet scrape failed for status ID {tweet_id}: {str(e)}"
                    )

        # Handle user profile / handle lookup via oembed
        handle = target.lstrip("@").strip()
        canonical_url = f"https://x.com/{handle}"
        try:
            oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/{handle}"
            json_str = fetch_url(oembed_url, timeout=timeout)
            data = json.loads(json_str)
            author = data.get("author_name", handle)
            html_embed = data.get("html", "")
            parser = SimpleHTMLTextExtractor()
            parser.feed(html_embed)
            text = parser.get_markdown()
            return ResearchResult(
                ok=True,
                source_type=self.source_type,
                canonical_url=canonical_url,
                title=f"X Profile / Handle: @{handle}",
                author=author,
                content=f"## Summary\n{text}"
            )
        except Exception as e:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error=(
                    f"X handle/profile lookup failed for '@{handle}': {str(e)}. "
                    "Note: For exact tweet contents, provide a direct Tweet status URL."
                )
            )


def scrape_x(target: str, timeout: int = 15) -> ResearchResult:
    return XScraper().fetch(target, timeout=timeout)
