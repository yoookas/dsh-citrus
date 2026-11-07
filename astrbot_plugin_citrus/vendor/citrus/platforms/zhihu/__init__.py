"""知乎平台适配器。

对外只暴露 ZhihuPlatform（注册表拿它当工厂用）和 normalize / client 两个内部模块。
"""

from .adapter import ZhihuPlatform

__all__ = ["ZhihuPlatform"]
