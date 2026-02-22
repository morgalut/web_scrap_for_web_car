from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.core.fetchers.base import BaseFetcher
from app.core.models import Article
from app.core.scrapers.base import BaseScraper


# ----------------------------
# Helpers
# ----------------------------
_HEB_MONTHS = {
    "ינו": 1,
    "פבר": 2,
    "מרץ": 3,
    "אפר": 4,
    "מאי": 5,
    "יונ": 6,
    "יול": 7,
    "אוג": 8,
    "ספט": 9,
    "אוק": 10,
    "נוב": 11,
    "דצמ": 12,
    # full names
    "ינואר": 1,
    "פברואר": 2,
    "אפריל": 4,
    "יוני": 6,
    "יולי": 7,
    "אוגוסט": 8,
    "ספטמבר": 9,
    "אוקטובר": 10,
    "נובמבר": 11,
    "דצמבר": 12,
}


def _clean_text(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _parse_wheel_date(date_str: str) -> Optional[datetime]:
    """
    Examples:
      "16 בפבר, 2026"
      "16 בפבר 2026"
      "16 בפברואר 2026"
      "16 בינו, 2026"
    """
    raw = _clean_text(date_str)
    if not raw:
        return None

    raw = raw.replace(",", " ")
    parts = [p for p in raw.split(" ") if p]
    if len(parts) < 3:
        return None

    # day
    try:
        day = int(parts[0])
    except Exception:
        return None

    # month token might have leading "ב"
    month_tok = parts[1]
    if month_tok.startswith("ב") and len(month_tok) > 1:
        month_tok = month_tok[1:]

    month = _HEB_MONTHS.get(month_tok)
    if not month:
        return None

    # year
    try:
        year = int(parts[2])
    except Exception:
        return None

    try:
        return datetime(year, month, day)
    except Exception:
        return None


@dataclass
class WheelTestDrivesScraper(BaseScraper):
    """
    Wheel.co.il category scraper.

    Discovery:
    - Primary: <a class="catArtiBox" href="ARTICLE_URL"><article .../></a>
    - Pagination: a.next.page-numbers

    Fetch:
    - title: h1.entry-title (fallback og:title)
    - published: span.xb-date parsed to ISO YYYY-MM-DD (fallback meta article:published_time)
    - content: div.entry-content text
    - raw_html: full page HTML
    """
    fetcher: BaseFetcher
    concurrency: int = 10

    # Optional runtime knobs (router sets these)
    request_delay_s: float = 0.0
    request_delay_jitter_s: float = 0.15
    close_ads: bool = False

    # Safety bounds
    max_pages: int = 6

    # ----------------------------
    # Internal: HTML acquisition with PW fallback
    # ----------------------------
    async def _get_listing_html(self, url: str) -> str:
        """
        Wheel category pages sometimes need JS.
        Strategy:
        1) Try self.fetcher.get_html(url) (HTTPX or Hybrid)
        2) If no cards found AND Playwright is available, force PW and wait for cards.
        """
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        if soup.select_one("a.catArtiBox[href]") or soup.select_one("article[id^='post-']"):
            return html

        # Force Playwright if possible (HybridFetcher exposes .pw)
        pw = getattr(self.fetcher, "pw", None)
        if pw is not None:
            html = await pw.get_html(
                url,
                wait_for_selector="a.catArtiBox[href], article[id^='post-']",
                wait_state="attached",
                extra_wait_ms=300,
            )
        return html

    # ----------------------------
    # Discovery
    # ----------------------------
    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        next_url: Optional[str] = start_url
        pages = 0

        while next_url and pages < self.max_pages:
            pages += 1

            html = await self._get_listing_html(next_url)
            soup = BeautifulSoup(html, "lxml")

            # ✅ Primary: wrapper links
            cards = soup.select("a.catArtiBox[href]")
            for a in cards:
                href = a.get("href")
                if not href:
                    continue
                u = urljoin(next_url, href.strip())
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
                if limit and len(urls) >= limit:
                    return urls[:limit]

            # ✅ Fallback: try any link inside article cards
            if not cards:
                for art in soup.select("article[id^='post-']"):
                    a2 = art.select_one("a[href]")
                    if not a2 or not a2.get("href"):
                        continue
                    u = urljoin(next_url, a2["href"].strip())
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
                    if limit and len(urls) >= limit:
                        return urls[:limit]

            # Pagination
            nxt = soup.select_one("a.next.page-numbers[href]")
            next_url = urljoin(next_url, nxt["href"].strip()) if nxt else None

        return urls[:limit] if limit else urls

    # ----------------------------
    # Article fetch
    # ----------------------------
    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        # Title
        title = ""
        h1 = soup.select_one("h1.entry-title")
        if h1:
            title = _clean_text(h1.get_text(" ", strip=True))
        if not title:
            ogt = soup.select_one("meta[property='og:title'][content]")
            if ogt:
                title = _clean_text(ogt["content"])

        # Published date
        published_at: Optional[datetime] = None
        d = soup.select_one("span.xb-date")
        if d:
            published_at = _parse_wheel_date(d.get_text(" ", strip=True))

        if published_at is None:
            mtime = soup.select_one("meta[property='article:published_time'][content]")
            if mtime:
                try:
                    published_at = datetime.fromisoformat(mtime["content"].replace("Z", "+00:00"))
                except Exception:
                    published_at = None

        published_str: Optional[str] = None
        if published_at is not None:
            published_str = published_at.date().isoformat()  # "YYYY-MM-DD"

        # Content
        content_text = ""
        content_el = soup.select_one("div.entry-content")
        if content_el:
            # remove read-more block (if present)
            for rm in content_el.select("div.bMore"):
                rm.decompose()
            content_text = _clean_text(content_el.get_text(" ", strip=True))

        return Article(
            url=url,
            title=title or url,
            content=content_text or "",
            published=published_str,
            raw_html=html,
        )