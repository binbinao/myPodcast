#!/usr/bin/env python3
"""补写 AI Infra 文章缺失的 Section 3-7 完整正文，替换大纲摘要。

用法：
    python scripts/expand_ai_infra_sections.py
"""
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

SECTIONS = {
    "section-3-1-hardware": {
        "title": "硬件层 - 算力底座",
        "outline": [
            "GPU选型深度对比：H100/H200/A100/L40S规格对比",
            "NVIDIA中国定制版显卡：A800（2022）→ H800（2023）→ H20（2024），含管制升级时间线",
            "H20深度解析：96GB显存、FP16仅148TFLOPS（-85%）、推理性能达H100的60-80%",
            "国产GPU进展：华为昇腾910B、寒武纪思元590、海光DCU、摩尔线程MTT S4000综合评估",
            "存储系统选型：Lustre/GPFS/WEKA/3FS对比，DeepSeek 3FS创新",
            "网络拓扑设计：胖树/轨式优化/全连接架构",
        ],
    },
    "section-3-2-virtualization": {
        "title": "虚拟化与资源管理层",
        "outline": [
            "GPU虚拟化技术对比：MIG（硬件级）vs MPS（软件级）vs vGPU vs Time-slicing",
            "多租户调度策略：FIFO/优先级/Fair Share/Gang Scheduling",
            "Serverless推理架构：Knative Serving、冷启动优化、自动扩缩容",
        ],
    },
    "section-3-3-framework": {
        "title": "框架与运行时层",
        "outline": [
            "并行策略演进：DP/TP/PP/SP/EP，3D并行标配",
            "训练框架对比：DeepSpeed ZeRO（-1/2/3）、Megatron-LM、Colossal-AI、FSDP",
            "推理引擎对比：vLLM（PagedAttention）、TensorRT-LLM、llama.cpp",
            "量化技术：FP16/INT8/GPTQ/AWQ/SmoothQuant",
        ],
    },
    "section-3-4-scheduler": {
        "title": "调度与编排层",
        "outline": [
            "训练调度器：Slurm vs Volcano vs YuniKorn，Gang Scheduling",
            "弹性训练与容错：TorchElastic、Spot实例训练策略",
            "推理服务编排：K8s HPA/VPA、Knative、KServe、Triton",
            "流量管理：金丝雀发布、A/B测试、Istio",
        ],
    },
    "section-3-5-data": {
        "title": "数据管理层",
        "outline": [
            "数据加载优化：预取、多进程、内存映射、WebDataset",
            "并行文件系统：DeepSeek 3FS详解（6.6TB/s，CRAQ协议）",
            "数据版本管理：DVC/LakeFS/Pachyderm",
            "KV Cache管理：计算公式、MQA/GQA/PagedAttention优化",
            "向量数据库：Milvus/Pinecone/Weaviate/Pgvector/FAISS",
        ],
    },
    "section-3-6-observability": {
        "title": "观测与优化层",
        "outline": [
            "MFU详解：计算公式、行业基准（优秀>55%，平均20-40%）",
            "实验跟踪工具：W&B/MLflow/TensorBoard/Neptune/ClearML对比",
            "性能分析工具：Nsight Systems、PyTorch Profiler",
            "推理监控指标：P99延迟、首Token延迟、TPS、长尾延迟问题",
            "成本追踪框架：成本构成分析、优化策略矩阵、Kubecost",
        ],
    },
    "section-4-architecture-patterns": {
        "title": "四种架构模式总览",
        "outline": [
            "超大规模训练：万卡级、3D并行、弹性容错",
            "成本优化训练：百卡级、Spot实例、PEFT",
            "实时推理服务：动态扩缩容、缓存优化",
            "边缘推理：量化、蒸馏、NAS",
        ],
    },
    "section-5-trends": {
        "title": "六大趋势总览",
        "outline": [
            "云化：Training-as-a-Service / Serverless推理",
            "一体化：MLOps端到端平台 / 统一推理网关",
            "垂直化：专用训练芯片（TPU/Trainium）/ 专用推理芯片（ASIC）",
            "开源化：开源框架+多芯片支持 / 开源推理引擎（vLLM等）",
            "融合化：训推统一架构 / 边缘云协同推理",
            "自动化：自动并行、AutoML / 自动扩缩容、自动量化",
        ],
    },
    "section-6-investment": {
        "title": "核心决策要点",
        "outline": [
            "三大核心问题：自建vs云服务vs混合、训练集群vs推理集群资源分配、短期投入vs长期规划",
            "TCO关键结论（128张H100，3年周期）",
            "五大避坑指南",
        ],
    },
}


def call_llm(prompt: str, system: str = "") -> str:
    """调用 MiniMax LLM，返回文本。"""
    api_key = LLM_CFG["api_key"]
    if not api_key:
        print("⚠ 未设置 MINIMAX_API_KEY，跳过 LLM 调用", file=sys.stderr)
        return ""

    is_minimax = "minimax" in LLM_CFG["base_url"].lower()
    payload = {
        "model": LLM_CFG["model"],
        "messages": [
            {"role": "system", "content": system or "你是一名AI基础设施领域的技术作家，撰写技术博客内容。"},
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
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"].get("content", "")
        return content.strip()
    except Exception as e:
        print(f"⚠ LLM 调用失败: {e}", file=sys.stderr)
        return ""


def generate_section_content(section_id: str, section: dict) -> str:
    """用 LLM 生成一个章节的完整正文 Markdown。"""
    title = section["title"]
    outline_html = "\n".join(f"- {item}" for item in section["outline"])

    prompt = f"""你是一名AI基础设施领域的技术播客编辑。请为以下章节写一段约800-1200字的技术正文，用于播客朗读。

## 章节标题
{title}

## 必须覆盖的技术要点
{outline_html}

## 要求
1. 用通俗易懂的语言解释每个技术要点，适合技术从业者（非零基础）
2. 适当加入数据点（如性能数字、厂商对比）增加可信度
3. 训练场景 vs 推理场景双轨对比的内容要明确标注
4. 播客友好的口语化表达，避免过于书面的句式
5. 直接输出正文，不需要标题、结论等额外结构，字数控制在800-1200字
"""

    return call_llm(prompt)


def manual_section_content(section_id: str, section: dict) -> str:
    """当 LLM 不可用时，使用手动编写的降级内容。"""
    title = section["title"]

    manuals = {
        "section-3-1-hardware": f"""硬件层是整个 AI 基础设施的地基，直接决定了训练和推理的理论性能上限。这一层的选择往往是最先被讨论的，但也是最容易被误解的——以为买到了好 GPU 就万事大吉，忽视了网络、存储、散热等配套系统。

GPU 选型是硬件层的核心议题。当前主流训练GPU梯队分明：第一梯队是 NVIDIA H100 和 H200，拥有业界最高的 FP16 算力和显存带宽，是万卡集群的首选；第二梯队是 A100，成熟稳定，性价比仍在；第三梯队是 L40S，专为推理优化，能效比出色。中国市场受出口管制影响，经历了从 A800 到 H800 再到 H20 的演进路线。H20 虽然带宽大幅下降，但凭借 NVLink 互联优势，在某些场景下仍能发挥相当于 H100 六到八成的推理性能。

国产 GPU 近年来进步显著。华为昇腾 910B 在部分场景已接近 A100 水平，配合 MindSpore 框架形成完整生态；寒武纪思元 590 在特定模型上展现出竞争力；海光 DCU 在通用性上有一定优势；摩尔线程 MTT S4000 正在追赶。企业选型时要综合考虑芯片性能、软件生态、供货稳定性和成本五个维度。

存储系统的选择同样关键。Lustre 和 GPFS 是经典高性能并行文件系统方案，WEKA 提供更好的云原生支持，而 DeepSeek 自主研发的 3FS 系统以 6.6TB/s 的吞吐性能刷新了纪录，其基于 CRAQ 协议的创新设计值得重点关注。

网络拓扑决定了多卡、多机通信效率。胖树架构适合大规模集群，二层Clos结构简洁有效；轨式拓扑针对特定通信模式优化；全连接架构延迟最低但扩展性差。InfiniBand 目前仍是最高性能的集群网络方案，但 RoCE v2 在成本效益上形成强有力竞争。
""",
        "section-3-2-virtualization": f"""虚拟化与资源管理层负责将物理 GPU 资源高效地分配给不同任务和用户。在训练和推理两种场景下，这一层的挑战截然不同。

训练场景的核心需求是多任务隔离和GPU切分。NVIDIA MIG（多实例GPU）提供硬件级的算力隔离，每个MIG实例拥有独立显存和计算单元，适合对稳定性要求极高的多租户训练环境。MPS（多进程服务）则是软件级的方案，开销更小但隔离性稍弱。Time-slicing 通过时间片轮转实现资源共享，实现简单但可能导致延迟敏感任务受影响。

推理场景对弹性伸缩有更高要求。Serverless 推理架构成为新范式：Knative Serving 根据实际请求量自动扩缩容到零，冷启动延迟通过模型预热和快照缓存等技术得到有效控制。AWS Lambda 和阿里云函数计算等平台已开始支持 GPU 推理，不过冷启动问题仍是行业痛点。

多租户环境下的调度策略直接影响集群效率。FIFO 简单直接但容易产生饥饿；优先级调度保证重要任务优先；Fair Share 则平衡各用户/项目的资源配额；Gang Scheduling 确保分布式训练任务的所有 worker 同时启动，避免部分等待的无效浪费。
""",
        "section-3-3-framework": f"""框架与运行时层是 AI 基础设施的软件核心，直接决定了硬件算力能否被充分释放。这一层是过去几年创新最密集的领域。

训练框架的并行策略演进清晰可见：数据并行（DP）是最基础的方式；模型并行（MP）解决单卡放不下模型的问题；管道并行（PP）通过微批次流水线降低管道气泡；张量并行（TP）把单层矩阵乘法拆分到多卡。当前万卡级训练的标准配置是 3D 并行——数据并行叠加管道并行叠加张量并行。

DeepSpeed 以 ZeRO 优化器系列著称：ZeRO-1 分片优化器状态，ZeRO-2 分片优化器加梯度，ZeRO-3 分片全部参数。Megatron-LM 专注于张量并行和序列并行的极致优化。FSDP（完全分片数据并行）是 PyTorch 原生的全参分片方案，与 PyTorch 生态无缝集成。Colossal-AI 则提供了更统一的并行抽象。

推理引擎领域 vLLM 成为现象级产品，其 PagedAttention 技术通过分页管理 KV Cache，将 GPU 利用率提升数倍。TensorRT-LLM 是 NVIDIA 官方推理优化引擎，在 H 系列 GPU 上性能领先。llama.cpp 则以纯 CPU/C++ 实现著称，适合边缘部署。

量化技术是推理成本优化的核心杠杆。FP16 是训练和推理的通用精度；INT8 在精度损失可接受的前提下大幅降低显存和算力需求；GPTQ 和 AWQ 是主流的后训练量化方法；SmoothQuant 则通过数学变换平衡各通道的量化难度。
""",
        "section-3-4-scheduler": f"""调度与编排层是连接用户需求和底层资源的桥梁，决定了集群效率的最大化边界。

训练场景下的调度器选择是平台团队的核心决策。Slurm 是 HPC 领域的老牌霸主，生态成熟、文档丰富，是超算中心的首选。Volcano 来自华为云，专为 AI 训练场景设计，对 Gang Scheduling、优先级队列、Spot 实例中断恢复有原生支持。YuniKorn 是 Apache 基金会的项目，起源于百度的 Yarn 改进，兼顾批处理和 AI 负载。

弹性训练是降低训练成本的关键。TorchElastic 让训练任务可以在节点丢失时自动恢复，配合 Spot 实例可以将 GPU 成本降低七成以上。弹性训练的关键设计点包括：-checkpoint 频率（太频繁影响性能，太稀疏损失恢复进度）；恢复后数据加载器的状态同步；以及全局梯度累积步数的正确处理。

推理服务编排的主流方案是 Kubernetes 原生生态。K8s HPA（水平 Pod 自动扩缩容）基于 CPU 或自定义指标扩缩；VPA（垂直扩缩）调整 Pod 的资源配额。Knative 在 Serverless 场景下更胜一筹，支持缩容到零和基于并发数的扩缩策略。KServe 则提供了标准化的推理服务抽象，支持多模型Serving和 A/B 测试。Triton 推理服务器与 KServe 深度集成，是 NVIDIA GPU 推理的标准部署方式。

流量管理对于多版本推理服务至关重要。金丝雀发布先让小比例流量走新版本，监控无误后逐步切换；A/B 测试则同时运行多个版本用于对照实验；Istio 服务网格提供了细粒度的流量控制和熔断能力。
""",
        "section-3-5-data": f"""数据是 AI 的燃料，数据管理效率往往成为训练和推理系统的隐形瓶颈。

训练场景下，数据加载优化的核心矛盾是：GPU 计算速度远快于数据读取速度，形成计算等待数据的窘境。解决方案包括：预取机制在 GPU 处理当前批次时后台加载下一批次；多进程数据加载器绕过 Python GIL 限制；内存映射（Memory Mapping）减少文件系统开销；WebDataset 将大量小文件打包成少数大文件，减少元数据压力。

并行文件系统是高性能训练的数据底座。Lustre 是 HPC 领域的传统选择，成熟稳定；GPFS（IBM Spectrum Scale）在企业市场应用广泛；WEKA Data Platform 提供云原生和对象存储原生支持。DeepSeek 3FS 是一个值得特别关注的创新：6.6TB/s 的聚合吞吐、CRAQ 协议的强一致性保证、以及对 KV Cache 的原生优化设计，使其成为大规模训练的有力选择。

数据版本管理对于实验迭代至关重要。DVC（Data Version Control）以 Git 的思路管理数据和模型，是开源社区的主流选择；LakeFS 提供了类似 Git 的分支和版本控制语义，适合企业级数据湖场景；Pachyderm 则强调数据处理的幂等性和可追溯性。

KV Cache 管理是推理优化的核心战场。大模型推理的自回归生成过程中，已计算的 Key-Value 张量被缓存复用，避免重复计算。PagedAttention 通过分页管理 KV Cache，将有效显存利用率提升数倍。MQA（多查询注意力）和 GQA（分组查询注意力）通过减少 Key-Value 头数降低显存占用，是 Llama 3 等新模型的标配。

向量数据库是 RAG 系统的关键基础设施。Milvus 是最成熟的开源向量数据库，支持十亿级向量规模；Pinecone 是托管服务，适合快速上线；Weaviate 以多模态支持著称；Pgvector 将向量能力带入 PostgreSQL 生态，降低工程复杂度；FAISS 适合离线场景和嵌入式部署。
""",
        "section-3-6-observability": f"""没有观测就没有优化。观测层是判断整个基础设施是否健康的眼睛，也是持续迭代改进的数据基础。

MFU（Model FLOPS Utilization，模型算力利用率）是训练场景的核心指标。计算公式是：MFU = 实际 FLOPS / 理论峰值 FLOPS × 100%。优秀团队的 MFU 通常在 55% 以上，全球平均水平在 20% 到 40% 之间，许多企业甚至低于 20%。提升 MFU 的常见手段包括：增加 batch size 以提高算力密度、优化数据加载以减少 GPU 空闲、调整并行策略以减少通信开销。

实验跟踪工具是研发效率的倍增器。Weights & Biases（W&B）是 AI 团队的主流选择，集成度高、UI 友好；MLflow 是开源生态的标准，灵活但需要自行运维；TensorBoard 配合 TensorFlow 使用体验最佳；Neptune 和 ClearML 各有特色，前者轻量，后者强调实验可复现性。

推理场景的监控指标体系与训练完全不同。P99 延迟是 SLA 的核心依据——99% 的请求必须在约定时间内完成；首 Token 延迟（Time to First Token）直接影响用户体验；TPS（Token Per Second）是吞吐量的衡量指标；长尾延迟问题尤其值得警惕——即使 P99 达标，P999 可能仍会超时影响重要用户。

性能分析工具帮助定位瓶颈。Nsight Systems 提供 GPU 级别的时空分析视图；PyTorch Profiler 可以深入到算子级别的性能剖析；NVIDIA DLI（Deep Learning Institute）课程中有大量性能优化的实战案例。

成本追踪是 AI Infra 持续运营的关键。成本通常分为三块：GPU 计算成本、存储成本和网络成本。Kubecost 提供了 Kubernetes 层面的资源成本归属能力，帮助企业精确核算每个团队、每个项目的 AI 计算成本。
""",
        "section-4-architecture-patterns": f"""不同的业务场景需要完全不同的 AI Infra 架构模式。照搬大厂方案往往事倍功半，理解自身场景特征才能做出正确的架构选择。

超大规模训练架构面向万卡以上集群，核心目标是在最短时间内完成训练。这类架构的标志性挑战是：如何保证数千张 GPU 同时高效运行而不因通信或故障导致整体停摆。3D 并行策略是标准配置；弹性容错是必备能力——任何单点故障导致整体训练重启的代价都是数百万美元级的损失；InfiniBand 全互联网络是刚需。代表案例包括 OpenAI GPT-4 和 DeepSeek V3 的训练集群。

成本优化训练面向中小规模（百卡级）场景，核心是在有限预算内完成模型训练。Spot 实例是最大的成本杠杆——AWS Spot 实例价格仅为 On-Demand 的十分之一，配合 checkpoint 容错机制可以在保证训练成功率的前提下大幅降低成本。PEFT（参数高效微调）技术如 LoRA、QLoRA 使得用更少 GPU 微调大模型成为可能。

实时推理服务架构面向面向用户的产品场景，SLA 要求高（通常 99.9% 以上），流量特征是突发性强、高峰低谷差异巨大。水平自动扩缩容是基础能力；多级缓存（结果缓存 + KV Cache + Embedding 缓存）是降低推理成本的关键；冷启动优化保证突发流量下的响应时间。Character.AI 的架构是这类场景的典型代表。

边缘推理架构面向手机、IoT 设备等端侧部署，核心约束是功耗、内存和计算资源极其有限。模型量化是最常用的压缩手段，INT8 或 INT4 量化可以在几乎不损失精度的情况下将模型体积缩小 2-4 倍；知识蒸馏将大模型的能力迁移到小模型；NAS（神经网络架构搜索）自动寻找特定硬件平台上效率最优的模型结构。
""",
        "section-5-trends": f"""AI Infra 正处于快速演进的阶段。理解趋势不是为了追赶时髦，而是为了做出更长远的技术投资决策。

云化是最确定的长期趋势。Training-as-a-Service 将训练能力抽象成按需调用的云服务，中小企业无需自建集群即可训练大模型。Serverless 推理则更进一步——企业甚至不需要管理任何服务器，只为实际调用的算力付费。挑战在于：GPU 的冷启动延迟远高于 CPU，目前还没有完美的解决方案，但软硬件层面都在快速进步。

一体化趋势体现在两个方向：MLOps 端到端平台将数据处理、训练、部署、监控串联成完整闭环；统一推理网关加模型中心的架构让多个团队共享推理基础设施，降低重复建设。Hugging Face 正在从模型托管平台向推理平台演进，是这一趋势的缩影。

垂直化趋势催生了专用芯片市场。TPU 和 Trainium 代表训练专用芯片的方向，针对训练 workload 的特性做硬件优化，在特定场景下能效比远超通用 GPU。推理专用 ASIC 如 Groq 的 LPU 以极高的吞吐和极低延迟挑战 GPU 的推理霸主地位。

开源化是过去三年最令人兴奋的变化。vLLM、SGLang 等开源推理引擎的崛起打破了厂商垄断，让企业可以在任何硬件上部署最优的推理方案。开源框架的多芯片支持也在改善——PyTorch 对 AMD ROCM、NVIDIA CUDA、Intel oneAPI 的统一抽象让芯片切换成本大幅降低。

训推融合架构是下一个前沿。同一套硬件白天跑推理、晚上跑训练的资源复用方案正在被更多企业采纳。边缘云协同推理则将推理任务按复杂度分层——简单查询在边缘节点处理，复杂推理回传到云端，既保证响应速度又控制成本。

自动化趋势在推理侧进展更快。自动扩缩容算法越来越智能，从基于简单规则的 HPA 演进到基于预测的主动扩缩。自动量化工具可以一键将 FP16 模型转换成 INT8 甚至 INT4，无需人工调参。这些自动化能力降低了 AI 运维的门槛，让更多企业可以参与进来。
""",
        "section-6-investment": f"""AI Infra 投资是大多数 AI 项目中最大的一块成本，也是最容易踩坑的地方。一套科学决策框架比任何具体的芯片选型都更重要。

第一个核心问题是自建 vs 云服务 vs 混合模式的选择。自建的优势是长期成本更低（规模效应显著），数据安全可控，灵活性最高；劣势是前期投入大（128 张 H100 集群初始投入约 500 万美元），技术团队要求高，资产折旧快。云服务按需付费，初期成本低，适合早期探索阶段；劣势是长期成本高（128 张 H100 按需使用三年约需 2300 万美元，是自建成本的 3-4 倍）。混合模式——核心训练自建，日常推理和弹性需求用云——是大多数中型企业的最优解。

第二个核心问题是训练集群和推理集群的资源配比。大多数企业犯的错误是"训练优先"——把大部分 GPU 预算投入训练集群，推理时发现资源不足。正确的思路是：先确定推理 SLA 要求，用倒推法算出推理集群的基准规模，再将剩余资源用于训练。

第三个核心问题是短期投入和长期规划的平衡。GPU 芯片的更新周期约为 18 个月，每一代性能提升显著。过度超前采购意味着资产快速贬值；过度保守则错失竞争力。行业经验是：核心训练集群按当前最新芯片采购，备用/探索集群可以考虑上一代芯片以获得更好的性价比。

128 张 H100 集群三年的 TCO 对比数据值得反复参考：自建约 800 万美元；纯云按需约 2300-2600 万美元；云 Spot 混合约 800 万美元（与自建持平，但无初始 CAPEX）。这个数字因电价、人力成本、利用率不同会有显著差异，但倍数关系是普遍成立的。

五大避坑指南：第一，过度关注硬件规格而忽视软件栈——同样的 H100 集群，好的软件栈和差的软件栈实际算力可能相差两倍；第二，训练推理混用同一套 Infra，牺牲两边的最优体验；第三，忽视数据管理瓶颈——数据加载慢是 GPU 空转的首要原因；第四，供应商锁定风险——过度依赖单一芯片厂商；第五，低估运维复杂性——AI 集群的运维复杂度远超传统 IT 系统，需要专门的基础设施工程师团队。
""",
    }

    return manuals.get(section_id, f"## {title}\n\n此章节内容正在补充中。\n")


def main():
    import os as _os
    # 从 zshrc 读取 API key
    try:
        zshrc = Path.home() / ".zshrc"
        for line in zshrc.read_text().splitlines():
            if line.startswith("export MINIMAX_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
                _os.environ.setdefault("MINIMAX_API_KEY", key)
                break
    except Exception:
        pass
    _os.environ.setdefault("MINIMAX_API_KEY", _os.environ.get("MINIMAX_API_KEY", ""))

    article_text = ARTICLE.read_text(encoding="utf-8")
    lines = article_text.splitlines()

    for section_id, section in SECTIONS.items():
        title = section["title"]

        # 找到 section header 的行号
        header_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if (stripped.startswith("### ") or stripped.startswith("## ")) and title in stripped:
                header_idx = i
                break

        if header_idx is None:
            print(f"⚠ {section_id}: 找不到标题 '{title}'")
            continue

        # 找下一个同级或更高级 header 的位置
        next_header_idx = len(lines)
        current_level = len(lines[header_idx]) - len(lines[header_idx].lstrip())
        for i in range(header_idx + 1, len(lines)):
            line = lines[i].rstrip()
            if not line:
                continue
            # 遇到同级或更高级 header 停止
            level = len(line) - len(line.lstrip())
            if level <= current_level and (line.startswith("#") or line.startswith("**")):
                next_header_idx = i
                break

        # 检查现有内容长度
        existing_content = "\n".join(lines[header_idx:next_header_idx])
        if len(existing_content) > 300:
            print(f"✓ {section_id}: 已有内容（{len(existing_content)}字），跳过")
            continue

        print(f"→ 生成 {section_id}: {title} ...", end=" ", flush=True)
        content = generate_section_content(section_id, section)
        if not content:
            print("LLM 不可用，使用降级内容")
            content = manual_section_content(section_id, section)

        # 替换该 section 的内容
        new_section = [lines[header_idx], ""] + content.strip().splitlines() + [""]
        lines = lines[:header_idx] + new_section + lines[next_header_idx:]
        print(f"✓ 替换成功（{len(content)} 字）")

    article_text = "\n".join(lines)
    ARTICLE.write_text(article_text, encoding="utf-8")
    print(f"\n✓ 文章已更新：{ARTICLE}")


if __name__ == "__main__":
    main()
