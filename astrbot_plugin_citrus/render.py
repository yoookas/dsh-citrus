"""把 citrus 的统一数据模型渲染成紧凑文本。

渲染原则：

* 给大模型看的文本要「够判断、又不撑爆上下文」：标题 + 关键数字 + 链接 + 截断摘要。
* 链接永远保留，模型回答时才能引用来源。
* 绝不输出 cookie、原始 JSON 或内部状态。

citrus 的 Item / Page / Comment 形状见 citrus/core/model.py，键永远存在。
"""

from __future__ import annotations

from typing import Any

KIND_LABELS = {
    "answer": "回答",
    "article": "文章",
    "question": "问题",
    "pin": "想法",
    "video": "视频",
    "zvideo": "视频",
    "user": "用户",
    "topic": "话题",
    "collection": "收藏夹",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(str(kind or ""), "内容")


def compact_number(value: Any) -> str:
    """12345 -> 1.2万；12 -> 12；非法值 -> 空串。"""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if number >= 100_000_000:
        return "%.1f亿" % (number / 100_000_000.0)
    if number >= 10_000:
        return "%.1f万" % (number / 10_000.0)
    return str(number)


def oneline(value: Any, limit: int = 0) -> str:
    """压成一行（列表项用），可选截断。"""
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def multiline(value: Any, limit: int = 0) -> str:
    """保留段落（正文用），可选截断。"""
    lines = [line.rstrip() for line in str(value or "").strip().splitlines()]
    text = "\n".join(line for line in lines if line.strip())
    if not text:
        return ""
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _stats_line(stats: dict[str, Any]) -> str:
    parts = []
    for key, label in (("likes", "赞"), ("comments", "评论"), ("heat", "热度"), ("views", "浏览")):
        value = compact_number((stats or {}).get(key))
        if value:
            parts.append(f"{value}{label}")
    return " · ".join(parts)


def _item_meta(item: dict[str, Any]) -> str:
    """列表项后面那串数字。"""
    parts = []
    stats_line = _stats_line(item.get("stats") or {})
    if stats_line:
        parts.append(stats_line)
    extra = item.get("extra") or {}
    answers = compact_number(extra.get("answer_count"))
    if answers:
        parts.append(f"{answers} 个回答")
    hot_text = str(extra.get("hot_text") or "").strip()
    if hot_text and "热度" in hot_text and hot_text not in parts:
        # 热榜上游自带「1047 万热度」，比 stats.heat 更直观
        parts = [p for p in parts if not p.endswith("热度")] or parts
        parts.insert(0, hot_text)
    return " · ".join(parts)


def _item_line(index: int, item: dict[str, Any], *, title_limit: int = 90, excerpt_limit: int = 120) -> list[str]:
    lines: list[str] = []
    title = oneline(item.get("title") or item.get("excerpt"), title_limit) or "（无标题）"
    meta = _item_meta(item)
    head = f"{index}. 【{kind_label(item.get('kind'))}】{title}"
    if meta:
        head += f"｜{meta}"
    lines.append(head)
    url = str(item.get("url") or "").strip()
    if url:
        lines.append(f"   {url}")
    excerpt = oneline(item.get("excerpt"), excerpt_limit)
    if excerpt and excerpt != title:
        lines.append(f"   摘要：{excerpt}")
    return lines


def render_hot(page: dict[str, Any], *, max_items: int = 10, excerpt_chars: int = 120) -> str:
    items = list(page.get("items") or [])[:max_items]
    if not items:
        return "知乎热榜这次没有拿到内容。"
    lines = [f"知乎热榜（共 {page.get('count') or len(items)} 条）"]
    for index, item in enumerate(items, 1):
        lines.extend(_item_line(index, item, excerpt_limit=excerpt_chars))
    return "\n".join(lines)


def render_search(page: dict[str, Any], *, query: str = "", max_items: int = 8,
                  excerpt_chars: int = 120) -> str:
    items = list(page.get("items") or [])[:max_items]
    head = f"知乎搜索「{query}」" if query else "知乎搜索结果"
    if not items:
        return f"{head}：没有匹配结果。"
    lines = [f"{head}（本次 {len(items)} 条）"]
    for index, item in enumerate(items, 1):
        lines.extend(_item_line(index, item, excerpt_limit=excerpt_chars))
    return "\n".join(lines)


def render_item(item: dict[str, Any], *, content_chars: int = 1500,
                related: int = 3, related_chars: int = 600) -> str:
    kind = kind_label(item.get("kind"))
    title = oneline(item.get("title"), 120)
    author = (item.get("author") or {}).get("name") or ""
    stats_line = _stats_line(item.get("stats") or {})
    lines: list[str] = []

    head = f"【{kind}】{title}" if title else f"【{kind}】"
    if author:
        head += f"｜作者：{author}"
    if stats_line:
        head += f"｜{stats_line}"
    lines.append(head)

    parent = item.get("parent") or {}
    if parent.get("title"):
        lines.append(f"所属问题：{oneline(parent.get('title'), 120)}")
    url = str(item.get("url") or "").strip()
    if url:
        lines.append(f"链接：{url}")

    body = multiline(item.get("content"), content_chars)
    if body:
        lines.append("正文：")
        lines.append(body)
    else:
        excerpt = multiline(item.get("excerpt"), content_chars)
        if excerpt:
            lines.append("摘要：")
            lines.append(excerpt)

    rows = list(item.get("related") or [])[:related]
    if rows:
        lines.append(f"其他高赞回答（{len(rows)} 条，已截断）：")
        for index, row in enumerate(rows, 1):
            who = (row.get("author") or {}).get("name") or "匿名用户"
            likes = compact_number((row.get("stats") or {}).get("likes"))
            head2 = f"{index}. {who}" + (f"（{likes} 赞）" if likes else "")
            lines.append(head2)
            text = multiline(row.get("content") or row.get("excerpt"), related_chars)
            if text:
                lines.append(text)
    return "\n".join(lines)


def render_comments(page: dict[str, Any], *, max_items: int = 20, content_chars: int = 200) -> str:
    items = list(page.get("items") or [])[:max_items]
    total = page.get("total")
    head = "评论"
    if total:
        head += f"（上游共 {total} 条，本次 {len(items)} 条）"
    else:
        head += f"（本次 {len(items)} 条）"
    if not items:
        errors = page.get("errors") or []
        if errors:
            codes = "、".join(str((row or {}).get("code") or "") for row in errors)
            return f"{head}：这次没读到评论（{codes}）。"
        return f"{head}：没有评论。"
    lines = [head]
    for index, row in enumerate(items, 1):
        who = (row.get("author") or {}).get("name") or "匿名用户"
        likes = compact_number(row.get("likes"))
        replies = compact_number(row.get("replies"))
        meta = []
        if likes:
            meta.append(f"{likes} 赞")
        if replies:
            meta.append(f"{replies} 回复")
        suffix = f"（{' / '.join(meta)}）" if meta else ""
        text = oneline(row.get("content"), content_chars)
        lines.append(f"{index}. {who}{suffix}：{text}")
    return "\n".join(lines)


def render_account(info: dict[str, Any], *, platform_name: str = "知乎") -> str:
    profile = info.get("profile") or {}
    name = profile.get("name") or ""
    hint = info.get("cookie_hint") or ""
    parts = [f"{platform_name}账号：{name}" if name else f"{platform_name}账号已配置"]
    if hint:
        parts.append(f"Cookie 指纹 {hint}")
    return "｜".join(parts)
