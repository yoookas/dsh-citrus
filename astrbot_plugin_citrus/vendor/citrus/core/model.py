"""统一数据模型 —— 这套形状就是本项目的「API 契约」。

不管底层是知乎还是别的平台，agent 拿到的永远是这个形状：

    Item   一条内容（回答/文章/视频/帖子/提问……）
    Author 作者
    Stats  互动数据（缺的字段填 0，不要省略键）
    Page   一页列表 + 翻页信息

键永远存在、类型永远稳定 —— agent 不需要写 if 判断有没有这个字段。
"""

import datetime
from collections.abc import Iterable
from typing import Any

#: 内容类型。平台只需把自己那边的类型映射到这几个词上。
CONTENT_KINDS = frozenset({
    "answer", "article", "question", "post", "pin",
    "video", "zvideo", "user", "topic", "collection", "other",
})


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(value: Any) -> str | None:
    """epoch 秒 / 毫秒 / ISO 字符串 -> ISO 8601（UTC，带 Z）。拿不准就返回 None。"""
    if value is None or value == "" or value == 0:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("+00:00"):
            return text
        try:
            return to_iso(float(text))
        except ValueError:
            return text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 1e12:  # 毫秒
        number = number / 1000.0
    try:
        moment = datetime.datetime.fromtimestamp(number, datetime.UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_author(id: str = "", name: str = "", url: str = "", *,
                handle: str = "", headline: str = "", avatar: str = "") -> dict[str, Any]:
    return {
        "id": id or "",
        "name": name or "",
        "handle": handle or "",
        "url": url or "",
        "headline": headline or "",
        "avatar": avatar or "",
    }


def make_stats(likes: int = 0, comments: int = 0, shares: int = 0,
               views: int = 0, heat: int = 0) -> dict[str, Any]:
    return {
        "likes": int(likes or 0),
        "comments": int(comments or 0),
        "shares": int(shares or 0),
        "views": int(views or 0),
        "heat": int(heat or 0),
    }


def make_item(platform: str, kind: str, id: str, *,
              title: str = "",
              url: str = "",
              excerpt: str = "",
              content: str = "",
              content_truncated: bool = False,
              author: dict[str, Any] | None = None,
              parent: dict[str, Any] | None = None,
              stats: dict[str, Any] | None = None,
              created_at: Any = None,
              updated_at: Any = None,
              source: str = "",
              media: Iterable[dict[str, Any]] | None = None,
              related: Iterable[dict[str, Any]] | None = None,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """所有平台都通过这一个函数造 item，形状自然就统一了。"""
    return {
        "platform": platform,
        "kind": kind if kind in CONTENT_KINDS else "other",
        "id": str(id or ""),
        "url": url or "",
        "title": title or "",
        "excerpt": excerpt or "",
        "content": content or "",
        "content_truncated": bool(content_truncated),
        "author": author if author is not None else make_author(),
        "parent": parent,
        "stats": stats if stats is not None else make_stats(),
        "created_at": to_iso(created_at),
        "updated_at": to_iso(updated_at),
        "source": source or "",
        "media": list(media or []),
        "related": list(related or []),
        "extra": extra or {},
    }


def make_parent(kind: str, id: str, title: str = "", url: str = "") -> dict[str, Any] | None:
    if not id:
        return None
    return {"kind": kind, "id": str(id), "title": title or "", "url": url or ""}


def make_page(items: Iterable[dict[str, Any]], *,
              page: int = 1,
              has_more: bool = False,
              source: str = "",
              errors: list[dict[str, Any]] | None = None,
              total: int | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = list(items)
    payload: dict[str, Any] = {
        "items": rows,
        "count": len(rows),
        "page": int(page),
        "has_more": bool(has_more),
        "next_page": int(page) + 1 if has_more else None,
        "source": source or "",
    }
    if errors:
        payload["errors"] = errors
    if total is not None:
        payload["total"] = int(total)
    return payload


def make_comment(platform: str, id: str, *,
                 author: dict[str, Any] | None = None,
                 content: str = "",
                 likes: int = 0,
                 replies: int = 0,
                 created_at: Any = None,
                 url: str = "",
                 parent_id: str = "") -> dict[str, Any]:
    return {
        "platform": platform,
        "id": str(id or ""),
        "author": author if author is not None else make_author(),
        "content": content or "",
        "likes": int(likes or 0),
        "replies": int(replies or 0),
        "created_at": to_iso(created_at),
        "url": url or "",
        "parent_id": parent_id or "",
    }


def make_profile(platform: str, *, id: str = "", name: str = "", handle: str = "",
                 url: str = "", headline: str = "", avatar: str = "",
                 stats: dict[str, Any] | None = None,
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "platform": platform,
        "id": id or "",
        "name": name or "",
        "handle": handle or "",
        "url": url or "",
        "headline": headline or "",
        "avatar": avatar or "",
        "stats": stats if stats is not None else make_stats(),
        "extra": extra or {},
    }
