---
title: "AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第4部分"
series: "AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析"
date: 2026-08-14
duration: 436
audio: series/ai-chips/ep-03/episode.mp3
---

# AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第4部分

> AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第 3 集

听：series/ai-chips/ep-03/episode.mp3 · 时长 7 分 16 秒 · 2026-08-14 · 主播：小搭

**[host]** 大家好，欢迎回来！上期我们聊了NVIDIA的Blackwell架构，这期来看看它的两个挑战者——AMD和Intel的表现。

**[guest]** 好嘞！先说AMD吧，这家公司最近在数据中心业务上真是火力全开。

**[host]** 对，2024年AMD数据中心部门收入直接翻倍，达到了126亿美元。其中AI GPU是核心增长引擎。

**[guest]** 这个数字很夸张啊翻倍。

**[host]** 而且市场预期更高，预计到2026年，AMD的AI GPU相关收入能突破150亿美元。就看MI350系列接下来的出货情况了。

**[guest]** 那现在有哪些大客户在用AMD的GPU？

**[host]** 几个重量级玩家都进来了。Microsoft Azure已经把AMD MI系列GPU纳入AI云服务产品线；Meta在Llama模型的训练和推理工作负载中部署了AMD GPU；还有OpenAI，据报道也开始测试和采购AMD的GPU，为了供应链多元化。

**[guest]** OpenAI都用上了？这意义挺重大的。

**[host]** 确实。不过我们也要看清现实，AMD目前在全球AI GPU市场的份额大概是6%到8%。

**[guest]** 跟NVIDIA的80%以上相比，差距还是悬殊的。

**[host]** 但你得看增长速度啊，两年前这个数字几乎为零。现在能占到6%-8%，这个势头是不能忽视的。

**[guest]** 对，有进步就是好事。那AMD下一步怎么走？

**[host]** 他们计划在2026年初推出MI400系列，基于CDNA 5架构。这次的升级很激进——首次采用HBM4显存，容量直接干到432GB，显存带宽提升到19.6 TB/s。

**[guest]** 432GB HBM4，这太夸张了。

**[host]** FP4峰值算力预计达到40 PFLOPS，较MI350X翻倍。而且这个推出节奏跟NVIDIA Rubin基本同步，显示AMD正力图在产品迭代速度上跟NVIDIA保持对等竞争。

**[guest]** 好，那Intel呢？他们的AI加速器表现如何？

**[host]** Intel的Gaudi 3走的是完全不同的路线——差异化定位，主打性价比。它提供1835 TFLOPS BF16算力，128GB HBM2e显存，3.7 TB/s带宽，TDP 600W。

**[guest]** 价格呢？

**[host]** 约15000美元，约为H100价格的一半。

**[guest]** 便宜一半，这价格挺香的。

**[host]** 但Gaudi 3最独特的设计在于网络互连方案。它在芯片内集成了24个200Gb/s RoCE端口，可以直接通过标准以太网实现多卡互连，不需要昂贵的InfiniBand交换机。

**[guest]** 这个设计挺聪明的，降低了集群组网成本。

**[host]** 对，对于预算有限但需要部署中等规模AI推理集群的企业来说，Gaudi 3提供了不错的TCO优势。客户包括IBM Cloud、阿里云、Microsoft Azure、LinkedIn、百度等等。

**[guest]** 那市场表现怎么样？

**[host]** 有点尴尬，据报道Intel已经把2025年Gaudi系列的出货目标下调了30%，从原计划的约35万片降到20到25万片。

**[guest]** 怎么回事？

**[host]** 主要是软件生态不成熟，客户适配周期长，再加上来自NVIDIA和AMD的竞争太激烈。目前Gaudi系列在AI加速器市场的份额大概只有1%到3%。

**[guest]** Intel需要在软件栈上多下功夫了。

**[host]** 没错。好了，我们来看一下核心产品对比。先看NVIDIA H100：4nm制程，800亿晶体管，80GB HBM3，3.35 TB/s带宽，FP8峰值算力约4 PFLOPS。

**[guest]** H100现在还是主流选择。

**[host]** B200就夸张了，2080亿晶体管，192GB HBM3e，8 TB/s带宽，FP8峰值算力约10 PFLOPS，FP4能达到20 PFLOPS。不过TDP也到了1000W。

**[guest]** 功耗越来越高，散热是个大问题。

**[host]** AMD MI355X，3nm制程，1850亿晶体管，288GB HBM3e，8 TB/s带宽，FP4峰值算力20 PFLOPS。但是TDP高达1400W，需要液冷。

**[guest]** 1400W，这功率确实惊人。

**[host]** Intel Gaudi 3，5nm制程，128GB HBM2e，3.7 TB/s带宽，FP8/BF16算力1.8 PFLOPS，TDP 600W，优势在于集成RoCE以太网互连。

**[guest]** 整体看下来，NVIDIA还是一骑绝尘，AMD在追赶，Intel在找自己的位置。

**[host]** 对，GPU作为AI算力基石的地位短期内难以撼动。不过下一章我们要聊的TPU，可能会改变这个格局。

**[guest]** 哦？Google的TPU？

**[host]** 对，Google走的是端到端垂直整合路线，从芯片微架构到编译器框架再到云平台服务，全部自己来。自2016年首代TPU问世至今，已经迭代七代产品了。

**[guest]** 七代？那技术积累很深厚了。

**[host]** TPU的核心架构是脉动阵列，这个设计理念非常优雅——将大量处理单元排列为二维网格，数据像血液在心脏中流动一样在阵列中逐拍流动，每个PE在接收数据的同时完成乘加运算并将结果传递给下一个节点。

**[guest]** 听起来很高深。

**[host]** 简单说，这种设计与深度学习的核心运算——矩阵乘法形成天然适配。权重矩阵预加载到PE的本地寄存器中，激活值从阵列左侧注入，部分积从上方向下累加，整个过程无需反复访问外部存储，数据复用率极高。

**[guest]** 比GPU更高效？

**[host]** 从能效比来看，脉动阵列以远低的控制逻辑开销和访存带宽需求，实现了更高的能效比。这代表了AI芯片设计的另一种哲学。

**[guest]** 期待下一期的深入解析！

**[host]** 好，我们下期见！

## 订阅

- [RSS / Atom](https://binbinao.github.io/myPodcast/feed.xml)
- 在 [Apple Podcasts](https://podcasts.apple.com/)、[小宇宙](https://www.xiaoyuzhoufm.com/) 等客户端粘贴 RSS 链接
