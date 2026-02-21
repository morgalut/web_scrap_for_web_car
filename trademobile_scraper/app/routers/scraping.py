from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import Settings
from app.core.fetchers.httpx_fetcher import HttpxFetcher
from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.fetchers.hybrid_fetcher import HybridFetcher
from app.core.scrapers.trademobile_scraper import TradeMobileScraper
from app.core.storage.csv_storage import CsvStorage
from app.core.logging import get_logger

router = APIRouter(tags=["scraping"])

settings = Settings()
log = get_logger()


@router.get("/health")
async def health():
    log.info("Health check requested")
    return {"ok": True}


@router.post("/scrape")
async def scrape(
    start_url: str = Query(default=settings.base_url),
    limit: Optional[int] = Query(default=None, ge=1),
    concurrency: int = Query(default=12, ge=1, le=60),
    headless: bool = Query(default=True),
    out_dir: str = Query(default="output"),
):
    log.info("Scrape request received")
    log.info(
        f"Parameters -> start_url={start_url}, limit={limit}, "
        f"concurrency={concurrency}, headless={headless}"
    )

    os.makedirs(out_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"trademobile_posts_{ts}.csv")

    log.info("Initializing fetchers...")

    http = HttpxFetcher(config=settings.httpx)
    pw = PlaywrightFetcher(headless=headless)
    fetcher = HybridFetcher(http=http, pw=pw, require_selector="div.ProseMirror")

    scraper = TradeMobileScraper(fetcher=fetcher, concurrency=concurrency)
    storage = CsvStorage()

    try:
        log.info("Starting URL discovery...")
        urls = await scraper.discover_article_urls(
            start_url=start_url,
            limit=limit
        )
        log.info(f"Discovered {len(urls)} article URLs")

        if not urls:
            log.warning("No URLs found!")

        log.info("Starting article fetch phase...")
        articles = await scraper.fetch_many(urls)
        log.info(f"Fetched {len(articles)} articles successfully")

        log.info("Saving to CSV...")
        storage.save(articles, out_path)
        log.info(f"CSV saved at: {out_path}")

    except Exception as e:
        log.exception("Scraping failed with exception")
        raise e

    finally:
        log.info("Closing fetchers...")
        await fetcher.aclose()
        log.info("Fetchers closed successfully")

    log.info("Scrape process completed successfully")

    return {
        "start_url": start_url,
        "found_urls": len(urls),
        "saved_csv": out_path,
        "download_endpoint": f"/download?path={out_path}",
    }


@router.get("/download")
async def download(path: str = Query(...)):
    log.info(f"Download requested for file: {path}")

    if not os.path.isfile(path):
        log.warning(f"File not found: {path}")
        return JSONResponse(
            {"error": "File not found", "path": path},
            status_code=404,
        )

    log.info(f"File found. Sending: {path}")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=os.path.basename(path),
    )