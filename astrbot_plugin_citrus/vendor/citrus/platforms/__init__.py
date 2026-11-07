"""platforms —— 每个平台一个包，各自封装 cookie 用法、接口路径、归一化规则。

新增平台 = 新增一个目录 + 在 citrus/platforms/__init__.py 的 BUILTIN 里登记。
核心层不感知任何平台。
"""

from .zhihu import ZhihuPlatform

#: 内置平台工厂列表。顺序即 /v1/platforms 的展示顺序。
BUILTIN = (ZhihuPlatform,)

__all__ = ["BUILTIN", "ZhihuPlatform"]
