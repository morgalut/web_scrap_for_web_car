from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import asyncio
import re
import httpx
from app.core.models import Article
from app.core.scrapers.base import BaseScraper
from app.core.fetchers.base import BaseFetcher


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = x.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _is_carwiz_magazine_article(href: str) -> bool:
    """
    Accept:  /magazine/<slug>
    Reject:  /magazine
             /magazine/page/<n>
    """
    if not href:
        return False

    def _path(u: str) -> str:
        if u.startswith("http"):
            return urlparse(u).path or ""
        return u

    path = _path(href)

    # Must be under /magazine/
    if not path.startswith("/magazine/"):
        return False

    # Reject listing and pagination
    if path.rstrip("/") == "/magazine":
        return False
    if path.startswith("/magazine/page/"):
        return False

    return True


@dataclass
class _Extracted:
    title: str
    text: str
    captions: list[str]


class CarwizMagazineScraper(BaseScraper):
    """
    Carwiz magazine (Next.js/MUI).
    - Listing: https://carwiz.co.il/magazine
    - Article:  https://carwiz.co.il/magazine/<slug>
    """

    def __init__(self, fetcher: BaseFetcher, concurrency: int = 10) -> None:
        self.fetcher = fetcher
        self.concurrency = concurrency

        # can be overridden from router (you already do this):
        self.request_delay_s = 0.0
        self.request_delay_jitter_s = 0.15
        self.close_ads = True

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        """
        Preflight:
        - detect how many pages exist (from pagination links)
        - count how many article links are on each page
        - wait before returning URLs (so fetch phase starts after preflight + wait)

        Crawl:
        /magazine
        /magazine/page/2
        /magazine/page/3
        ...
        """

        # You can override this from the router (like delay_s) if you want:
        # scraper.preflight_wait_s = 5.0
        preflight_wait_s = float(getattr(self, "preflight_wait_s", 3.0) or 0.0)

        def _listing_url_for_page(base: str, n: int) -> str:
            if n <= 1:
                return base
            return urljoin(base, f"/magazine/page/{n}")

        def _extract_page_numbers(soup: BeautifulSoup) -> list[int]:
            nums: list[int] = []
            for a in soup.select('a[aria-label^="Go to page"][href]'):
                label = (a.get("aria-label") or "").strip()
                # "Go to page 2"
                m = re.search(r"(\d+)", label)
                if m:
                    try:
                        nums.append(int(m.group(1)))
                    except Exception:
                        pass
            return nums

        async def _safe_get_html(u: str) -> tuple[Optional[str], Optional[str]]:
            """
            Returns (html, error_str). If 404 -> (None, '404').
            """
            try:
                html = await self.fetcher.get_html(u)
                return html, None
            except httpx.HTTPStatusError as e:
                # specifically stop on 404 pages
                if e.response is not None and e.response.status_code == 404:
                    return None, "404"
                return None, f"http_{getattr(e.response, 'status_code', 'error')}"
            except Exception as e:
                return None, type(e).__name__

        # ------------------------------------------------------------
        # 1) Load page 1 and detect max pages
        # ------------------------------------------------------------
        first_html, first_err = await _safe_get_html(start_url)
        if not first_html:
            # If magazine listing fails, return empty list (router will handle "no_urls")
            return []

        first_soup = BeautifulSoup(first_html, "lxml")
        page_nums = _extract_page_numbers(first_soup)
        max_pages = max(page_nums) if page_nums else 1

        # ------------------------------------------------------------
        # 2) Preflight: count links per page and gather URLs
        # ------------------------------------------------------------
        collected: list[str] = []
        per_page_counts: list[dict] = []

        for page_n in range(1, max_pages + 1):
            page_url = _listing_url_for_page(start_url, page_n)

            html, err = (first_html, None) if page_n == 1 else await _safe_get_html(page_url)
            if html is None:
                # If a later page 404s, it means pagination over-reported; stop gracefully
                per_page_counts.append(
                    {"page": page_n, "url": page_url, "article_links": 0, "status": err or "error"}
                )
                break

            soup = BeautifulSoup(html, "lxml")

            page_article_urls: list[str] = []
            for a in soup.select("a[href]"):
                href = (a.get("href") or "").strip()
                if _is_carwiz_magazine_article(href):
                    page_article_urls.append(urljoin(page_url, href))

            page_article_urls = _dedupe_keep_order(page_article_urls)
            per_page_counts.append(
                {"page": page_n, "url": page_url, "article_links": len(page_article_urls), "status": "ok"}
            )

            # Add into global
            collected.extend(page_article_urls)
            collected = _dedupe_keep_order(collected)

            if limit is not None and len(collected) >= int(limit):
                collected = collected[: int(limit)]
                break

        # ------------------------------------------------------------
        # 3) WAIT before returning (so fetch phase starts after this)
        # ------------------------------------------------------------
        total_links = len(collected)
        # (You can replace prints with your logger if you pass it in; this keeps it scraper-local)
        print(f"[carwiz] Preflight: detected max_pages≈{max_pages}")
        for row in per_page_counts:
            print(f"[carwiz] page={row['page']} links={row['article_links']} status={row['status']} url={row['url']}")
        print(f"[carwiz] Total unique article URLs: {total_links}")
        if preflight_wait_s > 0:
            print(f"[carwiz] Waiting {preflight_wait_s:.1f}s before starting fetch_many...")
            await asyncio.sleep(preflight_wait_s)

        return collected

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        extracted = self._extract_article(html)

        # Embed captions into content (no model/storage changes needed)
        content = extracted.text.strip()
        caps = [c.strip() for c in extracted.captions if c and c.strip()]
        caps = _dedupe_keep_order(caps)

        if caps:
            content = (
                f"{content}\n\n"
                f"---\n"
                f"CAPTIONS:\n"
                + "\n".join(f"- {c}" for c in caps)
            )

        return Article(
            url=url,
            title=extracted.title.strip() or "",
            content=content,
            published=None,
            raw_html=html,
        )

    def _extract_article(self, html: str) -> _Extracted:
        soup = BeautifulSoup(html, "lxml")

        # Title
        title = ""
        h1 = soup.select_one("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(" ", strip=True)
        if not title:
            og = soup.select_one('meta[property="og:title"]')
            if og and og.get("content"):
                title = og["content"].strip()
        if not title and soup.title and soup.title.get_text(strip=True):
            title = soup.title.get_text(" ", strip=True)

        # Find a reasonable “main content” root:
        # Prefer <main>, else the closest big container around h1, else <body>.
        root = soup.select_one("main")
        if root is None and h1 is not None:
            # climb a bit to find a container that likely holds the article
            cur = h1
            for _ in range(6):
                if cur is None or cur.parent is None:
                    break
                cur = cur.parent
                # heuristic: container with multiple paragraphs/headings
                if cur and len(cur.select("p, h2, h3, li")) >= 5:
                    root = cur
                    break
        if root is None:
            root = soup.body or soup

        # Captions: figcaption + meaningful img alts
        captions: list[str] = []
        for fc in root.select("figcaption"):
            t = fc.get_text(" ", strip=True)
            if t:
                captions.append(t)

        for img in root.select("img[alt]"):
            alt = (img.get("alt") or "").strip()
            if alt:
                captions.append(alt)

        # Text content: headings + paragraphs + list items
        # (Skip obvious nav/footer blocks if present)
        for bad in root.select("nav, footer, header"):
            bad.decompose()

        parts: list[str] = []
        for el in root.select("h1, h2, h3, h4, p, li"):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue

            # Avoid repeating title too many times
            if title and txt == title and parts:
                continue

            parts.append(txt)

        text = "\n\n".join(parts)
        return _Extracted(title=title, text=text, captions=captions)