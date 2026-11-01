"""Backend-independent asynchronous cache contract and local LRU adapter."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Tuple, runtime_checkable


@dataclass(frozen=True)
class CacheStats:
    entries: int
    hits: int
    misses: int
    evictions: int
    stale_expirations: int = 0


@runtime_checkable
class CacheBackend(Protocol):
    async def get(self, key: str) -> Tuple[bool, Any]: ...

    async def set(self, key: str, value: Any, *, ttl_seconds: Optional[float] = None) -> None: ...

    async def delete(self, key: str) -> bool: ...

    async def clear(self) -> None: ...


@runtime_checkable
class SQLiteCacheBackend(CacheBackend, Protocol):
    """CacheBackend contract for a future local SQLite implementation."""


@runtime_checkable
class RedisCacheBackend(CacheBackend, Protocol):
    """CacheBackend contract for a future Redis implementation."""


@runtime_checkable
class ObjectStorageCacheBackend(CacheBackend, Protocol):
    """CacheBackend contract for a future object-storage implementation."""


class MemoryCache:
    """Thread-safe local cache; ``max_entries=None`` leaves capacity unbounded."""

    def __init__(self, *, max_entries: Optional[int] = None) -> None:
        if max_entries is not None and max_entries < 1:
            raise ValueError("max_entries must be greater than zero or None")
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[Any, Optional[float]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._stale_expirations = 0

    async def get(self, key: str) -> Tuple[bool, Any]:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return False, None
            value, expires_at = entry
            if expires_at is not None and expires_at <= time.monotonic():
                del self._entries[key]
                self._misses += 1
                self._stale_expirations += 1
                return False, None
            self._entries.move_to_end(key)
            self._hits += 1
            return True, value

    async def set(self, key: str, value: Any, *, ttl_seconds: Optional[float] = None) -> None:
        if not key:
            raise ValueError("cache key must not be empty")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero or None")
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        async with self._lock:
            self._entries[key] = (value, expires_at)
            self._entries.move_to_end(key)
            while self.max_entries is not None and len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._entries.pop(key, None) is not None

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    async def stats(self) -> CacheStats:
        async with self._lock:
            self._expire_stale()
            return CacheStats(
                entries=len(self._entries),
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                stale_expirations=self._stale_expirations,
            )

    def _expire_stale(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (_, expires_at) in self._entries.items()
            if expires_at is not None and expires_at <= now
        ]
        for key in expired:
            del self._entries[key]
            self._stale_expirations += 1
