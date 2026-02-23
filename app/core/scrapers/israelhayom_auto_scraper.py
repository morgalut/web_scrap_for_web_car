from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.core.fetchers.base import BaseFetcher
from app.core.models import Article
from app.core.scrapers.base import BaseScraper


_BASE = "https://www.israelhayom.co.il"


def _clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            t = _clean_text(el.get_text(" ", strip=True))
            if t:
                return t
    return ""


def _first_attr(soup: BeautifulSoup, selectors: list[str], attr: str) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.has_attr(attr):
            v = (el.get(attr) or "").strip()
            if v:
                return v
    return ""


def _parse_iso(dt: str) -> Optional[datetime]:
    # Handles: 2026-02-11T07:51:39.000Z
    try:
        if dt.endswith("Z"):
            return datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return datetime.fromisoformat(dt)
    except Exception:
        return None


def _parse_il_datetime_from_text(page_text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Best-effort parse of strings like:
      "11/2/2026, 05:51, עודכן 11/2/2026, 06:00"
    Returns (published_at, updated_at) in UTC (naive fallback if parsing fails).
    """
    # published: dd/mm/yyyy, HH:MM  OR d/m/yyyy, HH:MM
    pub_m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{2}):(\d{2})", page_text)
    upd_m = re.search(r"עודכן\s*(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{2}):(\d{2})", page_text)

    def _to_dt(m: re.Match) -> Optional[datetime]:
        try:
            d, mo, y, hh, mm = map(int, m.groups())
            # Treat as local Israel time; store as UTC to be consistent.
            # If you prefer local tz-aware, you can use zoneinfo("Asia/Jerusalem").
            local = datetime(y, mo, d, hh, mm)
            return local.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    pub_dt = _to_dt(pub_m) if pub_m else None
    upd_dt = _to_dt(upd_m) if upd_m else None
    return pub_dt, upd_dt


class IsraelHayomAutoScraper(BaseScraper):
    """
    Scrapes IsraelHayom Auto section:
      Listing: https://www.israelhayom.co.il/auto
      Articles: https://www.israelhayom.co.il/auto/article/<id>
    """

    def __init__(self, fetcher: BaseFetcher, concurrency: int = 12) -> None:
        self.fetcher = fetcher
        self.concurrency = concurrency

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        html = await self.fetcher.get_html(start_url)
        soup = BeautifulSoup(html, "lxml")

        urls: list[str] = []
        seen: set[str] = set()

        # Primary: any /auto/article/<id> link
        for a in soup.select("a[href^='/auto/article/']"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            abs_url = urljoin(_BASE, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            urls.append(abs_url)
            if limit and len(urls) >= limit:
                break

        # Fallback: sometimes links can appear without /auto prefix (rare)
        if not urls:
            for a in soup.select("article a[href]"):
                href = (a.get("href") or "").strip()
                if "/article/" in href:
                    abs_url = urljoin(_BASE, href)
                    if abs_url not in seen:
                        seen.add(abs_url)
                        urls.append(abs_url)
                        if limit and len(urls) >= limit:
                            break

        return urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        # Title: prefer h1 (page has it), else titleText span, else og:title
        title = _first_text(
            soup,
            [
                "h1 .titleText",
                "h1",
                "h3.post-title .titleText",
                "meta[property='og:title']",
                "title",
            ],
        )
        if not title:
            title = url  # last-resort

        # Subtitle (often h2 under title)
        subtitle = _first_text(soup, ["h2", ".post-subtitle", ".article-subtitle"])

        # Author: writer link
        author = _first_text(soup, ["a[href^='/writer/']"])

        # Published datetime:
        # - listing uses <time datetime="...Z">
        # - article page may have time tags OR just text like "11/2/2026, 05:51..."
        published_at: Optional[datetime] = None
        updated_at: Optional[datetime] = None

        iso_dt = _first_attr(soup, ["time[datetime]"], "datetime")
        if iso_dt:
            published_at = _parse_iso(iso_dt)

        if not published_at:
            page_text = soup.get_text(" ", strip=True)
            pub_dt, upd_dt = _parse_il_datetime_from_text(page_text)
            published_at = pub_dt
            updated_at = upd_dt

        # Content: collect meaningful paragraphs (avoid nav/footer)
        paras: list[str] = []
        for p in soup.select(
            "article p, .article-content p, .post-content p, .entry-content p, main p"
        ):
            t = _clean_text(p.get_text(" ", strip=True))
            # filter tiny / junk lines
            if len(t) < 25:
                continue
            if "טעינו? נתקן" in t:
                continue
            paras.append(t)

        # Deduplicate consecutive duplicates
        cleaned: list[str] = []
        for t in paras:
            if not cleaned or cleaned[-1] != t:
                cleaned.append(t)

        content = "\n\n".join(cleaned).strip()

        # Image: prefer og:image, else first meaningful img
        image_url = _first_attr(soup, ["meta[property='og:image']", "meta[name='twitter:image']"], "content")
        if not image_url:
            img = soup.select_one("article img[src], main img[src]")
            if img and img.get("src"):
                image_url = urljoin(_BASE, img.get("src"))

        # NOTE: adapt fields to your Article model if names differ.
        # Common pattern is Article(url=..., title=..., content=..., author=..., published_at=...)
        return Article(
            url=url,
            title=title,
            content=content,
            published=published_at.isoformat() if published_at else None,
            raw_html=html,
        )