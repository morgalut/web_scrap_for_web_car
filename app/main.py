from __future__ import annotations

import sys
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
import psycopg2
from fastapi import FastAPI

from app.core.logging import get_logger
from app.routers.scraping import router as scraping_router


# ✅ IMPORTANT (Windows + Playwright):
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

log = get_logger()

app = FastAPI(
    title="TradeMobile Hybrid Scraper (httpx + playwright)",
    version="1.1.0",
)

app.include_router(scraping_router)


@app.get("/")
async def root():
    return {"ok": True, "service": app.title, "version": app.version}


# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    log.info("Application startup")
    log.info("Platform: %s", sys.platform)

    if sys.platform.startswith("win"):
        log.info("AsyncIO event loop policy: WindowsProactorEventLoopPolicy enabled")

    # ✅ DATABASE CONNECTION TEST
    dsn = os.getenv("DATABASE_URL")

    if not dsn:
        log.warning("DATABASE_URL not configured — skipping DB connectivity check")
        return

    try:
        log.info("Attempting to connect to database...")
        conn = psycopg2.connect(dsn)
        conn.close()
        log.info("✅ Database connection successful")

    except Exception as e:
        log.error("❌ Database connection FAILED")
        log.error("Error type: %s", type(e).__name__)
        log.error("Error details: %s", str(e))


# ------------------------------------------------------------------
# SHUTDOWN
# ------------------------------------------------------------------
@app.on_event("shutdown")
async def on_shutdown() -> None:
    log.info("Application shutdown")