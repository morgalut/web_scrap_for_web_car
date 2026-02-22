from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.core.models import Article
from app.core.fetchers.base import BaseFetcher
from app.core.scrapers.base import BaseScraper

class AutoCoIlTestDrivesScraper(BaseScraper):
    """
    Scraper for:
      https://www.auto.co.il/articles/test-drives/

    Discovery:
      ul#articles-lobby-items-container a.article-card[href]

    Article content:
      - Title:  .heading__title--h1_v2 h1
      - Lead:   .heading__subtitle--v3-mod p
      - Body:   .text-container.article-rte-section .text-wrapper
      - Summary (optional): .article-summary
      - FAQ (optional): .faq__container details[itemtype=Question] ...
    """

    def __init__(self, fetcher: BaseFetcher, concurrency: int = 12) -> None:
        self.fetcher = fetcher
        self.concurrency = max(1, concurrency)

    # -------------------------
    # Helpers
    # -------------------------
    @staticmethod
    def _clean_text(s: str) -> str:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    @staticmethod
    def _same_host(url: str, start_url: str) -> bool:
        return urlparse(url).netloc == urlparse(start_url).netloc

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        # prefer explicit H1 in heading block
        h1 = soup.select_one(".heading__title--h1_v2 h1") or soup.select_one("h1")
        if h1:
            return h1.get_text(" ", strip=True)

        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            return og["content"].strip()

        return soup.title.get_text(" ", strip=True) if soup.title else ""

    @staticmethod
    def _extract_published(soup: BeautifulSoup) -> Optional[str]:
        """
        In lobby it's like: 'אלי שאולי | 19/02/2026'
        On article page usually similar. We'll scan the page text.
        """
        text_all = soup.get_text("\n", strip=True)
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text_all)
        return m.group(1) if m else None

    @staticmethod
    def _extract_lead(soup: BeautifulSoup) -> str:
        lead_box = soup.select_one(".heading__subtitle--v3-mod")
        if not lead_box:
            return ""
        # Join all <p> inside
        ps = lead_box.select("p")
        parts = [p.get_text(" ", strip=True) for p in ps if p.get_text(" ", strip=True)]
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_body(soup: BeautifulSoup) -> str:
        """
        Collect all text blocks in order from:
          div.text-container.article-rte-section div.text-wrapper
        """
        blocks = soup.select("div.text-container.article-rte-section div.text-wrapper")
        if not blocks:
            return ""

        parts: list[str] = []
        for b in blocks:
            t = b.get_text("\n", strip=True)
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _extract_summary(soup: BeautifulSoup) -> str:
        node = soup.select_one("div.article-summary")
        if not node:
            return ""
        # keep h2 + p etc as text
        return node.get_text("\n", strip=True).strip()

    @staticmethod
    def _extract_faq(soup: BeautifulSoup) -> str:
        """
        FAQ is in:
          div.faq__container details[itemtype=Question]
        Q: summary span[itemprop=name]
        A: div[itemprop=text]
        """
        root = soup.select_one("div.faq__container")
        if not root:
            return ""

        qa_lines: list[str] = []
        for details in root.select('details[itemtype="https://schema.org/Question"]'):
            q = details.select_one('[itemprop="name"]')
            a = details.select_one('[itemprop="text"]')

            q_text = q.get_text(" ", strip=True) if q else ""
            a_text = a.get_text(" ", strip=True) if a else ""

            if q_text and a_text:
                qa_lines.append(f"Q: {q_text}\nA: {a_text}")

        return "\n\n".join(qa_lines).strip()

    # -------------------------
    # Required BaseScraper API
    # -------------------------
    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        html = await self.fetcher.get_html(start_url)
        soup = BeautifulSoup(html, "lxml")

        urls: list[str] = []
        seen: set[str] = set()

        # Only take links from the lobby container
        container = soup.select_one("#articles-lobby-items-container")
        if not container:
            return []

        for a in container.select("a.article-card[href]"):
            href = a.get("href") or ""
            if not href:
                continue

            # site already gives absolute URLs, but keep safe:
            full = href.strip()

            # must be same host
            if not self._same_host(full, start_url):
                continue

            if full not in seen:
                seen.add(full)
                urls.append(full)

            if limit and len(urls) >= limit:
                break

        return urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        published = self._extract_published(soup)
        lead = self._extract_lead(soup)
        body = self._extract_body(soup)
        summary = self._extract_summary(soup)
        faq = self._extract_faq(soup)

        # Build final "content" field in a stable, readable way
        content_parts: list[str] = []
        if lead:
            content_parts.append(lead)
        if body:
            content_parts.append(body)
        if summary:
            content_parts.append("סיכום:\n" + summary)
        if faq:
            content_parts.append("שאלות ותשובות:\n" + faq)

        content = "\n\n".join([p for p in content_parts if p.strip()])

        return Article(
            url=url,
            title=self._clean_text(title),
            content=self._clean_text(content),
            published=published,
            raw_html=html,  # ✅ NEW
        )

    async def fetch_many(self, urls):
        # reuse BaseScraper concurrency logic, but with our instance concurrency
        return await super().fetch_many(urls, concurrency=self.concurrency)