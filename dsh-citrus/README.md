# dsh-citrus · 知乎内容插件

给 DeepSeek Harness 装上「真的去知乎看」的能力：热榜、问题、回答正文、评论区观点，
用户在对话里正常提问，模型会自己调用工具抓取真实内容再总结。

零第三方运行时依赖（只用 Node 内置模块），采集层是从 citrus 项目移植的 JavaScript 实现。

---

## 工具

| 工具 | 什么时候调用 | 参数 |
|---|---|---|
| `zhihu_hot` | 知乎热榜、今天在讨论什么 | `limit`（1-30） |
| `zhihu_search` | 找某个话题下的问题/回答/文章/用户 | `query`、`limit`、`kind` |
| `zhihu_read` | 读问题或回答正文（问题会带高赞回答） | `ref`、`with_answers`、`content_chars` |
| `zhihu_comments` | 评论区怎么看、有哪些不同意见 | `ref`、`limit`、`sort` |

另外，当工具在当前会话可见时，会往系统提示词里加一句「知乎内容要现场抓，别凭记忆编」。

`ref` 认这些写法：`https://www.zhihu.com/question/123`、
`https://www.zhihu.com/question/123/answer/456`、`answer:456`、`question:123`、`p:789`、纯数字。

---

## 安装

在仓库根目录运行：

```bash
node scripts/install.mjs
```

它会：

1. 把插件复制到 `<DSH_HOME>/plugins/dsh-citrus`；
2. 在插件目录建一个 `node_modules` 链接，指向 `<DSH_HOME>/profiles/node_modules`（解析宿主包）；
3. 往当前 profile 的 `cordis.patch.yml` 里插入一段带标记的配置（幂等，可重复跑）。

可选参数：

```bash
node scripts/install.mjs --profile web   # 指定 profile（默认 desktop）
node scripts/install.mjs --dry-run       # 只看会做什么
node scripts/install.mjs --uninstall     # 卸载
```

> 装好后如果 GUI 里还看不到工具，重启一次 DeepSeek Harness。
> Electron 桌面端当前不会热加载 `cordis.patch.yml` 的变更。

---

## 配置 Cookie

### 方式 A：命令行（推荐）

```bash
node <DSH_HOME>/plugins/dsh-citrus/bin/cli.mjs auth
```

把浏览器里 `F12 -> Network -> 右键任意知乎请求 -> Copy -> Copy as cURL` 的内容粘进去，
按 `Ctrl+Z` 回车（Linux/macOS 是 `Ctrl+D`）。四种格式都认：cURL 整段、请求头块、裸 Cookie 串、JSON。

检查：

```bash
node <DSH_HOME>/plugins/dsh-citrus/bin/cli.mjs status
```

会显示 Cookie 指纹（**不显示原文**）、登录态、上游账号和热榜连通性。

### 方式 B：插件配置

在 `cordis.patch.yml` 的 `dsh-citrus` 条目里填：

```yaml
- insert:
    - id: dsh-citrus
      name: 'file:///.../plugins/dsh-citrus/lib/index.js'
      config:
        cookie: '把 cURL 粘在这里'
        # 或
        # cookieFile: 'C:/Users/you/.dsh/dsh-citrus/zhihu.cookie'
```

Cookie 文件默认在 `<DSH_HOME>/dsh-citrus/zhihu.cookie`，换号后下一次工具调用立即生效，不用重启。

---

## 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `cookie` | 空 | 直接粘贴 cURL（secret 角色，配置界面会遮罩） |
| `cookieFile` | 空 | Cookie 文件路径；空 = `<DSH_HOME>/dsh-citrus/zhihu.cookie` |
| `hotLimit` | 10 | 热榜默认条数（1-30） |
| `searchLimit` | 8 | 搜索默认条数（1-20） |
| `commentLimit` | 20 | 评论默认条数（1-100） |
| `contentChars` | 1500 | 单条正文字数上限（200-16000） |
| `commentChars` | 200 | 单条评论字数上限（40-800） |
| `excerptChars` | 120 | 列表摘要字数上限（20-600） |
| `relatedAnswers` | 3 | 读问题时附带几条高赞回答（0-5） |
| `gapMs` | 350 | 请求最小间隔；别长期设 0，那是给自己找风控 |
| `jitterMs` | 250 | 请求随机抖动 |
| `timeoutMs` | 20000 | 单次上游请求超时 |
| `maxRetries` | 2 | 429/5xx/网络错误重试次数 |
| `promptHint` | true | 是否注入系统提示词指引 |

---

## 常见错误

工具失败会返回一句 `Error: ...`，原因和下一步都写在里面：

| 现象 | 处理 |
|---|---|
| 还没有配置知乎 Cookie | 跑 `cli.mjs auth` 粘贴 cURL |
| Cookie 里的登录态失效了 | 浏览器重新登录知乎，重新复制一次 |
| 被知乎风控拦住了（验证页） | 去浏览器过一次验证，等几分钟；**不要连续重试** |
| 知乎限流了 | 等几分钟；把 `gapMs` 调大 |
| 请求没能发到知乎 | 检查这台机器的网络 / 代理 / DNS |

---

## 开发

```bash
cd dsh-citrus

# 宿主包解析：本地开发时把 <DSH_HOME>/profiles/node_modules 链接成 node_modules
# Windows: mklink /J node_modules %USERPROFILE%\.dsh\profiles\node_modules

npm test                       # 28 个离线用例（假知乎，不联网）
node --check lib/index.js      # 语法检查
```

测试覆盖：Cookie 四种格式、HTML 转文本、热榜/搜索/正文/评论、错误码翻译、渲染、工具注册与执行。

目录：

```
dsh-citrus/
├── lib/
│   ├── index.js                 # Cordis 插件入口（name / inject / Config / apply）
│   ├── config.js                # schemastery 配置
│   ├── tools.js                 # 4 个模型工具
│   ├── prompt.js                # 系统提示词段落
│   ├── runtime.js               # Cookie -> 适配器
│   ├── render.js                # 统一模型 -> 文本
│   ├── store.js                 # Cookie 文件读写
│   ├── core/                    # 错误、Cookie 解析、HTML、限速 HTTP、模型、缓存
│   └── platforms/zhihu/         # 接口地址、字段归一化、适配器
├── bin/cli.mjs                  # auth / status / hot / logout
└── tests/                       # node:test
```

---

## 隐私与边界

* Cookie 只存在本地文件（默认 `<DSH_HOME>/dsh-citrus/zhihu.cookie`）或插件配置里；
* 日志和工具输出里只有指纹（`#8562c066` 这种），永远不打印原文；
* 只读：不点赞、不评论、不关注、不私信；
* 不绕过风控：没有验证码破解、没有代理池；撞上验证页就如实报错。

---

## 许可

MIT，见 [LICENSE](LICENSE)。