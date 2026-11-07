"""知乎适配器 —— 把统一能力接到知乎的具体接口上。

编排逻辑全在这里：选接口、限条数、翻页、缓存、把错误补齐上下文。
字段层面的脏活都在 normalize.py。
"""

import re
from typing import Any

from ...core.cookies import mask_cookie
from ...core.model import make_page, now_iso
from ...errors import CitrusError
from ..base import BaseAdapter
from . import normalize
from . import endpoints
from .client import ERROR_HINTS, ZhihuClient, DEFAULT_UA
from .endpoints import BASE_URL

RAW_TTL = 300.0        # 单条正文/档案：5 分钟
LIST_TTL = 60.0        # 热榜这类半静态列表：1 分钟
COMMENT_TTL = 120.0

MAX_PAGE = 10
MAX_FEED = 50
MAX_HOT = 30           # 热榜不给翻页，上游一次最多 30 条
MAX_SEARCH = 100       # 上游每页 20，内部翻页凑够
MAX_COMMENTS = 100     # v5 每页 10 / 旧接口每页 20，内部翻页凑够

#: 一次调用最多打几次上游（翻页预算）。翻倍的是请求数，也是被风控盯上的机会。
SEARCH_PAGE_BUDGET = 6
COMMENT_PAGE_BUDGET = 8

FEED_SOURCES = ("recommend", "hot", "following", "mixed")


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


class ZhihuPlatform(BaseAdapter):
    platform = "zhihu"
    name = "知乎"
    homepage = "https://www.zhihu.com"
    capabilities = ("account", "feed", "hot", "search", "item", "comments", "user", "user_content")
    auth_cookie_names = ("z_c0",)
    error_hints = ERROR_HINTS
    notes = ("只读。用浏览器里的登录态（Cookie 里要有 z_c0）；"
             "请求串行 + 最小间隔，被风控拦了会如实报 challenge，不会假装成功。")

    def __init__(self, app: Any, credential: dict[str, Any] | None = None,
                 label: str = "default") -> None:
        super().__init__(app, credential, label)
        self._client: ZhihuClient | None = None

    # ---- 客户端 -----------------------------------------------------

    @property
    def client(self) -> ZhihuClient:
        cookie = self.require_credential()
        if self._client is None:
            options = self.app.config.platform_options("zhihu") if hasattr(self.app, "config") else {}
            self._client = ZhihuClient(
                cookie,
                self.user_agent or DEFAULT_UA,
                base_url=options.get("base_url", BASE_URL),
                gap_seconds=float(options.get("gap_seconds", 0.35)),
                jitter_seconds=float(options.get("jitter_seconds", 0.25)),
                burst_every=int(options.get("burst_every", 15)),
                burst_min_seconds=float(options.get("burst_min_seconds", 1.2)),
                burst_max_seconds=float(options.get("burst_max_seconds", 3.0)),
                timeout=float(options.get("timeout", 20.0)),
                max_retries=int(options.get("max_retries", 2)),
                logger=lambda message: self.log("[zhihu] " + message),
            )
            self._client.cookie = cookie
        return self._client

    def limits(self) -> dict[str, Any]:
        """各能力的真实上限。知乎会偷偷截断 limit，所以这里给的是「我们保证能凑到」的数。"""
        return {
            "feed": {"limit_max": MAX_FEED, "page_max": MAX_PAGE},
            "hot": {"limit_max": MAX_HOT, "note": "热榜不给翻页"},
            "search": {"limit_max": MAX_SEARCH, "page_max": MAX_PAGE,
                       "note": "上游每页 20，内部翻页"},
            "comments": {"limit_max": MAX_COMMENTS, "page_max": MAX_PAGE,
                         "sort": ["hot", "new"],
                         "note": "上游每页 10/20，内部翻页"},
            "user_content": {"limit_max": MAX_FEED, "page_max": MAX_PAGE},
            "item": {"content_limit_max": normalize.CONTENT_MAX},
        }

    def _cache_key(self, *parts: Any) -> Any:
        return ("zhihu", mask_cookie(self.cookie)) + tuple(str(p) for p in parts)

    def _cached(self, key: Any, ttl: float, loader: Any) -> Any:
        cache = self.app.cache if hasattr(self.app, "cache") else None
        if cache is None:
            return loader()
        found = cache.get(key, _MISSING)
        if found is not _MISSING:
            return found
        value = loader()
        cache.set(key, value, ttl)
        return value

    # ---- account ----------------------------------------------------

    def account(self) -> dict[str, Any]:
        payload = self._cached(self._cache_key("me"), RAW_TTL, self.client.me)
        profile = normalize.normalize_profile(payload)
        try:
            self.app.accounts.update_profile(self.platform, profile, self.label)
        except Exception:  # 存不上只是少了个便利，不该影响这次调用
            pass
        return {
            "platform": self.platform,
            "label": self.label,
            "configured": True,
            "cookie_hint": self.cookie_hint,
            "profile": profile,
            "fetched_at": now_iso(),
        }

    # ---- feed -------------------------------------------------------

    def feed(self, source: str = "", limit: int = 20, page: int = 1) -> dict[str, Any]:
        chosen = (source or "recommend").strip().lower()
        if chosen not in FEED_SOURCES:
            raise CitrusError("bad_request", "不认识的来源：%s" % source,
                              "可用：%s。" % ", ".join(FEED_SOURCES), platform=self.platform)
        count = _clamp(limit, 1, MAX_FEED, 20)
        current = _clamp(page, 1, MAX_PAGE, 1)

        if chosen == "hot":
            return self.hot(limit=count)
        if chosen == "following":
            payload = self.client.following(count, current)
            items = normalize.normalize_feed(payload, "following")
        elif chosen == "mixed":
            items = self._mixed(count, current)
        else:
            payload = self.client.recommend(count, current)
            items = normalize.normalize_feed(payload, "recommend")

        items = _dedupe(items)[:count]
        return make_page(items, page=current, has_more=len(items) >= count, source=chosen)

    def _mixed(self, count: int, page: int) -> list[dict[str, Any]]:
        half = max(1, count // 2)
        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        try:
            items.extend(normalize.normalize_feed(self.client.recommend(half, page), "recommend"))
        except CitrusError as exc:
            errors.append({"source": "recommend", "code": exc.code, "message": exc.message})
        try:
            items.extend(self._hot_items(count - half))
        except CitrusError as exc:
            errors.append({"source": "hot", "code": exc.code, "message": exc.message})
        if not items and errors:
            raise CitrusError(errors[0]["code"], "所有来源都没拿到东西：%s" % errors[0]["message"],
                              "先 POST /v1/accounts/zhihu/verify 看看哪条链路被拦了。",
                              platform=self.platform)
        return _dedupe(items)

    # ---- hot --------------------------------------------------------

    def _hot_items(self, count: int) -> list[dict[str, Any]]:
        payload = self._cached(self._cache_key("hot", count), LIST_TTL, lambda: self.client.hot(count))
        rows = payload.get("data") if isinstance(payload, dict) else None
        items: list[dict[str, Any]] = []
        for row in rows or []:
            item = normalize.normalize_hot_item(row)
            if item is not None:
                items.append(item)
        if not items and isinstance(payload, dict):
            items = normalize.normalize_feed(payload, "hot")
        return items[:count]

    def hot(self, limit: int = 20) -> dict[str, Any]:
        count = _clamp(limit, 1, MAX_HOT, 20)
        items = self._hot_items(count)
        if not items:
            raise CitrusError("bad_upstream_response", "热榜接口通了，但没解析出条目。",
                              "知乎可能改版了；先用 /v1/zhihu/feed?source=recommend 兜底。",
                              platform=self.platform)
        return make_page(items, page=1, has_more=False, source="hot")

    # ---- search -----------------------------------------------------

    def search(self, query: str, limit: int = 20, page: int = 1,
               sort: str = "", kind: str = "") -> dict[str, Any]:
        text = (query or "").strip()
        if not text:
            raise CitrusError("bad_request", "search 需要一个 q（关键词）。",
                              "例如 /v1/zhihu/search?q=大模型&limit=10", platform=self.platform)
        wanted_sort = (sort or "").strip().lower()
        if wanted_sort not in ("", "relevant", "default", "hot"):
            raise CitrusError("bad_request", "知乎搜索不支持 sort=%s。" % sort,
                              "去掉 sort（搜索固定按相关度），或者用 sort=relevant。",
                              platform=self.platform)
        count = _clamp(limit, 1, MAX_SEARCH, 20)
        current = _clamp(page, 1, MAX_PAGE, 1)
        wanted = (kind or "").strip().lower()

        # 上游一页只给 20 条，想要更多就得自己翻。
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        cursor = (current - 1) * count
        pages = 0
        payload: dict[str, Any] | None = None

        while len(items) < count and pages < SEARCH_PAGE_BUDGET:
            pages += 1
            payload = self.client.search(text, count - len(items), cursor, wanted)
            chunk = normalize.normalize_search(payload)
            fresh = []
            for row in chunk:
                if wanted and row.get("kind") != wanted:
                    continue
                key = (row.get("kind", ""), row.get("id", ""))
                if key in seen:
                    continue
                seen.add(key)
                fresh.append(row)
            items.extend(fresh)
            if len(chunk) < endpoints.SEARCH_PAGE_CAP:
                break
            cursor += len(chunk)

        items = items[:count]
        notes: list[dict[str, Any]] = []
        if not items and isinstance(payload, dict):
            raw_rows = payload.get("data")
            if raw_rows:
                # 上游这一页只有广告位/时间提示，没有真正的搜索结果 —— 说清楚，别让 agent 以为「没搜到」
                notes.append({
                    "source": "search",
                    "code": "no_usable_results",
                    "message": "上游这一页只返回了广告/推荐位（%d 行），没有可用条目。" % len(raw_rows),
                })
        return make_page(items, page=current,
                         has_more=_has_more_by_paging(payload or {}, items, count),
                         source="search", errors=notes)

    # ---- item -------------------------------------------------------

    def item(self, ref: str = "", kind: str = "", id: str = "", *,
             related: bool = False, include_html: bool = False,
             content_limit: int = 0) -> dict[str, Any]:
        resolved = self._resolve(ref, kind, id)
        limit = _clamp(content_limit, 0, normalize.CONTENT_MAX, normalize.CONTENT_MAX)
        target_kind = resolved["kind"]

        if target_kind == "unknown":
            item = self._item_by_trial(resolved["id"], include_html=include_html,
                                       content_limit=limit)
            if related:
                self._attach_related(item, resolved)
            return item

        item = self._load_item(target_kind, resolved["id"], include_html=include_html,
                               content_limit=limit)
        if related:
            self._attach_related(item, resolved)
        return item

    def _resolve(self, ref: str, kind: str, item_id: str) -> dict[str, Any]:
        if kind and item_id:
            return {"kind": kind.strip().lower(), "id": str(item_id), "question_id": ""}
        if ref:
            resolved = normalize.parse_ref(ref)
            if kind:
                resolved["kind"] = kind.strip().lower()
            return resolved
        raise CitrusError("bad_request", "要么给 ref（链接或 id），要么给 kind + id。",
                          "例如 ?ref=https://www.zhihu.com/question/1/answer/2 或 ?kind=answer&id=2",
                          platform=self.platform)

    def _item_by_trial(self, item_id: str, **kwargs: Any) -> dict[str, Any]:
        last_error: CitrusError | None = None
        for candidate in ("answer", "question", "article"):
            try:
                return self._load_item(candidate, item_id, **kwargs)
            except CitrusError as exc:
                if exc.code not in ("not_found", "bad_upstream_response"):
                    raise
                last_error = exc
        raise last_error or CitrusError("not_found", "找不到 id=%s 的内容。" % item_id,
                                        platform=self.platform)

    def _load_item(self, kind: str, item_id: str, *, include_html: bool = False,
                   content_limit: int = normalize.CONTENT_MAX) -> dict[str, Any]:
        kind = kind or "answer"
        key = self._cache_key("raw", kind, item_id)
        raw = self._cached(key, RAW_TTL, lambda: self._fetch_raw(kind, item_id))

        match kind:
            case "question":
                return self._question_item(raw, str(item_id), include_html=include_html,
                                           content_limit=content_limit)
            case "pin":
                return self._pin_item(raw, str(item_id))
            case "zvideo":
                return self._zvideo_item(raw, str(item_id))
            case "article":
                item = normalize.normalize_item(dict(raw, type="article"), source="item",
                                                content_limit=content_limit,
                                                include_html=include_html)
                item["kind"] = "article"
                item["id"] = str(item.get("id") or item_id)
                item["url"] = item.get("url") or normalize.web_url("article", str(item_id))
                return item
            case _:
                item = normalize.normalize_item(raw, source="item", content_limit=content_limit,
                                                include_html=include_html)
                item["kind"] = "answer"
                item["id"] = str(item.get("id") or item_id)
                question = raw.get("question") or {}
                question_id = str(question.get("id") or "")
                if question_id:
                    item["url"] = normalize.web_url("answer", item["id"], question_id)
                    item["parent"] = {
                        "kind": "question",
                        "id": question_id,
                        "title": str(question.get("title") or ""),
                        "url": normalize.web_url("question", question_id),
                    }
                return item

    def _fetch_raw(self, kind: str, item_id: str) -> dict[str, Any]:
        if kind == "question":
            meta: dict[str, Any] = {}
            try:
                meta = dict(self.client.question(item_id))
            except CitrusError as exc:
                if exc.code not in ("challenge", "forbidden", "not_found"):
                    raise
            answers: list[dict[str, Any]] = []
            try:
                payload = self.client.question_answers(item_id, 3, 0)
                answers = payload.get("data") if isinstance(payload, dict) else []
            except CitrusError as exc:
                if exc.code not in ("challenge", "forbidden"):
                    raise
            if not meta.get("title") and not answers:
                raise CitrusError("not_found", "问题 %s 拿不到内容。" % item_id,
                                  "可能问题不存在，或这份 Cookie 没权限。", platform=self.platform)
            meta["_answers"] = answers or []
            return meta
        if kind == "pin":
            return dict(self.client.pin(item_id))
        if kind == "zvideo":
            return dict(self.client.zvideo(item_id))
        if kind == "article":
            return dict(self.client.article(item_id))
        return dict(self.client.answer(item_id))

    def _question_item(self, raw: dict[str, Any], item_id: str, **kwargs: Any) -> dict[str, Any]:
        answers_raw = raw.get("_answers") or []
        item = normalize.normalize_item(
            dict(raw, type="question", id=item_id, question={"id": item_id, "title": raw.get("title")}),
            source="item",
            content_limit=kwargs.get("content_limit", normalize.CONTENT_MAX),
            include_html=kwargs.get("include_html", False),
        )
        item["kind"] = "question"
        item["id"] = str(item_id)
        item["title"] = str(raw.get("title") or item.get("title") or ("问题 %s" % item_id))
        item["url"] = normalize.web_url("question", item_id)
        item["stats"]["views"] = int(raw.get("visit_count") or 0)
        item["extra"].update({
            "answer_count": int(raw.get("answer_count") or 0),
            "follower_count": int(raw.get("follower_count") or 0),
            "top_answers": [
                _brief_answer(answer, item_id) for answer in answers_raw[:3]
            ],
        })
        item["related"] = [
            normalize.normalize_item(dict(answer, type="answer"), source="item",
                                     content_limit=3000)
            for answer in answers_raw[:3]
        ]
        return item

    def _pin_item(self, raw: dict[str, Any], item_id: str) -> dict[str, Any]:
        item = normalize.normalize_item(dict(raw, type="pin", id=item_id), source="item")
        item["kind"] = "pin"
        item["id"] = str(item_id)
        item["url"] = normalize.web_url("pin", item_id)
        return item

    def _zvideo_item(self, raw: dict[str, Any], item_id: str) -> dict[str, Any]:
        item = normalize.normalize_item(dict(raw, type="zvideo", id=item_id), source="item")
        item["kind"] = "zvideo"
        item["id"] = str(item_id)
        item["url"] = normalize.web_url("zvideo", item_id)
        item["content"] = str(raw.get("description") or "")
        return item

    def _attach_related(self, item: dict[str, Any], resolved: dict[str, Any]) -> None:
        question_id = resolved.get("question_id") or ""
        if not question_id and item.get("parent"):
            question_id = str(item["parent"].get("id") or "")
        if not question_id:
            return
        try:
            payload = self.client.question_answers(str(question_id), 4, 0)
        except CitrusError as exc:
            item["extra"]["related_error"] = exc.code
            return
        rows = payload.get("data") if isinstance(payload, dict) else []
        related = []
        for row in rows or []:
            other = normalize.normalize_item(dict(row, type="answer"), source="related", content_limit=800)
            if other.get("id") and other["id"] != item.get("id"):
                related.append(other)
        item["related"] = related[:3]

    # ---- comments ---------------------------------------------------

    def comments(self, ref: str = "", kind: str = "", id: str = "", *,
                 limit: int = 20, page: int = 1, sort: str = "") -> dict[str, Any]:
        order = _normalize_sort(sort)
        resolved = self._resolve(ref, kind, id)
        target_kind = resolved["kind"]
        if target_kind == "unknown":
            target_kind = "answer"
        count = _clamp(limit, 1, MAX_COMMENTS, 20)
        current = _clamp(page, 1, MAX_PAGE, 1)
        offset = (current - 1) * count
        resource_id = str(resolved["id"])

        return self._cached(
            self._cache_key("comments", target_kind, resource_id, count, offset, order),
            COMMENT_TTL,
            lambda: self._load_comments(target_kind, resource_id, count, offset, current, order),
        )

    def _load_comments(self, kind: str, resource_id: str, count: int, offset: int,
                       page: int, sort: str = "hot") -> dict[str, Any]:
        """两个评论接口各覆盖一半场景，谁也替代不了谁：

        * 旧接口 /api/v4/<noun>/<id>/comments：回答能拿到真评论，文章/问题直接 404；
        * 新接口 /api/v4/comment_v5/<noun>/<id>/root_comment：什么类型都回 200，
          但经常 data 为空、counts 里却写着有几百条（实测：7 个资源里 6 个是空的）。

        所以先用对这类资源靠谱的那个，拿不到条目再换另一个；两个都没条目但有总数时，
        如实把总数和原因写进 errors —— 不能假装「没有评论」。
        """
        order = ("legacy", "v5") if kind == "answer" else ("v5", "legacy")
        total: int | None = None
        last_error: CitrusError | None = None
        answered = False
        chosen: str | None = None

        # 上游一页只给 10（v5）或 20（旧接口）条，想要 100 条就得自己翻。
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = offset
        pages = 0

        while len(items) < count and pages < COMMENT_PAGE_BUDGET:
            pages += 1
            want = count - len(items)
            payload: dict[str, Any] | None = None
            # 第一页两个接口都试，选中哪个就一直用它翻下去
            for variant in ([chosen] if chosen else order):
                try:
                    payload = self.client.comments(kind, resource_id, want, cursor,
                                                   variant=variant, sort=sort)
                except CitrusError as exc:
                    last_error = exc
                    continue
                if isinstance(payload, dict):
                    chosen = variant
                    break
                payload = None
            if payload is None:
                break

            answered = True
            found = _upstream_total(payload)
            if found is not None:
                total = found
            chunk = normalize.normalize_comments(payload, resource_id)
            fresh = [row for row in chunk if row["id"] not in seen]
            for row in fresh:
                seen.add(row["id"])
                items.append(row)

            cap = endpoints.COMMENT_PAGE_CAPS.get(chosen or "legacy", 20)
            if not fresh or len(chunk) < min(want, cap):
                break
            cursor += len(chunk)
            if total is not None and cursor >= total:
                break

        if not answered and last_error is not None:
            raise last_error

        items = items[:count]
        notes: list[dict[str, Any]] = []
        if not items and total:
            notes.append({
                "source": "comments",
                "code": "comments_unavailable",
                "message": ("上游说有 %d 条评论，但两个评论接口都没返回内容"
                            "（多半被风控或评论已关闭）。" % total),
            })
        return make_page(items, page=page,
                         has_more=_has_more(total, offset, len(items), count),
                         source="comments", total=total, errors=notes)

    # ---- user -------------------------------------------------------

    def user(self, ref: str = "") -> dict[str, Any]:
        token = self._member_token(ref)
        payload = self._cached(self._cache_key("member", token), RAW_TTL,
                               lambda: self.client.member(token))
        profile = normalize.normalize_profile(payload)
        profile["fetched_at"] = now_iso()
        return profile

    def user_content(self, ref: str = "", limit: int = 20, page: int = 1) -> dict[str, Any]:
        token = self._member_token(ref)
        count = _clamp(limit, 1, MAX_FEED, 20)
        current = _clamp(page, 1, MAX_PAGE, 1)
        offset = (current - 1) * count
        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        try:
            payload = self.client.member_answers(token, count, offset)
            items.extend(normalize.normalize_feed(payload, "user"))
        except CitrusError as exc:
            errors.append({"source": "answers", "code": exc.code, "message": exc.message})
        try:
            payload = self.client.member_articles(token, count, offset)
            items.extend(normalize.normalize_feed(payload, "user"))
        except CitrusError as exc:
            errors.append({"source": "articles", "code": exc.code, "message": exc.message})
        if not items and errors:
            raise CitrusError(errors[0]["code"], "读不到这个人的内容：%s" % errors[0]["message"],
                              platform=self.platform)
        items.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        items = _dedupe(items)[:count]
        return make_page(items, page=current, has_more=len(items) >= count, source="user")

    def _member_token(self, ref: str) -> str:
        text = (ref or "").strip()
        if not text:
            raise CitrusError("bad_request", "user 需要一个 ref（主页链接或 url_token）。",
                              "例如 ?ref=https://www.zhihu.com/people/abc 或 ?ref=abc",
                              platform=self.platform)
        try:
            resolved = normalize.parse_ref(text)
        except CitrusError:
            # 纯 token（zhangsan / 8f2b...）：没有链接特征的短串就当 url_token
            if re.match(r"^[\w\-.%]+$", text):
                return text
            raise
        if resolved["kind"] == "user":
            return str(resolved["id"])
        if resolved["kind"] == "unknown":
            return str(resolved["id"])
        raise CitrusError("bad_request", "这不是一个用户主页：%s" % text[:80],
                          "传 https://www.zhihu.com/people/<token> 或直接传 token。",
                          platform=self.platform)

    # ---- verify -----------------------------------------------------

    def verify(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def record(name: str, func: Any, detail_ok: str) -> None:
            try:
                value = func()
                count = len(value) if isinstance(value, list) else 0
                checks.append({
                    "name": name,
                    "ok": True,
                    "detail": "%s（%d 条）" % (detail_ok, count) if isinstance(value, list) else detail_ok,
                    "hint": "",
                })
            except CitrusError as exc:
                checks.append({
                    "name": name,
                    "ok": False,
                    "detail": "%s %s" % (exc.code, exc.message),
                    "hint": exc.hint or self.error_hints.get(exc.code, ""),
                })
            except Exception as exc:  # 自检永远不该把服务打挂
                checks.append({
                    "name": name,
                    "ok": False,
                    "detail": "%s: %s" % (type(exc).__name__, exc),
                    "hint": "",
                })

        checks.append({
            "name": "Cookie 已配置",
            "ok": bool(self.cookie),
            "detail": self.cookie_hint or "没有",
            "hint": "" if self.cookie else ERROR_HINTS["no_credential"],
        })
        if not self.cookie:
            return {"platform": self.platform, "configured": False, "checks": checks}

        record("身份（/me）", lambda: [self.client.me()], "读到账号信息")
        record("热榜", lambda: self._hot_items(5), "拿到热榜")
        record("推荐流", lambda: normalize.normalize_feed(self.client.recommend(3, 1), "recommend"), "拿到推荐")
        record("关注动态", lambda: normalize.normalize_feed(self.client.following(3, 1), "following"), "拿到动态")

        probe: dict[str, Any] = {}

        def probe_item() -> list[dict[str, Any]]:
            try:
                feed_items = normalize.normalize_feed(self.client.recommend(5, 1), "recommend")
            except CitrusError:
                feed_items = []
            if not feed_items:
                feed_items = self._hot_items(3)
            candidate = next((row for row in feed_items if row.get("kind") in ("answer", "article")), None)
            if candidate is None:
                raise CitrusError("not_found", "没有可试的条目", "推荐流/热榜都没拿到东西，先解决上面两条。")
            probe["kind"] = candidate["kind"]
            probe["id"] = candidate["id"]
            loaded = self._load_item(candidate["kind"], candidate["id"])
            if not loaded.get("content"):
                raise CitrusError("bad_upstream_response", "只拿到摘要，没有正文", "退回到列表摘要。")
            return [loaded]

        record("正文接口", probe_item, "读到正文")
        return {
            "platform": self.platform,
            "configured": True,
            "cookie_hint": self.cookie_hint,
            "checks": checks,
            "ok": all(check.get("ok") for check in checks),
            "checked_at": now_iso(),
        }


def _brief_answer(answer: Any, question_id: str) -> dict[str, Any]:
    row = answer if isinstance(answer, dict) else {}
    answer_id = str(row.get("id") or "")
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    return {
        "id": answer_id,
        "author": str(author.get("name") or ""),
        "votes": int(row.get("voteup_count") or 0),
        "url": normalize.web_url("answer", answer_id, question_id) if answer_id else "",
    }


#: 统一排序名 -> 内部取值。写进来的是这一套，各家接口的魔法值在 endpoints 里。
COMMENT_SORTS = {
    "hot": "hot",
    "score": "hot",
    "default": "hot",
    "new": "new",
    "ts": "new",
    "time": "new",
    "latest": "new",
}


def _normalize_sort(value: str) -> str:
    """空 = hot；认 hot/new 及其常见别名；其它一律报错，绝不悄悄忽略。"""
    key = (value or "").strip().lower()
    if not key:
        return "hot"
    resolved = COMMENT_SORTS.get(key)
    if resolved is None:
        raise CitrusError(
            "bad_request",
            "不认识的评论排序：%s" % value,
            "支持 sort=hot（默认，按热度）或 sort=new（按时间倒序）。",
            platform="zhihu",
        )
    return resolved


def _upstream_total(payload: dict[str, Any]) -> int | None:
    """上游说的评论总数：v5 在 counts.total_counts，旧接口在 paging.totals。"""
    counts = payload.get("counts")
    if isinstance(counts, dict):
        value = counts.get("total_counts")
        if isinstance(value, int) and value >= 0:
            return value
    paging = payload.get("paging")
    if isinstance(paging, dict):
        value = paging.get("totals")
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _has_more(total: int | None, offset: int, returned: int, count: int) -> bool:
    """知道总数就按总数算，不知道就退回「这一页拿满了」。"""
    if returned <= 0:
        return False
    if total is not None:
        return offset + returned < total
    return returned >= count


def _has_more_by_paging(payload: Any, items: list[dict[str, Any]], count: int) -> bool:
    """给别的列表接口用：优先读上游 paging.is_end。"""
    if not items:
        return False
    paging = payload.get("paging") if isinstance(payload, dict) else None
    if isinstance(paging, dict) and isinstance(paging.get("is_end"), bool):
        return not paging["is_end"]
    return len(items) >= count


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("kind"), item.get("id"))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


_MISSING = object()
