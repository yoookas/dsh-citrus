"""极简路由：把 path 切成段做前缀匹配，支持 :param。

只为了服务这一套固定接口，不需要正则路由库：

    /v1/:platform/item      -> {"platform": "zhihu"}
    /v1/accounts/:platform  -> {"platform": "zhihu"}

路径里带中文/空格也无所谓，会先 unquote。
"""

import re
import urllib.parse
from collections.abc import Callable
from typing import Any

from ..errors import CitrusError

_SLASHES = re.compile(r"/+")


def normalize_path(path: str) -> str:
    raw = urllib.parse.unquote(path or "/")
    raw = _SLASHES.sub("/", raw.strip())
    if not raw.startswith("/"):
        raw = "/" + raw
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw.rstrip("/") or "/"
    return raw


class Route:
    __slots__ = ("method", "pattern", "segments", "handler", "name")

    def __init__(self, method: str, pattern: str, handler: Callable[..., Any], name: str = "") -> None:
        self.method = method.upper()
        self.pattern = pattern
        self.segments = [seg for seg in normalize_path(pattern).split("/") if seg]
        self.handler = handler
        self.name = name or pattern

    def match(self, segments: list[str]) -> dict[str, str] | None:
        if len(segments) != len(self.segments):
            return None
        params: dict[str, str] = {}
        for expected, actual in zip(self.segments, segments):
            if expected.startswith(":"):
                if not actual:
                    return None
                params[expected[1:]] = actual
            elif expected != actual:
                return None
        return params


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Callable[..., Any], name: str = "") -> Route:
        route = Route(method, pattern, handler, name)
        self.routes.append(route)
        return route

    def get(self, pattern: str, handler: Callable[..., Any], name: str = "") -> Route:
        return self.add("GET", pattern, handler, name)

    def post(self, pattern: str, handler: Callable[..., Any], name: str = "") -> Route:
        return self.add("POST", pattern, handler, name)

    def put(self, pattern: str, handler: Callable[..., Any], name: str = "") -> Route:
        return self.add("PUT", pattern, handler, name)

    def delete(self, pattern: str, handler: Callable[..., Any], name: str = "") -> Route:
        return self.add("DELETE", pattern, handler, name)

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]]:
        method = (method or "GET").upper()
        segments = [seg for seg in normalize_path(path).split("/") if seg]
        allowed: list[str] = []
        for route in self.routes:
            params = route.match(segments)
            if params is None:
                continue
            if route.method == method or route.method == "ANY":
                return route, params
            allowed.append(route.method)
        if allowed:
            raise CitrusError("method_not_allowed",
                              "%s 不支持 %s 方法。" % (normalize_path(path), method),
                              "可用方法：%s。" % ", ".join(sorted(set(allowed))),
                              status=405)
        raise CitrusError("route_not_found", "没有这个接口：%s" % normalize_path(path),
                          "先 GET /v1/platforms 看看平台和能力，或 GET /v1/openapi.json 拿完整清单。",
                          status=404)
