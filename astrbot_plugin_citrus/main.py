"""柑橘 · 知乎内容插件（AstrBot）。

它只做一件事：把 citrus 的知乎读接口接到 AstrBot 上，让机器人能真的去知乎拿
热榜、问题、回答、评论，而不是靠模型记忆编。

触发方式有两种：

* 大模型自动调用：注册了 zhihu_hot / zhihu_search / zhihu_read / zhihu_comments
  四个 function calling 工具；
* 确定性指令：/知乎热榜、/知乎搜、/知乎看、/知乎评论、/知乎状态。

Cookie 只从插件配置或文件读，永远不打印、不回显。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .bridge import CitrusBridge, CitrusError, friendly_error, load_cookie_from_file
from .render import render_comments, render_hot, render_item, render_search

try:  # AstrBot 4.x 都有，但不同小版本的导出位置略有差异
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
except Exception:  # pragma: no cover - 兜底：相对当前工作目录

    def get_astrbot_plugin_data_path() -> str:
        return os.path.join(os.getcwd(), "data", "plugin_data")


PLUGIN_NAME = "astrbot_plugin_citrus"
PLATFORMS = ("zhihu",)
PLATFORM_NAMES = {"zhihu": "知乎"}

HINT_TEXT = (
    "这条消息可能涉及知乎内容。如果你需要知乎热榜、问题、回答或评论的真实数据，"
    "请调用 zhihu_hot / zhihu_search / zhihu_read / zhihu_comments 工具获取，"
    "不要凭记忆编造知乎上的内容和数据；引用时附上工具返回的链接。"
)

DEFAULT_SUMMARY_PROMPT = (
    "你是知乎内容助理。下面是刚刚从知乎抓到的真实数据，请据此回答用户的问题："
    "先用一句话给结论，再分点列出关键信息（主要观点、数据、争议点），"
    "最后附上你引用的知乎链接。不要编造数据里没有的内容；数据不足就直接说明。"
)

HELP_TEXT = (
    "柑橘 · 知乎插件\n"
    "指令：\n"
    "  /知乎热榜 [条数]        看知乎实时热榜\n"
    "  /知乎搜 <关键词>        搜索知乎问题/回答/文章\n"
    "  /知乎看 <链接或ID>      读问题或回答正文（问题会带高赞回答）\n"
    "  /知乎评论 <链接或ID> [条数]  读评论\n"
    "  /知乎状态               看 Cookie 与限速配置\n"
    "  /知乎帮助               显示这份说明\n"
    "也可以直接问：「知乎热榜有什么」「这个知乎问题大家怎么看」，模型会自动调用工具。"
)


def _clamp(value: Any, default: int, low: int, high: int) -> int:
    """把配置/模型给的值收敛到合法区间，任何脏数据都退回默认值。"""
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y"):
        return True
    if text in ("0", "false", "no", "off", "n"):
        return False
    return default


class CitrusPlugin(Star):
    """知乎热榜 / 问答 / 评论采集（底层是 citrus）。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config: Any = config if config is not None else {}
        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._bridge: CitrusBridge | None = None
        self._applied: dict[str, str] = {}
        self._cfg_cache: dict[str, Any] | None = None
        self._cfg_mtime: float | None = None
        self._ready = asyncio.Lock()

        logger.info("[citrus] 插件已加载，数据目录：%s", self.data_dir)

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def _cfg(self) -> dict[str, Any]:
        """读配置；文件变了就重新读（WebUI 保存配置后不用重载插件）。"""
        cfg: dict[str, Any] = {}
        if isinstance(self.config, dict):
            cfg = dict(self.config)
        path = getattr(self.config, "config_path", None)
        if path:
            try:
                mtime = os.path.getmtime(path)
                if self._cfg_mtime != mtime:
                    with open(path, encoding="utf-8-sig") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        self._cfg_cache = loaded
                        self._cfg_mtime = mtime
            except (OSError, ValueError):
                pass
        if self._cfg_cache is not None:
            merged = dict(cfg)
            merged.update(self._cfg_cache)
            return merged
        return cfg

    def _section(self, cfg: dict[str, Any], platform: str) -> dict[str, Any]:
        raw = cfg.get(platform)
        return raw if isinstance(raw, dict) else {}

    def _platform(self) -> str:
        name = str(self._cfg().get("default_platform") or "zhihu").strip().lower()
        return name if name in PLATFORMS else "zhihu"

    def _num(self, key: str, default: int, low: int = 1, high: int = 100000) -> int:
        return _clamp(self._cfg().get(key, default), default, low, high)

    # ------------------------------------------------------------------
    # 桥接层
    # ------------------------------------------------------------------

    async def _ensure_bridge(self) -> CitrusBridge:
        """按需创建 citrus 桥，并把配置里的 Cookie 同步进去。"""
        async with self._ready:
            cfg = self._cfg()
            if self._bridge is None:
                self._bridge = CitrusBridge(
                    home=self.data_dir / "citrus_home",
                    logger=getattr(self, "logger", logger),
                    gap_seconds=_clamp(cfg.get("pace_gap_ms", 350), 350, 0, 10000) / 1000.0,
                    jitter_seconds=_clamp(cfg.get("pace_jitter_ms", 250), 250, 0, 10000) / 1000.0,
                    timeout_seconds=_clamp(cfg.get("http_timeout_ms", 20000), 20000, 1000, 120000) / 1000.0,
                )
            bridge = self._bridge

            for platform in PLATFORMS:
                section = self._section(cfg, platform)
                enabled = _as_bool(section.get("enabled", True), True)
                raw = str(section.get("cookie") or "").strip()
                if not raw:
                    file_path = str(section.get("cookie_file") or "").strip()
                    if file_path:
                        try:
                            raw = load_cookie_from_file(file_path)
                        except OSError as exc:
                            logger.warning("[citrus] 读取 Cookie 文件失败：%s", exc)
                if not enabled or not raw:
                    if platform in self._applied:
                        bridge.clear_cookie(platform)
                        self._applied.pop(platform, None)
                    continue
                if self._applied.get(platform) == raw:
                    continue
                try:
                    info = bridge.set_cookie(platform, raw)
                except CitrusError as exc:
                    logger.warning(
                        "[citrus] %s 的 Cookie 无法使用：%s",
                        PLATFORM_NAMES.get(platform, platform),
                        friendly_error(exc),
                    )
                    # 配置里写的就是这份，用不了就明确失效，别偷偷留着一份旧的
                    self._applied.pop(platform, None)
                    bridge.clear_cookie(platform)
                    continue
                self._applied[platform] = raw
                logger.info(
                    "[citrus] %s Cookie 已载入（%s，%d 项，登录态：%s）",
                    PLATFORM_NAMES.get(platform, platform),
                    info["fingerprint"],
                    info["cookie_count"],
                    "有" if info["has_login"] else "缺",
                )
                if not info["has_login"]:
                    logger.warning(
                        "[citrus] 这份 Cookie 里没有登录态（缺少 z_c0），大概率会被上游判成未登录。"
                    )
            return bridge

    async def _call(self, capability: str, **kwargs: Any) -> Any:
        bridge = await self._ensure_bridge()
        return await bridge.call(self._platform(), capability, **kwargs)

    def _cookie_configured(self) -> bool:
        section = self._section(self._cfg(), self._platform())
        return bool(
            str(section.get("cookie") or "").strip()
            or str(section.get("cookie_file") or "").strip()
        )

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------

    def _allowed(self, event: AstrMessageEvent) -> bool:
        cfg = self._cfg()
        mode = str(cfg.get("access_mode") or "whitelist").strip().lower()
        if mode != "whitelist":
            return True
        rows = cfg.get("allowed_users") or []
        if isinstance(rows, str):
            rows = rows.replace("，", ",").split(",")
        allowed = {str(item).strip() for item in rows if str(item).strip()}
        sender = str(event.get_sender_id() or "").strip()
        return bool(sender) and sender in allowed

    def _deny_text(self, event: AstrMessageEvent) -> str:
        sender = str(event.get_sender_id() or "未知")
        return (
            "你不在知乎插件允许的用户名单里。\n"
            "你的用户 ID 是 " + sender + "，把它加到插件配置的「允许的用户 ID」里就能用了。"
        )

    # ------------------------------------------------------------------
    # 指令参数
    # ------------------------------------------------------------------

    @staticmethod
    def _command_args(event: AstrMessageEvent, *names: str) -> str:
        """从原始消息里取出指令后面的那截文本（不依赖 AstrBot 的参数解析）。"""
        text = str(event.get_message_str() or "").strip()
        while text and text[0] in "/!！／.。、~～#":
            text = text[1:].lstrip()
        for name in names:
            if text.startswith(name):
                return text[len(name):].strip()
        parts = text.split(None, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    # ------------------------------------------------------------------
    # 大模型工具（function calling）
    # ------------------------------------------------------------------

    @filter.llm_tool(name="zhihu_hot")
    async def zhihu_hot(self, event: AstrMessageEvent, limit: int = 10) -> str:
        """获取知乎实时热榜。当用户问「知乎热榜」「今天知乎在讨论什么」「最近有什么热门话题」时调用，返回标题、热度、摘要和链接。

        Args:
            limit(number): 返回条数，1 到 30，默认 10
        """
        if not self._allowed(event):
            return "当前用户没有使用知乎插件的权限。"
        try:
            page = await self._call("hot", limit=_clamp(limit, 10, 1, 30))
        except Exception as exc:  # noqa: BLE001 - 任何失败都要变成模型能读懂的一句话
            return friendly_error(exc)
        return render_hot(
            page,
            max_items=self._num("hot_items", 10, 1, 30),
            excerpt_chars=self._num("excerpt_chars", 120, 20, 600),
        )

    @filter.llm_tool(name="zhihu_search")
    async def zhihu_search(self, event: AstrMessageEvent, query: str, limit: int = 8) -> str:
        """在知乎里搜索问题、回答、文章和用户。当用户对某个话题不熟悉、或想找特定内容时调用。

        Args:
            query(string): 搜索关键词，例如「大模型」或「AI 取代程序员」
            limit(number): 返回条数，1 到 20，默认 8
        """
        if not self._allowed(event):
            return "当前用户没有使用知乎插件的权限。"
        keyword = str(query or "").strip()
        if not keyword:
            return "没有给搜索关键词。"
        try:
            page = await self._call("search", query=keyword, limit=_clamp(limit, 8, 1, 20))
        except Exception as exc:  # noqa: BLE001
            return friendly_error(exc)
        return render_search(
            page,
            query=keyword,
            max_items=self._num("search_items", 8, 1, 20),
            excerpt_chars=self._num("excerpt_chars", 120, 20, 600),
        )

    @filter.llm_tool(name="zhihu_read")
    async def zhihu_read(self, event: AstrMessageEvent, ref: str, with_answers: bool = True) -> str:
        """读取一条知乎内容的正文：可以传问题链接、回答链接、文章链接，或纯数字 ID。传问题时默认会带上几条高赞回答。

        Args:
            ref(string): 知乎链接（question/answer/article）或内容 ID
            with_answers(boolean): 读问题时是否附带同问题下的高赞回答，默认 true
        """
        if not self._allowed(event):
            return "当前用户没有使用知乎插件的权限。"
        target = str(ref or "").strip()
        if not target:
            return "没有给知乎链接或 ID。"
        try:
            item = await self._call(
                "item",
                ref=target,
                related=bool(with_answers),
                content_limit=self._num("content_chars", 1500, 200, 16000),
            )
        except Exception as exc:  # noqa: BLE001
            return friendly_error(exc)
        return render_item(
            item,
            content_chars=self._num("content_chars", 1500, 200, 16000),
            related=self._num("related_answers", 3, 0, 5),
            related_chars=self._num("related_chars", 600, 100, 3000),
        )

    @filter.llm_tool(name="zhihu_comments")
    async def zhihu_comments(self, event: AstrMessageEvent, ref: str, limit: int = 20, sort: str = "hot") -> str:
        """读取某条知乎问题或回答下面的评论。当用户想知道「评论区怎么看」「大家有什么不同意见」时调用。

        Args:
            ref(string): 知乎链接（question/answer/article）或内容 ID
            limit(number): 返回评论条数，1 到 100，默认 20
            sort(string): hot 按热度，new 按时间倒序，默认 hot
        """
        if not self._allowed(event):
            return "当前用户没有使用知乎插件的权限。"
        target = str(ref or "").strip()
        if not target:
            return "没有给知乎链接或 ID。"
        order = "new" if str(sort or "").strip().lower() in ("new", "latest", "ts") else "hot"
        try:
            page = await self._call(
                "comments",
                ref=target,
                limit=_clamp(limit, 20, 1, 100),
                sort=order,
            )
        except Exception as exc:  # noqa: BLE001
            return friendly_error(exc)
        return render_comments(
            page,
            max_items=self._num("comment_items", 30, 1, 100),
            content_chars=self._num("comment_chars", 200, 40, 800),
        )

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------

    def _finalize(self, text: str) -> str:
        """命令回复的长度上限（QQ 之类的平台单条消息有上限）。"""
        limit = self._num("reply_max_chars", 1800, 200, 8000)
        body = str(text or "").strip()
        if len(body) <= limit:
            return body
        return body[:limit].rstrip() + "\n…（内容过长已截断）"

    async def _answer(self, event: AstrMessageEvent, question: str, data: str) -> str:
        """命令模式下：默认让模型把抓到的数据总结成人话，失败就退回原文。"""
        cfg = self._cfg()
        if not _as_bool(cfg.get("command_use_llm", True), True):
            return data
        provider = None
        try:
            try:
                provider = self.context.get_using_provider(event.unified_msg_origin)
            except TypeError:
                provider = self.context.get_using_provider()
        except Exception:  # noqa: BLE001
            provider = None
        if provider is None:
            return data
        prompt = "用户想要：" + question + "\n\n抓取到的知乎数据：\n" + data
        system_prompt = str(cfg.get("summary_prompt") or DEFAULT_SUMMARY_PROMPT)
        try:
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt,
                contexts=[],
            )
            text = str(getattr(response, "completion_text", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[citrus] 模型总结失败，退回原始数据：%s", exc)
            return data
        return text or data

    @filter.command("知乎热榜", alias={"zhihu_hot"})
    async def cmd_hot(self, event: AstrMessageEvent):
        """查看知乎热榜。用法：/知乎热榜 [条数]"""
        if not self._allowed(event):
            yield event.plain_result(self._deny_text(event))
            return
        args = self._command_args(event, "知乎热榜", "zhihu_hot")
        limit = _clamp(args.split()[0] if args else "", self._num("hot_items", 10, 1, 30), 1, 30)
        try:
            page = await self._call("hot", limit=limit)
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(friendly_error(exc))
            return
        data = render_hot(page, max_items=limit, excerpt_chars=self._num("excerpt_chars", 120, 20, 600))
        reply = await self._answer(event, "看一下知乎热榜前 " + str(limit) + " 条，说说今天大家在讨论什么", data)
        yield event.plain_result(self._finalize(reply))

    @filter.command("知乎搜", alias={"知乎搜索", "zhihu_search"})
    async def cmd_search(self, event: AstrMessageEvent):
        """搜索知乎内容。用法：/知乎搜 <关键词>"""
        if not self._allowed(event):
            yield event.plain_result(self._deny_text(event))
            return
        keyword = self._command_args(event, "知乎搜索", "知乎搜", "zhihu_search")
        if not keyword:
            yield event.plain_result("用法：/知乎搜 <关键词>，例如 /知乎搜 大模型")
            return
        try:
            page = await self._call("search", query=keyword, limit=self._num("search_items", 8, 1, 20))
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(friendly_error(exc))
            return
        data = render_search(
            page,
            query=keyword,
            max_items=self._num("search_items", 8, 1, 20),
            excerpt_chars=self._num("excerpt_chars", 120, 20, 600),
        )
        reply = await self._answer(event, "在知乎搜索「" + keyword + "」并总结最有价值的几条", data)
        yield event.plain_result(self._finalize(reply))

    @filter.command("知乎看", alias={"zhihu_read"})
    async def cmd_read(self, event: AstrMessageEvent):
        """读知乎问题或回答正文。用法：/知乎看 <链接或ID>"""
        if not self._allowed(event):
            yield event.plain_result(self._deny_text(event))
            return
        target = self._command_args(event, "知乎看", "zhihu_read")
        if not target:
            yield event.plain_result("用法：/知乎看 <知乎链接或内容 ID>，例如 /知乎看 https://www.zhihu.com/question/123")
            return
        try:
            item = await self._call(
                "item",
                ref=target,
                related=True,
                content_limit=self._num("content_chars", 1500, 200, 16000),
            )
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(friendly_error(exc))
            return
        data = render_item(
            item,
            content_chars=self._num("content_chars", 1500, 200, 16000),
            related=self._num("related_answers", 3, 0, 5),
            related_chars=self._num("related_chars", 600, 100, 3000),
        )
        reply = await self._answer(event, "读一下这条知乎内容，说它讲了什么、有哪些主要观点", data)
        yield event.plain_result(self._finalize(reply))

    @filter.command("知乎评论", alias={"zhihu_comments"})
    async def cmd_comments(self, event: AstrMessageEvent):
        """读知乎评论。用法：/知乎评论 <链接或ID> [条数]"""
        if not self._allowed(event):
            yield event.plain_result(self._deny_text(event))
            return
        args = self._command_args(event, "知乎评论", "zhihu_comments")
        if not args:
            yield event.plain_result("用法：/知乎评论 <知乎链接或内容 ID> [条数]，例如 /知乎评论 https://www.zhihu.com/question/123 20")
            return
        parts = args.split()
        target = parts[0]
        limit = _clamp(parts[1] if len(parts) > 1 else "", 20, 1, 100)
        try:
            page = await self._call("comments", ref=target, limit=limit, sort="hot")
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(friendly_error(exc))
            return
        data = render_comments(
            page,
            max_items=self._num("comment_items", 30, 1, 100),
            content_chars=self._num("comment_chars", 200, 40, 800),
        )
        reply = await self._answer(event, "看看这条知乎内容下面的评论，总结大家在争论什么、有哪些代表性观点", data)
        yield event.plain_result(self._finalize(reply))

    @filter.command("知乎状态", alias={"zhihu_status"})
    async def cmd_status(self, event: AstrMessageEvent):
        """查看知乎 Cookie 与限速状态。"""
        if not self._allowed(event):
            yield event.plain_result(self._deny_text(event))
            return
        cfg = self._cfg()
        platform = self._platform()
        lines = ["柑橘 · 知乎插件状态"]
        lines.append("当前平台：" + PLATFORM_NAMES.get(platform, platform))
        lines.append("Cookie：" + ("已配置" if self._cookie_configured() else "未配置"))
        if self._cookie_configured():
            try:
                bridge = await self._ensure_bridge()
                hint = bridge.cookie_hint(platform)
                if hint:
                    lines.append("Cookie 指纹：" + hint)
            except Exception:  # noqa: BLE001
                pass
        lines.append(
            "请求节奏：间隔 "
            + str(_clamp(cfg.get("pace_gap_ms", 350), 350, 0, 10000))
            + "ms + 抖动 "
            + str(_clamp(cfg.get("pace_jitter_ms", 250), 250, 0, 10000))
            + "ms"
        )
        lines.append("访问模式：" + ("白名单" if str(cfg.get("access_mode") or "whitelist") == "whitelist" else "所有人"))
        try:
            await self._call("account")
            lines.append("上游连通：正常")
        except Exception as exc:  # noqa: BLE001
            lines.append("上游连通：异常 -> " + friendly_error(exc))
        yield event.plain_result("\n".join(lines))

    @filter.command("知乎帮助", alias={"zhihu_help", "知乎"})
    async def cmd_help(self, event: AstrMessageEvent):
        """查看知乎插件用法。"""
        yield event.plain_result(HELP_TEXT)

    # ------------------------------------------------------------------
    # 钩子
    # ------------------------------------------------------------------

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: Any) -> None:
        """消息里提到知乎时，提醒模型去调工具，而不是凭记忆编。"""
        try:
            if not _as_bool(self._cfg().get("auto_hint", True), True):
                return
            if not self._allowed(event) or not self._cookie_configured():
                return
            text = str(getattr(event, "message_str", "") or "")
            prompt = str(getattr(req, "prompt", "") or "")
            haystack = text + " " + prompt
            if not any(word in haystack for word in ("知乎", "zhihu", "Zhihu", "ZHIHU")):
                return
            current = getattr(req, "system_prompt", "") or ""
            req.system_prompt = (current + "\n\n" + HINT_TEXT).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[citrus] 注入提示词失败：%s", exc)

    async def terminate(self) -> None:
        """插件被卸载/停用。"""
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None
            self._applied.clear()
        logger.info("[citrus] 插件已卸载")
