"""富文本 -> 纯文本。

agent 要读的是字，不是标签。这里只做「读得懂」：段落/换行/列表保留，
图片给 [图] 占位，脚本样式注释全扔，实体解码。

故意不引 HTML 解析器 —— 服务要能在一台只有标准库的机器上跑起来，
而且知乎的正文 HTML 结构很规整，正则足够。
"""

import re

_NAMED_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
    "hellip": "…", "mdash": "—", "ndash": "–", "middot": "·", "bull": "•",
    "ldquo": "“", "rdquo": "”", "lsquo": "‘", "rsquo": "’",
    "laquo": "«", "raquo": "»", "copy": "©", "reg": "®", "trade": "™",
    "times": "×", "divide": "÷", "plusmn": "±", "deg": "°", "sect": "§",
    "para": "¶", "dagger": "†", "permil": "‰", "euro": "€", "pound": "£",
    "yen": "¥", "cent": "¢", "curren": "¤", "sup2": "²", "sup3": "³",
    "frac12": "½", "frac14": "¼", "frac34": "¾", "inexact": "≈", "asymp": "≈",
    "ne": "≠", "le": "≤", "ge": "≥", "equiv": "≡", "infin": "∞", "sum": "∑",
    "prod": "∏", "radic": "√", "int": "∫", "part": "∂", "nabla": "∇",
    "isin": "∈", "notin": "∉", "cap": "∩", "cup": "∪", "and": "∧", "or": "∨",
    "there4": "∴", "sim": "∼", "cong": "≅", "tilde": "˜", "prime": "′",
    "larr": "←", "rarr": "→", "uarr": "↑", "darr": "↓", "harr": "↔",
    "ensp": " ", "emsp": " ", "thinsp": " ", "zwnj": "", "zwj": "",
    "lrm": "", "rlm": "", "shy": "", "iexcl": "¡", "iquest": "¿", "micro": "µ",
}

_ENTITY_RE = re.compile(r"&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});")
_BLOCK_TAGS = r"(p|div|section|article|blockquote|pre|h[1-6]|tr|table|ul|ol|dl|figure|figcaption)"


def decode_entities(text: str) -> str:
    """解 HTML 实体（命名 + 十进制 + 十六进制）；坏实体原样留着。"""
    if not text:
        return ""

    def _sub(match: "re.Match[str]") -> str:
        body = match.group(1)
        if body[:1] == "#":
            hex_form = body[1:2] in ("x", "X")
            digits = body[2:] if hex_form else body[1:]
            try:
                code = int(digits, 16 if hex_form else 10)
            except ValueError:
                return match.group(0)
            if code < 0 or code > 0x10FFFF:
                return match.group(0)
            try:
                return chr(code)
            except (ValueError, OverflowError):
                return match.group(0)
        named = _NAMED_ENTITIES.get(body)
        return named if named is not None else match.group(0)

    return _ENTITY_RE.sub(_sub, text)


def html_to_text(html: str | None, max_chars: int = 0, truncation_note: str = "\n…（后面还有，已截断）") -> str:
    """HTML -> 纯文本。max_chars <= 0 表示不截断。"""
    s = html or ""
    if not s:
        return ""

    # 脚本 / 样式 / 注释 / noscript：整段扔掉
    s = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<noscript\b[^>]*>[\s\S]*?</noscript>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<!--[\s\S]*?-->", "", s)

    # 图片 / 视频 / 公式：留占位，别让正文出现一串空行
    s = re.sub(r"<img\b[^>]*>", "[图]", s, flags=re.IGNORECASE)
    s = re.sub(r"<video\b[^>]*>[\s\S]*?</video>", "[视频]", s, flags=re.IGNORECASE)
    s = re.sub(r"<math\b[^>]*>[\s\S]*?</math>", "[公式]", s, flags=re.IGNORECASE)

    # 块级元素 -> 换行；列表项 -> 圆点
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</" + _BLOCK_TAGS + r"\s*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<" + _BLOCK_TAGS + r"\b[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<li\b[^>]*>", "\n· ", s, flags=re.IGNORECASE)
    s = re.sub(r"<hr\s*/?>", "\n——\n", s, flags=re.IGNORECASE)

    # 剩下所有标签剥掉（<a> 的文字自然保留）
    s = re.sub(r"<[^>]+>", "", s)
    s = decode_entities(s)

    # 空白收拾：行内空格压成一个，空行最多留两行
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t\f\v\u00a0\u200b]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()

    if max_chars and max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip() + truncation_note
    return s


def plain_excerpt(html: str | None, limit: int = 160) -> str:
    """从正文里裁一段当摘要（给列表用，不抢正文的戏）。"""
    if not html:
        return ""
    text = html_to_text(html).replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def looks_like_html(text: str | None, content_type: str = "") -> bool:
    """上游明明要 JSON，回来的却是网页 —— 多半是被塞了验证页。"""
    head = (text or "")[:2000]
    if "text/html" in (content_type or "").lower():
        return True
    lowered = head.lstrip().lower()
    return lowered.startswith("<!doctype html") or "<html" in lowered
