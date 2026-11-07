"""知乎的接口地址 —— 平台的所有「魔法字符串」都集中在这一个文件里。

知乎没有面向个人的开放 API，这里用的是网页端自己在用的 v3/v4 读接口
（只读、GET、带浏览器登录态）。接口一改，改这里就够了。
"""

import urllib.parse
from typing import Any

BASE_URL = "https://www.zhihu.com"

#: 列表接口返回的字段（v4 用 include=data[*].xxx 的写法）
ANSWER_FIELDS = ",".join([
    "content", "excerpt", "voteup_count", "comment_count",
    "author.name", "author.url_token", "author.headline", "author.avatar_url",
    "question.title", "question.id", "created_time", "updated_time",
])
ARTICLE_FIELDS = ",".join([
    "content", "excerpt", "voteup_count", "comment_count",
    "author.name", "author.url_token", "author.headline", "author.avatar_url",
    "title", "created", "updated",
])
LIST_INCLUDE = "data[*].content,excerpt,voteup_count,comment_count,author.name,author.url_token,question.title,question.id,created_time"
COMMENT_INCLUDE = "data[*].content,author.name,author.url_token,author.avatar_url,vote_count,created_time,reply_count"


def _quote(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="")


# ---- v3 列表 --------------------------------------------------------

def hot(limit: int) -> tuple[str, dict[str, Any]]:
    return "/api/v3/feed/topstory/hot-lists/total", {"limit": limit, "desktop": "true"}


def recommend(limit: int, page: int) -> tuple[str, dict[str, Any]]:
    return "/api/v3/feed/topstory/recommend", {
        "action": "down",
        "ad_interval": -10,
        "desktop": "true",
        "page_number": page,
        "limit": limit,
    }


def following(limit: int, page: int) -> tuple[str, dict[str, Any]]:
    return "/api/v3/feed/topstory", {
        "action": "down",
        "desktop": "true",
        "page_number": page,
        "limit": limit,
    }


# ---- 搜索 -----------------------------------------------------------

def search(query: str, limit: int, offset: int, kind: str = "") -> tuple[str, dict[str, Any]]:
    t = "content" if kind else "general"
    return "/api/v4/search_v3", {
        "t": t,
        "q": query,
        "correction": 1,
        "offset": offset,
        "limit": max(1, min(int(limit), SEARCH_PAGE_CAP)),
        "lc_idx": offset,
        "show_all_topics": 0,
        "search_source": "Normal",
    }


# ---- 单条正文 -------------------------------------------------------

def answer(answer_id: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/answers/" + _quote(answer_id), {"include": ANSWER_FIELDS}


def article(article_id: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/articles/" + _quote(article_id), {"include": ARTICLE_FIELDS}


def question(question_id: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/questions/" + _quote(question_id), {
        "include": "detail,excerpt,answer_count,follower_count,visit_count,created,updated",
    }


def question_answers(question_id: str, limit: int, offset: int, sort_by: str = "default") -> tuple[str, dict[str, Any]]:
    return "/api/v4/questions/" + _quote(question_id) + "/answers", {
        "include": LIST_INCLUDE,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
    }


def pin(pin_id: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/pins/" + _quote(pin_id), {"include": "content,excerpt,like_count,comment_count,created,updated"}


def zvideo(zvideo_id: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/zvideos/" + _quote(zvideo_id), {"include": "title,description,voteup_count,comment_count,created_time"}


# ---- 评论 -----------------------------------------------------------

#: kind -> 评论接口里的资源名
COMMENT_NOUNS = {
    "answer": "answers",
    "article": "articles",
    "question": "questions",
    "pin": "pins",
    "zvideo": "zvideos",
}


#: 上游每页真实能给多少（实测：传 100 也只回这么多，必须靠翻页凑）
COMMENT_PAGE_CAPS = {"v5": 10, "legacy": 20}
SEARCH_PAGE_CAP = 20

#: 统一排序名 -> 各接口自己的取值（实测：v5 的 ts = 时间倒序；旧接口的 score 才是时间倒序）
COMMENT_ORDERS = {
    "v5": {"hot": "score", "new": "ts"},
    "legacy": {"hot": "normal", "new": "score"},
}


def comments_v5(kind: str, resource_id: str, limit: int, offset: int,
                sort: str = "hot") -> tuple[str, dict[str, Any]]:
    """新版评论接口：什么类型都有一条路径，但经常回 200 + 空数组（见 adapter.comments）。"""
    noun = COMMENT_NOUNS.get(kind, "answers")
    return "/api/v4/comment_v5/" + noun + "/" + _quote(resource_id) + "/root_comment", {
        "order_by": COMMENT_ORDERS["v5"].get(sort, "score"),
        "limit": max(1, min(int(limit), COMMENT_PAGE_CAPS["v5"])),
        "offset": offset,
    }


def comments_legacy(kind: str, resource_id: str, limit: int, offset: int,
                    sort: str = "hot") -> tuple[str, dict[str, Any]]:
    """旧版评论接口：回答身上最靠谱；文章/问题会 404。"""
    noun = COMMENT_NOUNS.get(kind, "answers")
    return "/api/v4/" + noun + "/" + _quote(resource_id) + "/comments", {
        "include": COMMENT_INCLUDE,
        "limit": max(1, min(int(limit), COMMENT_PAGE_CAPS["legacy"])),
        "offset": offset,
        "order": COMMENT_ORDERS["legacy"].get(sort, "normal"),
    }


# ---- 人 -------------------------------------------------------------

def me() -> tuple[str, dict[str, Any]]:
    return "/api/v4/me", {"include": "name,url_token,headline,gender,avatar_url"}


def member(token: str) -> tuple[str, dict[str, Any]]:
    return "/api/v4/members/" + _quote(token), {
        "include": "name,url_token,headline,avatar_url,answer_count,articles_count,follower_count,description",
    }


def member_answers(token: str, limit: int, offset: int) -> tuple[str, dict[str, Any]]:
    return "/api/v4/members/" + _quote(token) + "/answers", {
        "include": LIST_INCLUDE,
        "limit": limit,
        "offset": offset,
        "sort_by": "created",
    }


def member_articles(token: str, limit: int, offset: int) -> tuple[str, dict[str, Any]]:
    return "/api/v4/members/" + _quote(token) + "/articles", {
        "include": "data[*].content,excerpt,voteup_count,comment_count,author.name,title,created",
        "limit": limit,
        "offset": offset,
        "sort_by": "created",
    }


def followees(token: str, limit: int, offset: int = 0) -> tuple[str, dict[str, Any]]:
    return "/api/v4/members/" + _quote(token) + "/followees", {"limit": limit, "offset": offset}
