"""把 astrbot_plugin_citrus 打成 AstrBot WebUI 能直接上传的 zip。

用法：

    python scripts/build_zip.py            # 版本号从 metadata.yaml 读
    python scripts/build_zip.py 26.11.01   # 指定版本号

产物：

    dist/astrbot_plugin_citrus_<版本>.zip
    dist/astrbot_plugin_citrus_<版本>.zip.sha256

zip 里只有一个顶层目录 astrbot_plugin_citrus/，AstrBot 上传后就是这么解开的。
tests/ 和 __pycache__ 不会进包（用户不需要，体积也小）。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "astrbot_plugin_citrus"
DIST_DIR = ROOT / "dist"

SKIP_DIRS = {"tests", "__pycache__", ".git", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def read_version() -> str:
    text = (PLUGIN_DIR / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)", text)
    if not match:
        raise SystemExit("metadata.yaml 里没有 version")
    return match.group(1)


def iter_files(base: pathlib.Path):
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        yield path


def build(version: str) -> pathlib.Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = DIST_DIR / ("astrbot_plugin_citrus_%s.zip" % version)
    if target.exists():
        target.unlink()

    files = list(iter_files(PLUGIN_DIR))
    if not files:
        raise SystemExit("插件目录是空的，打包中止")

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            arcname = pathlib.Path("astrbot_plugin_citrus") / path.relative_to(PLUGIN_DIR)
            archive.write(path, arcname.as_posix())

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text("%s  %s\n" % (digest, target.name), encoding="utf-8")

    print("打包完成：%s（%d 个文件，%.1f KB）" % (
        target.relative_to(ROOT), len(files), target.stat().st_size / 1024))
    print("sha256：%s" % digest)
    return target


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else read_version()
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", version):
        print("警告：版本号 %r 不是 YY.MM.TT 格式" % version, file=sys.stderr)
    build(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
