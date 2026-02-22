from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.models import Article
from app.core.scrapers.base import BaseScraper
from app.core.fetchers.base import BaseFetcher
from app.core.logging import get_logger

log = get_logger()


def _is_probably_ad_url(href: str) -> bool:
    h = (href or "").lower()
    bad = ("doubleclick", "googleadservices", "googlesyndication", "taboola", "outbrain")
    if any(b in h for b in bad):
        return True
    if "utm_" in h or "gclid=" in h or "fbclid=" in h:
        return True
    return False


def _same_site(base_url: str, href: str) -> bool:
    try:
        b = urlparse(base_url)
        u = urlparse(href)
        return (u.netloc or b.netloc) == b.netloc
    except Exception:
        return False


class QueenOfTheRoadTestDrivesScraper(BaseScraper):
    """
    Listing page contains cards like:
      <div class="elementor-post__card"> ... <a class="elementor-post__thumbnail__link" href="...">

    Pagination example:
      <a class="page-numbers" href=".../page/2/">2</a>
      <a class="next page-numbers" href=".../page/3/">הבא</a>

    Article page:
      <h1 class="elementor-heading-title ...">...</h1>
      many <p>...</p>
    """

    def __init__(self, fetcher: BaseFetcher, concurrency: int = 10) -> None:
        self.fetcher = fetcher
        self.concurrency = concurrency

        # Optional runtime flag (router sets scraper.close_ads)
        self.close_ads: bool = True

        # Safety to prevent infinite pagination loops
        self.max_pages: int = 200

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        urls: list[str] = []
        visited_pages: set[str] = set()

        next_page_url: Optional[str] = start_url
        page_i = 0

        while next_page_url:
            if next_page_url in visited_pages:
                log.info("[queenoftheroad] Pagination loop detected, stopping at: %s", next_page_url)
                break

            if page_i >= self.max_pages:
                log.info("[queenoftheroad] Reached max_pages=%d, stopping.", self.max_pages)
                break

            visited_pages.add(next_page_url)
            page_i += 1

            html = await self.fetcher.get_html(next_page_url)
            soup = BeautifulSoup(html, "lxml")

            cards = soup.select("div.elementor-post__card")
            log.info(
                "[queenoftheroad] Page %d: %s | cards=%d | urls_total=%d",
                page_i,
                next_page_url,
                len(cards),
                len(urls),
            )

            # If the page has no cards, often it means:
            # - blocked HTML
            # - different template
            # - end of pagination
            if not cards:
                log.info("[queenoftheroad] No cards found on page, stopping pagination.")
                break

            # --------------------------------------------------
            # Extract article URLs from current page
            # --------------------------------------------------
            added_this_page = 0
            for card in cards:
                a = card.select_one("a.elementor-post__thumbnail__link[href]") or card.select_one(
                    "h3.elementor-post__title a[href]"
                )
                if not a:
                    continue

                href = (a.get("href") or "").strip()
                if not href:
                    continue

                full = urljoin(start_url, href)

                if _is_probably_ad_url(full):
                    continue
                if not _same_site(start_url, full):
                    continue

                if full not in urls:
                    urls.append(full)
                    added_this_page += 1

                if limit and len(urls) >= limit:
                    log.info("[queenoftheroad] Limit reached (%d).", limit)
                    return urls

            log.info("[queenoftheroad] Added %d URLs from this page.", added_this_page)

            # --------------------------------------------------
            # Find next page link (robust)
            # --------------------------------------------------
            next_link: Optional[str] = None

            # 1) Best: WordPress standard "next" page button
            a_next = soup.select_one("a.next.page-numbers[href], a.page-numbers.next[href]")
            if a_next and a_next.get("href"):
                next_link = a_next.get("href")

            # 2) Also accept rel="next"
            if not next_link:
                rel_next = soup.select_one("a[rel='next'][href]")
                if rel_next and rel_next.get("href"):
                    next_link = rel_next.get("href")

            # 3) Fallback: any pagination link that looks like a page link
            #    Support both /page/2/ and ?paged=2
            if not next_link:
                for a in soup.select("a.page-numbers[href]"):
                    href = (a.get("href") or "").strip()
                    if not href:
                        continue

                    if ("/page/" not in href) and ("paged=" not in href):
                        continue

                    candidate = urljoin(start_url, href)
                    if candidate not in visited_pages:
                        next_link = candidate
                        break

            if not next_link:
                log.info("[queenoftheroad] No next page link found. Done.")
                break

            next_page_url = urljoin(start_url, next_link)
            log.info("[queenoftheroad] Next page -> %s", next_page_url)

        log.info("[queenoftheroad] Discovery finished. Total URLs=%d", len(urls))
        return urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        # Title
        h1 = (
            soup.select_one("h1.elementor-heading-title")
            or soup.select_one("h1.entry-title")
            or soup.select_one("article h1")
        )
        title = (h1.get_text(" ", strip=True) if h1 else "").strip()

        # Content root (Elementor post content is usually here)
        content_root = (
            soup.select_one("div.elementor-widget-theme-post-content")
            or soup.select_one("div.elementor-location-single")
            or soup.select_one("article")
            or soup
        )

        ps: list[str] = []
        for p in content_root.select("p"):
            txt = p.get_text(" ", strip=True)
            if txt:
                ps.append(txt)

        body_text = "\n\n".join(ps).strip()

        return Article(
            url=url,
            title=title,
            content=body_text,
            raw_html=html,
        )