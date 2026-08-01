#!/usr/bin/env python3
"""给所有薄章节补充引导段落，改善播客内容密度。"""
from __future__ import annotations
import re
from pathlib import Path

PROJECT = Path(__file__).parent.parent
ARTICLE = PROJECT / "raw/2026-03-09-ai-infra-redefined.md"

MANUAL_INTROS = {
    "2.1 架构总览": """当我们谈论 AI 基础设施，很多人脑海里浮现的是一排排闪烁着绿灯的 GPU 服务器。但真正的 AI Infra 比这复杂得多——它是一个由硬件、网络、调度框架、数据管理、观测工具组成的完整技术栈，每一层都在决定着整个系统的效率上限。

理解这个六层架构的价值在于：当你遇到瓶颈时，不再需要推倒重来，而是可以精准定位问题出在哪一层，然后针对性地投入资源解决。""",

    "2.2 分层优化的典型场景": """分层架构的另一大价值，是让问题诊断变得清晰可循。当 GPU 利用率上不去的时候，问题可能出在任何一个层次——硬件选型不当、网络带宽不足、调度策略低效、框架并行度不够、甚至是数据加载成为了瓶颈。定位错误的代价是巨大的，而分层的价值正在于此：每个层次都有自己独特的优化杠杆。

比如，如果 GPU 算力本身是瓶颈，最直接的解法是升级到 H100 或 H200；但如果数据加载拖慢了 GPU，那就应该优先优化并行文件系统和数据预取机制，而不是花冤枉钱买更多 GPU。""",

    "2.3 解耦责任边界": """大型组织里，AI 基础设施的建设从来不是一个人的工作。硬件工程师、平台工程师、算法科学家、运维团队，每个角色都在 AI Infra 的某个层次上发挥专长。但职责边界不清晰是很多团队的通病——硬件团队抱怨算法科学家乱申请资源，算法科学家觉得平台团队响应太慢。

分层架构天然地定义了责任的边界：硬件团队负责 GPU 选型和集群建设；平台团队负责调度系统和网络配置；算法团队专注于模型训练策略；运维团队负责监控和成本控制。当每个团队都在自己层次上深耕，并通过标准接口与其他层协作，整个系统的迭代速度会显著提升。""",

    "2.4 训练 vs 推理的架构差异": """虽然我们用同一套六层架构描述 AI 基础设施，但训练场景和推理场景在每一层的具体实现上有着根本性的差异。理解这些差异是做出正确技术决策的前提。

打个比方：训练就像建造一栋大楼，需要长时间、高强度、统筹规划的工作；推理则像物业管理，需要快速响应、灵活调整、控制成本。两者的需求截然不同——训练追求的是最大吞吐，推理追求的是最低延迟；训练可以容忍中断，推理要求 99.9% 以上的可用性；训练的成本以一次性采购为主，推理的成本以按量计费为主。""",

    "未来展望": """技术演进从来不是线性的，理解趋势才能在投资决策中少走弯路。AI 基础设施领域正在经历六个维度的深刻变化——每一个维度都在重塑整个行业的技术格局。

这些趋势并非独立发展，而是相互交织、相互加速：云化让小团队也能用上顶级算力，开源化打破了厂商垄断，自动化降低了运维门槛。三者叠加在一起，意味着 AI 基础设施的门槛正在快速下降，而真正的竞争焦点正在向应用层转移。""",

    "核心洞察": """回顾整篇文章，有四个核心洞察值得反复咀嚼——它们不只是知识点，更是思考 AI 基础设施的思维框架。

第一个洞察是训练和推理的本质差异。这是整篇文章的基础——混淆二者，用同一套基础设施试图同时满足两种需求，往往导致两边都做不好。第二个洞察是分层优化的力量。AI Infra 不是买 GPU 那么简单，识别瓶颈在哪一层，然后针对性地投入，才是高效的做法。第三个洞察是国产替代的时代机遇——昇腾 910B、寒武纪 590 等已经接近 A100 水平，对于受芯片管制影响的企业来说，这是一个重要的选项。第四个洞察是云化与开源的双重趋势正在深刻改变行业格局。""",

    "最后寄语": """聊到这里，我们已经从 GPU 选购聊到了投资决策框架，从训练集群聊到了边缘推理。内容很长，但每一层都是实打实的工程实践。

最后想说的一句话是：AI 基础设施没有银弹，没有一劳永逸的解决方案。但有方法论——理解分层架构、区分训练与推理的差异、建立成本意识、保持对技术趋势的敏感度，这四点是在 AI 基础设施这场竞赛中做出正确决策的关键。""",
}


def main():
    text = ARTICLE.read_text(encoding="utf-8")
    lines = text.splitlines()

    for title, intro in MANUAL_INTROS.items():
        # Find "## <title>" line
        idx = None
        for i, line in enumerate(lines):
            if line.strip() == f"## {title}":
                idx = i
                break
        if idx is None:
            print(f"⚠ 找不到：## {title}")
            continue

        # Skip if already has substantial content (non-table text before next H2)
        body_lines = []
        j = idx + 1
        while j < len(lines):
            l = lines[j].rstrip()
            if l.startswith("## ") or l.startswith("# "):
                break
            if l.strip() and not l.startswith("|") and not l.startswith("```"):
                body_lines.append(l.strip())
            j += 1

        body_chars = len("".join(body_lines))
        if body_chars > 250:
            print(f"✓ ## {title}: 已有内容（{body_chars}字），跳过")
            continue

        # Find insert position (after ## header, skip any code/table blocks)
        insert_pos = idx + 1
        while insert_pos < len(lines):
            l = lines[insert_pos].rstrip()
            if l.startswith("```") or l.startswith("|") or l.startswith("- **") or l.startswith("#"):
                insert_pos += 1
                continue
            if l.strip():
                break
            insert_pos += 1

        new_lines = [""] + intro.strip().splitlines() + [""]
        lines = lines[:insert_pos] + new_lines + lines[insert_pos:]
        print(f"✓ ## {title}: 插入 {len(intro)} 字引导段")

    ARTICLE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 保存：{ARTICLE}")


if __name__ == "__main__":
    main()
