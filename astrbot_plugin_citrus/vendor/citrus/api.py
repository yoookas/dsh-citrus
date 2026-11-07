"""HTTP 接口层 —— 一张路由表 + 每个接口做什么。

设计口径：

* 平台路由 /v1/<platform>/<capability> 与平台无关：加一个平台，路由不用改；
* 所有 handler 返回「数据」，信封（ok/data/meta）由 server 统一套；
* handler 里不写 try/except：错误往上抛，server 翻译成统一错误信封；
* 能力判定交给 adapter：没声明的能力会得到 unsupported_capability 而不是 404。
"""

import time
from typing import Any

from . import __version__
from .core.cookies import parse_cookie_input
from .core.model import now_iso
from .core.router import Router
from .errors import CitrusError
from .http_utils import Request
from .openapi import build_openapi

STARTED_AT = time.time()


class Api:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.router = Router()
        self._register()

    # ---- 路由表 -----------------------------------------------------

    def _register(self) -> None:
        router = self.router
        router.get("/", self.index, "index")
        router.get("/v1/health", self.health, "health")
        router.get("/v1/platforms", self.platforms, "platforms")
        router.get("/v1/openapi.json", self.openapi, "openapi")

        router.get("/v1/accounts", self.accounts_list, "accounts_list")
        router.put("/v1/accounts/:platform", self.accounts_put, "accounts_put")
        router.get("/v1/accounts/:platform", self.accounts_get, "accounts_get")
        router.delete("/v1/accounts/:platform", self.accounts_delete, "accounts_delete")
        router.post("/v1/accounts/:platform/verify", self.accounts_verify, "accounts_verify")

        router.get("/v1/:platform/account", self.platform_account, "platform_account")
        router.get("/v1/:platform/feed", self.platform_feed, "platform_feed")
        router.get("/v1/:platform/hot", self.platform_hot, "platform_hot")
        router.get("/v1/:platform/search", self.platform_search, "platform_search")
        router.get("/v1/:platform/item", self.platform_item, "platform_item")
        router.get("/v1/:platform/comments", self.platform_comments, "platform_comments")
        router.get("/v1/:platform/user", self.platform_user, "platform_user")
        router.get("/v1/:platform/user/content", self.platform_user_content, "platform_user_content")
        router.get("/v1/:platform/raw", self.platform_raw, "platform_raw")

    def dispatch(self, request: Request) -> tuple[Any, str]:
        route, params = self.router.match(request.method, request.path)
        data = route.handler(request, params)
        return data, params.get("platform", "")

    # ---- 取适配器 ---------------------------------------------------

    def _adapters(self, platform: str, request: Request) -> list[Any]:
        credential: dict[str, str] | None = None
        raw_cookie = request.header("x-citrus-cookie")
        if raw_cookie:
            meta = self.app.registry.meta(platform)
            parsed = parse_cookie_input(
                raw_cookie,
                auth_cookie_names=meta["auth_cookie_names"],
                platform=platform,
            )
            credential = {
                "cookie": parsed.cookie,
                "user_agent": request.header("x-citrus-user-agent") or parsed.user_agent,
            }
        label = request.query_str("account") or request.header("x-citrus-account") or None
        return self.app.adapter_chain(platform, label=label, credential=credential)

    def _adapter(self, platform: str, request: Request) -> Any:
        """只取首选账号（不需要故障转移的场合，例如看账号状态）。"""
        return self._adapters(platform, request)[0]

    def _call(self, platform: str, request: Request, action: Any) -> Any:
        """跑一个能力；当前号挂了就按配置换下一个号。

        只对 CITRUS_ROTATION_TRIGGERS 里的错误码换号（默认只有 not_logged_in，
        也就是「这个 Cookie 失效了」），不是见到什么都换 —— 换号不是绕过限流的手段。
        """
        chain = self._adapters(platform, request)
        triggers = (tuple(self.app.config.rotation_triggers)
                    if self.app.config.rotation == "failover" else ())
        last_error: CitrusError | None = None
        for index, adapter in enumerate(chain):
            try:
                data = action(adapter)
            except CitrusError as exc:
                last_error = exc
                if exc.code not in triggers or index == len(chain) - 1:
                    raise
                self.app.log("%s 账号 %s 不可用（%s），换 %s 重试" % (
                    platform, adapter.label, exc.code, chain[index + 1].label))
                continue
            request.served_by = adapter.label
            if index > 0:
                self.app.log("%s 这次由备用账号 %s 完成" % (platform, adapter.label))
            return data
        raise last_error

    # ---- 元信息 -----------------------------------------------------

    def index(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        return {
            "service": "citrus",
            "version": __version__,
            "description": "统一社交平台信息 API：给每个平台配一份 Cookie，就有一套形状一致的读接口。",
            "endpoints": {
                "platforms": "/v1/platforms",
                "accounts": "/v1/accounts",
                "openapi": "/v1/openapi.json",
                "health": "/v1/health",
                "platform_api": "/v1/<platform>/{account,feed,hot,search,item,comments,user,user/content}",
            },
            "auth": "默认只听 127.0.0.1；设了 CITRUS_API_TOKEN 就要带 Authorization: Bearer <token>。",
        }

    def health(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": int(time.time() - STARTED_AT),
            "platforms": self.app.registry.ids(),
            "cache": self.app.cache.stats(),
            "checked_at": now_iso(),
        }

    def platforms(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for platform in self.app.registry.ids():
            described = self.app.registry.describe(platform)
            accounts = [
                self.app.accounts.describe(platform, label)
                for label in self.app.accounts.labels(platform)
            ]
            described["configured"] = bool(accounts)
            described["accounts"] = accounts
            described["capability_endpoints"] = {
                capability: "/v1/%s/%s" % (platform, _CAPABILITY_PATHS.get(capability, capability))
                for capability in described.get("capabilities", [])
            }
            rows.append(described)
        return {"platforms": rows, "count": len(rows)}

    def openapi(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        return build_openapi(self.app)

    # ---- 账号 -------------------------------------------------------

    def accounts_list(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        rows = self.app.accounts.describe_all()
        return {"accounts": rows, "count": len(rows), "home": str(self.app.accounts.home)}

    def accounts_put(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        platform = params["platform"]
        self.app.registry.require(platform)
        body = request.json_body
        if not isinstance(body, dict):
            raise CitrusError("bad_request", "请求体必须是一个 JSON 对象。",
                              "例如 {\"cookie\": \"<浏览器里 Copy as cURL 的内容>\"}")
        text = ""
        for key in ("cookie", "curl", "raw", "value"):
            candidate = body.get(key)
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
                break
        if not text:
            raise CitrusError("bad_request", "请求体里没有 Cookie。",
                              "字段名用 cookie（也认 curl / raw），值可以是 cURL、Cookie 头、裸 Cookie 串或 JSON 对象。")
        label = str(body.get("label") or self.app.config.default_account)
        user_agent = str(body.get("user_agent") or "")
        described = self.app.set_credential(platform, text, label=label, user_agent=user_agent)
        return {"account": described, "message": "Cookie 已保存。可以 POST /v1/accounts/%s/verify 体检一下。" % platform}

    def accounts_get(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        platform = params["platform"]
        self.app.registry.require(platform)
        label = request.query_str("account") or self.app.config.default_account
        described = self.app.accounts.describe(platform, label)
        if request.query_bool("live") and described.get("configured"):
            described["profile"] = self._adapter(platform, request).account().get("profile")
        return described

    def accounts_delete(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        platform = params["platform"]
        self.app.registry.require(platform)
        label = request.query_str("account") or request.query_one("label")
        removed = self.app.accounts.delete(platform, label or None)
        self.app.registry.invalidate(platform)
        self.app.cache.clear()
        return {"platform": platform, "label": label or "*", "removed": removed}

    def accounts_verify(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        platform = params["platform"]
        if request.query_bool("all"):
            # 一次把所有号都体检一遍，多号场景下这比逐个问省事
            labels = self.app.account_labels(platform)
            results = []
            for label in labels:
                try:
                    results.append(self.app.adapter(platform, label=label).verify())
                except CitrusError as exc:
                    results.append({"platform": platform, "label": label,
                                    "configured": False, "ok": False,
                                    "checks": [], "error": exc.to_dict()})
            return {
                "platform": platform,
                "count": len(results),
                "ok": bool(results) and all(row.get("ok") for row in results),
                "accounts": results,
            }
        return self._adapter(platform, request).verify()

    # ---- 平台能力 ---------------------------------------------------

    def platform_account(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        return self._call(params["platform"], request, lambda adapter: adapter.account())

    def platform_feed(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        source = request.query_str("source")
        limit = request.query_int("limit", 20, 1, 100)
        page = request.query_int("page", 1, 1, 10)
        return self._call(params["platform"], request,
                          lambda adapter: adapter.feed(source=source, limit=limit, page=page))

    def platform_hot(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        limit = request.query_int("limit", 20, 1, 100)
        return self._call(params["platform"], request,
                          lambda adapter: adapter.hot(limit=limit))

    def platform_search(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        query = request.query_str("q") or request.query_str("query") or request.query_str("keyword")
        limit = request.query_int("limit", 20, 1, 100)
        page = request.query_int("page", 1, 1, 10)
        sort = request.query_str("sort")
        kind = request.query_str("kind")
        return self._call(params["platform"], request, lambda adapter: adapter.search(
            query=query, limit=limit, page=page, sort=sort, kind=kind))

    def platform_item(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        ref = (request.query_str("ref") or request.query_str("url")
               or request.query_str("id_or_url"))
        kind = request.query_str("kind")
        item_id = request.query_str("id")
        related = request.query_bool("related")
        include_html = request.query_bool("include_html")
        content_limit = request.query_int("content_limit", 0, 0, 50000)
        return self._call(params["platform"], request, lambda adapter: adapter.item(
            ref=ref, kind=kind, id=item_id, related=related,
            include_html=include_html, content_limit=content_limit))

    def platform_comments(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        ref = request.query_str("ref") or request.query_str("url")
        kind = request.query_str("kind")
        item_id = request.query_str("id")
        limit = request.query_int("limit", 20, 1, 100)
        page = request.query_int("page", 1, 1, 10)
        sort = request.query_str("sort")
        return self._call(params["platform"], request, lambda adapter: adapter.comments(
            ref=ref, kind=kind, id=item_id, limit=limit, page=page, sort=sort))

    def platform_user(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        ref = (request.query_str("ref") or request.query_str("url")
               or request.query_str("token"))
        return self._call(params["platform"], request,
                          lambda adapter: adapter.user(ref=ref))

    def platform_user_content(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        ref = (request.query_str("ref") or request.query_str("url")
               or request.query_str("token"))
        limit = request.query_int("limit", 20, 1, 100)
        page = request.query_int("page", 1, 1, 10)
        return self._call(params["platform"], request, lambda adapter: adapter.user_content(
            ref=ref, limit=limit, page=page))

    def platform_raw(self, request: Request, params: dict[str, str]) -> dict[str, Any]:
        """逃生口：直接打平台上还没被封装的读接口。默认关闭。"""
        if not self.app.config.allow_raw:
            raise CitrusError("forbidden", "raw 通道默认关闭。",
                              "启动服务时加 --allow-raw（或设 CITRUS_ALLOW_RAW=1）再试；"
                              "能用封装好的接口就别用 raw。")
        platform = params["platform"]
        path = request.query_str("path")
        if not path:
            raise CitrusError("bad_request", "raw 需要一个 path，例如 ?path=/api/v4/answers/123",
                              "只允许 GET，且只能打该平台自己的域名。")
        if not path.startswith("/"):
            raise CitrusError("bad_request", "path 必须以 / 开头。")
        if path.startswith("//"):
            raise CitrusError("bad_request", "path 不能是绝对 URL。")
        adapter = self._adapter(platform, request)
        client = getattr(adapter, "client", None)
        if client is None:
            raise CitrusError("unsupported_capability", "%s 没有可用的 raw 通道。" % platform)
        payload = client.get((path, {
            key: value for key, value in ((k, v[-1]) for k, v in request.query.items())
            if key not in ("path", "account")
        }))
        return {"platform": platform, "path": path, "payload": payload}


_CAPABILITY_PATHS = {
    "account": "account",
    "feed": "feed",
    "hot": "hot",
    "search": "search",
    "item": "item",
    "comments": "comments",
    "user": "user",
    "user_content": "user/content",
}
