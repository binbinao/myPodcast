"""TTS backend 抽象基类 + 注册表。

新加 backend：
1. 在 src/backends/ 创建 mybackend.py
2. 继承 Backend，重写 name + generate + build_episode
3. 用 @register 装饰器自动注册
4. config.yaml 的 tts.backend = "mybackend" 即生效

不需要改其它任何文件。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Backend(ABC):
    """所有 TTS backend 必须实现此接口。"""

    name: str = ""  # 注册名（config.yaml 用）

    @abstractmethod
    async def generate(
        self,
        segments: list[dict[str, Any]],
        voice_map: dict[str, str],
        cfg: dict[str, Any],
        out_path: Path,
    ) -> int:
        """合成音频到 out_path。返回时长秒。"""

    def build_episode(
        self,
        segments: list[dict[str, Any]],
        voice_map: dict[str, str],
        cfg: dict[str, Any],
        out_dir: Path,
        *,
        series_title: str,
        series_slug: str,
        ep_index: int,
    ) -> tuple[Path, int]:
        """默认实现：拼 output 路径 + 调 asyncio.run(generate)。backend 可覆盖。"""
        import asyncio
        from ..naming import ep_output_dir
        ep_dir = Path(ep_output_dir(str(out_dir), series_title, ep_index, series_slug))
        ep_dir.mkdir(parents=True, exist_ok=True)
        mp3 = ep_dir / "episode.mp3"
        duration = asyncio.run(self.generate(segments, voice_map, cfg, mp3))
        return mp3, duration


REGISTRY: dict[str, Backend] = {}


def register(cls: type[Backend]) -> type[Backend]:
    """类装饰器：自动把 Backend 子类注册到 REGISTRY。"""
    if not cls.name:
        raise ValueError(f"{cls.__name__} 必须设置 name")
    REGISTRY[cls.name] = cls()
    return cls


def get_backend(name: str) -> Backend:
    """按名字取 backend；不存在则列出可用的。"""
    if name not in REGISTRY:
        avail = ", ".join(sorted(REGISTRY.keys())) or "(无)"
        raise SystemExit(f"✗ tts backend '{name}' 未注册。可用：{avail}")
    return REGISTRY[name]