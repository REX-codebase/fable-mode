"""
YouTube metadata, search, and caption track scraper implementation.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional

from fable_engine.scrapers.base import ResearchResult, ResearchSource, fetch_url


class YouTubeScraper(ResearchSource):
    source_type = "youtube"

    def fetch(self, target: str, timeout: int = 15, max_content_length: int = 8000) -> ResearchResult:
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
            # YouTube search resolution
            try:
                query_enc = urllib.parse.quote(target)
                search_url = f"https://www.youtube.com/results?search_query={query_enc}"
                html = fetch_url(search_url, timeout=timeout)
                vids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
                if vids:
                    video_id = vids[0]
                else:
                    return ResearchResult(
                        ok=False,
                        source_type=self.source_type,
                        canonical_url=search_url,
                        error=f"No video ID could be resolved for query '{target}'."
                    )
            except Exception as e:
                return ResearchResult(
                    ok=False,
                    source_type=self.source_type,
                    canonical_url=f"https://www.youtube.com/results?search_query={urllib.parse.quote(target)}",
                    error=f"YouTube search resolution failed: {str(e)}"
                )

        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            html = fetch_url(canonical_url, timeout=timeout)

            title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html) or re.search(r'"title":"([^"]+)"', html)
            title = title_match.group(1) if title_match else f"YouTube Video ({video_id})"
            title = re.sub(r"\\u0026", "&", title)

            channel_match = re.search(r'<link itemprop="name" content="([^"]+)"', html) or re.search(r'"author":"([^"]+)"', html)
            channel = channel_match.group(1) if channel_match else "Unknown Channel"

            desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            description = desc_match.group(1) if desc_match else ""

            transcript_text = ""
            captions_match = re.search(r'"captionTracks":\[(.*?)\]', html)
            if captions_match:
                try:
                    tracks_json = json.loads(f"[{captions_match.group(1)}]")
                    if tracks_json and isinstance(tracks_json[0], dict) and "baseUrl" in tracks_json[0]:
                        caption_url = tracks_json[0]["baseUrl"]
                        caption_xml = fetch_url(caption_url, timeout=timeout)
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

            content_blocks = [f"**Channel**: {channel}\n"]
            if description:
                content_blocks.append(f"## Description\n{description[:1000]}\n")
            if transcript_text:
                if len(transcript_text) > max_content_length:
                    transcript_text = transcript_text[:max_content_length] + "...\n*(Transcript truncated)*"
                content_blocks.append(f"## Transcript / Captions\n{transcript_text}")
            else:
                content_blocks.append("*(Note: Automated transcript track was unavailable or missing for this video)*")

            return ResearchResult(
                ok=True,
                source_type=self.source_type,
                canonical_url=canonical_url,
                title=title,
                author=channel,
                content="\n".join(content_blocks),
                metadata={"video_id": video_id, "has_transcript": bool(transcript_text)}
            )
        except Exception as e:
            return ResearchResult(
                ok=False,
                source_type=self.source_type,
                canonical_url=canonical_url,
                error=f"YouTube video scrape failed: {str(e)}"
            )


def scrape_youtube(target: str, timeout: int = 15) -> ResearchResult:
    return YouTubeScraper().fetch(target, timeout=timeout)
