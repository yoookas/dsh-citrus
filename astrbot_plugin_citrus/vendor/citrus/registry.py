"""平台注册表 —— 平台 id -> 适配器工厂 -> 适配器实例。

这里是「高内聚」的接口面：核心只跟工厂打交道，新增平台不需要动核心任何一行。
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from .core.cookies import mask_cookie
from .errors import CitrusError

AdapterFactory = Callable[[Any], Any]


class PlatformRegistry:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._factories: dict[str, AdapterFactory] = {}
        self._order: list[str] = []
        self._instances: OrderedDict[tuple[str, str, str], Any] = OrderedDict()
        self._lock = threading.RLock()
        self._max_instances = 32

    # ---- 注册 -------------------------------------------------------

    def register(self, factory: AdapterFactory) -> AdapterFactory:
        probe = factory(self.app)
        platform = getattr(probe, "platform", "") or ""
        if not platform:
            raise ValueError("平台适配器必须声明 platform")
        if platform in self._factories:
            raise ValueError("平台 %s 已经注册过了" % platform)
        capabilities = tuple(getattr(probe, "capabilities", ()) or ())
        if not capabilities:
            raise ValueError("平台 %s 没有声明任何能力" % platform)
        self._factories[platform] = factory
        self._order.append(platform)
        return factory

    def register_all(self, factories: Any) -> None:
        for factory in factories:
            self.register(factory)

    # ---- 查询 -------------------------------------------------------

    def ids(self) -> list[str]:
        return list(self._order)

    def has(self, platform: str) -> bool:
        return platform in self._factories

    def require(self, platform: str) -> AdapterFactory:
        factory = self._factories.get(platform)
        if factory is None:
            raise CitrusError(
                "unknown_platform",
                "不认识平台 %s。" % platform,
                "目前支持：%s。" % (", ".join(self._order) or "（空）"),
            )
        return factory

    def describe(self, platform: str) -> dict[str, Any]:
        return self.require(platform)(self.app).describe()

    def describe_all(self) -> list[dict[str, Any]]:
        return [self.describe(platform) for platform in self._order]

    def meta(self, platform: str) -> dict[str, Any]:
        factory = self.require(platform)
        probe = factory(self.app)
        return {
            "id": getattr(probe, "platform", platform),
            "name": getattr(probe, "name", platform),
            "capabilities": list(getattr(probe, "capabilities", ())),
            "auth_cookie_names": list(getattr(probe, "auth_cookie_names", ())),
            "error_hints": dict(getattr(probe, "error_hints", {}) or {}),
        }

    # ---- 实例 -------------------------------------------------------

    def adapter(self, platform: str, credential: dict[str, Any] | None = None,
                label: str = "default") -> Any:
        factory = self.require(platform)
        cookie = str((credential or {}).get("cookie") or "")
        key = (platform, label, mask_cookie(cookie))
        with self._lock:
            cached = self._instances.get(key)
            if cached is not None:
                if cached.credential.get("cookie") == cookie:
                    self._instances.move_to_end(key)
                    return cached
                self._instances.pop(key, None)
        instance = factory(self.app)
        instance.credential = dict(credential or {})
        instance.label = label
        with self._lock:
            self._instances[key] = instance
            while len(self._instances) > self._max_instances:
                self._instances.popitem(last=False)
        return instance

    def invalidate(self, platform: str | None = None) -> None:
        with self._lock:
            if platform is None:
                self._instances.clear()
                return
            for key in [k for k in self._instances if k[0] == platform]:
                self._instances.pop(key, None)
