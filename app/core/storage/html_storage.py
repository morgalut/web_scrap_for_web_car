from __future__ import annotations

import os
import re
from dataclasses import asdict, is_dataclass
from typing import Iterable
from urllib.parse import urlparse

from app.core.models import Article


def _safe_filename(s: str, max_len: int = 160) -> str:
    # keep Hebrew chars too; just remove file-hostile chars
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] if len(s) > max_len else s


def _slug_from_url(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "").strip("/")
    if not path:
        return "index"
    # replace / with _
    return _safe_filename(path.replace("/", "_"))


class HtmlStorage:
    """
    Saves raw HTML pages for each Article into separate files.

    Output structure:
      <out_dir>/html/<site_key>/<ts>/<slug>.html
    """

    def save_all(self, articles: Iterable[Article], out_dir: str, site_key: str, ts: str) -> str:
        base_dir = os.path.join(out_dir, "html", site_key, ts)
        os.makedirs(base_dir, exist_ok=True)

        saved = 0
        for a in articles:
            html = getattr(a, "raw_html", None)
            if not html:
                continue

            slug = _slug_from_url(a.url)
            path = os.path.join(base_dir, f"{slug}.html")

            with open(path, "w", encoding="utf-8") as f:
                f.write(html)

            saved += 1

        return base_dir