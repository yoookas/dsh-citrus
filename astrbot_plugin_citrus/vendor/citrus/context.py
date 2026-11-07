"""CitrusApp —— 把核心件装在一起的容器（也是给库用户的入口）。

    from citrus import CitrusApp

    app = CitrusApp()
    app.set_credential("zhihu", open("cookie.txt").read())
    hot = app.adapter("zhihu").hot(limit=5)
"""

import logging
from typing import Any

from .core.accounts import DEFAULT_LABEL, AccountStore
from .core.cache import TTLCache
from .core.config import Config
from .core.cookies import parse_cookie_input
from .core.model import now_iso
from .registry import PlatformRegistry


class CitrusApp:
    def __init__(self, config: Config | None = None, *,
                 accounts: AccountStore | None = None,
                 registry: PlatformRegistry | None = None,
                 load_builtin: bool = True,
                 logger: logging.Logger | None = None) -> None:
        self.config = config or Config.from_env()
        self.accounts = accounts or AccountStore(self.config.home)
        self.cache = TTLCache(maxsize=1024, default_ttl=0.0)
        self.logger = logger or logging.getLogger("citrus")
        self.registry = registry or PlatformRegistry(self)
        if load_builtin and registry is None:
            from .platforms import BUILTIN

            self.registry.register_all(BUILTIN)

    # ---- 日志 -------------------------------------------------------

    def log(self, message: str, level: int = logging.INFO) -> None:
        self.logger.log(level, message)

    # ---- 账号 -------------------------------------------------------

    def set_credential(self, platform: str, text: str, *,
                       label: str = DEFAULT_LABEL,
                       user_agent: str = "") -> dict[str, Any]:
        """接受 cURL / 请求头 / 裸 Cookie / JSON 对象，统一落盘。"""
        meta = self.registry.meta(platform)
        parsed = parse_cookie_input(
            text,
            auth_cookie_names=meta["auth_cookie_names"],
            platform=platform,
        )
        entry = {
            "cookie": parsed.cookie,
            "user_agent": user_agent or parsed.user_agent or "",
            "saved_at": now_iso(),
            "source": parsed.source,
            "has_login": parsed.has_login,
        }
        self.accounts.set(platform, entry, label)
        self.cache.clear()
        self.registry.invalidate(platform)
        self.log("%s 账号 %s 已更新（%s）" % (platform, label, parsed.fingerprint()))
        return self.accounts.describe(platform, label)

    def credential(self, platform: str, label: str | None = None) -> dict[str, Any]:
        entry = self.accounts.get(platform, label or self.config.default_account)
        return dict(entry or {})

    def has_credential(self, platform: str, label: str | None = None) -> bool:
        return bool(self.credential(platform, label).get("cookie"))

    def account_labels(self, platform: str) -> list[str]:
        """这个平台配了哪些号；默认号排最前。"""
        labels = self.accounts.labels(platform)
        preferred = self.config.default_account
        if preferred in labels:
            return [preferred] + [label for label in labels if label != preferred]
        return labels

    # ---- 适配器 -----------------------------------------------------

    def adapter(self, platform: str, *, label: str | None = None,
                credential: dict[str, Any] | None = None) -> Any:
        """拿一个平台适配器。credential 传了就完全绕过本地账号库（无状态调用）。"""
        effective_label = label or self.config.default_account
        if credential is None:
            credential = self.credential(platform, effective_label)
            if not credential.get("cookie"):
                # 没有配置也返回实例，让 require_credential() 给出统一的错误提示
                return self.registry.adapter(platform, {}, effective_label)
        return self.registry.adapter(platform, credential, effective_label)

    def adapter_chain(self, platform: str, *, label: str | None = None,
                      credential: dict[str, Any] | None = None) -> list[Any]:
        """按顺序给出可用的适配器：先试指定的号，不行再按配置换下一个。

        注意这不是「随机轮流」：只有当前号不可用（默认仅 not_logged_in）才换，
        换了就记住，不会为了「均匀分摊」在请求之间来回跳。
        """
        if credential is not None:
            # 请求头直接带 Cookie 时是无状态调用，没有第二个号可换
            return [self.adapter(platform, label=label or "default", credential=credential)]

        ordered = self.account_labels(platform)
        if label:
            ordered = [label] + [item for item in ordered if item != label]
        if not ordered:
            # 一个都没配：交给 require_credential() 报 no_credential
            return [self.adapter(platform, label=label)]
        limit = self.config.rotation_max if self.config.rotation == "failover" else 1
        return [self.adapter(platform, label=item) for item in ordered[:limit]]

    def close(self) -> None:
        self.registry.invalidate()
        self.cache.clear()

    # ---- 上下文管理器（命令行里用 with） ----------------------------

    def __enter__(self) -> "CitrusApp":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False
