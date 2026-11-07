"""HTTP 传输层 —— 标准库 http.server，够用且没有依赖。

这一层只做四件事：读请求、鉴权、把 handler 的结果套成信封、写回去。
业务判断一律不在这里。
"""

import json
import logging
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .api import Api
from .errors import CitrusError, as_citrus_error
from .http_utils import Request, error_envelope, success_envelope


class CitrusHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: Any) -> None:
        self.app = app
        self.api = Api(app)
        ThreadingHTTPServer.__init__(self, address, CitrusRequestHandler)

    @property
    def address_string(self) -> str:  # pragma: no cover - 兼容
        return "%s:%d" % self.server_address


class CitrusRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "citrus/" + __version__
    sys_version = ""

    # ---- 入口 -------------------------------------------------------

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:
        self._send(204, None, extra_headers=self._cors_headers())

    def log_message(self, fmt: str, *args: Any) -> None:
        # 交给 app 的 logger，别让默认 stderr 淹没日志
        self._app().log("%s - %s" % (self.address_string(), fmt % args), logging.DEBUG)

    # ---- 主流程 -----------------------------------------------------

    def _handle(self, method: str) -> None:
        app = self._app()
        try:
            parsed = urllib.parse.urlsplit(self.path)
            body = self._read_body(app)
            request = Request(
                method,
                urllib.parse.unquote(parsed.path) or "/",
                parsed.query,
                dict(self.headers.items()),
                body,
                self.client_address[0] if self.client_address else "",
            )
            self._authorize(app, request)
            data, platform = self.server.api.dispatch(request)  # type: ignore[attr-defined]
            payload = success_envelope(data, request, platform=platform)
            self._send(200, payload)
        except CitrusError as exc:
            self._send(exc.status, error_envelope(exc, locals().get("request")))
        except Exception as exc:  # 兜底：任何未捕获异常都不能让连接悬着
            traceback.print_exc()
            app.log("未处理异常：%s" % exc, logging.ERROR)
            wrapped = as_citrus_error(exc)
            self._send(500, error_envelope(wrapped))

    def _app(self) -> Any:
        return self.server.app  # type: ignore[attr-defined]

    def _read_body(self, app: Any) -> bytes:
        raw_length = self.headers.get("content-length")
        if not raw_length:
            return b""
        try:
            length = int(raw_length)
        except ValueError:
            raise CitrusError("bad_request", "Content-Length 不是数字。")
        if length <= 0:
            return b""
        limit = int(getattr(app.config, "max_body_bytes", 65536))
        if length > limit:
            # 没读 body 就不能复用这条连接，否则下一个请求会读到残留字节
            self.close_connection = True
            raise CitrusError("payload_too_large", "请求体太大了（%d 字节，上限 %d）。" % (length, limit),
                              "Cookie 一般不到 8 KB；确认没把整页 HTML 贴进来。")
        return self.rfile.read(length)

    def _authorize(self, app: Any, request: Request) -> None:
        token = getattr(app.config, "api_token", "") or ""
        if not token:
            return
        if request.path in ("/v1/health", "/"):
            return
        provided = request.header("x-api-key")
        if not provided:
            authorization = request.header("authorization")
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
        if provided != token:
            raise CitrusError("unauthorized", "缺少或错误的 API token。",
                              "带 Authorization: Bearer <CITRUS_API_TOKEN> 或 X-Api-Key。",
                              status=401)

    # ---- 回包 -------------------------------------------------------

    def _cors_headers(self) -> dict[str, str]:
        app = self._app()
        origin = getattr(app.config, "cors_origin", "") or ""
        if not origin:
            return {}
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Api-Key, X-Citrus-Cookie, X-Citrus-Account, X-Citrus-User-Agent",
            "Access-Control-Max-Age": "600",
        }

    def _send(self, status: int, payload: dict[str, Any] | None,
              extra_headers: dict[str, str] | None = None) -> None:
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            headers = self._cors_headers()
            headers.update(extra_headers or {})
            for key, value in headers.items():
                self.send_header(key, value)
            request_id = ""
            if isinstance(payload, dict):
                meta = payload.get("meta")
                if isinstance(meta, dict):
                    request_id = str(meta.get("request_id") or "")
                if not request_id:
                    error = payload.get("error")
                    if isinstance(error, dict):
                        request_id = str(error.get("request_id") or "")
            if request_id:
                self.send_header("X-Citrus-Request-Id", request_id)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def create_server(app: Any, host: str = "", port: int = 0) -> CitrusHTTPServer:
    host = host or app.config.host
    port = app.config.port if port is None else port
    return CitrusHTTPServer((host, int(port)), app)


def serve(app: Any, host: str = "", port: int | None = None,
          on_ready: Any = None) -> Any:
    """阻塞式启动。Ctrl-C 之后干净退出。"""
    server = create_server(app, host or app.config.host,
                           app.config.port if port is None else port)
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    app.log("citrus %s 已启动：http://%s:%d" % (__version__, bound_host, bound_port))
    if on_ready is not None:
        on_ready(server)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        app.log("收到 Ctrl-C，正在退出")
    finally:
        server.shutdown()
        server.server_close()
    return server
