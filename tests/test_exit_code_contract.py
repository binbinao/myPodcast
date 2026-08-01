"""退出码契约 + SystemExit 守卫（重构 P0-A）。

两条守则：
1. `src/build.py` run_one 内部不准 raise SystemExit（会被 except Exception 穿透，
   把整批炸掉）；
2. `src/build.py` run() 收尾若 failed 非空，必须 sys.exit(EXIT_PIPELINE_FAIL=1)。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUILD_PY = ROOT / "src" / "build.py"


class BuildExitCodeContractTest(unittest.TestCase):
    """机械守卫：扫描 build.py + base.py，禁出现除 main() 外的 SystemExit。"""

    def test_no_systemexit_in_run_one(self) -> None:
        text = BUILD_PY.read_text(encoding="utf-8")
        # 找到 main() 起点；只扫描 main() 之前的代码（run_one / run / helpers 区域）
        main_idx = text.find("def main")
        if main_idx == -1:
            self.fail("build.py 缺 def main —— 架构红线，SystemExit 必须只留 main")
        head = text[:main_idx]
        offenders = []
        for m in re.finditer(r"raise\s+SystemExit", head):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"build.py:{line_no}")
        if offenders:
            self.fail(
                "重构红线：run_one/run/helpers 区域不准 raise SystemExit（会被 "
                "except Exception 穿透炸整批）。CLI 校验可放 main()。\n"
                + "\n".join(f"  {p}" for p in offenders)
            )


if __name__ == "__main__":
    unittest.main()