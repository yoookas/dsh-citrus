# 知乎适配器

一切「懂知乎」的东西都在这个目录里，核心层不认识知乎。

```
endpoints.py   接口路径 + include 字段（知乎改版只改这里）
client.py      带登录态的请求 + 错误提示文案
normalize.py   原始 JSON -> 统一模型（字段映射的脏活）
adapter.py     编排：选接口、翻页、缓存、体检
```

## 能力

| 能力 | 走的接口 | 说明 |
|---|---|---|
| `account` | `GET /api/v4/me` | 当前 Cookie 是谁 |
| `feed` | `v3/feed/topstory/recommend`、`v3/feed/topstory`、热榜 | `recommend` / `hot` / `following` / `mixed` |
| `hot` | `GET /api/v3/feed/topstory/hot-lists/total` | 热榜，`card_id` 前缀决定 kind |
| `search` | `GET /api/v4/search_v3` | 综合搜索，用户结果也归一成 item |
| `item` | `v4/answers`、`v4/articles`、`v4/questions`、`v4/pins`、`v4/zvideos` | 正文转纯文本 |
| `comments` | 回答走 `v4/answers/{id}/comments`，其余走 `v4/comment_v5/{noun}/{id}/root_comment` | 两个接口互补，见下面「评论为什么两套接口」；排序统一 `sort=hot/new` |
| `user` | `GET /api/v4/members/{token}` | |
| `user_content` | `v4/members/{token}/answers` + `/articles` | 按时间倒序合并 |

## Cookie 怎么给

只需要浏览器里的登录态，**不要账号密码**：

1. 浏览器登录 zhihu.com；
2. `F12` → **Network**；
3. 选一条 **Request URL 为 `https://www.zhihu.com`**（页面本身那条 Document 请求，没有 `/api/...` 后缀）的请求；
4. 右键 → **Copy → Copy as cURL**；
5. 丢给 `PUT /v1/accounts/zhihu` 或 `citrus auth zhihu`。

判断标准很简单：**Cookie 里有 `z_c0`** 才算登录（`/v1/accounts/zhihu` 的 `cookie_hint` 会显示名字，不显示值）。

为什么不用扫码/短信/密码：知乎对非浏览器客户端的登录轮询风控很严，传统 Cookie 反而最稳，
也不需要服务碰用户的账号密码。

## 请求口径

- 串行 + 最小间隔 350ms（`CITRUS_ZHIHU_GAP_MS`）+ 随机抖动 0–250ms（`_JITTER_MS`），
  每 15 次长歇 1.2–3s（`_BURST_EVERY`）—— 别把请求打成节拍器；
- 带浏览器头：`user-agent`（从 cURL 里取）、`referer`、`origin`、`x-requested-with`、`x-api-version`；
- `accept-encoding: identity`（避免自己解压缩），万一上游还是压缩了会自动解 gzip/deflate；
- 429 / 5xx / 网络错误自动退避重试（默认 2 次，尊重 `Retry-After`）。

## 上限（实测，2026-11）

知乎会**偷偷截断** `limit`，传多少都只给这么多：

| 接口 | 一次最多给 | 我们对外允许 | 怎么凑够 |
|---|---|---|---|
| `comment_v5` root_comment | 10 | 100 | 内部分页（最多 8 次） |
| 旧 `comments` | 20 | 100 | 内部分页（最多 8 次） |
| `search_v3` | 20 | 100 | 内部分页（最多 6 次） |
| 热榜 | 30 | 30 | 不给翻页，认命 |
| 推荐流 | 一页 6–10 条 | 50 | 用 `page` 翻 |

分页预算（`COMMENT_PAGE_BUDGET` / `SEARCH_PAGE_BUDGET`）是故意的：一次调用打太多次上游，
比慢一点更容易出问题。没凑够就如实给 `has_more: true`。

## 错误怎么翻

| 上游现象 | code | 让用户做什么 |
|---|---|---|
| HTTP 401 | `not_logged_in` | 重新登录知乎，再复制一次 cURL |
| 403 且是验证页（`acw_sc__v2` 等） | `challenge` | 回浏览器过验证，等几分钟 |
| 403 其他 | `forbidden` | 换账号 / 检查网络出口 |
| 404 | `not_found` | 内容没了 |
| 429 | `rate_limited` | 等几分钟 |
| 200 但返回 HTML | `challenge` | 同上（多半是风控页） |

> 搜索偶尔会只返回广告位/热榜时间提示（`hot_timing` / `knowledge_ad`），这时 `data.errors` 里会有
> `no_usable_results`，`count` 为 0 —— 不是「没搜到」，是上游这一页没给真结果，隔一会儿再试。

## 评论为什么两套接口

实测（12 个真实资源，2026-11）两个接口谁也不能替代谁：

| 接口 | 回答 | 文章 / 问题 |
|---|---|---|
| 旧 `v4/{noun}/{id}/comments` | **能拿到真评论** | 直接 404 |
| 新 `v4/comment_v5/{noun}/{id}/root_comment` | 约一半回 200 + 空数组（`counts` 却写着几百条） | 有响应，但同样常回空 |

所以策略是：

1. 回答先用旧接口，文章/问题先用新接口；
2. 这一路没拿到条目就换另一路再试；
3. **两路都没条目、但上游说有总数**时，返回 `count: 0` + `total: N` +
   `errors: [{code: "comments_unavailable"}]` —— 说清楚「有评论但没拿到」，不假装没有。

### 排序

对外只有两个值（`sort`），上游的取值各有各的说法：

| `sort` | `comment_v5` | 旧接口 |
|---|---|---|
| `hot`（默认） | `order_by=score` | `order=normal` |
| `new` | `order_by=ts` | `order=score`（实测这个才是时间倒序） |

注意旧接口的 `order` 命名很反直觉：`score`/`reverse`/`ts` 都等价于「最新在前」，
只有 `normal` 是热度序。别照着字面改。

## 刻意不做的事

- 点赞 / 评论 / 关注 / 私信 / 收藏 —— 一个写接口都没有；
- 破验证码、代理池、Cookie 轮换 —— 撞上风控就停；
- v4 正文被拦时退回列表摘要 —— 宁可报错，也不给半截数据；
- 关注列表（`followees`）—— 用 `user/content` 按人读就够了，先不扩。

## 改版了怎么办

1. 接口路径变了 → 改 `endpoints.py`；
2. 字段名变了 → 改 `normalize.py`；
3. 新增字段 → 塞进 `extra`，不要往统一模型里加平台专有键；
4. 改完跑 `tests/test_zhihu_normalize.py` 和 `tests/test_zhihu_adapter.py`，
   夹具在 `tests/support/mock_upstream.py`。
