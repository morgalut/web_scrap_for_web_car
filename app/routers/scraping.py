from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional, List
from urllib.parse import urlsplit, urlunsplit, unquote, quote

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.scrapers.registry import ScraperRegistry
from app.core.storage.csv_storage import CsvStorage
from app.core.storage.html_storage import HtmlStorage

router = APIRouter(tags=["scraping"])

settings = Settings()
log = get_logger()


# ------------------------------------------------------------------
# URL NORMALIZATION (Fix Hebrew encoded/decoded mismatch)
# ------------------------------------------------------------------
def normalize_url(u: str) -> str:
    """
    Normalize URL so encoded/decoded Hebrew paths match.
    - Decode path
    - Re-encode consistently
    - Remove trailing slash differences
    - Lowercase scheme + host
    """
    p = urlsplit(u.strip())

    path_decoded = unquote(p.path or "")
    path_encoded = quote(path_decoded, safe="/%")

    # Normalize trailing slash
    path_encoded = path_encoded.rstrip("/") or "/"

    return urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            path_encoded,
            p.query,
            "",  # drop fragment
        )
    )


# ------------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------------
@router.get("/health")
async def health():
    log.info("Health check requested")
    return {"ok": True}


# ------------------------------------------------------------------
# SCRAPE
# ------------------------------------------------------------------
@router.post("/scrape")
async def scrape(
    start_url: Optional[str] = Query(default=None),
    concurrency: int = Query(default=12, ge=1, le=60),
    headless: bool = Query(default=True),
    player: bool = Query(default=False),
    out_dir: str = Query(default="output"),
    all_sites: bool = Query(default=True),
    save_html: bool = Query(default=True),
    delay_s: float = Query(default=0.25, ge=0.0, le=5.0),
    delay_jitter_s: float = Query(default=0.15, ge=0.0, le=5.0),
    close_ads: bool = Query(default=True),
):
    t_req = time.perf_counter()

    log.info("Scrape request received")
    log.info(
        "Parameters -> all_sites=%s, start_url=%s, concurrency=%s, headless=%s, "
        "player=%s, out_dir=%s, save_html=%s, delay_s=%.2f, delay_jitter_s=%.2f, close_ads=%s",
        all_sites,
        start_url,
        concurrency,
        headless,
        player,
        out_dir,
        save_html,
        delay_s,
        delay_jitter_s,
        close_ads,
    )

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    storage = CsvStorage()
    html_storage = HtmlStorage()

    registry = ScraperRegistry(settings=settings, headless=headless)
    runtime = registry.runtime()

    results: List[dict] = []

    # --------------------------------------------------------------
    # Determine targets
    # --------------------------------------------------------------
    if all_sites:
        targets = list(settings.sites)
        log.info("Targeting ALL sites (%d): %s", len(targets), [s.key for s in targets])
    else:
        if not start_url:
            log.warning("all_sites=false but start_url not provided")
            return JSONResponse(
                {"error": "start_url must be provided when all_sites=false"},
                status_code=400,
            )

        start_norm = normalize_url(start_url)

        matched = [
            s
            for s in settings.sites
            if normalize_url(s.start_url) == start_norm
        ]

        if not matched:
            configured = [s.start_url for s in settings.sites]
            configured_norm = [normalize_url(s.start_url) for s in settings.sites]

            log.warning(
                "start_url not found in Settings().sites: %s (normalized=%s)",
                start_url,
                start_norm,
            )

            return JSONResponse(
                {
                    "error": "start_url not found in Settings().sites",
                    "start_url": start_url,
                    "start_url_normalized": start_norm,
                    "configured_sites": configured,
                    "configured_sites_normalized": configured_norm,
                },
                status_code=400,
            )

        targets = matched
        log.info("Targeting SINGLE site: %s", matched[0].key)

    # --------------------------------------------------------------
    # Scraping loop
    # --------------------------------------------------------------
    try:
        for site in targets:
            t0 = time.perf_counter()
            log.info("------------------------------------------------------------")
            log.info("Scraping site: key=%s | start_url=%s", site.key, site.start_url)

            out_csv_path = os.path.join(out_dir, f"{site.key}_{ts}.csv")
            saved_html_dir: Optional[str] = None

            try:
                scraper = registry.create(key=site.key, concurrency=concurrency)

                # Configure per-run behavior
                scraper.request_delay_s = delay_s
                scraper.request_delay_jitter_s = delay_jitter_s
                scraper.close_ads = close_ads

                log.info(
                    "Delay configured for %s: delay_s=%.2f jitter_s=%.2f",
                    site.key,
                    delay_s,
                    delay_jitter_s,
                )
                log.info("Ad closing configured for %s: close_ads=%s", site.key, close_ads)

                # Discover
                log.info("Starting URL discovery...")
                urls = await scraper.discover_article_urls(start_url=site.start_url)
                log.info("Discovered %d URLs for site=%s", len(urls), site.key)

                if not urls:
                    elapsed = round(time.perf_counter() - t0, 3)
                    log.warning("No URLs found for %s; skipping", site.key)
                    results.append(
                        {
                            "site_key": site.key,
                            "status": "no_urls",
                            "duration_s": elapsed,
                        }
                    )
                    continue

                # Fetch
                log.info("Starting article fetch phase...")
                articles = await scraper.fetch_many(urls)
                log.info("Fetched %d articles for site=%s", len(articles), site.key)

                if not articles:
                    elapsed = round(time.perf_counter() - t0, 3)
                    log.warning("No articles fetched for %s", site.key)
                    results.append(
                        {
                            "site_key": site.key,
                            "status": "no_articles",
                            "duration_s": elapsed,
                        }
                    )
                    continue

                # Save HTML
                if save_html:
                    saved_html_dir = html_storage.save_all(
                        articles=articles,
                        out_dir=out_dir,
                        site_key=site.key,
                        ts=ts,
                    )
                    log.info("HTML pages saved under: %s", saved_html_dir)

                # Save CSV
                storage.save(articles, out_csv_path)
                log.info("CSV saved at: %s", out_csv_path)

                elapsed = round(time.perf_counter() - t0, 3)

                results.append(
                    {
                        "site_key": site.key,
                        "status": "ok",
                        "found_urls": len(urls),
                        "fetched_articles": len(articles),
                        "saved_csv": out_csv_path,
                        "saved_html_dir": saved_html_dir,
                        "duration_s": elapsed,
                    }
                )

            except Exception as e:
                elapsed = round(time.perf_counter() - t0, 3)
                log.exception("Site scrape failed: %s", site.key)

                results.append(
                    {
                        "site_key": site.key,
                        "status": "error",
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "duration_s": elapsed,
                    }
                )

    finally:
        log.info("Closing fetchers/runtime...")
        await runtime.aclose()
        log.info("Fetchers closed successfully")

    total_elapsed = round(time.perf_counter() - t_req, 3)
    log.info("Scrape process completed (total %.3fs)", total_elapsed)

    return {
        "all_sites": all_sites,
        "requested_start_url": start_url,
        "summary": {
            "ok": sum(1 for r in results if r["status"] == "ok"),
            "error": sum(1 for r in results if r["status"] == "error"),
            "total": len(results),
            "duration_s": total_elapsed,
        },
        "results": results,
    }


# ------------------------------------------------------------------
# DOWNLOAD
# ------------------------------------------------------------------
@router.get("/download")
async def download(path: str = Query(...)):
    log.info("Download requested for file: %s", path)

    if not os.path.isfile(path):
        return JSONResponse(
            {"error": "File not found", "path": path},
            status_code=404,
        )

    return FileResponse(
        path,
        media_type="text/csv",
        filename=os.path.basename(path),
    )