"""进程内 TTL 缓存。

给上游省点请求：单条正文、账号信息这类「几分钟内不会变」的东西值得缓存；
热榜/推荐流这类列表默认不缓存，或者给极短 TTL。

线程安全（HTTP 服务是多线程的）。键是任意可哈希值。
"""

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, maxsize: int = 512, default_ttl: float = 0.0) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self._maxsize = max(1, int(maxsize))
        self._default_ttl = float(default_ttl)
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            row = self._data.get(key)
            if row is None:
                self.misses += 1
                return default
            expire_at, value = row
            if expire_at and expire_at <= now:
                self._data.pop(key, None)
                self.misses += 1
                return default
            self.hits += 1
            return value

    def set(self, key: Any, value: Any, ttl: float | None = None) -> Any:
        seconds = self._default_ttl if ttl is None else float(ttl)
        expire_at = time.monotonic() + seconds if seconds > 0 else 0.0
        with self._lock:
            if len(self._data) >= self._maxsize and key not in self._data:
                self._evict_locked()
            self._data[key] = (expire_at, value)
        return value

    def get_or_set(self, key: Any, ttl: float | None, factory: Callable[[], Any]) -> Any:
        found = self.get(key, _MISSING)
        if found is not _MISSING:
            return found
        value = factory()
        self.set(key, value, ttl)
        return value

    def delete(self, key: Any) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict[str, int]:
        return {"size": len(self), "hits": self.hits, "misses": self.misses}

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._data.items() if exp and exp <= now]
        for key in expired:
            self._data.pop(key, None)
        while len(self._data) >= self._maxsize:
            self._data.pop(next(iter(self._data)))


_MISSING = object()
