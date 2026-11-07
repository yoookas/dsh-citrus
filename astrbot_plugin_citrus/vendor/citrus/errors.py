"""统一错误。

整个服务只抛一种异常、只返回一套错误码 —— 这样 agent 读一次文档就能处理所有平台。
每个错误自带三样对 agent 有用的东西：

* code      —— 机器可判定的短码（not_logged_in / rate_limited / ...）
* message   —— 人话，说明发生了什么
* hint      —— 下一步该做什么（可以直接念给用户听）

HTTP 状态码只是 code 的投影，业务真正该看的是 code。
"""

from typing import Any

#: 错误码 -> HTTP 状态码
ERROR_STATUS = {
    "bad_request": 400,
    "invalid_argument": 400,
    "unauthorized": 401,
    "no_credential": 409,
    "not_logged_in": 401,
    "challenge": 403,
    "forbidden": 403,
    "not_found": 404,
    "unknown_platform": 404,
    "route_not_found": 404,
    "method_not_allowed": 405,
    "payload_too_large": 413,
    "unsupported_capability": 400,
    "rate_limited": 429,
    "network": 502,
    "upstream": 502,
    "bad_upstream_response": 502,
    "internal": 500,
}

#: 同样的请求晚点再发一次可能就成功的错误码
RETRYABLE_CODES = frozenset({"rate_limited", "network", "upstream"})


class CitrusError(Exception):
    """服务里唯一的异常类型。"""

    def __init__(self, code: str, message: str, hint: str = "", *,
                 status: int | None = None,
                 retryable: bool | None = None,
                 platform: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint or ""
        self.status = ERROR_STATUS.get(code, 500) if status is None else int(status)
        self.retryable = (code in RETRYABLE_CODES) if retryable is None else bool(retryable)
        self.platform = platform
        self.details = details or {}

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.hint:
            payload["hint"] = self.hint
        if self.platform:
            payload["platform"] = self.platform
        if self.details:
            payload["details"] = self.details
        if request_id:
            payload["request_id"] = request_id
        return payload

    def __str__(self) -> str:
        return self.message + ("\n" + self.hint if self.hint else "")


def bad_request(message: str, hint: str = "") -> CitrusError:
    return CitrusError("bad_request", message, hint)


def invalid_argument(name: str, message: str, hint: str = "") -> CitrusError:
    return CitrusError("invalid_argument", "参数 %s 不合法：%s" % (name, message), hint,
                       details={"argument": name})


def as_citrus_error(exc: BaseException, platform: str | None = None) -> CitrusError:
    """把任何异常收敛成 CitrusError，顺便补上平台名。"""
    if isinstance(exc, CitrusError):
        if platform and not exc.platform:
            exc.platform = platform
        return exc
    if isinstance(exc, KeyboardInterrupt):
        raise exc
    return CitrusError("internal", "%s: %s" % (type(exc).__name__, exc), platform=platform)
