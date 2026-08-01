"""myPodcast 流水线共享异常与退出码契约。

设计原则（重构路线图 Phase 3）：
- 流水线内部错误一律用 PipelineError（继承 Exception，可被 except Exception 捕获），
  让 run() 聚合 + 决定退出码。
- SystemExit 只允许出现在 main() / argparse 校验层，run_one / 业务函数里不准 raise SystemExit，
  否则会被 except Exception 穿透、逃出 try/except，把整批炸掉。
- 退出码契约（CI 依赖）：
  0  全成功
  1  流水线失败（集失败/门禁拦下/ffprobe 异常等）
  2  hard gate 违规（naming_enforce / validate 等门禁类工具专用）
"""
from __future__ import annotations

from typing import Optional


# CI / 运维约定的退出码。集中在一处，便于门禁和 build 共享。
EXIT_OK = 0
EXIT_PIPELINE_FAIL = 1
EXIT_GATE_VIOLATION = 2


class PipelineError(Exception):
    """run_one 内部所有"这集会失败"信号的统一类型。

    run() 用 except PipelineError + except Exception 双重捕获，聚合到 failed 列表，
    收尾根据 failed 非空 sys.exit(EXIT_PIPELINE_FAIL)。"""

    def __init__(self, message: str, *, code: int = EXIT_PIPELINE_FAIL, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint  # 给人类的修复建议，run() 会在 summary 里打印


class GateViolation(PipelineError):
    """门禁类（naming/validate）违规。run() 见到应立刻终止，不要再继续后续集。"""

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        super().__init__(message, code=EXIT_GATE_VIOLATION, hint=hint)


__all__ = [
    "EXIT_OK",
    "EXIT_PIPELINE_FAIL",
    "EXIT_GATE_VIOLATION",
    "PipelineError",
    "GateViolation",
]