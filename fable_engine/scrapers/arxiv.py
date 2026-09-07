"""
arXiv research paper and search query scraper implementation using arXiv export API.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, fetch_url


class ArxivScraper(ResearchSource):
    source_type = "arxiv"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 10000) -> ResearchResult:
        target = target.strip()
        if not target:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url="",
                error="Target arXiv paper ID or search query cannot be empty."
            )

        paper_id = None
        if "arxiv.org/" in target:
            id_match = re.search(r"(?:abs|pdf)/([0-9]+\.[0-9]+(?:v[0-9]+)?)", target)
            if id_match:
                paper_id = id_match.group(1)
        elif re.match(r"^[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?$", target):
            paper_id = target

        if paper_id:
            api_url = f"https://export.arxiv.org/api/query?id_list={paper_id}"
            canonical_url = f"https://arxiv.org/abs/{paper_id}"
        else:
            query_enc = urllib.parse.quote(target)
            api_url = f"https://export.arxiv.org/api/query?search_query=all:{query_enc}&max_results=5"
            canonical_url = f"https://arxiv.org/search/?query={query_enc}&searchtype=all"

        try:
            xml_str = fetch_url(api_url, timeout=timeout)
            root = ET.fromstring(xml_str)
            ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

            entries = root.findall("atom:entry", ns)
            if not entries:
                return ResearchResult(
                    ok=True,
                    source_type=self.source_type,
                    canonical_url=canonical_url,
                    title=f"arXiv Search: '{target}'",
                    content="*(No papers found for this query)*"
                )

            blocks = []
            first_title = ""
            first_author = ""
            for entry in entries:
                title_elem = entry.find("atom:title", ns)
                title = re.sub(r"\s+", " ", title_elem.text).strip() if title_elem is not None and title_elem.text else "Untitled"
                if not first_title:
                    first_title = title

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
                if not first_author and authors:
                    first_author = ", ".join(authors)

                pdf_link = entry_id.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in entry_id else entry_id

                blocks.append(f"## {title}")
                blocks.append(f"**Authors**: {', '.join(authors)}")
                blocks.append(f"**Published**: {published} | **arXiv**: [{entry_id}]({entry_id}) | **PDF**: [{pdf_link}]({pdf_link})\n")
                blocks.append(f"### Abstract\n{summary}\n")

            full_content = "\n".join(blocks)
            if len(full_content) > max_content_length:
                full_content = full_content[:max_content_length] + "\n\n*(Abstracts truncated)*"

            return ResearchResult(
                ok=True,
                source_type=self.source_type,
                canonical_url=canonical_url,
                title=first_title if paper_id else f"arXiv Papers for: '{target}'",
                author=first_author,
                content=full_content,
                metadata={"paper_count": len(entries)}
            )
        except Exception as e:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error=f"arXiv fetch failed: {str(e)}"
            )


def scrape_arxiv(target: str, timeout: int = 15) -> ResearchResult:
    return ArxivScraper().fetch(target, timeout=timeout)
