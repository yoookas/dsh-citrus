"""账号库 —— 每个平台一份（或多份）Cookie，落在本地一个 JSON 文件里。

设计口径：

* 一个平台可以有多个账号（默认标签 default），请求里用 ?account= 或
  X-Citrus-Account 选；agent 想并行用两个号也不会互相踩；
* 文件里存的是明文 Cookie —— 这是本机服务，权限压到 0600，且接口永远只回显指纹；
* 写盘用 tmp + os.replace，进程被杀不会留下半个文件。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any

from .cookies import mask_cookie

DEFAULT_LABEL = "default"
STORE_VERSION = 1


def default_home() -> Path:
    override = os.environ.get("CITRUS_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".citrus"


class AccountStore:
    """按平台 + 标签存放的 Cookie 仓库。"""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self.home / "accounts.json"

    # ---- 读写 -------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (IOError, OSError):
                return {"version": STORE_VERSION, "platforms": {}}
            except ValueError:
                return {"version": STORE_VERSION, "platforms": {}}
            if not isinstance(data, dict):
                return {"version": STORE_VERSION, "platforms": {}}
            platforms = data.get("platforms")
            if not isinstance(platforms, dict):
                data["platforms"] = {}
            data.setdefault("version", STORE_VERSION)
            return data

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.home.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except (OSError, ValueError):
                    pass
            os.replace(tmp_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass  # Windows 上基本无效，尽力而为

    # ---- 增删查 -----------------------------------------------------

    def get(self, platform: str, label: str = DEFAULT_LABEL) -> dict[str, Any] | None:
        entry = self._read()["platforms"].get(platform, {}).get(label)
        if not isinstance(entry, dict) or not entry.get("cookie"):
            return None
        return dict(entry)

    def set(self, platform: str, entry: dict[str, Any], label: str = DEFAULT_LABEL) -> dict[str, Any]:
        data = self._read()
        bucket = data["platforms"].setdefault(platform, {})
        previous = bucket.get(label) or {}
        merged = dict(previous)
        merged.update(entry)
        bucket[label] = merged
        self._write(data)
        return dict(merged)

    def delete(self, platform: str, label: str | None = None) -> bool:
        data = self._read()
        platforms = data["platforms"]
        if platform not in platforms:
            return False
        if label is None:
            removed = bool(platforms.pop(platform))
        else:
            removed = bool(platforms[platform].pop(label, None))
            if not platforms[platform]:
                platforms.pop(platform)
        if removed:
            self._write(data)
        return removed

    def labels(self, platform: str) -> list[str]:
        return sorted(self._read()["platforms"].get(platform, {}).keys())

    def platforms(self) -> list[str]:
        return sorted(self._read()["platforms"].keys())

    def has(self, platform: str, label: str = DEFAULT_LABEL) -> bool:
        return self.get(platform, label) is not None

    # ---- 对外展示（永不回显 Cookie 本体） ---------------------------

    def describe(self, platform: str, label: str = DEFAULT_LABEL) -> dict[str, Any]:
        entry = self.get(platform, label)
        if entry is None:
            return {"platform": platform, "label": label, "configured": False}
        return {
            "platform": platform,
            "label": label,
            "configured": True,
            "cookie_hint": mask_cookie(entry.get("cookie", "")),
            "cookie_count": len(entry.get("cookie", "").split(";")) if entry.get("cookie") else 0,
            "saved_at": entry.get("saved_at"),
            "source": entry.get("source"),
            "profile": entry.get("profile") or None,
        }

    def describe_all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for platform in self.platforms():
            for label in self.labels(platform):
                out.append(self.describe(platform, label))
        return out

    def update_profile(self, platform: str, profile: dict[str, Any], label: str = DEFAULT_LABEL) -> None:
        entry = self.get(platform, label)
        if entry is None:
            return
        entry["profile"] = profile
        self.set(platform, entry, label)
