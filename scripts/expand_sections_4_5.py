#!/usr/bin/env python3
"""补写 Section 4/5 的引导段落，并清理元数据垃圾章节。"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).parent.parent
ARTICLE = PROJECT / "raw/2026-03-09-ai-infra-redefined.md"

LLM_CFG = {
    "base_url": "https://api.minimaxi.com/v1",
    "api_key": os.environ.get("MINIMAX_API_KEY", ""),
    "model": "MiniMax-M2.5",
}


def call_llm(prompt: str, system: str = "") -> str:
    api_key = LLM_CFG["api_key"]
    if not api_key:
        return ""
    is_minimax = "minimax" in LLM_CFG["base_url"].lower()
    payload = {
        "model": LLM_CFG["model"],
        "messages": [
            {"role": "system", "content": system or "你是一名AI基础设施领域的技术作家。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }
    if is_minimax:
        payload["thinking"] = {"type": "disabled"}
        payload["reasoning_split"] = True
    req = urllib.request.Request(
        LLM_CFG["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        print(f"⚠ LLM error: {e}", file=sys.stderr)
        return ""


MANUAL_INTROS = {
    "四种架构模式总览": """当我们把视角从单层技术放大到整体架构时，AI Infra 就呈现为四种截然不同的典型模式。每种模式都有其独特的硬件配置、软件栈和运营策略，适用于完全不同的业务场景和规模阶段。理解这四种模式，是做出正确架构决策的前提。

超大规模训练集群代表了 AI 基础设施的巅峰——通常指万卡以上 GPU 规模的集群，其核心挑战是让如此多的计算单元同时高效运转而不因单点故障导致整体损失。这需要硬件、调度、容错三位一体的协同设计，是只有少数顶级科技公司才能玩得起的游戏。

成本优化训练则代表了大多数 AI 团队的现实——用有限预算完成尽可能多的训练任务。Spot 实例、断点续训、参数高效微调等技术，使得小团队也能在百卡规模上完成高质量模型训练，而不需要百万美元级的投入。

实时推理服务架构面向的是真正的终端用户——SLA 通常要求 99.9% 以上的可用性，流量特征是突发性强、高峰低谷差异巨大。这类架构的核心挑战不是算力而是弹性：如何在流量高峰时快速扩容，又在低谷时收缩到零以节省成本。

边缘推理代表了 AI 部署的另一极——把智能推向数据产生的地方，而不是集中在云端数据中心。这带来了全新的约束：功耗、内存、计算资源都极其有限。模型量化、知识蒸馏、神经架构搜索等技术，让在手机和 IoT 设备上跑大模型成为可能。""",

    "六大趋势总览": """展望未来，AI Infra 正在经历一场深刻的多维度变革。理解这些趋势不是为了追逐时髦，而是为了在技术投资的长期决策中少走弯路。

云化是最确定的长期方向。Training-as-a-Service 将训练能力抽象成按需调用的云服务，中小企业无需自建集群即可训练大模型；Serverless 推理则更进一步，连服务器都不需要管理，只为实际调用的算力付费。挑战在于 GPU 冷启动延迟远高于 CPU，但软硬件层面都在快速进步。

一体化趋势体现在两个方向：MLOps 端到端平台将数据处理、训练、部署、监控串联成完整闭环；Hugging Face 正在从模型托管平台向推理平台演进，是这一趋势的缩影。

垂直化催生了专用芯片市场。TPU 和 Trainium 针对训练 workload 特性做硬件优化，在特定场景下能效比远超通用 GPU；推理专用 ASIC 如 Groq 的 LPU 以极高吞吐和极低延迟挑战 GPU 的霸主地位。

开源化是过去三年最令人兴奋的变化。vLLM、SGLang 等开源推理引擎的崛起打破了厂商垄断；开源框架的多芯片支持也在改善，PyTorch 对 AMD ROCM、NVIDIA CUDA、Intel oneAPI 的统一抽象让芯片切换成本大幅降低。

训推融合架构是下一个前沿——同一套硬件白天跑推理、晚上跑训练的资源复用方案正在被更多企业采纳。边缘云协同推理则将推理任务按复杂度分层，简单查询在边缘节点处理，复杂推理回传云端。

自动化趋势在推理侧进展更快，从基于简单规则的 HPA 演进到基于预测的主动扩缩容，自动量化工具可以一键将 FP16 模型转换成 INT8 甚至 INT4，这些能力正在降低 AI 运维的门槛。""",
}


def main():
    import os as _os
    try:
        zshrc = Path.home() / ".zshrc"
        for line in zshrc.read_text().splitlines():
            if line.startswith("export MINIMAX_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
                _os.environ.setdefault("MINIMAX_API_KEY", key)
    except Exception:
        pass

    text = ARTICLE.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ── 1. 补写引导段落 ──────────────────────────────────────
    for title, intro in MANUAL_INTROS.items():
        # 找 "## <title>" 行
        idx = None
        for i, line in enumerate(lines):
            if line.strip() == f"## {title}":
                idx = i
                break
        if idx is None:
            print(f"⚠ 找不到：{title}")
            continue

        # 检查是否已有引导段落（>3行非表格非列表的内容在标题后）
        body_lines = []
        for j in range(idx + 1, min(idx + 20, len(lines))):
            l = lines[j].rstrip()
            if l.startswith("|") or l.startswith("- ") or l.startswith("**") or l.startswith("#"):
                break
            if l.strip():
                body_lines.append(l.strip())
        body_chars = len("".join(body_lines))
        if body_chars > 300:
            print(f"✓ {title} 已有引导段落（{body_chars}字），跳过")
            continue

        # 在标题后、表格/列表前插入引导段落
        insert_pos = idx + 1
        while insert_pos < len(lines):
            l = lines[insert_pos].rstrip()
            if l.startswith("|") or l.startswith("- **") or l.startswith("## ") or l.startswith("# "):
                break
            insert_pos += 1

        new_lines = [""] + intro.strip().splitlines() + [""]
        lines = lines[:insert_pos] + new_lines + lines[insert_pos:]
        print(f"✓ {title}: 插入引导段落（{len(intro)}字）")

    # ── 2. 清理元数据块（文件清单、审核报告、文档统计）─────
    garbage_titles = ["文章统计", "文件清单", "文档生成完成"]
    new_lines = []
    skip_mode = False
    for line in lines:
        skip = False
        for gt in garbage_titles:
            if line.strip() in (f"## {gt}", f"# {gt}", gt):
                skip_mode = True
                skip = True
                break
        if skip_mode and line.startswith("#"):
            # 遇到新 H1/H2 且不是垃圾 → 退出 skip
            if not any(line.strip() == f"## {g}" or line.strip() == f"# {g}" for g in garbage_titles):
                skip_mode = False
        if not skip:
            new_lines.append(line)

    if len(new_lines) < len(lines):
        print(f"✓ 清理元数据块：删减 {len(lines)-len(new_lines)} 行")

    # ── 3. 修复第5部分的 H1 标记 ──────────────────────────
    lines = new_lines
    for i, line in enumerate(lines):
        if line.strip() == "# 第五部分：行业趋势与未来展望":
            lines[i] = "## 第五部分：行业趋势与未来展望"
            print("✓ 修复第5部分 H1 → H2")
            break

    # ── 4. 删除 ep-01 的纯目录集和 ep-22 的垃圾集 ────────
    # 策略：删除第一集的目录内容（只剩标题+description，没实质正文）
    # 删除最后一集的文件清单（meta 垃圾）
    # 改为在文章里清理，而不是在 draft 里——更干净

    ARTICLE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 文章已保存：{ARTICLE}")


if __name__ == "__main__":
    main()
