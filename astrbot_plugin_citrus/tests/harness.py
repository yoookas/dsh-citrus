"""测试用的最小 AstrBot 桩件 + 插件加载器。

这里不启动真正的 AstrBot，只把 main.py 依赖的那几个模块塞进 sys.modules，
这样在本机（或 CI）就能直接跑插件的全部逻辑。
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "astrbot_plugin_citrus"

_DATA_ROOT = Path(tempfile.mkdtemp(prefix="astrbot-test-data-"))


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


class FakeEvent:
    """够用的 AstrMessageEvent 替身。"""

    def __init__(self, message: str = "", sender: str = "10001",
                 umo: str = "aiocqhttp:GroupMessage:1") -> None:
        self.message_str = message
        self._sender = sender
        self.unified_msg_origin = umo

    def get_sender_id(self) -> str:
        return self._sender

    def get_message_str(self) -> str:
        return self.message_str

    def plain_result(self, text: str) -> dict:
        return {"plain": text}


class FakeRequest:
    """ProviderRequest 替身（只用到 system_prompt / prompt）。"""

    def __init__(self, prompt: str = "") -> None:
        self.prompt = prompt
        self.system_prompt = "基础系统提示词"


def install_astrbot_stubs() -> None:
    if "astrbot" in sys.modules and getattr(sys.modules["astrbot"], "_stub", False):
        return

    astrbot = _module("astrbot")
    astrbot._stub = True
    api = _module("astrbot.api")
    event_mod = _module("astrbot.api.event")
    star_mod = _module("astrbot.api.star")
    core = _module("astrbot.core")
    utils = _module("astrbot.core.utils")
    path_mod = _module("astrbot.core.utils.astrbot_path")

    class AstrBotConfig(dict):
        """真实 AstrBotConfig 也是 dict 子类，够用。"""

    class _Filter:
        @staticmethod
        def command(*names, **kwargs):
            def decorator(func):
                return func
            return decorator

        @staticmethod
        def llm_tool(*args, **kwargs):
            def decorator(func):
                return func
            return decorator

        @staticmethod
        def on_llm_request(*args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class Star:
        def __init__(self, context=None, config=None):
            self.context = context
            self.config = config
            self.logger = logging.getLogger("astrbot.stub")

    class Context:
        def __init__(self):
            self.provider = None

        def get_using_provider(self, *args, **kwargs):
            return self.provider

    api.AstrBotConfig = AstrBotConfig
    api.logger = logging.getLogger("astrbot.stub")
    event_mod.AstrMessageEvent = FakeEvent
    event_mod.filter = _Filter()
    star_mod.Star = Star
    star_mod.Context = Context
    path_mod.get_astrbot_plugin_data_path = lambda: str(_DATA_ROOT / "plugin_data")

    astrbot.api = api
    astrbot.core = core
    api.event = event_mod
    api.star = star_mod
    core.utils = utils
    utils.astrbot_path = path_mod


def load_main():
    """把插件 main.py 当作包里的模块导入（相对导入才能工作）。"""
    install_astrbot_stubs()
    if PACKAGE_NAME in sys.modules:
        return sys.modules[PACKAGE_NAME].main

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PACKAGE_NAME] = package

    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME + ".main", PLUGIN_DIR / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME + ".main"] = module
    package.main = module
    spec.loader.exec_module(module)
    return module


def make_config(**overrides) -> dict:
    config = {
        "zhihu": {
            "enabled": True,
            "cookie": "curl 'https://www.zhihu.com/' -H 'cookie: z_c0=demo-token; d_c0=demo'",
            "cookie_file": "",
        },
        "default_platform": "zhihu",
        "access_mode": "whitelist",
        "allowed_users": ["10001"],
        "auto_hint": True,
        "command_use_llm": False,
        "hot_items": 10,
        "search_items": 8,
        "comment_items": 30,
        "content_chars": 1500,
        "comment_chars": 200,
        "excerpt_chars": 120,
        "related_answers": 3,
        "related_chars": 600,
        "pace_gap_ms": 0,
        "pace_jitter_ms": 0,
        "http_timeout_ms": 20000,
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config
