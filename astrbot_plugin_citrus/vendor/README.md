# vendor/citrus

这里放的是 **citrus**（统一社交平台读接口）的**原样副本**，插件运行时直接 import 它，
所以安装插件不需要 pip、也不需要另外起服务。

## 来源

| 项 | 值 |
|---|---|
| 来源项目 | 本地 citrus 项目（citrus_api/citrus） |
| 版本 | 见 citrus/__init__.py 里的 __version__（当前 0.1.0） |
| 改动 | 无。除缓存文件外逐文件 SHA256 与上游一致 |
| 许可 | 见 citrus/LICENSE（MIT） |

复制时排除了 __pycache__，其余文件一字未改。

## 升级步骤

1. 用上游的新版本覆盖 vendor/citrus/（整目录替换，别逐个文件改）：

   ```
   robocopy <上游>\citrus astrbot_plugin_citrus\vendor\citrus /MIR /XD __pycache__
   ```

2. 在插件目录跑一遍离线测试：

   ```
   cd astrbot_plugin_citrus && python -m unittest discover -s tests -t . -v
   ```

3. 提交：git add -A && git commit -m "chore(vendor): 升级 citrus 到 x.y.z"

如果 citrus 新版本加了平台，插件这边还要在 _conf_schema.json 里补一段平台配置，
main.py 的 PLATFORMS 也要加一行。

## 为什么不用 pip 装

citrus 只有一个本地项目、没有发布到 PyPI；而且 AstrBot 容器里拷源码比装包更可靠。
vendor 进来以后插件是自包含的：一个 zip 丢进 WebUI 就能用。
