"""把路由表 + 平台能力翻译成 OpenAPI 3.1 —— agent 靠它自动长出工具。

不手写几十页 YAML：从注册表里读能力，生成对应的 path。新增平台时文档自动多一节。
"""

from typing import Any

from . import __version__

_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "统一内容条目（各平台同形）。",
    "properties": {
        "platform": {"type": "string"},
        "kind": {"type": "string", "enum": ["answer", "article", "question", "post", "pin",
                                            "video", "zvideo", "user", "topic", "collection", "other"]},
        "id": {"type": "string"},
        "url": {"type": "string"},
        "title": {"type": "string"},
        "excerpt": {"type": "string"},
        "content": {"type": "string", "description": "正文，已转纯文本。"},
        "content_truncated": {"type": "boolean"},
        "author": {"type": "object"},
        "parent": {"type": ["object", "null"]},
        "stats": {
            "type": "object",
            "properties": {
                "likes": {"type": "integer"},
                "comments": {"type": "integer"},
                "shares": {"type": "integer"},
                "views": {"type": "integer"},
                "heat": {"type": "integer"},
            },
        },
        "created_at": {"type": ["string", "null"]},
        "updated_at": {"type": ["string", "null"]},
        "source": {"type": "string"},
        "related": {"type": "array", "items": {"type": "object"}},
        "extra": {"type": "object"},
    },
    "required": ["platform", "kind", "id", "url", "title", "content", "stats"],
}

_PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ITEM_SCHEMA},
        "count": {"type": "integer"},
        "page": {"type": "integer"},
        "has_more": {"type": "boolean"},
        "next_page": {"type": ["integer", "null"]},
        "source": {"type": "string"},
        "total": {"type": ["integer", "null"],
                  "description": "上游声明的总数（有的话）；用来判断还有多少没拿到。"},
        "errors": {"type": "array", "items": {"type": "object"},
                   "description": "局部降级说明，例如 comments_unavailable。"},
    },
    "required": ["items", "count", "page", "has_more"],
}

_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "enum": [False]},
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "hint": {"type": "string"},
                "retryable": {"type": "boolean"},
                "platform": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["code", "message"],
        },
    },
    "required": ["ok", "error"],
}

_REF_PARAMS: list[dict[str, Any]] = [
    {"name": "ref", "in": "query", "required": False,
     "description": "条目链接或带前缀的 id（answer:123 / question:456 / p:789）。与 kind+id 二选一。",
     "schema": {"type": "string"}},
    {"name": "kind", "in": "query", "required": False,
     "description": "条目类型；与 id 配合使用。", "schema": {"type": "string"}},
    {"name": "id", "in": "query", "required": False,
     "description": "条目 id；与 kind 配合使用。", "schema": {"type": "string"}},
]

_ACCOUNT_PARAMS: list[dict[str, Any]] = [
    {"name": "account", "in": "query", "required": False,
     "description": "用哪个账号标签（默认 default）。", "schema": {"type": "string"}},
]


def _ok(data_schema: dict[str, Any], summary: str, description: str = "",
        params: Any = None) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "responses": {
            "200": {
                "description": "成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean", "enum": [True]},
                                "data": data_schema,
                                "meta": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "401": {"description": "Cookie 失效 / 未配置",
                    "content": {"application/json": {"schema": _ERROR_SCHEMA}}},
            "403": {"description": "风控 / 无权限",
                    "content": {"application/json": {"schema": _ERROR_SCHEMA}}},
            "429": {"description": "限流",
                    "content": {"application/json": {"schema": _ERROR_SCHEMA}}},
        },
    }
    if params:
        operation["parameters"] = params
    return operation


def build_openapi(app: Any) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/v1/health": {"get": _ok({"type": "object"}, "健康检查")},
        "/v1/platforms": {"get": _ok({"type": "object"}, "列出平台、能力与账号状态")},
        "/v1/accounts": {"get": _ok({"type": "object"}, "列出已配置的账号（只回显指纹）")},
        "/v1/accounts/{platform}": {
            "put": {
                "summary": "保存某个平台的 Cookie",
                "description": "body 里放 cookie（可直接粘 cURL / Cookie 头 / 裸 Cookie / JSON 对象）。服务只在本机存这份 Cookie。",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "cookie": {"type": "string", "description": "cURL / Cookie 头 / 裸 Cookie 串 / JSON 对象"},
                                    "user_agent": {"type": "string"},
                                    "label": {"type": "string", "description": "账号标签，默认 default"},
                                },
                                "required": ["cookie"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "已保存"}},
            },
            "get": _ok({"type": "object"}, "查看某平台账号状态"),
            "delete": _ok({"type": "object"}, "删除某平台账号的 Cookie"),
        },
        "/v1/accounts/{platform}/verify": {
            "post": _ok({"type": "object"}, "体检：逐项报告哪条链路能走通"),
        },
    }

    for platform in app.registry.ids():
        meta = app.registry.describe(platform)
        capabilities = set(meta.get("capabilities", []))
        prefix = "/v1/%s" % platform
        if "account" in capabilities:
            paths[prefix + "/account"] = {
                "get": _ok({"type": "object"}, "当前账号信息", params=_ACCOUNT_PARAMS),
            }
        if "feed" in capabilities:
            paths[prefix + "/feed"] = {
                "get": _ok(_PAGE_SCHEMA, "内容流",
                           "按来源取列表；平台支持的来源见 /v1/platforms。",
                           params=_ACCOUNT_PARAMS + [
                               {"name": "source", "in": "query",
                                "description": "recommend / hot / following / mixed",
                                "schema": {"type": "string"}},
                               {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                               {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                           ]),
            }
        if "hot" in capabilities:
            paths[prefix + "/hot"] = {
                "get": _ok(_PAGE_SCHEMA, "热榜", params=_ACCOUNT_PARAMS + [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                ]),
            }
        if "search" in capabilities:
            paths[prefix + "/search"] = {
                "get": _ok(_PAGE_SCHEMA, "搜索", params=_ACCOUNT_PARAMS + [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "kind", "in": "query", "description": "按类型过滤（answer/article/question）",
                     "schema": {"type": "string"}},
                ]),
            }
        if "item" in capabilities:
            paths[prefix + "/item"] = {
                "get": _ok(_ITEM_SCHEMA, "读单条正文",
                           "ref 传链接或带前缀 id；related=true 时顺带返回同问题的高赞回答。",
                           params=_ACCOUNT_PARAMS + _REF_PARAMS + [
                               {"name": "related", "in": "query", "schema": {"type": "boolean", "default": False}},
                               {"name": "content_limit", "in": "query",
                                "description": "正文字数上限，0 表示默认上限。",
                                "schema": {"type": "integer", "default": 0}},
                               {"name": "include_html", "in": "query", "schema": {"type": "boolean", "default": False}},
                           ]),
            }
        if "comments" in capabilities:
            paths[prefix + "/comments"] = {
                "get": _ok(_PAGE_SCHEMA, "评论",
                           params=_ACCOUNT_PARAMS + _REF_PARAMS + [
                               {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                               {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                               {"name": "sort", "in": "query",
                                "description": "hot（默认，按热度）/ new（按时间倒序）",
                                "schema": {"type": "string", "enum": ["hot", "new"], "default": "hot"}},
                           ]),
            }
        if "user" in capabilities:
            paths[prefix + "/user"] = {
                "get": _ok({"type": "object"}, "用户主页信息", params=_ACCOUNT_PARAMS + [
                    {"name": "ref", "in": "query", "required": True,
                     "description": "主页链接或 url_token", "schema": {"type": "string"}},
                ]),
            }
        if "user_content" in capabilities:
            paths[prefix + "/user/content"] = {
                "get": _ok(_PAGE_SCHEMA, "某个用户的内容", params=_ACCOUNT_PARAMS + [
                    {"name": "ref", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                ]),
            }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "citrus 统一社交平台信息 API",
            "version": __version__,
            "description": ("一个形状、多个平台。给每个平台配一份浏览器 Cookie，就能用同一套接口读内容。\n\n"
                            "约定：成功 {ok:true, data, meta}；失败 {ok:false, error:{code,message,hint,retryable}}。"
                            " agent 只需处理 error.code。"),
        },
        "servers": [{"url": "http://%s:%d" % (app.config.host, app.config.port)}],
        "components": {"schemas": {"Item": _ITEM_SCHEMA, "Page": _PAGE_SCHEMA, "Error": _ERROR_SCHEMA}},
        "paths": paths,
    }
