"""知乎这一侧的「手」：带登录态的请求 + 错误翻译。

只管发请求和把上游异常翻译成统一错误码；数据长什么样由 normalize.py 负责。
"""

from typing import Any

from ...core.upstream import PacedHttpClient
from ...errors import CitrusError
from . import endpoints

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS: dict[str, str] = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.6",
    "accept-encoding": "identity",
    "referer": "https://www.zhihu.com/",
    "origin": "https://www.zhihu.com",
    "x-requested-with": "XMLHttpRequest",
    "x-api-version": "3.0.91",
}

ERROR_HINTS: dict[str, str] = {
    "no_credential": "先 PUT /v1/accounts/zhihu 把浏览器里的 Cookie 存进来。",
    "not_logged_in": "Cookie 里没有有效登录态（z_c0）。在浏览器重新登录知乎，再复制一次。",
    "challenge": "知乎的风控拦了这次请求（返回验证页）。先回浏览器正常打开 zhihu.com 通过验证，等几分钟再试；短时间别连续重试。",
    "forbidden": "知乎返回 403：可能 Cookie 不完整、请求太频繁，或当前网络出口被限制。",
    "not_found": "这条内容不存在，或已被删除/折叠。",
    "rate_limited": "被知乎限流了，等几分钟再试（服务已自动重试过）。",
    "network": "请求没发出去（网络/代理/DNS）。检查本机能否正常打开知乎。",
    "bad_upstream_response": "知乎返回的不是预期的 JSON（多半又是风控页）。过一会儿再试。",
    "upstream": "知乎返回了意外的状态码。",
}


class ZhihuClient:
    """一个（平台 + Cookie）组合对应一个实例；内部串行限速。"""

    def __init__(self, cookie: str, user_agent: str = "", *,
                 base_url: str = endpoints.BASE_URL,
                 gap_seconds: float = 0.35,
                 jitter_seconds: float = 0.25,
                 burst_every: int = 15,
                 burst_min_seconds: float = 1.2,
                 burst_max_seconds: float = 3.0,
                 timeout: float = 20.0,
                 max_retries: int = 2,
                 rng: Any | None = None,
                 logger: Any | None = None) -> None:
        self.cookie = cookie or ""
        self.user_agent = user_agent or DEFAULT_UA
        headers = dict(BROWSER_HEADERS)
        headers["user-agent"] = self.user_agent
        headers["cookie"] = self.cookie
        self.http = PacedHttpClient(
            base_url or endpoints.BASE_URL,
            gap_seconds=gap_seconds,
            jitter_seconds=jitter_seconds,
            burst_every=burst_every,
            burst_min_seconds=burst_min_seconds,
            burst_max_seconds=burst_max_seconds,
            timeout=timeout,
            rng=rng,
            max_retries=max_retries,
            default_headers=headers,
            error_hints=ERROR_HINTS,
            logger=logger,
        )

    def get(self, spec: Any) -> Any:
        """spec 是 endpoints 里那些函数返回的 (path, params)。"""
        path, params = spec
        return self.http.get_json(path, params=params)

    # ---- 语义化封装（adapter 只调这些） -----------------------------

    def me(self) -> Any:
        return self.get(endpoints.me())

    def hot(self, limit: int = 20) -> Any:
        return self.get(endpoints.hot(limit))

    def recommend(self, limit: int = 20, page: int = 1) -> Any:
        return self.get(endpoints.recommend(limit, page))

    def following(self, limit: int = 20, page: int = 1) -> Any:
        return self.get(endpoints.following(limit, page))

    def search(self, query: str, limit: int = 20, offset: int = 0, kind: str = "") -> Any:
        return self.get(endpoints.search(query, limit, offset, kind))

    def answer(self, answer_id: str) -> Any:
        return self.get(endpoints.answer(answer_id))

    def article(self, article_id: str) -> Any:
        return self.get(endpoints.article(article_id))

    def question(self, question_id: str) -> Any:
        return self.get(endpoints.question(question_id))

    def question_answers(self, question_id: str, limit: int = 3, offset: int = 0,
                         sort_by: str = "default") -> Any:
        return self.get(endpoints.question_answers(question_id, limit, offset, sort_by))

    def pin(self, pin_id: str) -> Any:
        return self.get(endpoints.pin(pin_id))

    def zvideo(self, zvideo_id: str) -> Any:
        return self.get(endpoints.zvideo(zvideo_id))

    def comments(self, kind: str, resource_id: str, limit: int = 20, offset: int = 0,
                 variant: str = "v5", sort: str = "hot") -> Any:
        """variant: v5 / legacy；sort: hot / new。选哪个由 adapter 按资源类型决定。"""
        if variant == "legacy":
            return self.get(endpoints.comments_legacy(kind, resource_id, limit, offset, sort))
        return self.get(endpoints.comments_v5(kind, resource_id, limit, offset, sort))

    def member(self, token: str) -> Any:
        return self.get(endpoints.member(token))

    def member_answers(self, token: str, limit: int = 20, offset: int = 0) -> Any:
        return self.get(endpoints.member_answers(token, limit, offset))

    def member_articles(self, token: str, limit: int = 20, offset: int = 0) -> Any:
        return self.get(endpoints.member_articles(token, limit, offset))

    def followees(self, token: str, limit: int = 20) -> Any:
        return self.get(endpoints.followees(token, limit))
