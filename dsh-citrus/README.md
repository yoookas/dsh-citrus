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
| `zhihu_status` | 排查「装没装好 / 设置生效没有」：返回命名空间、client bundle、Loader 条目和当前值 | 无 |

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
2. 在插件目录建一个 `node_modules` 链接，指向 `<DSH_HOME>/profiles/<profile>/node_modules`（解析宿主包；找不到就跳过）；
3. 把它登记成 profile bundle（`package.json` 的依赖 + `dsh.profile.bundles`），并清掉旧脚本留下的配置块。

可选参数：

```bash
node scripts/install.mjs --profile web   # 指定 profile（默认 desktop）
node scripts/install.mjs --dry-run       # 只看会做什么
node scripts/install.mjs --uninstall     # 卸载
```

> 装好后如果 GUI 里还看不到工具，重启一次 DeepSeek Harness。
> Electron 桌面端当前不会热加载 `cordis.patch.yml` 的变更。

---

## 面板卡片配置

安装并重载插件后有**两个入口**（同一份表单，改哪个都一样）：

- **设置 → citrus**：设置里的独立分区，最直观；
- **侧栏「插件」页 → dsh-citrus 这一行的「配置」**：行配置入口。

两个入口都只在 Host 真的 serve 了 `dsh-citrus` 这个 settings 命名空间时才出现；
没装、没启用或被别的 profile 覆盖时，界面里不会留下空壳。

卡片内容：

- **平台 tab**：一个平台一个页签（现在只有「知乎」）；加平台不用改页面结构，`PLATFORMS` 里加一项就多一个 tab。
- **全部配置字段**：schema 里 14 个字段面板都能改——Cookie（密码框，留空=不修改）、Cookie 文件路径、
  6 个条数/字数、附带高赞回答数、提示词开关、请求间隔/抖动/超时/重试次数。
- **保存设置**：写进**当前 profile 的 Cordis patch**（也就是这个 bundle 那一行的 `config`），**下一次工具调用立即生效**，不用重启。
- **恢复默认**：清掉这些用户覆盖，回退到组合配置里的值（包括 schema 默认值）。
- **清除「知乎」Cookie**：只清当前页签这个平台的 Cookie，回退到本地 Cookie 文件（`dsh-citrus auth` 写的那份）。

> 设置不是写进 `<DSH_HOME>/settings.yaml`：DSH 0.2 起，表单改动通过 config-editor 落盘到
> profile 的 Cordis patch。`settings.yaml` 只在旧版本迁移时被读一次。
> 面板里的 Cookie 也会跟着进这份 patch；不想让它落盘就用 `dsh-citrus auth` 或 `cookieFile`。
>
> 装完/更新插件后如果入口没出现，刷新一次 GUI 页面（Ctrl+R）——浏览器端模块图是页面加载时注入的。

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
        platforms:
          zhihu:
            cookie: '把 cURL 粘在这里'
            # 或
            # cookieFile: 'C:/Users/you/.dsh/dsh-citrus/zhihu.cookie'
```

Cookie 文件默认在 `<DSH_HOME>/dsh-citrus/zhihu.cookie`，换号后下一次工具调用立即生效，不用重启。

---

## 配置项

配置按平台分组，所以路径都是 `platforms.<平台>.<字段>`。目前只有 `zhihu` 一段。

| 配置 | 默认 | 说明 |
|---|---|---|
| `platforms.zhihu.cookie` | 空 | 直接粘贴 cURL（secret 角色，配置界面会遮罩） |
| `platforms.zhihu.cookieFile` | 空 | Cookie 文件路径；空 = `<DSH_HOME>/dsh-citrus/zhihu.cookie` |
| `platforms.zhihu.hotLimit` | 10 | 热榜默认条数（1-30） |
| `platforms.zhihu.searchLimit` | 8 | 搜索默认条数（1-20） |
| `platforms.zhihu.commentLimit` | 20 | 评论默认条数（1-100） |
| `platforms.zhihu.contentChars` | 1500 | 单条正文字数上限（200-16000） |
| `platforms.zhihu.commentChars` | 200 | 单条评论字数上限（40-800） |
| `platforms.zhihu.excerptChars` | 120 | 列表摘要字数上限（20-600） |
| `platforms.zhihu.relatedAnswers` | 3 | 读问题时附带几条高赞回答（0-5） |
| `platforms.zhihu.gapMs` | 350 | 请求最小间隔；别长期设 0，那是给自己找风控 |
| `platforms.zhihu.jitterMs` | 250 | 请求随机抖动 |
| `platforms.zhihu.timeoutMs` | 20000 | 单次上游请求超时 |
| `platforms.zhihu.maxRetries` | 2 | 429/5xx/网络错误重试次数 |
| `platforms.zhihu.promptHint` | true | 是否注入系统提示词指引 |

### 加一个平台要动哪儿

1. `lib/config.js`：`platforms` 里加一段 schema；
2. `lib/platforms/<id>/`：加适配器，并在 `lib/platforms/registry.js` 的 `PLATFORM_IDS` 里登记；
3. `lib/client.js`：`PLATFORMS` 数组里加一项，字段按 `kind` 声明：
   `number`（数字框，留空=取消覆盖）、`text`（文本，留空=取消覆盖）、
   `secret`（密码框，留空=不修改）、`toggle`（开关，写布尔值）。

tab、控件、写回语义都由 `PLATFORMS` 决定，不用再写 UI 代码。
宿主的工具层只认 `platformConfig(config, id)`，也不用逐个改。

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

## 自检

怀疑没装好、或者改完面板没生效时，让模型跑一次 `zhihu_status`（或 `zhihu_hot` 带 `limit: 0`，不发上游请求），返回的字段都能直接核对：

| 字段 | 期望 |
|---|---|
| `host.namespaceRegistered` | `true`——配置命名空间在，面板才有对象可改 |
| `host.values.hotLimit` 等 | 面板上设的值；改完面板再跑一次应该跟着变 |
| `clientModules.hasCitrus` | `true`——浏览器半侧进了启动图，界面才有入口 |
| `loader.entries[].fiber` | 不是 `null`——插件条目真的起来了 |

> **改完宿主代码要重启一次 DeepSeek Harness。** 开关插件只会重跑入口文件，
> 被 import 过的模块仍在 Node 的 ESM 缓存里，不重启不会加载新版本；
> 浏览器半侧是按文件 mtime 出 rev 的，刷新页面（Ctrl+R）就够。

---

## 开发

```bash
cd dsh-citrus

# 宿主包解析：本地开发时把 <DSH_HOME>/profiles/<profile>/node_modules 链接成 node_modules
# Windows: mklink /J node_modules %USERPROFILE%\.dsh\profiles\desktop\node_modules

npm test                       # 43 个离线用例（假知乎 + 假 React，不联网）
node --check lib/index.js      # 语法检查
node --check lib/client.js
```

测试覆盖：Cookie 四种格式、HTML 转文本、热榜/搜索/正文/评论、错误码翻译、渲染、工具注册与执行、
浏览器半侧的 slot 注册与写入结果处理。

> **浏览器半侧的两个硬性声明**（少一个，界面上就什么都看不到，而且不会报错）：
> `package.json` 里的 `dsh.client.platform = "web"`，以及 `exports["./client"]` 指向 `lib/client.js`。
> `dsh-client-modules` 只扫描带这个声明的包，再按 `./client` 去取 bundle。

目录：

```
dsh-citrus/
├── lib/
│   ├── index.js                 # Cordis 插件入口（name / inject / Config / apply）
│   ├── config.js                # schemastery 配置（meta.volatile = 可热改）
│   ├── client.js                # 浏览器半侧：settings.section + plugins.row.config
│   ├── tools.js                 # 4 个模型工具
│   ├── prompt.js                # 系统提示词段落
│   ├── runtime.js               # Cookie -> 适配器
│   ├── render.js                # 统一模型 -> 文本
│   ├── store.js                 # Cookie 文件读写
│   ├── core/                    # 错误、Cookie 解析、HTML、限速 HTTP、模型、缓存
│   └── platforms/
│       ├── registry.js          # 平台清单 + platformConfig()（不依赖宿主包）
│       └── zhihu/               # 接口地址、字段归一化、适配器
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