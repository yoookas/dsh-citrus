# dsh-citrus

DeepSeek Harness 的知乎内容插件：让 agent **真的去知乎抓内容**，而不是凭记忆编。

- 4 个模型工具：`zhihu_hot` / `zhihu_search` / `zhihu_read` / `zhihu_comments`
- 面板卡片：设置 → Citrus，或侧栏「插件」面板 → 内置插件配置 → 知乎内容；保存即生效
- 1 条系统提示词指引，只在工具可见时注入
- 零运行时依赖（只用 Node 内置模块）
- 只读、限速、如实报错

## 目录

```
.
├── dsh-citrus/               # 插件本体（npm 包）
│   ├── lib/                  # 插件代码
│   ├── bin/cli.mjs           # auth / status / hot / logout
│   └── tests/                # 31 个离线用例
├── scripts/
│   ├── install.mjs           # 装进某个 DSH profile
│   ├── build.mjs             # 打 npm tarball
│   └── bump_version.mjs      # 改版本号
└── .github/workflows/        # CI 与 Release
```

## 快速开始

```bash
# 1. 安装到当前 DeepSeek Harness profile
node scripts/install.mjs

# 2. 配置知乎 Cookie（粘贴浏览器 Copy as cURL 的内容）
node "$env:USERPROFILE/.dsh/plugins/dsh-citrus/bin/cli.mjs" auth

# 3. 重启一次 DeepSeek Harness，然后问：「知乎热榜有什么」
```

详细说明见 [dsh-citrus/README.md](dsh-citrus/README.md)。

## 兼容性

在 **DeepSeek Harness 0.1.5-rc.2 / Node 24** 上验证过：

- 最小插件树启动（`tools` + `systemPrompt` + 本插件）→ 4 个工具注册成功；
- 克隆 desktop profile、带完整 patch 启动 web 应用 → 插件正常激活；
- 真实知乎链路（`cli.mjs status` / `hot`）→ 账号与热榜均正常。

宿主包（`@deepseek-ai/dsh-tools` 等）通过 profile 的 `node_modules` 解析，插件本身不打包它们。

## 版本号规则

`YY.MM.TT`：年.月.本月第几次发布，例 `26.11.02` = 2026 年 11 月第二次发布。

## 发布

Actions → **Release** → **Run workflow**：

1. 自动算出本月下一个 TT；
2. 跑测试，改 `dsh-citrus/package.json` 版本号并提交；
3. 打 tag `vYY.MM.TT`；
4. 构建 `dist/dsh-citrus-YY.MM.TT.tgz`，发 Release（附 sha256）。

也可以自己推 tag：`git tag v26.11.03 && git push origin v26.11.03`。

## 开发

```bash
cd dsh-citrus
npm test
```

离线测试会起一个假知乎（本地 HTTP 服务），覆盖 Cookie 解析、热榜/搜索/正文/评论、错误翻译、
渲染和工具注册执行，**不需要联网、不需要真 Cookie**。

## 许可

MIT，见 [LICENSE](LICENSE)。