from __future__ import annotations

import sys
import asyncio

from fastapi import FastAPI

from app.core.logging import get_logger
from app.routers.scraping import router as scraping_router

# ✅ IMPORTANT (Windows + Playwright):
# Must be set BEFORE the event loop is created (uvicorn creates it early).
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


@app.on_event("startup")
async def on_startup() -> None:
    log.info("Application startup")
    log.info("Platform: %s", sys.platform)
    if sys.platform.startswith("win"):
        log.info("AsyncIO event loop policy: WindowsProactorEventLoopPolicy enabled")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    log.info("Application shutdown")