from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from app.core.models import Article

class BaseStorage(ABC):
    @abstractmethod
    def save(self, items: Iterable[Article], path: str) -> str:
        raise NotImplementedError