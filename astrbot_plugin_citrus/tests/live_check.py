"""真实链路的冒烟测试：用本机 ~/.citrus 里已有的 Cookie 打一次真知乎。

它不是单元测试（不叫 test_*，不会被 discover 跑到），只在你想确认
「cookie 能用 + 上游没变」时手动跑：

    python tests/live_check.py

只会发一个热榜请求。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402


def load_local_cookie() -> str:
    """从 citrus 的账号库里读一份已经配置好的知乎 Cookie。"""
    import os

    home = Path(os.environ.get("CITRUS_HOME") or (Path.home() / ".citrus"))
    path = home / "accounts.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    platform = (data.get("platforms") or {}).get("zhihu") or {}
    entry = platform.get("default") or next(iter(platform.values()), {})
    return str(entry.get("cookie") or "")


async def main() -> int:
    module = harness.load_main()
    cookie = load_local_cookie()
    if not cookie:
        print("没找到本机已配置的知乎 Cookie，跳过。")
        return 1
    plugin = module.CitrusPlugin(context=None, config=harness.make_config(zhihu={"cookie": cookie}))
    try:
        text = await plugin.zhihu_hot(harness.FakeEvent("知乎热榜"), 3)
        print(text)
        if "demo" in text or "z_c0" in text:
            print("!! 输出里出现了 Cookie 痕迹")
            return 2
    finally:
        if plugin._bridge is not None:
            plugin._bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
