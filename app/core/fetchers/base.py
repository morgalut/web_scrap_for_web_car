from __future__ import annotations

from abc import ABC, abstractmethod

class BaseFetcher(ABC):
    @abstractmethod
    async def get_html(self, url: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError