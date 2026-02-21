from __future__ import annotations

import csv
from typing import Iterable

from app.core.models import Article
from .base import BaseStorage

class CsvStorage(BaseStorage):
    def save(self, items: Iterable[Article], path: str) -> str:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["url", "title", "published", "content"])
            w.writeheader()
            for it in items:
                w.writerow(
                    {
                        "url": it.url,
                        "title": it.title,
                        "published": it.published or "",
                        "content": it.content,
                    }
                )
        return path