"""citrus 的异步桥接层。

AstrBot 是 asyncio 环境，而 citrus 的 HTTP 客户端是同步的（内部用 time.sleep 做请求
节奏和抖动）。所以这里做了两件事：

1. 所有 citrus 调用都丢进 asyncio.to_thread，绝不阻塞事件循环；
2. 用一把 asyncio.Lock 把调用串起来 —— 和 citrus「同一账号同时只有一个请求」的设计
   保持一致，也让请求节奏（间隔 + 抖动）真正生效。

Cookie 只存在于内存里（self._credentials），不写进 citrus 的账号库，也不写日志。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from citrus import CitrusApp, CitrusError  # noqa: E402
from citrus.core.config import Config as CitrusConfig  # noqa: E402
from citrus.core.cookies import mask_cookie, parse_cookie_input  # noqa: E402


#: 错误码 -> 给用户看的一句话
ERROR_MESSAGES = {
    "no_credential": "还没有配置知乎 Cookie。",
    "not_logged_in": "Cookie 里的登录态失效了。",
    "challenge": "被知乎风控拦住了（弹了验证页）。",
    "forbidden": "知乎拒绝了这次请求（没权限）。",
    "not_found": "这条内容不存在或已被删除。",
    "rate_limited": "知乎限流了，需要等几分钟。",
    "network": "本机网络请求失败。",
    "upstream": "知乎服务端出错了。",
    "bad_upstream_response": "知乎返回的不是预期内容。",
    "bad_request": "请求参数不对。",
    "invalid_argument": "请求参数不合法。",
    "unsupported_capability": "知乎不支持这个能力。",
    "unknown_platform": "没有这个平台。",
    "internal": "插件内部出错了。",
}

#: 每种错误给一句「下一步做什么」，比 citrus 通用 hint 更贴 AstrBot 场景
ERROR_NEXT_STEPS = {
    "no_credential": "在 AstrBot 的「插件」页找到本插件，把浏览器里复制出来的 cURL 粘贴到「知乎 Cookie」里保存。",
    "not_logged_in": "重新在浏览器登录知乎，F12 -> Network -> 右键任意知乎请求 -> Copy as cURL，再粘贴到插件配置里。",
    "challenge": "去浏览器打开知乎过一次验证，等几分钟再试；请不要连续重试。",
    "rate_limited": "等几分钟再问；连续重试只会更容易被风控。",
    "network": "检查容器能不能访问 www.zhihu.com（代理/网络）。",
}


def friendly_error(exc: BaseException) -> str:
    """把异常翻译成给用户/模型看的一句话。绝不打印 cookie。"""
    if not isinstance(exc, CitrusError):
        return "获取知乎内容失败：%s: %s" % (type(exc).__name__, exc)
    message = ERROR_MESSAGES.get(exc.code) or exc.message or "请求失败。"
    detail = ERROR_NEXT_STEPS.get(exc.code) or exc.hint or ""
    return "%s%s" % (message, detail) if detail else message


class CitrusBridge:
    """一个最小的异步门面：设置 Cookie / 调用某个平台能力。"""

    def __init__(self, home: Path, *, logger: logging.Logger | None = None,
                 gap_seconds: float = 0.35, jitter_seconds: float = 0.25,
                 timeout_seconds: float = 20.0, retries: int = 2) -> None:
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self._logger = logger or logging.getLogger("astrbot")
        self._config = CitrusConfig(
            home=self.home,
            gap_seconds=gap_seconds,
            jitter_seconds=jitter_seconds,
            timeout=timeout_seconds,
            max_retries=retries,
        )
        self._app = CitrusApp(config=self._config, logger=self._logger)
        self._credentials: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    # ---- 平台与 Cookie ------------------------------------------------

    def platforms(self) -> list[str]:
        return list(self._app.registry.ids())

    def has_cookie(self, platform: str) -> bool:
        return bool((self._credentials.get(platform) or {}).get("cookie"))

    def cookie_hint(self, platform: str) -> str:
        cookie = str((self._credentials.get(platform) or {}).get("cookie") or "")
        return mask_cookie(cookie) if cookie else ""

    def set_cookie(self, platform: str, raw: str) -> dict[str, Any]:
        """解析并记住一份 Cookie。抛 CitrusError 表示这份内容不可用。"""
        meta = self._app.registry.meta(platform)
        parsed = parse_cookie_input(
            raw,
            auth_cookie_names=meta.get("auth_cookie_names") or (),
            platform=platform,
        )
        self._credentials[platform] = {
            "cookie": parsed.cookie,
            "user_agent": parsed.user_agent or "",
        }
        # 换 cookie 之后旧的适配器实例（及其缓存）要作废
        self._app.registry.invalidate(platform)
        self._app.cache.clear()
        return {
            "platform": platform,
            "fingerprint": mask_cookie(parsed.cookie),
            "cookie_count": len(parsed.names),
            "has_login": bool(parsed.has_login),
            "source": parsed.source,
        }

    def clear_cookie(self, platform: str) -> None:
        self._credentials.pop(platform, None)
        self._app.registry.invalidate(platform)
        self._app.cache.clear()

    # ---- 调用 ---------------------------------------------------------

    async def call(self, platform: str, capability: str, /, **kwargs: Any) -> Any:
        """异步调用一个能力（hot / search / item / comments / account ...）。"""
        if not self.has_cookie(platform):
            raise CitrusError(
                "no_credential",
                "还没有给 %s 配置 Cookie。" % platform,
                "在插件配置里粘贴浏览器复制的 cURL。",
                platform=platform,
            )
        credential = dict(self._credentials[platform])
        app = self._app

        def _run() -> Any:
            adapter = app.adapter(platform, credential=credential)
            method = getattr(adapter, capability, None)
            if method is None:
                raise CitrusError(
                    "unsupported_capability",
                    "不认识的接口：%s" % capability,
                    platform=platform,
                )
            return method(**kwargs)

        async with self._lock:
            return await asyncio.to_thread(_run)

    # ---- 诊断 ---------------------------------------------------------

    def describe(self, platform: str) -> dict[str, Any]:
        try:
            return dict(self._app.registry.describe(platform))
        except CitrusError:
            return {}

    def close(self) -> None:
        try:
            self._app.close()
        except Exception:  # pragma: no cover - 关闭失败不该影响卸载
            pass


def load_cookie_from_file(path: str) -> str:
    """从文件里读 Cookie（支持 UTF-8 / UTF-8 BOM）。"""
    target = Path(path).expanduser()
    return target.read_text(encoding="utf-8-sig").strip()
