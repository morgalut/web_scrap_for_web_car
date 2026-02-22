from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Any


class BaseFetcher(ABC):
    """
    Base interface for all fetchers (HTTPX, Playwright, Hybrid).

    Important:
    - get_html supports **kwargs so different fetchers
      can accept extended parameters (wait_for_selector, etc.)
      without breaking polymorphism.
    """

    @abstractmethod
    async def get_html(
        self,
        url: str,
        **kwargs: Any,   # ✅ allows flexible parameters
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError