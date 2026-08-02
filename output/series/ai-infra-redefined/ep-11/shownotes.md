---
title: "重新定义AI Infra：从GPU堆砌到全栈基础设施的进化 · 3.4 调度与编排层"
series: "重新定义AI Infra：从GPU堆砌到全栈基础设施的进化"
date: 2026-08-02
duration: 153
audio: series/ai-infra-redefined/ep-11/episode.mp3
---

# 重新定义AI Infra：从GPU堆砌到全栈基础设施的进化 · 3.4 调度与编排层

> 《重新定义AI Infra：从GPU堆砌到全栈基础设施的进化》3.4 调度与编排层（第 11/19 集）

听：series/ai-infra-redefined/ep-11/episode.mp3 · 时长 2 分 33 秒 · 2026-08-02 · 主播：小搭

**[host]** 调度与编排层是连接用户需求和底层资源的桥梁，决定了集群效率的最大化边界。

**[host]** 训练场景下的调度器选择是平台团队的核心决策。Slurm 是 HPC 领域的老牌霸主，生态成熟、文档丰富，是超算中心的首选。Volcano 来自华为云，专为 AI 训练场景设计，对 Gang Scheduling、优先级队列、Spot 实例中断恢复有原生支持。YuniKorn 是 Apache 基金会的项目，起源于百度的 Yarn 改进，兼顾批处理和 AI 负载。

**[host]** 弹性训练是降低训练成本的关键。TorchElastic 让训练任务可以在节点丢失时自动恢复，配合 Spot 实例可以将 GPU 成本降低七成以上。弹性训练的关键设计点包括：-checkpoint 频率（太频繁影响性能，太稀疏损失恢复进度）；恢复后数据加载器的状态同步；以及全局梯度累积步数的正确处理。

**[host]** 推理服务编排的主流方案是 Kubernetes 原生生态。K8s HPA（水平 Pod 自动扩缩容）基于 CPU 或自定义指标扩缩；VPA（垂直扩缩）调整 Pod 的资源配额。Knative 在 Serverless 场景下更胜一筹，支持缩容到零和基于并发数的扩缩策略。KServe 则提供了标准化的推理服务抽象，支持多模型Serving和 A/B 测试。Triton 推理服务器与 KServe 深度集成，是 NVIDIA GPU 推理的标准部署方式。

**[host]** 流量管理对于多版本推理服务至关重要。金丝雀发布先让小比例流量走新版本，监控无误后逐步切换；A/B 测试则同时运行多个版本用于对照实验；Istio 服务网格提供了细粒度的流量控制和熔断能力。

**[host]** 核心内容

**[host]** - 训练调度器：Slurm vs Volcano vs YuniKorn，Gang Scheduling

**[host]** - 弹性训练与容错：TorchElastic、Spot实例训练策略

**[host]** - 推理服务编排：K8s HPA/VPA、Knative、KServe、Triton

**[host]** - 流量管理：金丝雀发布、A/B测试、Istio

## 订阅

- [RSS / Atom](https://binbinao.github.io/myPodcast/feed.xml)
- 在 [Apple Podcasts](https://podcasts.apple.com/)、[小宇宙](https://www.xiaoyuzhoufm.com/) 等客户端粘贴 RSS 链接
