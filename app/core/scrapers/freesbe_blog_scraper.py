from __future__ import annotations

from typing import Optional, Any, Dict
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.core.models import Article
from app.core.scrapers.base import BaseScraper
from app.core.fetchers.base import BaseFetcher


def _article_allowed_fields() -> set[str]:
    # Pydantic v2
    if hasattr(Article, "model_fields"):
        return set(getattr(Article, "model_fields").keys())

    # Pydantic v1
    if hasattr(Article, "__fields__"):
        return set(getattr(Article, "__fields__").keys())

    # dataclass
    if hasattr(Article, "__dataclass_fields__"):
        return set(getattr(Article, "__dataclass_fields__").keys())

    # fallback (rare)
    import inspect
    return set(inspect.signature(Article).parameters.keys())


def _make_article(**data: Any) -> Article:
    allowed = _article_allowed_fields()
    filtered = {k: v for k, v in data.items() if k in allowed}
    return Article(**filtered)


class FreesbeBlogScraper(BaseScraper):
    def __init__(self, fetcher: BaseFetcher, concurrency: int = 12) -> None:
        self.fetcher = fetcher
        self.concurrency = concurrency
        self.request_delay_s = 0.25
        self.request_delay_jitter_s = 0.15

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        html = await self.fetcher.get_html(start_url)
        soup = BeautifulSoup(html, "lxml")

        urls: list[str] = []
        seen: set[str] = set()

        for a in soup.select('a[href^="/blog/"]'):
            href = (a.get("href") or "").strip()
            if not href:
                continue

            parts = [p for p in href.split("/") if p]
            if len(parts) < 3:
                continue

            abs_url = urljoin(start_url.rstrip("/") + "/", href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            urls.append(abs_url)

            if limit is not None and len(urls) >= limit:
                break

        return urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        title_el = soup.select_one("h1#main-content") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else ""

        body = (
            soup.select_one("div.css-16n9ozw")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.body
        )

        text_content = body.get_text("\n", strip=True) if body else ""
        html_content = str(body) if body else html

        # Provide multiple candidate field names — _make_article filters to what your model supports
        return _make_article(
            url=url,
            title=title,

            # common names across projects
            text=text_content,
            content=text_content,
            body=text_content,
            article_text=text_content,

            html=html_content,
            content_html=html_content,
            raw_html=html_content,

            site="freesbe_blog",
            site_key="freesbe_blog",
            source="freesbe",
        )