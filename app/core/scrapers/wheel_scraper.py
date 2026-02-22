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
    raw = _clean_text(date_str)
    if not raw:
        return None

    raw = raw.replace(",", " ")
    parts = [p for p in raw.split(" ") if p]
    if len(parts) < 3:
        return None

    try:
        day = int(parts[0])
    except Exception:
        return None

    month_tok = parts[1]
    if month_tok.startswith("ב") and len(month_tok) > 1:
        month_tok = month_tok[1:]

    month = _HEB_MONTHS.get(month_tok)
    if not month:
        return None

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
    fetcher: BaseFetcher
    concurrency: int = 10

    request_delay_s: float = 0.0
    request_delay_jitter_s: float = 0.15
    close_ads: bool = False

    max_pages: int = 6

    # ----------------------------
    # Internal: HTML acquisition with PW fallback
    # ----------------------------
    async def _get_listing_html(self, url: str) -> str:
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
    # Pagination: page transition function ✅ NEW
    # ----------------------------
    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """
        Returns next page URL using:
        1) a.next.page-numbers[href] (WordPress "next" button)
        2) numeric links a.page-numbers[href] where text is a number (e.g. "2", "3")
           We choose the smallest numeric page that is > current numeric page.
        """
        # 1) Preferred: explicit "next"
        nxt = soup.select_one("a.next.page-numbers[href]")
        if nxt and nxt.get("href"):
            return urljoin(current_url, nxt["href"].strip())

        # 2) Fallback: numeric pagination links
        # Determine current page number:
        # - WP often marks current page as: <span class="page-numbers current">1</span>
        # - or can be inferred from URL containing "/page/<n>/"
        current_num = 1

        cur_span = soup.select_one("span.page-numbers.current")
        if cur_span:
            try:
                current_num = int(_clean_text(cur_span.get_text()))
            except Exception:
                current_num = 1
        else:
            # parse from URL if it contains /page/<n>/
            parts = current_url.rstrip("/").split("/")
            if "page" in parts:
                try:
                    i = parts.index("page")
                    current_num = int(parts[i + 1])
                except Exception:
                    current_num = 1

        # Collect numeric page links
        candidates: list[tuple[int, str]] = []
        for a in soup.select("a.page-numbers[href]"):
            txt = _clean_text(a.get_text())
            if not txt.isdigit():
                continue
            n = int(txt)
            href = a.get("href")
            if href:
                candidates.append((n, urljoin(current_url, href.strip())))

        # Choose next numeric page
        next_candidates = [c for c in candidates if c[0] > current_num]
        if not next_candidates:
            return None

        next_candidates.sort(key=lambda x: x[0])
        return next_candidates[0][1]

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

            # Primary: wrapper links
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

            # Fallback: try any link inside article cards
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

            # ✅ Use the new page transition function
            next_url = self._next_page_url(soup, next_url)

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
            published_str = published_at.date().isoformat()

        # Content
        content_text = ""
        content_el = soup.select_one("div.entry-content")
        if content_el:
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