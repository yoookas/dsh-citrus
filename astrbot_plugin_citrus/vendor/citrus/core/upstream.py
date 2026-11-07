"""限速 HTTP 客户端 —— 所有平台共用的「一张嘴」。

为什么不是直接 urllib：

* 平台基本都会限流，并发轰炸会直接把号打进风控。这里对同一个客户端实例
  做串行 + 最小间隔；
* 429 / 5xx / 网络抖动都值得重试一次，但要退避（尊重 Retry-After）；
* 上游把「登录失效」「验证页」「限流」混在 HTML 里返回，必须翻译成统一错误码。

只用标准库（urllib），不引第三方依赖。
"""

import gzip
import json
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterable
from typing import Any

from ..errors import CitrusError

DEFAULT_TIMEOUT = 20.0
DEFAULT_GAP_SECONDS = 0.35
DEFAULT_MAX_RETRIES = 2

#: 在固定间隔之上再随机加 0~JITTER 秒，让节奏不是等距的
DEFAULT_JITTER_SECONDS = 0.25
#: 连续发这么多请求后长歇一次（0 = 关）
DEFAULT_BURST_EVERY = 15
DEFAULT_BURST_MIN = 1.2
DEFAULT_BURST_MAX = 3.0

#: 403 里出现这些字样 = 不是「没权限」，而是被塞了验证页
DEFAULT_CHALLENGE_MARKERS = (
    "acw_sc__v2",
    "__jsl_clearance",
    "zh-zse-ck",
    "var arg1",
    "安全验证",
    "请开启 JavaScript",
    "unhuman",
)


class HttpResponse:
    """一次上游响应。body 已解压、已按 charset 解码。"""

    __slots__ = ("status", "headers", "body", "url", "elapsed_ms")

    def __init__(self, status: int, headers: dict[str, str], body: str, url: str, elapsed_ms: int) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url
        self.elapsed_ms = elapsed_ms

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    def json(self) -> Any:
        text = (self.body or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError as exc:
            raise CitrusError(
                "bad_upstream_response",
                "上游返回的不是合法 JSON（%s）。" % exc,
                "多半又被塞了一张网页/验证页；过一会儿再试。",
            )


class PacedHttpClient:
    """串行 + 最小间隔 + 退避重试 + 错误码翻译。"""

    def __init__(self, base_url: str = "", *,
                 gap_seconds: float = DEFAULT_GAP_SECONDS,
                 jitter_seconds: float = DEFAULT_JITTER_SECONDS,
                 burst_every: int = DEFAULT_BURST_EVERY,
                 burst_min_seconds: float = DEFAULT_BURST_MIN,
                 burst_max_seconds: float = DEFAULT_BURST_MAX,
                 timeout: float = DEFAULT_TIMEOUT,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 backoff_seconds: float = 0.7,
                 max_backoff_seconds: float = 8.0,
                 default_headers: dict[str, str] | None = None,
                 error_hints: dict[str, str] | None = None,
                 challenge_markers: Iterable[str] = DEFAULT_CHALLENGE_MARKERS,
                 rng: random.Random | None = None,
                 logger: Callable[[str], None] | None = None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.gap_seconds = max(0.0, float(gap_seconds))
        self.jitter_seconds = max(0.0, float(jitter_seconds))
        self.burst_every = max(0, int(burst_every))
        self.burst_min_seconds = max(0.0, float(burst_min_seconds))
        self.burst_max_seconds = max(self.burst_min_seconds, float(burst_max_seconds))
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.max_backoff_seconds = max(0.0, float(max_backoff_seconds))
        self.default_headers = dict(default_headers or {})
        self.error_hints = dict(error_hints or {})
        self.challenge_markers = tuple(challenge_markers or ())
        self.logger = logger or (lambda _msg: None)
        self._lock = threading.Lock()
        self._last_at = 0.0
        self._since_break = 0
        self._rng = rng or random.Random()
        self.request_count = 0

    # ---- URL / 限速 -------------------------------------------------

    def url_for(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            if not path.startswith("/"):
                path = "/" + path
            url = self.base_url + path
        if params:
            cleaned = {k: v for k, v in params.items() if v is not None}
            if cleaned:
                sep = "&" if urllib.parse.urlsplit(url).query else "?"
                url = url + sep + urllib.parse.urlencode(cleaned, doseq=True)
        return url

    def _pace(self) -> None:
        """让请求节奏别像机器：固定间隔 + 随机抖动，攒够一批再长歇一次。

        注意：这不是「绕过风控」。它只是不把请求打成整齐的节拍器，
        撞上验证页仍然老老实实报 challenge。
        """
        if self.gap_seconds <= 0 and self.jitter_seconds <= 0 and self.burst_every <= 0:
            return
        with self._lock:
            # 每一步都带一点随机：固定间隔 -> [gap, gap + jitter]
            target = self.gap_seconds
            if self.jitter_seconds > 0:
                target += self._rng.uniform(0.0, self.jitter_seconds)
            wait = target - (time.monotonic() - self._last_at)
            if wait > 0:
                time.sleep(wait)
            self._last_at = time.monotonic()

            # 连续请求一段时间后，像人一样停一下去「读」
            self._since_break += 1
            if self.burst_every and self._since_break >= self.burst_every:
                self._since_break = 0
                pause = self._rng.uniform(self.burst_min_seconds, self.burst_max_seconds)
                if pause > 0:
                    self.logger("连续请求 %d 次，歇 %.1fs 再继续" % (self.burst_every, pause))
                    time.sleep(pause)
                    self._last_at = time.monotonic()

    # ---- 请求 -------------------------------------------------------

    def request(self, path: str, *,
                method: str = "GET",
                params: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None,
                json_body: Any = None,
                raw_body: bytes | None = None,
                timeout: float | None = None) -> HttpResponse:
        url = self.url_for(path, params)
        merged = dict(self.default_headers)
        if headers:
            merged.update({k: v for k, v in headers.items() if v is not None})
        data = raw_body
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            merged.setdefault("content-type", "application/json;charset=UTF-8")

        attempt = 0
        last_error: CitrusError | None = None
        while attempt <= self.max_retries:
            attempt += 1
            started = time.monotonic()
            try:
                response = self._attempt(url, method, merged, data, timeout)
            except CitrusError as exc:
                if exc.code in ("network", "upstream", "rate_limited") and attempt <= self.max_retries:
                    last_error = exc
                    self._sleep_backoff(attempt, None)
                    continue
                raise
            elapsed = int((time.monotonic() - started) * 1000)
            response.elapsed_ms = elapsed
            if response.status in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                self._sleep_backoff(attempt, retry_after)
                continue
            self._raise_for_status(response)
            return response
        if last_error is not None:
            raise last_error
        raise CitrusError("upstream", "上游请求失败（重试 %d 次后仍失败）。" % self.max_retries)

    def get_json(self, path: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        return self.request(path, method="GET", params=params, headers=headers).json()

    def post_json(self, path: str, body: Any, *, headers: dict[str, str] | None = None) -> Any:
        return self.request(path, method="POST", json_body=body, headers=headers).json()

    # ---- 内部 -------------------------------------------------------

    def _sleep_backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            delay = min(retry_after, self.max_backoff_seconds)
        else:
            delay = min(self.backoff_seconds * (2 ** (attempt - 1)), self.max_backoff_seconds)
        delay += random.uniform(0, 0.25)
        if delay > 0:
            self.logger("上游限流/抖动，%.1fs 后重试（第 %d 次）" % (delay, attempt))
            time.sleep(delay)

    def _attempt(self, url: str, method: str, headers: dict[str, str],
                 data: bytes | None, timeout: float | None) -> HttpResponse:
        self._pace()
        self.request_count += 1
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        effective_timeout = self.timeout if timeout is None else float(timeout)
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as raw_response:
                status = getattr(raw_response, "status", 200)
                resp_headers = _lower_headers(raw_response.headers)
                body_bytes = raw_response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            resp_headers = _lower_headers(exc.headers)
            try:
                body_bytes = exc.read()
            except Exception:  # pragma: no cover - 极少见
                body_bytes = b""
            finally:
                exc.close()
        except socket.timeout:
            raise CitrusError("network", "请求超时（%ss）。" % effective_timeout,
                              self.error_hints.get("network", ""))
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise CitrusError("network", "请求没发出去：%s" % reason,
                              self.error_hints.get("network", ""))
        except OSError as exc:
            raise CitrusError("network", "请求没发出去：%s" % exc,
                              self.error_hints.get("network", ""))

        body_bytes = _decompress(body_bytes, resp_headers)
        text = _decode(body_bytes, resp_headers.get("content-type", ""))
        return HttpResponse(status, resp_headers, text, url, 0)

    def _raise_for_status(self, response: HttpResponse) -> None:
        status = response.status
        if 200 <= status < 300:
            if _looks_like_challenge(response.body, response.content_type, self.challenge_markers):
                raise CitrusError("challenge", "上游返回的是验证页，不是数据（HTTP %d）。" % status,
                                  self.error_hints.get("challenge", ""))
            return
        hints = self.error_hints
        text = response.body or ""
        if status == 401:
            raise CitrusError("not_logged_in", "上游说：身份未经过验证（401）。", hints.get("not_logged_in", ""))
        if status == 403:
            if _looks_like_challenge(text, response.content_type, self.challenge_markers):
                raise CitrusError("challenge", "上游返回了风控验证页（403）。", hints.get("challenge", ""))
            raise CitrusError("forbidden", "上游返回 403。", hints.get("forbidden", ""))
        if status == 404:
            raise CitrusError("not_found", "上游返回 404：内容不存在或已删除。", hints.get("not_found", ""))
        if status == 429:
            raise CitrusError("rate_limited", "上游限流（429）。", hints.get("rate_limited", ""))
        if status in (400, 422):
            raise CitrusError("bad_upstream_response", "上游拒绝了请求（HTTP %d）。" % status,
                              hints.get("bad_upstream_response", ""))
        raise CitrusError("upstream", "上游返回 HTTP %d。" % status, hints.get("upstream", ""))


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _lower_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if headers is None:
        return out
    try:
        items = headers.items()
    except AttributeError:
        return out
    for key, value in items:
        out[str(key).lower()] = str(value)
    return out


def _decompress(body: bytes, headers: dict[str, str]) -> bytes:
    encoding = (headers.get("content-encoding") or "").lower()
    if not body:
        return body
    try:
        if "gzip" in encoding:
            return gzip.decompress(body)
        if "deflate" in encoding:
            return zlib.decompress(body)
    except Exception:  # pragma: no cover - 上游数据坏了就按原样用
        return body
    return body


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    marker = "charset="
    lowered = (content_type or "").lower()
    if marker in lowered:
        charset = lowered.split(marker, 1)[1].split(";")[0].strip().strip('"')
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _looks_like_challenge(text: str, content_type: str, markers: Iterable[str]) -> bool:
    head = (text or "")[:20000]
    for marker in markers:
        if marker and marker in head:
            return True
    lowered = head.lstrip().lower()
    if "json" in (content_type or "").lower():
        return False
    return lowered.startswith("<!doctype html") or lowered.startswith("<html")
