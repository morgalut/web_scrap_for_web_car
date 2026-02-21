from __future__ import annotations

from fastapi import FastAPI

from app.routers.scraping import router as scraping_router

app = FastAPI(
    title="TradeMobile Hybrid Scraper (httpx + playwright)",
    version="1.1.0",
)

app.include_router(scraping_router)