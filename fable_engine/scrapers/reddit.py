"""
Reddit threads and subreddits scraper implementation using Reddit's public JSON interface (.json).
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, fetch_url


class RedditScraper(ResearchSource):
    source_type = "reddit"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 10000) -> ResearchResult:
        target = target.strip()
        if not target:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url="",
                error="Target Reddit URL, subreddit, or search query cannot be empty."
            )

        if target.startswith("http://") or target.startswith("https://"):
            clean_url = target.split("?")[0].rstrip("/")
            url = clean_url + ".json"
            canonical_url = clean_url
        elif target.startswith("r/") or target.startswith("/r/"):
            sub_path = target.lstrip("/").rstrip("/")
            url = f"https://www.reddit.com/{sub_path}/hot.json?limit=10"
            canonical_url = f"https://www.reddit.com/{sub_path}"
        else:
            query_enc = urllib.parse.quote(target)
            url = f"https://www.reddit.com/search.json?q={query_enc}&limit=10"
            canonical_url = f"https://www.reddit.com/search?q={query_enc}"

        try:
            json_str = fetch_url(url, timeout=timeout)
            data = json.loads(json_str)

            # Handle single thread post response (list of listings)
            if isinstance(data, list) and len(data) >= 1 and isinstance(data[0], dict):
                children = data[0].get("data", {}).get("children", [])
                if not children or not isinstance(children[0], dict):
                    return ResearchResult(
                        ok=False,
                        source_type=self.source_type,
                        canonical_url=canonical_url,
                        error="Reddit post data structure was empty or unexpected."
                    )

                post_data = children[0].get("data", {})
                title = post_data.get("title", "Reddit Post")
                subreddit = post_data.get("subreddit", "")
                author = post_data.get("author", "[deleted]")
                score = post_data.get("score", 0)
                selftext = post_data.get("selftext", "")
                permalink = post_data.get("permalink", "")
                post_url = f"https://www.reddit.com{permalink}" if permalink else canonical_url

                content_blocks = [
                    f"**Subreddit**: r/{subreddit} | **Author**: u/{author} | **Score**: {score}\n"
                ]
                if selftext:
                    content_blocks.append(f"## Post Text\n{selftext}\n")

                if len(data) >= 2 and isinstance(data[1], dict):
                    comments = data[1].get("data", {}).get("children", [])
                    comment_lines = ["## Top Comments\n"]
                    count = 0
                    for c in comments:
                        if count >= 10:
                            break
                        if isinstance(c, dict):
                            cdata = c.get("data", {})
                            c_author = cdata.get("author", "")
                            c_body = cdata.get("body", "")
                            c_score = cdata.get("score", 0)
                            if c_body:
                                comment_lines.append(f"### u/{c_author} ({c_score} points)")
                                comment_lines.append(f"{c_body}\n")
                                count += 1
                    if count > 0:
                        content_blocks.extend(comment_lines)

                full_content = "\n".join(content_blocks)
                if len(full_content) > max_content_length:
                    full_content = full_content[:max_content_length] + "\n\n*(Content truncated)*"

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=post_url,
                    title=title,
                    author=f"u/{author}",
                    content=full_content,
                    metadata={"subreddit": subreddit, "score": score}
                )

            # Handle subreddit listing or search results
            elif isinstance(data, dict) and "data" in data:
                children = data.get("data", {}).get("children", [])
                if not children:
                    return ResearchResult(
                        ok=True,
                        source_type=self.source_type,
                        canonical_url=canonical_url,
                        title=f"Reddit Listing: '{target}'",
                        content="*(No posts found for this subreddit or query)*"
                    )

                items = ["## Posts\n"]
                for child in children[:10]:
                    if isinstance(child, dict):
                        p = child.get("data", {})
                        p_title = p.get("title", "")
                        p_sub = p.get("subreddit", "")
                        p_author = p.get("author", "")
                        p_score = p.get("score", 0)
                        p_comments = p.get("num_comments", 0)
                        p_permalink = f"https://www.reddit.com{p.get('permalink', '')}"
                        p_text = p.get("selftext", "")[:250]
                        text_str = f"\n  _{p_text.strip()}..._" if p_text else ""
                        items.append(f"- **[{p_title}]({p_permalink})**")
                        items.append(f"  *r/{p_sub} | u/{p_author} | Score: {p_score} | Comments: {p_comments}*{text_str}\n")

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=canonical_url,
                    title=f"Reddit Listing: '{target}'",
                    content="\n".join(items)
                )

            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error="Unexpected JSON response format from Reddit API."
            )
        except Exception as e:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error=f"Reddit fetch failed: {str(e)}"
            )


def scrape_reddit(target: str, timeout: int = 15) -> ResearchResult:
    return RedditScraper().fetch(target, timeout=timeout)
