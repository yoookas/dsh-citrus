# citrus

AstrBot 的知乎内容插件：用户在群里问「知乎热榜有什么」「这个问题大家怎么看」「评论区在争什么」
的时候，机器人**真的去知乎抓内容**，再交给模型总结 —— 而不是凭记忆编。

采集层用的是 **citrus**（统一社交平台读接口），以 vendor 方式内置在插件里，
所以插件是自包含的：**不需要 pip 安装、不需要另外起服务**。

## 目录

```
.
├── astrbot_plugin_citrus/       # 插件本体（打进 zip 的就是这个目录）
│   ├── main.py                  # Star 子类：4 个 LLM 工具 + 6 个指令 + 白名单
│   ├── bridge.py                # citrus 异步门面（to_thread + 串行锁 + 错误翻译）
│   ├── render.py                # 统一模型 → 紧凑文本
│   ├── _conf_schema.json        # WebUI 配置表单
│   ├── metadata.yaml            # 插件元数据（版本号在这里）
│   ├── vendor/citrus/           # 原样内置的采集库
│   └── tests/                   # 离线测试（不进 zip）
├── scripts/
│   ├── build_zip.py             # 打 AstrBot 能直接安装的 zip
│   └── bump_version.py          # 改 metadata.yaml 的版本号
└── .github/workflows/           # CI 与 Release
```

## 安装

1. 到 [Releases](../../releases) 下载 `astrbot_plugin_citrus_<版本>.zip`；
2. AstrBot WebUI → 插件 → 上传插件；
3. 浏览器登录知乎 → F12 → Network → 右键任意知乎请求 → **Copy as cURL** →
   粘贴进插件配置的「知乎 Cookie」 → 保存；
4. 发 `/知乎状态` 自检，再发 `/知乎热榜` 试试。

白名单：先发 `/sid` 拿到自己的用户 ID，填进配置的「允许使用的用户 ID」。

详细说明见 [astrbot_plugin_citrus/README.md](astrbot_plugin_citrus/README.md)。

## 能力

| 方式 | 触发 |
|---|---|
| 模型自动调用 | `zhihu_hot` / `zhihu_search` / `zhihu_read` / `zhihu_comments` 四个 function calling 工具 |
| 确定性指令 | `/知乎热榜` `/知乎搜` `/知乎看` `/知乎评论` `/知乎状态` `/知乎帮助` |

## 版本号规则

`YY.MM.TT`：

- **YY** —— 年份后两位（26 = 2026）
- **MM** —— 月份（01-12）
- **TT** —— **本月第几次发布**，从 01 开始

例：`26.11.01` 是 2026 年 11 月第一次发版，同月再发就是 `26.11.02`；换月自动回到 `01`。

## 发布新版本

两种方式都会：跑测试 → 打包 zip → 建 GitHub Release（附 zip 与 sha256）。

### ① 手动触发（推荐）

Actions → **Release** → **Run workflow**。

版本号自动算：取当月已有的 `vYY.MM.*` 标签，最大 TT 加一；然后自动提交版本号、
打 tag、发版。同一个地方点第二次，就是本月第二次发布。

### ② 自己推 tag

```bash
git tag v26.11.03
git push origin v26.11.03
```

按 tag 里的版本号发版（格式不符会让 workflow 直接失败）。

## 本地开发

```bash
# 插件离线测试：起一个假知乎，跑通所有工具与指令（20 个用例）
cd astrbot_plugin_citrus
python -m unittest discover -s tests -t . -v

# 真实链路冒烟（可选，只发一个请求；需要本机 ~/.citrus 里有 Cookie）
python tests/live_check.py
```

```bash
# 打包
python scripts/build_zip.py              # 版本号取 metadata.yaml
python scripts/build_zip.py 26.11.02     # 指定版本号
```

打包产物在 `dist/`，结构是 `astrbot_plugin_citrus/...`，正好是 WebUI 能吃的样子。

## 内置的 citrus

`astrbot_plugin_citrus/vendor/citrus/` 是上游 citrus 项目的原样副本（未改一行），
升级方式与注意事项见 [vendor/README.md](astrbot_plugin_citrus/vendor/README.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。`vendor/citrus/` 是第三方代码，遵循它自带的 LICENSE。
