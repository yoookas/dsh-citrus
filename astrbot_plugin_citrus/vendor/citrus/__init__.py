"""citrus —— 统一社交平台信息 API。

只做一件事：把「各平台的 cookie」变成「一套形状一致的读接口」。

    from citrus import CitrusApp
    app = CitrusApp()
    app.accounts.set("zhihu", {"cookie": "z_c0=..."})
    app.adapter("zhihu").hot(limit=5)

HTTP 层见 citrus.server，命令行见 citrus.cli。
"""

import sys

# 只支持新解释器：代码里用了 match / X | None / dict[str, Any] 这些 3.11 的写法。
# 这段故意保持在 3.8 也能解析，好让老解释器给出人话而不是 SyntaxError。
if sys.version_info < (3, 11):  # pragma: no cover
    raise RuntimeError(
        "citrus 需要 Python 3.11+，当前是 %s。\n"
        "换一个新解释器再跑，例如：python3.12 -m citrus serve" % sys.version.split()[0]
    )

__version__ = "0.1.0"

from .errors import CitrusError  # noqa: E402
from .context import CitrusApp  # noqa: E402

__all__ = ["CitrusApp", "CitrusError", "__version__"]
