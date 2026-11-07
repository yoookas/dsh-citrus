"""插件的离线测试：用假知乎（本地 HTTP 服务）跑通全部工具与指令。

跑法（在插件目录下）：

    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import harness  # noqa: E402
from harness import FakeEvent, FakeRequest, make_config  # noqa: E402
from support.mock_upstream import MockUpstream, install_default_routes  # noqa: E402


class PluginTestBase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = harness.load_main()

    def setUp(self) -> None:
        self.upstream = MockUpstream().start()
        install_default_routes(self.upstream)
        os.environ["CITRUS_ZHIHU_BASE_URL"] = self.upstream.url
        os.environ["CITRUS_ZHIHU_GAP_MS"] = "0"
        os.environ["CITRUS_ZHIHU_JITTER_MS"] = "0"
        self.plugin = self.main.CitrusPlugin(context=None, config=make_config())

    def tearDown(self) -> None:
        bridge = getattr(self.plugin, "_bridge", None)
        if bridge is not None:
            bridge.close()
        self.upstream.stop()
        os.environ.pop("CITRUS_ZHIHU_BASE_URL", None)

    async def collect(self, async_gen) -> str:
        chunks = []
        async for item in async_gen:
            chunks.append(str(item.get("plain", item)))
        return "\n".join(chunks)


class TestTools(PluginTestBase):
    async def test_hot_tool(self) -> None:
        text = await self.plugin.zhihu_hot(FakeEvent("知乎热榜"), 3)
        self.assertIn("知乎热榜", text)
        self.assertIn("如何评价最近的大模型竞赛？", text)
        self.assertIn("https://www.zhihu.com/question/123456", text)

    async def test_search_tool(self) -> None:
        text = await self.plugin.zhihu_search(FakeEvent("搜一下"), "大模型", 5)
        self.assertIn("知乎搜索「大模型」", text)
        self.assertIn("这个问题值得读吗？", text)

    async def test_read_answer(self) -> None:
        text = await self.plugin.zhihu_read(FakeEvent("看看"), "answer:111", True)
        self.assertIn("【回答】", text)
        self.assertIn("张三", text)
        self.assertIn("这是正文第一段。", text)

    async def test_read_question_with_answers(self) -> None:
        text = await self.plugin.zhihu_read(FakeEvent("看看"), "question:222", True)
        self.assertIn("【问题】这个问题值得读吗？", text)
        self.assertIn("其他高赞回答", text)

    async def test_comments_tool(self) -> None:
        text = await self.plugin.zhihu_comments(FakeEvent("评论"), "answer:111", 20, "hot")
        self.assertIn("评论", text)
        self.assertIn("说得好。", text)

    async def test_cookie_never_leaks(self) -> None:
        text = await self.plugin.zhihu_hot(FakeEvent("知乎热榜"), 3)
        self.assertNotIn("demo-token", text)
        self.assertNotIn("z_c0", text)


class TestAccess(PluginTestBase):
    async def test_whitelist_denied(self) -> None:
        text = await self.plugin.zhihu_hot(FakeEvent("知乎热榜", sender="99999"), 3)
        self.assertIn("权限", text)

    async def test_whitelist_allows_all_in_open_mode(self) -> None:
        self.plugin.config = make_config(access_mode="all")
        text = await self.plugin.zhihu_hot(FakeEvent("知乎热榜", sender="99999"), 3)
        self.assertIn("知乎热榜", text)

    async def test_missing_cookie_message(self) -> None:
        self.plugin.config = make_config(zhihu_cookie="")
        self.plugin.config["zhihu"]["cookie"] = ""
        text = await self.plugin.zhihu_hot(FakeEvent("知乎热榜"), 3)
        self.assertIn("还没有配置知乎 Cookie", text)


class TestCommands(PluginTestBase):
    async def test_command_hot_with_count(self) -> None:
        event = FakeEvent("/知乎热榜 2")
        text = await self.collect(self.plugin.cmd_hot(event))
        self.assertIn("知乎热榜", text)

    async def test_command_search(self) -> None:
        text = await self.collect(self.plugin.cmd_search(FakeEvent("/知乎搜 大模型")))
        self.assertIn("知乎搜索「大模型」", text)

    async def test_command_read(self) -> None:
        text = await self.collect(self.plugin.cmd_read(FakeEvent("/知乎看 answer:111")))
        self.assertIn("【回答】", text)

    async def test_command_comments(self) -> None:
        text = await self.collect(self.plugin.cmd_comments(FakeEvent("/知乎评论 answer:111 5")))
        self.assertIn("评论", text)

    async def test_command_help(self) -> None:
        text = await self.collect(self.plugin.cmd_help(FakeEvent("/知乎帮助")))
        self.assertIn("/知乎热榜", text)

    async def test_command_status(self) -> None:
        text = await self.collect(self.plugin.cmd_status(FakeEvent("/知乎状态")))
        self.assertIn("Cookie：已配置", text)

    async def test_command_denied(self) -> None:
        text = await self.collect(self.plugin.cmd_hot(FakeEvent("/知乎热榜", sender="99999")))
        self.assertIn("不在知乎插件允许的用户名单里", text)


class TestHooks(PluginTestBase):
    async def test_hint_added_when_zhihu_mentioned(self) -> None:
        request = FakeRequest("帮我看看知乎热榜")
        await self.plugin.on_llm_request(FakeEvent("知乎热榜有什么"), request)
        self.assertIn("zhihu_hot", request.system_prompt)

    async def test_hint_skipped_for_unrelated_message(self) -> None:
        request = FakeRequest("今天天气怎么样")
        await self.plugin.on_llm_request(FakeEvent("今天天气怎么样"), request)
        self.assertNotIn("zhihu_hot", request.system_prompt)


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        self.main = harness.load_main()
        self.render = self.main.render_hot.__globals__  # 借用同名模块的命名空间取函数

    def test_compact_number(self) -> None:
        from importlib import import_module

        module = import_module("astrbot_plugin_citrus.render")
        self.assertEqual(module.compact_number(12345), "1.2万")
        self.assertEqual(module.compact_number(0), "")
        self.assertEqual(module.compact_number(880000), "88.0万")

    def test_error_translation(self) -> None:
        from citrus import CitrusError

        bridge = self.main.CitrusBridge
        message = self.main.friendly_error(CitrusError("challenge", "风控"))
        self.assertIn("风控", message)
        self.assertIn("验证", message)


if __name__ == "__main__":
    unittest.main()
