"""把知乎 v3/v4 的原始 JSON 摊平成统一模型。

这是适配器里唯一需要「懂知乎」的地方：字段名、卡片结构、热榜的 metric 文案、
各种链接形态，全都收敛在这里。adapter.py 只负责编排，不碰原始字段。
"""

import re
from typing import Any

from ...core.html_text import html_to_text, plain_excerpt
from ...core.model import (
    make_author,
    make_comment,
    make_item,
    make_parent,
    make_profile,
    make_stats,
)
from ...errors import CitrusError

PLATFORM = "zhihu"
PEOPLE_URL = "https://www.zhihu.com/people/%s"

CONTENT_MAX = 16000
EXCERPT_MAX = 200

# ---- 链接识别 --------------------------------------------------------

_ANSWER_IN_QUESTION = re.compile(r"zhihu\.com/question/(\d+)/answer/(\d+)", re.IGNORECASE)
_ANSWER = re.compile(r"(?:zhihu\.com/answer/|^answer[:/])(\d+)", re.IGNORECASE)
_QUESTION = re.compile(r"(?:zhihu\.com/question/|^question[:/])(\d+)", re.IGNORECASE)
_ARTICLE = re.compile(r"(?:zhuanlan\.zhihu\.com/p/|zhihu\.com/p/|^p[:/]|^article[:/])(\d+)", re.IGNORECASE)
_PEOPLE = re.compile(r"zhihu\.com/(?:people|org)/([\w\-%.]+)", re.IGNORECASE)
_PEOPLE_PREFIX = re.compile(r"^(?:user|people)[:/](.+)$", re.IGNORECASE)
_PIN = re.compile(r"(?:zhihu\.com/pin/|^pin[:/])(\d+)", re.IGNORECASE)
_ZVIDEO = re.compile(r"(?:zhihu\.com/zvideo/|^zvideo[:/])(\d+)", re.IGNORECASE)
_DIGITS = re.compile(r"^\d+$")


def parse_ref(ref: str) -> dict[str, Any]:
    """知乎链接 / 纯 id / 带前缀的 id -> {kind, id, question_id}。"""
    text = str(ref or "").strip()
    if not text:
        raise CitrusError("bad_request", "没给条目：ref 是空的。",
                          "传知乎链接，或 answer:123 / question:123 / p:456 这种带前缀的 id。")

    match = _ANSWER_IN_QUESTION.search(text)
    if match:
        return {"kind": "answer", "id": match.group(2), "question_id": match.group(1)}
    match = _ANSWER.search(text)
    if match:
        return {"kind": "answer", "id": match.group(1), "question_id": ""}
    match = _QUESTION.search(text)
    if match:
        return {"kind": "question", "id": match.group(1), "question_id": match.group(1)}
    match = _ARTICLE.search(text)
    if match:
        return {"kind": "article", "id": match.group(1), "question_id": ""}
    match = _PEOPLE.search(text)
    if match:
        return {"kind": "user", "id": match.group(1), "question_id": ""}
    match = _PEOPLE_PREFIX.match(text)
    if match:
        return {"kind": "user", "id": match.group(1), "question_id": ""}
    match = _PIN.search(text)
    if match:
        return {"kind": "pin", "id": match.group(1), "question_id": ""}
    match = _ZVIDEO.search(text)
    if match:
        return {"kind": "zvideo", "id": match.group(1), "question_id": ""}
    if _DIGITS.match(text):
        return {"kind": "unknown", "id": text, "question_id": ""}
    raise CitrusError("bad_request", "认不出这个条目：%s" % text[:80],
                      "传知乎的回答/问题/文章链接，或带前缀的 id（answer:123）。")


def web_url(kind: str, item_id: str, question_id: str = "") -> str:
    if kind == "answer":
        if question_id:
            return "https://www.zhihu.com/question/%s/answer/%s" % (question_id, item_id)
        return "https://www.zhihu.com/answer/%s" % item_id
    if kind == "question":
        return "https://www.zhihu.com/question/%s" % item_id
    if kind == "article":
        return "https://zhuanlan.zhihu.com/p/%s" % item_id
    if kind == "user":
        return PEOPLE_URL % item_id
    if kind == "pin":
        return "https://www.zhihu.com/pin/%s" % item_id
    if kind == "zvideo":
        return "https://www.zhihu.com/zvideo/%s" % item_id
    return "https://www.zhihu.com/"


def comment_url(kind: str, item_id: str, question_id: str = "") -> str:
    base = web_url(kind, item_id, question_id)
    return base


# ---- 小工具 ----------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def parse_heat(text: str) -> int:
    """把「1234 万热度」这种中文计数换成数字。"""
    raw = (text or "").replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*(亿|万)?", raw)
    if not match:
        return 0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0
    unit = {"亿": 1e8, "万": 1e4}.get(match.group(2) or "", 1.0)
    return int(number * unit)


def _clip_content(html: str, limit: int) -> Any:
    """HTML -> 纯文本，按需截断。返回 (文本, 是否截断)。"""
    full = html_to_text(html)
    if limit and limit > 0 and len(full) > limit:
        return full[:limit].rstrip() + "\n…（后面还有，已截断）", True
    return full, False


# ---- 作者 / 档案 -----------------------------------------------------


def normalize_author(raw: Any) -> dict[str, Any]:
    author = _as_dict(raw)
    token = _as_str(author.get("url_token")) or _as_str(author.get("id"))
    name = _as_str(author.get("name")) or "匿名用户"
    if not token and author.get("is_org"):
        name = name or "机构号"
    return make_author(
        id=token,
        name=name,
        url=PEOPLE_URL % token if token else "",
        handle=token,
        headline=_as_str(author.get("headline")),
        avatar=_as_str(author.get("avatar_url")),
    )


def normalize_profile(raw: Any) -> dict[str, Any]:
    person = _as_dict(raw)
    token = _as_str(person.get("url_token")) or _as_str(person.get("id"))
    return make_profile(
        PLATFORM,
        id=token,
        name=_as_str(person.get("name")) or token,
        handle=token,
        url=PEOPLE_URL % token if token else "",
        headline=_as_str(person.get("headline")),
        avatar=_as_str(person.get("avatar_url")),
        stats=make_stats(),
        extra={
            "answers": _as_int(person.get("answer_count")),
            "articles": _as_int(person.get("articles_count")),
            "followers": _as_int(person.get("follower_count")),
            "description": _as_str(person.get("description")),
            "gender": _as_str(person.get("gender")),
        },
    )


# ---- 单条 ------------------------------------------------------------

_KIND_WORDS = {
    "answer": "回答",
    "article": "文章",
    "question": "问题",
    "pin": "想法",
    "zvideo": "视频",
}


def normalize_item(raw: Any, *, source: str = "", content_limit: int = CONTENT_MAX,
                   include_html: bool = False) -> dict[str, Any]:
    """v3/v4 返回的一条（可能是 {target: {...}} 包装）-> 统一 item。"""
    wrap = _as_dict(raw)
    target = _as_dict(wrap.get("target")) or wrap
    question = _as_dict(target.get("question")) or _as_dict(wrap.get("question"))

    raw_url = _as_str(target.get("url")) or _as_str(wrap.get("url"))
    guessed: dict[str, Any] = {}
    if raw_url:
        try:
            guessed = parse_ref(raw_url)
        except CitrusError:
            guessed = {}

    kind = _as_str(target.get("type") or wrap.get("type")).lower()
    if kind in ("feed", "feed_item"):
        kind = ""
    if kind not in ("answer", "article", "question", "pin", "zvideo", "video"):
        guess_kind = guessed.get("kind") or ""
        if guess_kind in ("answer", "article", "question", "pin", "zvideo"):
            kind = guess_kind
        elif question.get("id"):
            kind = "answer"
        else:
            kind = "question"
    if kind == "video":
        kind = "zvideo"

    item_id = str(target.get("id") or question.get("id") or guessed.get("id") or "")
    if question.get("id") and kind == "answer":
        item_id = str(target.get("id") or guessed.get("id") or "")
    question_id = str(question.get("id") or target.get("question_id") or guessed.get("question_id") or "")

    title = (_as_str(target.get("title"))
             or _as_str(question.get("title"))
             or _as_str(target.get("excerpt"))[:60]
             or "知乎%s %s" % (_KIND_WORDS.get(kind, "内容"), item_id))

    content_html = _as_str(target.get("content")) or _as_str(target.get("detail"))
    excerpt = _as_str(target.get("excerpt")) or plain_excerpt(content_html, EXCERPT_MAX)
    content, truncated = _clip_content(content_html, content_limit)

    metrics = _as_dict(target.get("metrics"))
    tags = target.get("tags") if isinstance(target.get("tags"), list) else []
    stats = make_stats(
        likes=_as_int(target.get("voteup_count") or target.get("vote_count") or metrics.get("voteup_count")),
        comments=_as_int(target.get("comment_count") or metrics.get("comment_count")),
        shares=_as_int(target.get("reaction_count")),
        views=_as_int(target.get("visit_count") or metrics.get("visit_count")),
        heat=parse_heat(_as_str(metrics.get("hot")) or _as_str(target.get("hot"))),
    )

    parent = None
    if kind == "answer" and question_id:
        parent = make_parent("question", question_id, _as_str(question.get("title")),
                             web_url("question", question_id))

    extra: dict[str, Any] = {}
    if _as_str(metrics.get("hot")):
        extra["hot_text"] = _as_str(metrics.get("hot"))
    if tags:
        extra["tags"] = [t for t in (_as_str(tag.get("name")) for tag in tags if isinstance(tag, dict)) if t]
    if include_html and content_html:
        extra["content_html"] = content_html

    url = _normalize_web_url(raw_url) or web_url(kind, item_id, question_id)
    return make_item(
        PLATFORM,
        kind,
        item_id,
        title=title,
        url=url,
        excerpt=excerpt,
        content=content,
        content_truncated=truncated,
        author=normalize_author(target.get("author")),
        parent=parent,
        stats=stats,
        created_at=target.get("created_time") or target.get("created"),
        updated_at=target.get("updated_time") or target.get("updated"),
        source=source,
        extra=extra,
    )


def _normalize_web_url(url: str) -> str:
    if not url:
        return ""
    if _ANSWER_IN_QUESTION.search(url):
        return url.replace("http://", "https://")
    if _ARTICLE.search(url):
        return url.replace("http://", "https://")
    if _QUESTION.search(url):
        return url.replace("http://", "https://").split("?")[0]
    return ""


# ---- 热榜 ------------------------------------------------------------

_CARD_RE = re.compile(r"^([QPA])_(\d+)$")


def normalize_hot_item(row: Any) -> dict[str, Any] | None:
    """热榜现在是 title_area / excerpt_area / metrics_area + card_id 的结构。"""
    card = _as_dict(row)
    if not card:
        return None
    target = _as_dict(card.get("target")) or card
    card_id = _as_str(card.get("card_id")) or _as_str(target.get("card_id"))
    new_shape = (isinstance(target.get("title_area"), dict)
                 or isinstance(target.get("excerpt_area"), dict)
                 or isinstance(target.get("metrics_area"), dict)
                 or bool(_CARD_RE.match(card_id)))

    if not new_shape:
        item = normalize_item(row, source="hot")
        if not item.get("id"):
            return None
        return item

    match = _CARD_RE.match(card_id)
    if match:
        prefix, item_id = match.group(1), match.group(2)
        kind = {"Q": "question", "P": "article", "A": "answer"}[prefix]
    else:
        item_id = str(target.get("id") or card.get("id") or "")
        kind = "question"
    if not item_id:
        return None

    question_id = str(_as_dict(target.get("question")).get("id") or target.get("question_id") or "")
    title = (_as_str(_as_dict(target.get("title_area")).get("text"))
             or _as_str(target.get("title"))
             or _as_str(_as_dict(card.get("title_area")).get("text")))
    excerpt = (_as_str(_as_dict(target.get("excerpt_area")).get("text"))
               or _as_str(target.get("excerpt"))
               or _as_str(_as_dict(card.get("excerpt_area")).get("text")))
    metrics_text = (_as_str(_as_dict(target.get("metrics_area")).get("text"))
                    or _as_str(_as_dict(card.get("metrics_area")).get("text")))
    heat = parse_heat(metrics_text)

    extra: dict[str, Any] = {}
    if metrics_text:
        extra["hot_text"] = metrics_text
    answer_count = _as_int(_as_dict(card.get("feed_specific")).get("answer_count")
                           or target.get("answer_count"))
    if answer_count:
        extra["answer_count"] = answer_count

    return make_item(
        PLATFORM,
        kind,
        item_id,
        title=title or "知乎热榜 %s" % item_id,
        url=web_url(kind, item_id, question_id),
        excerpt=excerpt,
        author=make_author(),
        parent=make_parent("question", question_id, title) if (kind == "answer" and question_id) else None,
        stats=make_stats(heat=heat),
        source="hot",
        extra=extra,
    )


# ---- 列表 ------------------------------------------------------------


def normalize_feed(payload: Any, source: str) -> list[dict[str, Any]]:
    data = _as_dict(payload).get("data")
    rows = data if isinstance(data, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        row_dict = _as_dict(row)
        if not row_dict:
            continue
        if _as_str(row_dict.get("type")).lower() in ("ad", "ad_feed"):
            continue
        target = _as_dict(row_dict.get("target")) or row_dict
        if _as_str(target.get("type")).lower() == "ad":
            continue
        item = normalize_item(row_dict, source=source)
        if not item.get("id"):
            continue
        out.append(item)
    return out


def normalize_search(payload: Any) -> list[dict[str, Any]]:
    """search_v3 的 data[] 是 {type: "search_result", object: {...}}。"""
    data = _as_dict(payload).get("data")
    rows = data if isinstance(data, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        row_dict = _as_dict(row)
        if not row_dict:
            continue
        if _as_str(row_dict.get("type")).lower() != "search_result":
            continue
        obj = _as_dict(row_dict.get("object"))
        if not obj:
            continue
        obj_type = _as_str(obj.get("type")).lower()
        if obj_type == "people":
            token = _as_str(obj.get("url_token")) or _as_str(obj.get("id"))
            if not token:
                continue
            out.append(make_item(
                PLATFORM,
                "user",
                token,
                title=_as_str(obj.get("name")) or token,
                url=PEOPLE_URL % token,
                excerpt=_as_str(obj.get("headline")),
                author=make_author(id=token, name=_as_str(obj.get("name")), url=PEOPLE_URL % token,
                                   handle=token, headline=_as_str(obj.get("headline")),
                                   avatar=_as_str(obj.get("avatar_url"))),
                source="search",
                extra={"followers": _as_int(obj.get("follower_count"))},
            ))
            continue
        item = normalize_item(obj, source="search")
        if item.get("id"):
            out.append(item)
    return out


# ---- 评论 ------------------------------------------------------------


def normalize_comment(raw: Any, parent_id: str = "") -> dict[str, Any]:
    row = _as_dict(raw)
    return make_comment(
        PLATFORM,
        str(row.get("id") or ""),
        author=normalize_author(row.get("author")),
        content=html_to_text(_as_str(row.get("content")), max_chars=1200),
        likes=_as_int(row.get("vote_count") or row.get("like_count")),
        replies=_as_int(row.get("reply_count") or row.get("child_comment_count")),
        created_at=row.get("created_time") or row.get("created"),
        url="",
        parent_id=parent_id,
    )


def normalize_comments(payload: Any, parent_id: str = "") -> list[dict[str, Any]]:
    data = _as_dict(payload).get("data")
    rows = data if isinstance(data, list) else []
    return [normalize_comment(row, parent_id) for row in rows if isinstance(row, dict)]
