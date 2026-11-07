"""把插件 metadata.yaml 里的 version 改成指定值。

用法：python scripts/bump_version.py 26.11.01
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
METADATA = ROOT / "astrbot_plugin_citrus" / "metadata.yaml"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：python scripts/bump_version.py <YY.MM.TT>", file=sys.stderr)
        return 2
    version = argv[1].strip()
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", version):
        print("版本号 %r 不是 YY.MM.TT 格式" % version, file=sys.stderr)
        return 2

    text = METADATA.read_text(encoding="utf-8")
    updated, count = re.subn(r"(?m)^version:.*$", 'version: "%s"' % version, text)
    if count == 0:
        print("metadata.yaml 里没有 version 行", file=sys.stderr)
        return 1
    METADATA.write_text(updated, encoding="utf-8")
    print("metadata.yaml 版本 -> %s" % version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
