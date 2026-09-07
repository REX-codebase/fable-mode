"""
GitHub repository metadata, README content, and repository search scraper implementation.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, fetch_url


class GitHubScraper(ResearchSource):
    source_type = "github"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 8000) -> ResearchResult:
        target = target.strip()
        if not target:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url="",
                error="Target GitHub repository or search query cannot be empty."
            )

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
            canonical_url = f"https://github.com/{repo_path}"
            try:
                repo_json = fetch_url(api_url, headers={"Accept": "application/vnd.github.v3+json"}, timeout=timeout)
                data = json.loads(repo_json)

                name = data.get("full_name", repo_path)
                description = data.get("description", "No description provided.")
                stars = data.get("stargazers_count", 0)
                forks = data.get("forks_count", 0)
                language = data.get("language", "Unknown")
                default_branch = data.get("default_branch", "main")
                html_url = data.get("html_url", canonical_url)

                content_blocks = [
                    f"**Stars**: {stars} | **Forks**: {forks} | **Language**: {language} | **Branch**: {default_branch}\n",
                    f"**Description**: {description}\n"
                ]

                # Fetch README content
                readme_url = f"https://raw.githubusercontent.com/{repo_path}/{default_branch}/README.md"
                try:
                    readme_text = fetch_url(readme_url, timeout=timeout)
                    if len(readme_text) > max_content_length:
                        readme_text = readme_text[:max_content_length] + "\n\n*(README truncated for size)*"
                    content_blocks.append(f"## README.md\n{readme_text}")
                except Exception:
                    content_blocks.append("*(Note: README.md could not be retrieved automatically)*")

                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=html_url,
                    title=f"GitHub Repo: {name}",
                    author=repo_path.split("/")[0],
                    content="\n".join(content_blocks),
                    metadata={"stars": stars, "language": language}
                )
            except Exception as e:
                return ResearchResult(
                    ok=False,
                    source_type=self.source_type,
                    canonical_url=canonical_url,
                    error=f"GitHub repository fetch failed: {str(e)}"
                )

        # Repository Search Fallback
        query_enc = urllib.parse.quote(target)
        search_url = f"https://api.github.com/search/repositories?q={query_enc}&per_page=10"
        canonical_url = f"https://github.com/search?q={query_enc}"
        try:
            search_json = fetch_url(search_url, headers={"Accept": "application/vnd.github.v3+json"}, timeout=timeout)
            data = json.loads(search_json)
            items = data.get("items", [])

            if not items:
                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=canonical_url,
                    title=f"GitHub Search: '{target}'",
                    content="*(No repositories found for this query)*"
                )

            lines = ["## Repositories\n"]
            for item in items[:10]:
                full_name = item.get("full_name", "")
                desc = item.get("description", "") or "No description"
                stars = item.get("stargazers_count", 0)
                lang = item.get("language", "N/A")
                url = item.get("html_url", "")
                lines.append(f"### [{full_name}]({url})")
                lines.append(f"**Stars**: {stars} | **Language**: {lang}\n**Description**: {desc}\n")

            return ResearchResult(
                ok=True,
                source_type=self.source_type,
                canonical_url=canonical_url,
                title=f"GitHub Repository Search: '{target}'",
                content="\n".join(lines)
            )
        except Exception as e:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error=f"GitHub repository search failed: {str(e)}"
            )


def scrape_github(target: str, timeout: int = 15) -> ResearchResult:
    return GitHubScraper().fetch(target, timeout=timeout)
