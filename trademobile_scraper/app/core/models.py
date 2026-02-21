from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

@dataclass
class Article:
    url: str
    title: str
    content: str
    published: Optional[str] = None