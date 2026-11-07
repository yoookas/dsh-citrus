"""命令行入口：citrus serve / auth / accounts / verify / call / doctor。

不装 pip 包也能用：python -m citrus serve 就够了。
"""

import argparse
import json
import sys
from typing import Any

from . import __version__
from .context import CitrusApp
from .core.config import Config
from .errors import CitrusError


def _print_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _read_cookie_text(cookie: str, cookie_file: str) -> str:
    if cookie_file:
        with open(cookie_file, "r", encoding="utf-8") as handle:
            return handle.read()
    if cookie and cookie != "-":
        return cookie
    data = sys.stdin.read()
    if not data.strip():
        raise CitrusError("bad_request", "没有读到 Cookie。",
                          "用 --cookie、--cookie-file，或者把 Cookie 从标准输入喂进来。")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citrus",
        description="统一社交平台信息 API：只提供各平台 Cookie，agent 就能用一套形状读内容。",
    )
    parser.add_argument("--home", default="", help="数据目录（默认 ~/.citrus）")
    parser.add_argument("--version", action="version", version="citrus " + __version__)

    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default="", help="监听地址（默认 127.0.0.1）")
    serve.add_argument("--port", type=int, default=0, help="监听端口（默认 8787）")
    serve.add_argument("--token", default="", help="API token；设了就要求 Bearer 鉴权")
    serve.add_argument("--allow-raw", action="store_true", help="打开 raw 逃生口（默认关）")
    serve.add_argument("--cors", default="", help="允许的 CORS 来源，例如 * ")
    serve.add_argument("--log-level", default="", help="debug / info / warning / error")

    auth = sub.add_parser("auth", help="保存某个平台的 Cookie")
    auth.add_argument("platform")
    auth.add_argument("--cookie", default="", help="cURL / Cookie 头 / 裸 Cookie；- 表示读 stdin")
    auth.add_argument("--cookie-file", default="", help="从文件读 Cookie")
    auth.add_argument("--label", default="default", help="账号标签")
    auth.add_argument("--user-agent", default="", help="浏览器 UA（一般不用填）")

    sub.add_parser("accounts", help="列出已配置的账号")

    logout = sub.add_parser("logout", help="删除某个平台的 Cookie")
    logout.add_argument("platform")
    logout.add_argument("--label", default="", help="只删这个标签；不填删整个平台")

    verify = sub.add_parser("verify", help="体检：逐项报告哪条链路能走通")
    verify.add_argument("platform")
    verify.add_argument("--label", default="", help="账号标签")
    verify.add_argument("--all", action="store_true", help="把所有账号都体检一遍")

    call = sub.add_parser("call", help="不经服务，直接调一次适配器")
    call.add_argument("platform")
    call.add_argument("capability",
                      help="account / feed / hot / search / item / comments / user / user_content")
    call.add_argument("--ref", default="")
    call.add_argument("--kind", default="")
    call.add_argument("--id", default="")
    call.add_argument("--q", default="")
    call.add_argument("--source", default="")
    call.add_argument("--limit", type=int, default=0)
    call.add_argument("--page", type=int, default=0)
    call.add_argument("--sort", default="", help="comments: hot（默认）/ new")
    call.add_argument("--related", action="store_true")
    call.add_argument("--account", default="")

    sub.add_parser("doctor", help="看看本地环境、账号、平台清单")
    return parser


def _make_app(args: argparse.Namespace) -> CitrusApp:
    overrides: dict[str, Any] = {}
    if getattr(args, "home", ""):
        overrides["home"] = args.home
    config = Config.from_env(**overrides)
    return CitrusApp(config)


def _cmd_serve(args: argparse.Namespace, app: CitrusApp) -> int:
    import logging

    from .server import serve

    if args.host:
        app.config.host = args.host
    if args.port:
        app.config.port = args.port
    if args.token:
        app.config.api_token = args.token
    if args.allow_raw:
        app.config.allow_raw = True
    if args.cors:
        app.config.cors_origin = args.cors
    if args.log_level:
        app.config.log_level = args.log_level
    logging.basicConfig(
        level=getattr(logging, str(app.config.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    serve(app, app.config.host, app.config.port)
    return 0


def _cmd_auth(args: argparse.Namespace, app: CitrusApp) -> int:
    text = _read_cookie_text(args.cookie, args.cookie_file)
    described = app.set_credential(args.platform, text, label=args.label,
                                   user_agent=args.user_agent)
    _print_json({"ok": True, "account": described})
    return 0


def _cmd_accounts(args: argparse.Namespace, app: CitrusApp) -> int:
    _print_json({"ok": True, "home": str(app.accounts.home), "accounts": app.accounts.describe_all()})
    return 0


def _cmd_logout(args: argparse.Namespace, app: CitrusApp) -> int:
    removed = app.accounts.delete(args.platform, args.label or None)
    app.cache.clear()
    app.registry.invalidate(args.platform)
    _print_json({"ok": True, "platform": args.platform, "removed": removed})
    return 0


def _cmd_verify(args: argparse.Namespace, app: CitrusApp) -> int:
    if args.all:
        results = [app.adapter(args.platform, label=label).verify()
                   for label in app.account_labels(args.platform)]
        result = {
            "platform": args.platform,
            "count": len(results),
            "ok": bool(results) and all(row.get("ok") for row in results),
            "accounts": results,
        }
    else:
        result = app.adapter(args.platform, label=args.label or None).verify()
    _print_json(result)
    return 0 if result.get("ok") else 1


def _cmd_call(args: argparse.Namespace, app: CitrusApp) -> int:
    adapter = app.adapter(args.platform, label=args.account or None)
    capability = args.capability
    if capability == "account":
        payload = adapter.account()
    elif capability == "feed":
        payload = adapter.feed(source=args.source, limit=args.limit or 20, page=args.page or 1)
    elif capability == "hot":
        payload = adapter.hot(limit=args.limit or 20)
    elif capability == "search":
        if not args.q:
            raise CitrusError("bad_request", "search 需要 --q。")
        payload = adapter.search(query=args.q, limit=args.limit or 20, page=args.page or 1)
    elif capability == "item":
        payload = adapter.item(ref=args.ref, kind=args.kind, id=args.id, related=args.related)
    elif capability in ("comments", "user_content"):
        if capability == "comments":
            payload = adapter.comments(ref=args.ref, kind=args.kind, id=args.id,
                                       limit=args.limit or 20, page=args.page or 1,
                                       sort=args.sort)
        else:
            payload = adapter.user_content(ref=args.ref, limit=args.limit or 20,
                                           page=args.page or 1)
    elif capability == "user":
        payload = adapter.user(ref=args.ref)
    else:
        raise CitrusError("bad_request", "不认识的 capability：%s" % capability)
    _print_json({"ok": True, "data": payload})
    return 0


def _cmd_doctor(args: argparse.Namespace, app: CitrusApp) -> int:
    info: dict[str, Any] = {
        "ok": True,
        "version": __version__,
        "python": sys.version.split()[0],
        "home": str(app.accounts.home),
        "accounts": app.accounts.describe_all(),
        "platforms": [app.registry.describe(platform) for platform in app.registry.ids()],
        "config": app.config.public_dict(),
    }
    _print_json(info)
    return 0


_COMMANDS = {
    "serve": _cmd_serve,
    "auth": _cmd_auth,
    "accounts": _cmd_accounts,
    "logout": _cmd_logout,
    "verify": _cmd_verify,
    "call": _cmd_call,
    "doctor": _cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        with _make_app(args) as app:
            handler = _COMMANDS.get(args.command)
            if handler is None:
                parser.print_help()
                return 2
            return handler(args, app)
    except CitrusError as exc:
        _print_json({"ok": False, "error": exc.to_dict()})
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
