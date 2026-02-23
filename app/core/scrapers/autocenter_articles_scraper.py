from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlencode, urlparse, parse_qs, urlunparse

from bs4 import BeautifulSoup

from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.models import Article
from app.core.scrapers.base import BaseScraper


BASE = "https://www.autocenter.co.il"


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def _abs_url(href: str) -> str:
    return urljoin(BASE, (href or "").strip())


def _set_page_param(url: str, page: int) -> str:
    p = urlparse(url)
    qs = parse_qs(p.query)
    qs["p"] = [str(page)]
    new_q = urlencode(qs, doseq=True)
    # ✅ urlunparse needs 6 items: scheme, netloc, path, params, query, fragment
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, ""))


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _is_listing_url(u: str) -> bool:
    return u.rstrip("/") == (BASE + "/articles").rstrip("/")


def _looks_like_article_url(u: str) -> bool:
    if not u:
        return False
    if "/articles/" not in u:
        return False
    if _is_listing_url(u):
        return False
    return True


# -------------------------------------------------
# Scraper
# -------------------------------------------------
@dataclass
class AutoCenterArticlesScraper(BaseScraper):
    pw: PlaywrightFetcher
    concurrency: int = 10

    # very safe selector
    listing_wait_selector: str = "body"
    article_wait_selector: str = "body"

    # -------------------------------------------------
    # DISCOVERY
    # -------------------------------------------------
    async def discover_article_urls(
        self,
        start_url: str,
        limit: Optional[int] = None
    ) -> list[str]:

        seen: set[str] = set()
        out: list[str] = []

        max_pages = 30

        for page in range(1, max_pages + 1):
            url = start_url if page == 1 else _set_page_param(start_url, page)

            html = await self.pw.get_html(
                url,
                wait_for_selector=self.listing_wait_selector,
                wait_state="attached",
                extra_wait_ms=1500,
                wait_networkidle=False,
                scroll_steps=6,
                scroll_wait_ms=800,
            )

            # ✅ never crash if blocked
            if not html or len(html) < 100:
                break

            soup = BeautifulSoup(html, "lxml")

            anchors = soup.select("a[href]")
            new_count = 0

            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href:
                    continue

                full = href if href.startswith("http") else _abs_url(href)
                full = full.rstrip("/")

                if not _looks_like_article_url(full):
                    continue

                if full not in seen:
                    seen.add(full)
                    out.append(full)
                    new_count += 1

                    if limit and len(out) >= limit:
                        return out

            # stop paging when no new articles found
            if new_count == 0:
                break

        return out

    # -------------------------------------------------
    # FETCH ARTICLE
    # -------------------------------------------------
    async def fetch_article(self, url: str) -> Article:

        html = await self.pw.get_html(
            url,
            wait_for_selector=self.article_wait_selector,
            wait_state="attached",
            extra_wait_ms=1200,
            wait_networkidle=False,
            scroll_steps=2,
            scroll_wait_ms=600,
        )

        if not html:
            return Article(
                url=url,
                title="",
                content="",
                published=None,
                raw_html="",
            )

        soup = BeautifulSoup(html, "lxml")

        # -----------------------------
        # TITLE
        # -----------------------------
        title = ""
        h1 = soup.select_one("h1")
        if h1:
            title = _clean_text(h1.get_text(" ", strip=True))

        if not title:
            og = soup.select_one("meta[property='og:title']")
            if og and og.get("content"):
                title = _clean_text(og["content"])

        if not title and soup.title:
            title = _clean_text(soup.title.get_text(" ", strip=True))

        # -----------------------------
        # DATE
        # -----------------------------
        published: Optional[str] = None

        meta_pub = soup.select_one("meta[property='article:published_time']")
        if meta_pub and meta_pub.get("content"):
            published = _clean_text(meta_pub["content"])

        if not published:
            t = soup.select_one("time[datetime]")
            if t and t.get("datetime"):
                published = _clean_text(t["datetime"])

        if not published:
            txt = soup.get_text(" ", strip=True)
            m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", txt)
            if m:
                published = m.group(1)

        # -----------------------------
        # CONTENT
        # -----------------------------
        content_root = (
            soup.select_one(".magefan-blog-post")
            or soup.select_one(".post-view")
            or soup.select_one("article")
            or soup.select_one("main")
            or soup
        )

        paragraphs: list[str] = []

        for p in content_root.select("div[data-content-type='text'] p, article p, p"):
            text = _clean_text(p.get_text(" ", strip=True))
            if not text:
                continue
            if "JavaScript is disabled" in text:
                continue
            paragraphs.append(text)

        # de-duplicate
        seen_p: set[str] = set()
        cleaned: list[str] = []

        for t in paragraphs:
            if t not in seen_p:
                seen_p.add(t)
                cleaned.append(t)

        content = "\n".join(cleaned).strip()

        return Article(
            url=url,
            title=title,
            content=content,
            published=published,
            raw_html=html,
        )