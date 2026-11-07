"""HTTP 小工具：请求对象、参数解析、响应封装。只依赖标准库。"""

import json
import time
import urllib.parse
import uuid
from typing import Any

from .errors import CitrusError, invalid_argument


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


def parse_query(query_string: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(query_string or "", keep_blank_values=True)


class Request:
    """一次进来的调用。handler 只跟它打交道。"""

    def __init__(self, method: str, path: str, query_string: str = "",
                 headers: dict[str, str] | None = None, body: bytes = b"",
                 client: str = "") -> None:
        self.method = (method or "GET").upper()
        self.path = path or "/"
        self.query = parse_query(query_string)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body or b""
        self.client = client
        self.request_id = new_request_id()
        self.started_at = time.monotonic()
        #: 这次真正用的是哪个账号（故障转移后会和默认号不同）
        self.served_by = ""
        self._json_cache: Any = _UNSET

    # ---- header -----------------------------------------------------

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default) or default

    # ---- query ------------------------------------------------------

    def query_one(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        if not values:
            return default
        return values[-1]

    def query_str(self, name: str, default: str = "") -> str:
        return self.query_one(name, default)

    def query_int(self, name: str, default: int, minimum: int = 0, maximum: int = 0) -> int:
        raw = self.query_one(name)
        if raw == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            raise invalid_argument(name, "应该是整数，收到 %r" % raw)
        if minimum and value < minimum:
            value = minimum
        if maximum and value > maximum:
            value = maximum
        return value

    def query_bool(self, name: str, default: bool = False) -> bool:
        raw = self.query_one(name)
        if raw == "":
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on", "y")

    # ---- body -------------------------------------------------------

    @property
    def json_body(self) -> Any:
        if self._json_cache is not _UNSET:
            return self._json_cache
        if not self.body:
            self._json_cache = {}
            return self._json_cache
        try:
            self._json_cache = json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CitrusError("bad_request", "请求体不是合法 JSON：%s" % exc,
                              "Content-Type 用 application/json，body 放一个 JSON 对象。")
        return self._json_cache

    def body_str(self, name: str, default: str = "") -> str:
        data = self.json_body
        if not isinstance(data, dict):
            return default
        value = data.get(name)
        return value if isinstance(value, str) else default

    def body_any(self, name: str, default: Any = None) -> Any:
        data = self.json_body
        if not isinstance(data, dict):
            return default
        return data.get(name, default)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


def success_envelope(data: Any, request: Request | None = None,
                     platform: str = "", extra_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if platform:
        meta["platform"] = platform
    if request is not None:
        meta["took_ms"] = request.elapsed_ms()
        meta["request_id"] = request.request_id
        if request.served_by:
            meta["account"] = request.served_by
    if extra_meta:
        meta.update(extra_meta)
    return {"ok": True, "data": data, "meta": meta}


def error_envelope(error: CitrusError, request: Request | None = None) -> dict[str, Any]:
    request_id = request.request_id if request is not None else None
    payload: dict[str, Any] = {"ok": False, "error": error.to_dict(request_id)}
    if request is not None:
        payload["meta"] = {"took_ms": request.elapsed_ms(), "request_id": request.request_id}
    return payload


_UNSET = object()
