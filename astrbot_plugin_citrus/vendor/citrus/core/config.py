"""配置 —— 一切都能用环境变量覆盖，命令行参数优先级最高。"""

import os
from pathlib import Path
from typing import Any

from .accounts import default_home

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    items = [part.strip() for part in raw.replace(";", ",").split(",")]
    return [item for item in items if item] or list(default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """服务配置。平台专属配置走 platform_options()。"""

    def __init__(self, *,
                 host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT,
                 api_token: str = "",
                 home: Path | None = None,
                 cors_origin: str = "",
                 log_level: str = "info",
                 max_body_bytes: int = 65536,
                 allow_raw: bool = False,
                 gap_seconds: float = 0.35,
                 jitter_seconds: float = 0.25,
                 burst_every: int = 15,
                 burst_min_seconds: float = 1.2,
                 burst_max_seconds: float = 3.0,
                 timeout: float = 20.0,
                 max_retries: int = 2,
                 default_account: str = "default",
                 rotation: str = "failover",
                 rotation_triggers: tuple[str, ...] = ("not_logged_in",),
                 rotation_max: int = 3) -> None:
        self.host = host
        self.port = int(port)
        self.api_token = api_token or ""
        self.home = Path(home).expanduser() if home else default_home()
        self.cors_origin = cors_origin or ""
        self.log_level = (log_level or "info").lower()
        self.max_body_bytes = int(max_body_bytes)
        self.allow_raw = bool(allow_raw)
        self.gap_seconds = float(gap_seconds)
        self.jitter_seconds = float(jitter_seconds)
        self.burst_every = int(burst_every)
        self.burst_min_seconds = float(burst_min_seconds)
        self.burst_max_seconds = float(burst_max_seconds)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.default_account = default_account or "default"
        #: off = 只用一个号；failover = 当前号不可用时换下一个（不做随机轮流）
        self.rotation = (rotation or "failover").strip().lower()
        if self.rotation not in ("off", "failover"):
            self.rotation = "failover"
        self.rotation_triggers = tuple(rotation_triggers) or ("not_logged_in",)
        self.rotation_max = max(1, int(rotation_max))

    @classmethod
    def from_env(cls, **overrides: Any) -> "Config":
        config = cls(
            host=_env_str("CITRUS_HOST", DEFAULT_HOST) or DEFAULT_HOST,
            port=_env_int("CITRUS_PORT", DEFAULT_PORT),
            api_token=_env_str("CITRUS_API_TOKEN"),
            home=Path(_env_str("CITRUS_HOME")) if _env_str("CITRUS_HOME") else None,
            cors_origin=_env_str("CITRUS_CORS_ORIGIN"),
            log_level=_env_str("CITRUS_LOG_LEVEL", "info"),
            max_body_bytes=_env_int("CITRUS_MAX_BODY_BYTES", 65536),
            allow_raw=_env_bool("CITRUS_ALLOW_RAW", False),
            gap_seconds=_env_float("CITRUS_GAP_MS", 350.0) / 1000.0,
            jitter_seconds=_env_float("CITRUS_JITTER_MS", 250.0) / 1000.0,
            burst_every=_env_int("CITRUS_BURST_EVERY", 15),
            burst_min_seconds=_env_float("CITRUS_BURST_MIN_MS", 1200.0) / 1000.0,
            burst_max_seconds=_env_float("CITRUS_BURST_MAX_MS", 3000.0) / 1000.0,
            timeout=_env_float("CITRUS_TIMEOUT_MS", 20000.0) / 1000.0,
            max_retries=_env_int("CITRUS_MAX_RETRIES", 2),
            default_account=_env_str("CITRUS_ACCOUNT", "default") or "default",
            rotation=_env_str("CITRUS_ROTATION", "failover"),
            rotation_triggers=_env_list("CITRUS_ROTATION_TRIGGERS", ["not_logged_in"]),
            rotation_max=_env_int("CITRUS_ROTATION_MAX", 3),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        return config

    def platform_options(self, platform: str) -> dict[str, Any]:
        """平台专属覆盖：CITRUS_ZHIHU_BASE_URL / CITRUS_ZHIHU_GAP_MS / ..."""
        prefix = "CITRUS_" + platform.upper() + "_"
        options: dict[str, Any] = {
            "gap_seconds": _env_float(prefix + "GAP_MS", self.gap_seconds * 1000.0) / 1000.0,
            "jitter_seconds": _env_float(
                prefix + "JITTER_MS", self.jitter_seconds * 1000.0) / 1000.0,
            "burst_every": _env_int(prefix + "BURST_EVERY", self.burst_every),
            "burst_min_seconds": _env_float(
                prefix + "BURST_MIN_MS", self.burst_min_seconds * 1000.0) / 1000.0,
            "burst_max_seconds": _env_float(
                prefix + "BURST_MAX_MS", self.burst_max_seconds * 1000.0) / 1000.0,
            "timeout": _env_float(prefix + "TIMEOUT_MS", self.timeout * 1000.0) / 1000.0,
            "max_retries": _env_int(prefix + "RETRIES", self.max_retries),
        }
        base_url = _env_str(prefix + "BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return options

    def public_dict(self) -> dict[str, Any]:
        """能安全丢给客户端的配置（没有 token、没有 cookie）。"""
        return {
            "host": self.host,
            "port": self.port,
            "home": str(self.home),
            "auth_required": bool(self.api_token),
            "allow_raw": bool(self.allow_raw),
            "gap_seconds": self.gap_seconds,
            "jitter_seconds": self.jitter_seconds,
            "burst_every": self.burst_every,
            "timeout_seconds": self.timeout,
            "max_retries": self.max_retries,
            "rotation": self.rotation,
            "rotation_triggers": list(self.rotation_triggers),
            "rotation_max": self.rotation_max,
        }
