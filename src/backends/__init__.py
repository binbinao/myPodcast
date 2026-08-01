"""Backend 注册表 + 自动 import 触发器。

新加 backend：只需在 src/backends/ 创建 mybackend.py 用 @register 装饰。
"""
from __future__ import annotations

# 导入触发各 backend 模块的 @register 装饰器
from .base import Backend, REGISTRY, register, get_backend  # noqa: F401
from . import edge  # noqa: F401
from . import minimax  # noqa: F401

__all__ = ["Backend", "REGISTRY", "register", "get_backend"]