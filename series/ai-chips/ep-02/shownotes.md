---
title: "AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第3部分"
series: "AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析"
date: 2026-08-14
duration: 484
audio: series/ai-chips/ep-02/episode.mp3
---

# AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第3部分

> AI芯片全景深度报告：GPU、TPU、NPU及其他AI专用芯片分类解析 · 第 2 集

听：series/ai-chips/ep-02/episode.mp3 · 时长 8 分 4 秒 · 2026-08-14 · 主播：小搭

**[host]** 大家好，欢迎回来！上期我们聊完了AI芯片的整体格局，今天终于要进入重头戏了——NVIDIA和AMD的直接对决。

**[guest]** 是的，这应该是大家最关心的部分了。NVIDIA在AI GPU市场的统治力有多强？AMD能不能真的威胁到它？咱们今天好好聊聊。

**[host]** 先说NVIDIA的市场地位。外界一直说它占80%以上，真的这么夸张吗？

**[guest]** 一点不夸张。NVIDIA在AI GPU市场的份额长期维持在80%以上，高端训练芯片领域更是接近垄断。这个数字已经很说明问题了。

**[host]** 那它的护城河到底是什么？总不能光靠品牌吧？

**[guest]** 护城河太深了。我给你举个例子：就算AMD在硬件参数上接近甚至超越NVIDIA，客户迁移到新平台面临的软件适配成本、性能调优周期和工程风险都是巨大障碍。ROCm生态和Intel的oneAPI虽然在追赶，但库的完备性、社区活跃度和开箱即用的兼容性还是有明显差距。

**[host]** 软件生态确实是关键。那咱们具体看看产品。2024年NVIDIA推出的Blackwell架构，具体强在哪？

**[guest]** Blackwell这次升级非常激进。它采用双芯片组封装，总计约2,080亿个晶体管，这是半导体工业量产的最大规模单一GPU芯片。B200配备192GB HBM3e显存，显存带宽8 TB/s，TDP功耗约1,000W。

**[host]** 2,080亿晶体管...这个数字确实夸张。那GB200 NVL72呢？我看资料说它是重新定义AI计算基础设施？

**[guest]** 对，NVL72是Blackwell的旗舰系统。每个机架集成36颗Grace CPU和72颗Blackwell GPU，通过第五代NVLink互连实现高速通信，NVLink总带宽达130 TB/s。整机架配备13.4 TB HBM3e显存，总内存带宽576 TB/s。

**[host]** 算力呢？

**[guest]** FP4峰值性能1,440 PFLOPS，FP8是720 PFLOPS。官方数据说大模型推理任务比H100快30倍，训练任务快4倍。当然，这是特定基准测试的结果，实际提升幅度会因工作负载而异。

**[host]** 不过这个功耗也确实惊人，120 kW整机架功耗，得上液冷了吧？

**[host]** 对，传统风冷完全扛不住，所以GB200 NVL72采用全液冷设计。这也是为什么它以完整液冷机架为交付单位。

**[guest]** 顺便说一句，NVIDIA的利润能力非常恐怖。H100制造成本约3,320美元，终端售价约28,000美元，毛利率高达88.1%。这定价权真是没谁了。

**[host]** 88%的毛利率...这也太夸张了。那客户那边采购价格呢？我看资料里提到云服务商定价差异很大。

**[guest]** 对，CoreWeave约10.50美元/小时/GPU，Oracle约16美元，Azure约27美元。差异主要反映供给能力、合约结构和增值服务的不同。

**[host]** 接下来看看客户覆盖。哪些公司在用NVIDIA？

**[guest]** 覆盖了全球AI产业的核心玩家：OpenAI是最大客户之一，Meta训练Llama系列，Microsoft Azure是OpenAI独家云合作伙伴，Oracle Cloud部署非常激进，Google和AWS虽然自研芯片但也继续采购NVIDIA GPU。

**[host]** 产品迭代节奏呢？我看资料说NVIDIA保持一年一更？

**[guest]** 对，非常激进。Blackwell之后是Rubin架构，预计2026年下半年推出。R100首次采用HBM4显存，容量288GB，带宽22 TB/s，比B200的8 TB/s提升近3倍。峰值FP4算力达50 PFLOPS，较B200再提升约2.5倍。

**[host]** 这迭代速度，AMD压力太大了。那AMD现在表现怎么样？

**[guest]** AMD是目前最具威胁的挑战者。2025年推出基于CDNA 4架构的MI350系列，实现了相较MI300X的代际跃升。

**[host]** 具体规格？

**[guest]** MI350系列采用台积电3nm工艺，1,850亿晶体管。Chiplet设计，由8个XCD和2个IOD组成，共256个计算单元、16,384个流处理器和1,024个专用矩阵核心。

**[host]** 两款产品怎么定位？

**[guest]** MI350X是风冷配置，TDP 1,000W，频率2.2 GHz，配备288GB HBM3e，显存带宽8 TB/s。MI355X是液冷配置，TDP 1,400W，频率2.4 GHz。

**[host]** 算力表现呢？

**[guest]** FP4/FP6峰值算力20 PFLOPS，FP8算力80.5 PFLOPS（含2:4稀疏加速）。AMD公布的数据显示：基于Llama 3.1 405B模型的推理吞吐量较MI300X提升35倍，DeepSeek R1推理性能提升近3倍。

**[host]** 35倍？这提升幅度有点夸张啊。

**[guest]** 是挺夸张的，但更值得关注的是，MI350X支持单卡同时运行多达8个700亿参数模型实例。这对推理服务部署密度和成本效率很有意义。

**[host]** 那成本和定价呢？

**[guest]** MI300X制造成本约5,300美元，售价约15,000美元，毛利率约64.7%。虽然低于NVIDIA的88%，但AMD定价更激进，为客户提供更具性价比的选择。

**[host]** 整体来看，AMD和NVIDIA的差距主要在哪？

**[guest]** 硬件参数其实已经越来越接近了，但软件生态和客户信任度还是主要差距。NVIDIA的CUDA生态耕耘了这么多年，护城河不是一朝一夕能突破的。

**[host]** 好，今天的分享就到这里。下期我们要不要聊聊其他玩家，比如Intel、Google的TPU？

**[guest]** 好啊，Intel的Gaudi和Google的TPU其实也很有意思，咱们下期接着聊！

## 订阅

- [RSS / Atom](https://binbinao.github.io/myPodcast/feed.xml)
- 在 [Apple Podcasts](https://podcasts.apple.com/)、[小宇宙](https://www.xiaoyuzhoufm.com/) 等客户端粘贴 RSS 链接
