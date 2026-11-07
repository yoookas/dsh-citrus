"""平台适配器契约 —— 想接一个新平台，照这个类实现就够了。

核心层（HTTP/缓存/账号/错误）不认识任何平台。它只认这个契约：

    platform            平台 id，出现在 URL 里（/v1/zhihu/hot）
    name                给人看的名字
    capabilities        声明支持哪些能力，/v1/platforms 会原样吐出去
    auth_cookie_names   哪些 cookie 名代表「已登录」，用来判断 Cookie 是否有效
    error_hints         错误码 -> 下一步该做什么（直接写给用户看）

能力方法一律返回「统一模型」（见 citrus.core.model）。实现不了的直接不声明；
声明了却调用失败，就抛 CitrusError —— 永远不要返回半个假数据。
"""

from typing import Any

from ..errors import CitrusError
from ..core.cookies import mask_cookie

#: 全部能力（顺序即 /v1/platforms 的输出顺序）
ALL_CAPABILITIES: tuple[str, ...] = (
    "account", "feed", "hot", "search", "item", "comments", "user", "user_content",
)


class BaseAdapter:
    """一个平台 × 一份 Cookie 的适配器实例。"""

    platform: str = ""
    name: str = ""
    homepage: str = ""
    capabilities: tuple[str, ...] = ()
    auth_cookie_names: tuple[str, ...] = ()
    error_hints: dict[str, str] = {}
    notes: str = ""

    def __init__(self, app: Any, credential: dict[str, Any] | None = None,
                 label: str = "default") -> None:
        self.app = app
        self.credential = dict(credential or {})
        self.label = label
        self.cache = getattr(app, "cache", None)
        self.log = getattr(app, "log", lambda _m: None)

    # ---- 身份 -------------------------------------------------------

    @property
    def cookie(self) -> str:
        return str(self.credential.get("cookie") or "")

    @property
    def user_agent(self) -> str:
        return str(self.credential.get("user_agent") or "")

    @property
    def has_credential(self) -> bool:
        return bool(self.cookie)

    @property
    def cookie_hint(self) -> str:
        return mask_cookie(self.cookie) if self.cookie else ""

    def require_credential(self) -> str:
        if not self.cookie:
            raise CitrusError(
                "no_credential",
                "还没有给 %s 配置 Cookie。" % (self.name or self.platform),
                "PUT /v1/accounts/%s，body 里放 {\"cookie\": \"<浏览器里复制的 cURL 或 Cookie>\"}" % self.platform,
                platform=self.platform,
            )
        return self.cookie

    # ---- 能力声明 ---------------------------------------------------

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def require_capability(self, capability: str) -> None:
        if not self.supports(capability):
            raise CitrusError(
                "unsupported_capability",
                "%s 不支持 %s。" % (self.name or self.platform, capability),
                "它支持：%s。" % (", ".join(self.capabilities) or "（无）"),
                platform=self.platform,
            )

    def limits(self) -> dict[str, Any]:
        """各能力的上限 / 可选值。平台自己覆盖，/v1/platforms 会原样吐给 agent。"""
        return {}

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.platform,
            "name": self.name,
            "homepage": self.homepage,
            "capabilities": list(self.capabilities),
            "auth": {
                "cookie_names": list(self.auth_cookie_names),
                "hint": "把浏览器里复制的 cURL、Cookie 头或裸 Cookie 串交给 PUT /v1/accounts/%s " % self.platform,
            },
            "notes": self.notes,
            "limits": self.limits(),
        }

    # ---- 能力方法（默认「不支持」） ---------------------------------

    def account(self) -> dict[str, Any]:
        self.require_capability("account")
        raise CitrusError("unsupported_capability", "account 未实现。", platform=self.platform)

    def feed(self, source: str = "", limit: int = 20, page: int = 1) -> dict[str, Any]:
        self.require_capability("feed")
        raise CitrusError("unsupported_capability", "feed 未实现。", platform=self.platform)

    def hot(self, limit: int = 20) -> dict[str, Any]:
        self.require_capability("hot")
        raise CitrusError("unsupported_capability", "hot 未实现。", platform=self.platform)

    def search(self, query: str, limit: int = 20, page: int = 1,
               sort: str = "", kind: str = "") -> dict[str, Any]:
        self.require_capability("search")
        raise CitrusError("unsupported_capability", "search 未实现。", platform=self.platform)

    def item(self, ref: str = "", kind: str = "", id: str = "", *,
             related: bool = False, include_html: bool = False,
             content_limit: int = 0) -> dict[str, Any]:
        self.require_capability("item")
        raise CitrusError("unsupported_capability", "item 未实现。", platform=self.platform)

    def comments(self, ref: str = "", kind: str = "", id: str = "", *,
                 limit: int = 20, page: int = 1, sort: str = "") -> dict[str, Any]:
        self.require_capability("comments")
        raise CitrusError("unsupported_capability", "comments 未实现。", platform=self.platform)

    def user(self, ref: str = "") -> dict[str, Any]:
        self.require_capability("user")
        raise CitrusError("unsupported_capability", "user 未实现。", platform=self.platform)

    def user_content(self, ref: str = "", limit: int = 20, page: int = 1) -> dict[str, Any]:
        self.require_capability("user_content")
        raise CitrusError("unsupported_capability", "user_content 未实现。", platform=self.platform)

    def verify(self) -> dict[str, Any]:
        """逐项体检：返回 [{name, ok, detail, hint}]，永远不抛异常。"""
        results: list[dict[str, Any]] = []
        for capability in self.capabilities:
            if capability == "account":
                continue
            results.append({
                "name": capability,
                "ok": False,
                "detail": "未实现自检",
                "hint": "",
            })
        return {"platform": self.platform, "configured": self.has_credential, "checks": results}
