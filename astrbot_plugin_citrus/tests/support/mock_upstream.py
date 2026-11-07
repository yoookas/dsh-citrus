"""一个假的知乎：本地起一个 HTTP 服务，按路径吐固定 JSON。

测试里把 CITRUS_ZHIHU_BASE_URL 指过来就行 —— 适配器本来就走 PacedHttpClient，
换 base_url 不需要任何代码改动。
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        store = self.server.store  # type: ignore[attr-defined]
        store.record(parsed.path, parsed.query, dict(self.headers.items()))
        status, payload, raw = store.resolve(parsed.path, parsed.query, dict(self.headers.items()))
        if raw is not None:
            body = raw.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class MockUpstream:
    """按 path 注册响应；同时记录所有收到的请求，方便断言。"""

    def __init__(self) -> None:
        self._routes: dict[str, tuple[int, Any, str | None]] = {}
        self._sequences: dict[str, list[tuple[int, Any]]] = {}
        self._dynamic: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.store = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ---- 生命周期 ---------------------------------------------------

    def start(self) -> "MockUpstream":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return "http://%s:%d" % (host, port)

    # ---- 路由 -------------------------------------------------------

    def reset_routes(self) -> None:
        """清空所有路由，避免上一个用例的动态路由污染下一个。"""
        self._routes.clear()
        self._sequences.clear()
        self._dynamic.clear()

    def add_json(self, path: str, payload: Any, status: int = 200) -> None:
        self._routes[urllib.parse.urlsplit(path).path] = (status, payload, None)

    def add_raw(self, path: str, text: str, status: int = 200) -> None:
        self._routes[urllib.parse.urlsplit(path).path] = (status, None, text)

    def add_status(self, path: str, status: int, payload: Any = None) -> None:
        self._routes[urllib.parse.urlsplit(path).path] = (status, payload or {}, None)

    def add_sequence(self, path: str, responses: list[tuple[int, Any]]) -> None:
        """按顺序吐一串响应（最后一个会一直重复），用来测重试。"""
        self._sequences[urllib.parse.urlsplit(path).path] = list(responses)

    def add_dynamic(self, path: str, factory: Any) -> None:
        """factory(query, headers) -> (status, payload)：模拟翻页、或按 Cookie 区分账号。"""
        self._dynamic[urllib.parse.urlsplit(path).path] = factory

    def resolve(self, path: str, query: str = "",
                headers: dict[str, str] | None = None) -> tuple[int, Any, str | None]:
        dynamic = self._dynamic.get(path)
        if dynamic is not None:
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(query).items()}
            status, payload = dynamic(params, {k.lower(): v for k, v in (headers or {}).items()})
            return status, payload, None
        sequence = self._sequences.get(path)
        if sequence:
            status, payload = sequence.pop(0) if len(sequence) > 1 else sequence[0]
            return status, payload, None
        if path in self._routes:
            return self._routes[path]
        return 404, {"error": {"message": "not found"}}, None

    def record(self, path: str, query: str, headers: dict[str, str]) -> None:
        with self._lock:
            self.calls.append({"path": path, "query": query, "headers": headers})

    def paths(self) -> list[str]:
        with self._lock:
            return [call["path"] for call in self.calls]

    def last(self) -> dict[str, Any]:
        with self._lock:
            return self.calls[-1] if self.calls else {}

    def reset(self) -> None:
        with self._lock:
            self.calls = []


def sample_hot_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "card_id": "Q_123456",
                "target": {
                    "title_area": {"text": "如何评价最近的大模型竞赛？"},
                    "excerpt_area": {"text": "几家厂商同时发模型。"},
                    "metrics_area": {"text": "1234 万热度"},
                    "question": {"id": "123456"},
                },
            },
            {
                "card_id": "P_789",
                "target": {
                    "title_area": {"text": "一篇讲性能优化的文章"},
                    "excerpt_area": {"text": "从 GC 讲到缓存。"},
                    "metrics_area": {"text": "88 万热度"},
                },
            },
        ]
    }


def sample_answer(target_id: int = 111, question_id: int = 222) -> dict[str, Any]:
    return {
        "type": "answer",
        "id": target_id,
        "question": {"id": question_id, "title": "这个问题值得读吗？"},
        "content": "<p>这是<strong>正文</strong>第一段。</p><p>第二段。</p>",
        "excerpt": "这是正文第一段。",
        "author": {"name": "张三", "url_token": "zhangsan", "headline": "写代码的"},
        "voteup_count": 1234,
        "comment_count": 56,
        "created_time": 1700000000,
        "updated_time": 1700003600,
    }


def sample_feed_payload() -> dict[str, Any]:
    return {
        "data": [
            {"type": "feed", "target": sample_answer(111, 222)},
            {"type": "ad_feed", "target": {"type": "ad", "id": 999}},
            {
                "type": "feed",
                "target": {
                    "type": "article",
                    "id": 333,
                    "title": "一篇文章",
                    "content": "<p>文章正文</p>",
                    "excerpt": "文章正文",
                    "author": {"name": "李四", "url_token": "lisi"},
                    "voteup_count": 20,
                    "comment_count": 3,
                    "created": 1699999999,
                },
            },
        ]
    }


def sample_search_payload() -> dict[str, Any]:
    return {
        "data": [
            {"type": "relevant_query", "object": {"type": "relevant_query"}},
            {"type": "search_result", "object": sample_answer(111, 222)},
            {
                "type": "search_result",
                "object": {
                    "type": "people",
                    "id": "zhangsan",
                    "url_token": "zhangsan",
                    "name": "张三",
                    "headline": "写代码的",
                    "follower_count": 4321,
                },
            },
        ]
    }


def sample_comments_v5_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "9001",
                "content": "<p>说得好。</p>",
                "author": {"name": "李四", "url_token": "lisi"},
                "like_count": 12,
                "child_comment_count": 2,
                "created_time": 1700000000,
            }
        ],
        "paging": {"is_end": True, "totals": 1},
    }


def sample_comments_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": 9001,
                "content": "<p>说得好。</p>",
                "author": {"name": "李四", "url_token": "lisi"},
                "vote_count": 3,
                "reply_count": 2,
                "created_time": 1700000000,
            }
        ],
        "paging": {"is_end": True, "totals": 1},
    }


def install_default_routes(upstream: MockUpstream) -> None:
    """装好一套「一切正常」的知乎（会先清空旧路由）。"""
    upstream.reset_routes()
    upstream.add_json("/api/v3/feed/topstory/hot-lists/total", sample_hot_payload())
    upstream.add_json("/api/v3/feed/topstory/recommend", sample_feed_payload())
    upstream.add_json("/api/v3/feed/topstory", sample_feed_payload())
    upstream.add_json("/api/v4/search_v3", sample_search_payload())
    upstream.add_json("/api/v4/answers/111", sample_answer(111, 222))
    upstream.add_json("/api/v4/articles/333", {
        "type": "article",
        "id": 333,
        "title": "一篇文章",
        "content": "<p>文章正文</p>",
        "excerpt": "文章正文",
        "author": {"name": "李四", "url_token": "lisi"},
        "voteup_count": 20,
        "comment_count": 3,
        "created": 1699999999,
    })
    upstream.add_json("/api/v4/questions/222", {
        "id": 222,
        "title": "这个问题值得读吗？",
        "detail": "<p>问题描述。</p>",
        "answer_count": 42,
        "follower_count": 1000,
        "visit_count": 99999,
        "created": 1699990000,
    })
    upstream.add_json("/api/v4/questions/222/answers", {
        "data": [sample_answer(111, 222), sample_answer(444, 222)],
    })
    # 新版评论接口（主路径）
    upstream.add_json("/api/v4/comment_v5/answers/111/root_comment", sample_comments_v5_payload())
    upstream.add_json("/api/v4/comment_v5/articles/333/root_comment",
                      {"data": [], "paging": {"is_end": True, "totals": 0}})
    # 旧版评论接口（comment_v5 挂了时兜底）
    upstream.add_json("/api/v4/answers/111/comments", sample_comments_payload())
    upstream.add_status("/api/v4/articles/333/comments", 404)
    upstream.add_json("/api/v4/me", {"name": "我", "url_token": "me-self", "headline": "测试账号"})
    upstream.add_json("/api/v4/members/zhangsan", {
        "name": "张三",
        "url_token": "zhangsan",
        "headline": "写代码的",
        "answer_count": 5,
        "articles_count": 2,
        "follower_count": 100,
    })
    upstream.add_json("/api/v4/members/zhangsan/answers", {"data": [sample_answer(111, 222)]})
    upstream.add_json("/api/v4/members/zhangsan/articles", {"data": []})
