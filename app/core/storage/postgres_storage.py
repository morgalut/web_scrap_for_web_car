from __future__ import annotations

from typing import Iterable, Optional
import os

import psycopg2
from psycopg2.extras import execute_values

from app.core.models import Article
from .base import BaseStorage


class PostgresStorage(BaseStorage):
    """
    Saves Articles into Postgres.

    - Uses url as a natural unique key
    - Upserts on conflict(url)
    - 'path' argument is treated as a DSN / connection string, e.g.:
        "postgresql://user:pass@localhost:5432/dbname"
      If path is empty, it falls back to DATABASE_URL env var.
    """

    def __init__(self, table: str = "articles") -> None:
        self.table = table

    def save(self, items: Iterable[Article], path: str) -> str:
        dsn = (path or "").strip() or (os.getenv("DATABASE_URL") or "").strip()
        if not dsn:
            raise ValueError(
                "PostgresStorage.save(): missing DSN. Provide it as `path` or set DATABASE_URL."
            )

        rows = []
        for it in items:
            rows.append(
                (
                    it.url,
                    it.title or "",
                    it.published,
                    it.content or "",
                    getattr(it, "raw_html", None),
                )
            )

        if not rows:
            return f"postgres:{self.table} (0 rows)"

        sql = f"""
            INSERT INTO {self.table} (url, title, published, content, raw_html)
            VALUES %s
            ON CONFLICT (url) DO UPDATE SET
                title     = EXCLUDED.title,
                published = EXCLUDED.published,
                content   = EXCLUDED.content,
                raw_html  = EXCLUDED.raw_html
        """

        conn = psycopg2.connect(dsn)
        try:
            with conn:
                with conn.cursor() as cur:
                    execute_values(cur, sql, rows, page_size=500)
            return f"postgres:{self.table} ({len(rows)} rows)"
        finally:
            conn.close()