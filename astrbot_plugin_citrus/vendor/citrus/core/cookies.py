"""Cookie 解析 —— 用户能粘什么，这里就得认什么。

支持四种输入（顺序即尝试顺序）：

1. DevTools 的 "Copy as cURL"（浏览器里右键请求最省事）；
2. 一整段请求头（含 Cookie: 行）；
3. 裸的 Cookie 串：name=value; name2=value2；
4. JSON 对象：{"z_c0": "...", "d_c0": "..."}（agent 拼起来最方便）。

只取 cookie 和 user-agent，其它头（Authorization 之类）一概不碰、不存。
"""

import hashlib
import json
import re
from collections.abc import Iterable

from ..errors import CitrusError

MAX_INPUT_BYTES = 20000
MAX_COOKIE_BYTES = 8192

_HEADER_RE = re.compile(r"""(-H|--header)\s+(?:'([^']*)'|"([^"]*)")""")
_COOKIE_FLAG_RE = re.compile(r"""(-b|--cookie)\s+(?:'([^']*)'|"([^"]*)")""")
_COOKIE_LINE_RE = re.compile(r"^\s*cookie\s*:\s*(.+)$", re.IGNORECASE)
_USER_AGENT_LINE_RE = re.compile(r"^\s*user-agent\s*:\s*(.+)$", re.IGNORECASE)
_PAIR_RE = re.compile(r"^([^=;\s]+)=(.*)$")


class CookieInput:
    """解析结果。has_login 由平台自己用 auth_cookie_names 判定。"""

    __slots__ = ("cookie", "user_agent", "source", "names", "has_login", "xsrf")

    def __init__(self, cookie: str, user_agent: str = "", source: str = "raw",
                 auth_cookie_names: Iterable[str] = ()) -> None:
        self.cookie = cookie
        self.user_agent = user_agent
        self.source = source
        pairs = parse_pairs(cookie)
        self.names: list[str] = list(pairs.keys())
        self.has_login = any(name in pairs for name in auth_cookie_names)
        self.xsrf = pairs.get("_xsrf", "")

    def fingerprint(self) -> str:
        return mask_cookie(self.cookie)

    def __repr__(self) -> str:
        return "CookieInput(source=%r, login=%s, cookies=%d)" % (self.source, self.has_login, len(self.names))


def _unquote(value: str) -> str:
    return (value or "").strip().strip("'").strip('"').strip()


def parse_pairs(cookie: str) -> dict[str, str]:
    """name=value; name2=value2 -> dict（保序，重复名后者覆盖）。"""
    pairs: dict[str, str] = {}
    if not cookie:
        return pairs
    for chunk in str(cookie).split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _PAIR_RE.match(chunk)
        if not m:
            continue
        pairs[m.group(1).strip()] = m.group(2).strip()
    return pairs


def _pairs_to_cookie(pairs: dict[str, str]) -> str:
    return "; ".join("%s=%s" % (k, v) for k, v in pairs.items())


def mask_cookie(cookie: str, keep: int = 3) -> str:
    """给日志/接口看的指纹：只露名字，值一律遮掉。"""
    names = list(parse_pairs(cookie).keys())
    if not names:
        return ""
    digest = hashlib.sha256((cookie or "").encode("utf-8")).hexdigest()[:8]
    shown = names[:keep] + (["+%d" % (len(names) - keep)] if len(names) > keep else [])
    return "%s · #%s" % (", ".join(shown), digest)


def _from_json_object(raw: str) -> str | None:
    if not raw.lstrip().startswith("{"):
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    pairs: dict[str, str] = {}
    for key, value in obj.items():
        if isinstance(value, (str, int, float)):
            pairs[str(key)] = str(value)
    return _pairs_to_cookie(pairs) if pairs else None


def parse_cookie_input(text: str, *, auth_cookie_names: Iterable[str] = (),
                       platform: str = "") -> CookieInput:
    """把用户粘进来的任何东西变成一条干净的 Cookie 串。"""
    raw = (text or "").strip()
    if not raw:
        raise CitrusError("no_credential", "粘进来的内容是空的。",
                          "把浏览器里的 Cookie / cURL 复制过来，或者传一个 {name: value} 的 JSON 对象。",
                          platform=platform or None)
    if len(raw) > MAX_INPUT_BYTES:
        raise CitrusError("bad_request", "粘进来的内容太长了（超过 20 KB）。",
                          "只复制 Cookie 那一行或一条请求的 cURL 就够了。",
                          platform=platform or None)

    cookie = ""
    user_agent = ""
    source = "raw"

    # ④ JSON 对象
    json_cookie = _from_json_object(raw)
    if json_cookie:
        cookie = json_cookie
        source = "json"

    # ① cURL
    if not cookie and re.search(r"(^|\s)curl\s", raw, re.IGNORECASE):
        source = "curl"
        flat = raw.replace("\\\r\n", " ").replace("\r\n", " ").replace("\n", " ")
        for match in _HEADER_RE.finditer(flat):
            line = match.group(2) if match.group(2) is not None else match.group(3)
            if not line or ":" not in line:
                continue
            name, _, value = line.partition(":")
            lname = name.strip().lower()
            if lname == "cookie":
                cookie = value.strip()
            elif lname == "user-agent":
                user_agent = value.strip()
        if not cookie:
            m = _COOKIE_FLAG_RE.search(flat)
            if m:
                cookie = m.group(2) if m.group(2) is not None else m.group(3)

    # ② 请求头块
    if not cookie:
        for line in raw.splitlines():
            m = _COOKIE_LINE_RE.match(line)
            if m:
                cookie = m.group(1)
                source = "header"
                break
        for line in raw.splitlines():
            m = _USER_AGENT_LINE_RE.match(line)
            if m:
                user_agent = m.group(1)
                break

    # ③ 裸 Cookie 串
    if not cookie:
        cookie = re.sub(r"^\s*cookie\s*:\s*", "", raw, flags=re.IGNORECASE)
        if re.match(r"^[a-z][a-z0-9+.\-]*://", cookie, re.IGNORECASE):
            raise CitrusError("bad_request", "这看起来是一个网址，不是 Cookie。",
                              "在浏览器里按 F12 -> Network -> 右键请求 -> Copy -> Copy as cURL，再粘过来。",
                              platform=platform or None)
        source = "raw"

    cookie = _unquote(cookie)
    cookie = cookie.replace("\\u003b", ";").replace("\\u003d", "=")
    cookie = re.sub(r"[\r\n]+", " ", cookie)
    cookie = re.sub(r"^\s*cookie\s*:\s*", "", cookie, flags=re.IGNORECASE).strip()

    if len(cookie) > MAX_COOKIE_BYTES:
        raise CitrusError("bad_request", "Cookie 太长了（超过 8 KB），不像是一条正常的 Cookie。",
                          platform=platform or None)
    if "=" not in cookie:
        raise CitrusError("bad_request", "这段内容里没有 name=value 形式的 Cookie。",
                          "选 Copy as cURL 复制整条请求，别只复制网页正文。",
                          platform=platform or None)

    parsed = CookieInput(cookie, _unquote(user_agent), source, auth_cookie_names)
    if not parsed.names:
        raise CitrusError("bad_request", "解析不出任何 Cookie 键值对。", platform=platform or None)
    return parsed
