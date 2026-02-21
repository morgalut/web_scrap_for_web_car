from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import Settings
from app.core.storage.csv_storage import CsvStorage
from app.core.logging import get_logger
from app.core.scrapers.registry import ScraperRegistry

router = APIRouter(tags=["scraping"])

settings = Settings()
log = get_logger()


@router.get("/health")
async def health():
    log.info("Health check requested")
    return {"ok": True}


@router.post("/scrape")
async def scrape(
    # Backwards compatible: still allow single start_url
    start_url: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1),
    concurrency: int = Query(default=12, ge=1, le=60),
    headless: bool = Query(default=True),
    out_dir: str = Query(default="output"),
    all_sites: bool = Query(default=True),
):
    """
    If all_sites=True (default): scrape all sites in Settings().sites
    Else: scrape only `start_url` (must be provided and must match Settings().sites).
    """
    log.info("Scrape request received")
    log.info(
        f"Parameters -> all_sites={all_sites}, start_url={start_url}, limit={limit}, "
        f"concurrency={concurrency}, headless={headless}, out_dir={out_dir}"
    )

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    storage = CsvStorage()
    registry = ScraperRegistry(settings=settings, headless=headless)
    runtime = registry.runtime()

    results: List[dict] = []

    # Determine targets
    if all_sites:
        targets = list(settings.sites)
    else:
        if not start_url:
            return JSONResponse(
                {"error": "start_url must be provided when all_sites=false"},
                status_code=400,
            )

        matched = [s for s in settings.sites if s.start_url == start_url]
        if not matched:
            return JSONResponse(
                {
                    "error": "start_url not found in Settings().sites",
                    "start_url": start_url,
                    "configured_sites": [s.start_url for s in settings.sites],
                },
                status_code=400,
            )
        targets = matched

    try:
        for site in targets:
            t0 = time.perf_counter()
            log.info(f"--- Scraping site key={site.key} start_url={site.start_url} ---")

            out_path = os.path.join(out_dir, f"{site.key}_{ts}.csv")

            try:
                scraper = registry.create(key=site.key, concurrency=concurrency)
                if scraper is None:
                    raise RuntimeError(f"Registry returned None for site key={site.key}")

                log.info("Starting URL discovery...")
                urls = await scraper.discover_article_urls(
                    start_url=site.start_url,
                    limit=limit,
                )
                log.info(f"Discovered {len(urls)} URLs for {site.key}")

                if not urls:
                    elapsed = round(time.perf_counter() - t0, 3)
                    log.warning(f"No URLs found for {site.key}; skipping fetch/save")
                    results.append(
                        {
                            "site_key": site.key,
                            "start_url": site.start_url,
                            "status": "no_urls",
                            "found_urls": 0,
                            "saved_csv": None,
                            "download_endpoint": None,
                            "duration_s": elapsed,
                        }
                    )
                    continue

                log.info("Starting article fetch phase...")
                articles = await scraper.fetch_many(urls)
                log.info(f"Fetched {len(articles)} articles for {site.key}")

                if not articles:
                    elapsed = round(time.perf_counter() - t0, 3)
                    log.warning(f"No articles fetched for {site.key}; skipping save")
                    results.append(
                        {
                            "site_key": site.key,
                            "start_url": site.start_url,
                            "status": "no_articles",
                            "found_urls": len(urls),
                            "saved_csv": None,
                            "download_endpoint": None,
                            "duration_s": elapsed,
                        }
                    )
                    continue

                log.info("Saving to CSV...")
                storage.save(articles, out_path)
                log.info(f"CSV saved at: {out_path}")

                elapsed = round(time.perf_counter() - t0, 3)
                results.append(
                    {
                        "site_key": site.key,
                        "start_url": site.start_url,
                        "status": "ok",
                        "found_urls": len(urls),
                        "fetched_articles": len(articles),
                        "saved_csv": out_path,
                        "download_endpoint": f"/download?path={out_path}",
                        "duration_s": elapsed,
                    }
                )

            except Exception as e:
                elapsed = round(time.perf_counter() - t0, 3)
                log.exception(f"Site scrape failed: {site.key}")
                results.append(
                    {
                        "site_key": site.key,
                        "start_url": site.start_url,
                        "status": "error",
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "saved_csv": None,
                        "download_endpoint": None,
                        "duration_s": elapsed,
                    }
                )
                continue

    finally:
        log.info("Closing fetchers...")
        await runtime.aclose()
        log.info("Fetchers closed successfully")

    log.info("Scrape process completed")

    # Optionally summarize totals
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = sum(1 for r in results if r.get("status") == "error")

    return {
        "all_sites": all_sites,
        "requested_start_url": start_url,
        "summary": {"ok": ok, "error": err, "total": len(results)},
        "results": results,
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