---
title: "裸金属对外售卖机型全清单"
date: 2026-08-06
series_slug: cbm-baremetal
format: solo
voice: audiobook_male_1
split_strategy: by_chars
---

这是一份裸金属对外售卖机型的完整清单，面向选型和对客报价参考。全量机型按实例类型分成十组，逐款给出机型名、内部代号、硬件配置、CPU 型号、单 CPU 物理核、vCPU 核数、网卡形态和刊例价，方便你在做资源规划或者报价核对时一次查全。核心数的换算关系统一是：单 CPU 物理核 乘以 路数 再乘以 2，等于 vCPU 核数；Arm 平台不开超线程，所以物理核乘以路数就是 vCPU。

## 标准型

标准型是通用算力底座，两款机型都不带 GPU，网卡统一走水杉 1.0 的 50G 双口，适合通用计算和数据库类负载。BMSA2 是 AMD 双路平台，BMS5 是 Intel 四路平台。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMSA2 | T0-CS21AM-50GS | 7K62 × 2 (192vcpu)/ 32 × 16 (512G) | AMD EPYC 7K62 2.6GHz | 48 | 192 | 水杉1.0 50G × 2P | 预计8月底上线 | 按量付费29.27/h；包年包月15053/m |
| BMS5 | T0-CS56XM-50GS | CPX6 × 4 (208vcpu)/ 32 × 24 (768G) | Intel Xeon Cooper Lake 2.6GHz | 26 | 208 | 水杉1.0 50G × 2P | 空 | 按量付费63.5/h；包年包月19050/m |

## GPU 型

GPU 型是机型数量最多的一档，一共九款，网卡统一是 Stingary SmartNIC。卡型覆盖 A10、T4、2080ti、V100、3080、3090 和 3070，价格带从两万一到七万四。这里有两组容易混的：BMG5t 和 BMG5tu 共用同一个内部代号 Y0-GG51M-25G，唯一区别是系统盘做不做 RAID1；另外 3080、3090、3070 那几款都带 HDMI 欺骗器，属于图形渲染场景专用。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMGNV4 | T0-GR11XM-25GS | 8372HC 26C 4/32G 24/3.2T NVMe 4/480G SATA SSD2(No RAID)/Nvidia A10*16 | Intel Xeon Cooper Lake 3.4GHz | 26 | 208 | Stingary SmartNIC | 空 | 73980 |
| BMG5t | Y0-GG51M-25G | 8255c × 2/384G(32G × 12)/SSD-480G × 2 RAID1/NVIDIA-T4 × 4 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 25248 |
| BMG5tu | Y0-GG51M-25G | 8255c × 2/384G(32G × 12)/SSD-480G × 2 NoRAID/NVIDIA-T4 × 4 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 25248 |
| BMG5i | Y0-GG55M-25G | 8255c × 2/384G(32G × 12)/SSD-480G × 2 HBA/NVMe-SSD 3.84T × 4/2080ti × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 26980 |
| BMG5v | Y0-GG54M-100G_FORGPUONLY | 8255c × 2/384G(32G × 12)/SSD-480G × 1/NVMe-SSD 3.2T × 4/V100 × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 50200 |
| BMG5e | T0-GG61XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 2 RAID1 HBA/NVMe-SSD 3.84T× 2/3080*8（含HDMI欺骗器） | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 25280 |
| BMG5ec | T0-GG62XM-25GS | 4214c × 2/768G(32G × 24)/SSD-480G × 1 /NVMe-SSD 1.92T× 1/3080*4（含HDMI欺骗器） | Intel Xeon Silver 2.2GHz | 12 | 48 | Stingary SmartNIC | 空 | 21480 |
| BMG5n | T0-GG63XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 2 RAID1 HBA/NVMe-SSD 3.84T× 2/3090*8（含HDMI欺骗器） | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 35280 |
| BMGC37 | T0-GG64XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 2 RAID1 HBA/NVMe-SSD 1.92T× 1/3070*8（含HDMI欺骗器） | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 22880 |

逐款念一遍：BMGNV4 是四路 8372HC 配十六张 A10，七万三千九百八十；BMG5t 和 BMG5tu 都是四张 T4，两万五千二百四十八；BMG5i 是八张 2080ti，两万六千九百八十；BMG5v 是八张 V100，五万零两百；BMG5e 是八张 3080，两万五千二百八十；BMG5ec 是四张 3080，两万一千四百八十；BMG5n 是八张 3090，三万五千二百八十；BMGC37 是八张 3070，两万两千八百八十。

## 高性能 GPU 型

高性能 GPU 型和普通 GPU 型的核心差别，在于多了一组 100GE 的 RDMA 网卡做多机互联，所以适合跑分布式训练。三款机型都是八卡配置。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| HCCG5v | Y0-GG54M-100G | 8255c × 2/384G(32G × 12)/SSD-480G × 1/NVMe-SSD 3.2T × 4/V100 × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | CX5 100GE × 2 | 79960 |
| HCCPNV4h | T0-GT12AM-25GS | 7K62 × 2/1024G(32G × 32)/SSD-480G × 1/NVMe-SSD 3.2T × 4/A100 × 8 | AMD EPYC 7K62 2.6GHz | 48 | 192 | Stingary SmartNIC | CX5 100GE × 2 | 116280 |
| HCCPNV4s | T0-GT15AM-25GS | 7K83 × 2/1024G(32G × 32)/SSD-480G × 1/NVMe-SSD 3.2T × 4/A100 × 8 | AMD EPYC 7K83 2.6GHz | 64 | 256 | Stingary SmartNIC | CX6dx 100GE × 2 | 126800 |

HCCG5v 的硬件跟 BMG5v 几乎一样，多的就是两张 CX5 100GE，价格从五万零两百涨到七万九千九百六十。HCCPNV4h 和 HCCPNV4s 都是八张 A100 配 1024G 内存，区别在 CPU 是 7K62 还是 7K83，后者物理核从 48 涨到 64，网卡也升级到 CX6dx。

## 高主频 IO 型

高主频 IO 型只有一款，主打 3.2GHz 的高主频加 100GE 网卡，适合对单核性能和 IO 延迟都敏感的场景。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| HCCIC5 | T0-CI51XM-100G | 6231C × 2/32G*12/SSD-480G × 2/NVMeSSD-3.84T × 2/HBA-IR/VROC-Key | Intel Xeon Gold 3.2GHz | 16 | 64 | Stingary SmartNIC | CX5 100GE × 2 | 15985 |

## 高 IO 型

高 IO 型三款，共同点是都配了 NVMe SSD。BMIA2m 和 BMIA2 是 AMD 平台走水杉网卡，两者唯一区别是内存 1024G 还是 512G，刊例价完全一致；BMI5 是 Intel 平台的入门款。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMIA2m | T0-CI22AM-50GS | 7K62 × 2 (192vcpu)/ 64 × 16 (1024G)/NVMe-SSD 3.84T × 4 | AMD EPYC 7K62 2.6GHz | 48 | 192 | 水杉1.0 50G × 2P | 空 | 按量付费35.1/h；包年包月18053/m |
| BMIA2 | T0-CI21AM-50GS | 7K62 × 2 (192vcpu)/ 32 × 16 (512G)/NVMe-SSD 3.84T × 4 | AMD EPYC 7K62 2.6GHz | 48 | 192 | 水杉1.0 50G × 2P | 空 | 按量付费35.1/h；包年包月18053/m |
| BMI5 | Y0-MI51M-25G | 8255c × 2/384G(32G × 12)/SSD-480G × 2/NVMe-SSD 3.84T × 2 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 12884 |

## 大数据型

大数据型四款，特征是挂大容量机械盘。BMDA2 是 AMD 平台配十二块 16T 盘；BMD3 和 BMD3c 是十二块 12T 盘，后者多一块 NVMe 做缓存；BMD3w 是密度最高的一款，二十四块 16T SATA 盘，但 CPU 只有 Silver 2.2GHz。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMDA2 | T0-BS24AM-50GS | 7K62 × 2 (192vcpu)/ 32 × 16 (512G)/HDD-16T × 12/NVMe-SSD 3.84T × 1 | AMD EPYC 7K62 2.6GHz | 48 | 192 | 水杉1.0 50G × 2P | 空 | 按量付费38.91/h；包年包月20010/m |
| BMD3 | T0-BS51XM-25GS | 8255c × 2/384G(32G × 12)/HDD-12T × 12/SSD-480G × 2 HBA-IR | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 16780 |
| BMD3c | T0-BS52XM-25GS | 8255c × 2/384G(32G × 12)/HDD-12T × 12/SSD-480G × 2 HBA-IR/NVMeSSD-3.84T × 1 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 19230 |
| BMD3w | T0-SC11XM-25GS | 4214c× 2（48C）/128G（16G × 8)/SSD-480G × 1/SATA-HDD 16T × 24 | Intel Xeon Silver 2.2GHz | 12 | 48 | Stingary SmartNIC | 空 | 14250 |

## 内存型

内存型主打大内存。BMM5c 是四路 Cooper Lake 配 3T 内存，是全清单内存最大的一款；BMM5r 是 768G，BMM5 是 1536G。另外内存型里还有一款 BMM6i，源数据里内部代号、配置、CPU、核数、网卡、刊例价全部为空，属于占位待补充机型，报价前必须单独确认。

| 机型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMM5c | T0-CM53XM-50GS | CPX6 × 4 (208vcpu)/ 64 × 48 (3T) | Intel Xeon Cooper Lake 2.6GHz | 26 | 208 | 水杉1.0 50G × 2P | 空 | 按量付费65.27/h；包年包月33566/m |
| BMM5r | T0-CM51XM-25GS | 8255c × 2/768G(32G × 24)/SSD-480G × 2 RAID1/NVMeSSD-3.84T × 2 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 13630 |
| BMM5 | X0-CM52XM-25GS | 8255c × 2/1536G(64G × 24)/SSD-480G × 2 RAID1/NVMeSSD-3.84T × 2 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 空 | 19680 |
| BMM6i | 空 | 空 | 空 | 空 | 空 | 空 | 空 | 空 |

## Arm 型

Arm 型两款，都是鲲鹏 920 双路、64 物理核、128 vCPU、512G 内存。Arm 平台不开超线程，所以物理核乘以路数就是 vCPU 核数。BMIK1 是高 IO 型，BMDK1 是大数据型，多挂了十二块 12T 的 SATA 机械盘。

| 机型 | 类型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 其他 | 刊例价 |
|---|---|---|---|---|---|---|---|---|---|
| BMIK1 | Arm高IO型 | T0-CS51WM-25GS | Kunpeng 920 × 2/512G(32G × 16)/SataSSD-480G × 1/NVMeSSD-3.84T × 2 | Kunpeng 920 2.6GHz | 64 | 128 | Stingary SmartNIC | 空 | 11458 |
| BMDK1 | Arm大数据型 | T0-BS51WM-25GS | Kunpeng 920 × 2/512G(32G × 16)/SataSSD-480G* × 1/NVMeSSD-3.84T × 1/SataHDD 12 × 12T | Kunpeng 920 2.6GHz | 64 | 128 | Stingary SmartNIC | 空 | 15073 |

## 定制机型

定制机型一共七款，特点是系统盘基本都是单盘 NO-RAID，成本压得更低。这里注意两款同内部代号的：BMGC39me 和 BMTGC39me 都是 T0-GG69XM-25GS，硬件完全一致，八张 3090，但 BMTGC39me 是特惠版，三万七千八百的机器只卖一万八千九。

| 机型 | 类型 | 内部代号 | 配置 | CPU 型号 | 单CPU物理核 | vCPU核数 | 网卡 | 刊例价 |
|---|---|---|---|---|---|---|---|---|
| BMG5tc | 定制机型-GPU型 | T0-GI52XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 1 NO-RAID/NVIDIA-T4 × 2 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 13896 |
| BMGY5（IEG专用） | 定制机型-GPU型 | Y0-G52M-25G | 6231c × 2/256G(32G × 8)/SSD-480G × 4 NO-RAID/T10 × 4 | Intel Xeon Cascade Lake 3.2GHz | 16 | 64 | Stingary SmartNIC | 13168 |
| BMGC28me | 定制机型-GPU型 | Y0-GG56M-25G | 8255c × 2/768G(32G × 24)/SSD-480G × 2 HBA/NVMe-SSD 3.84T × 4/2080ti × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 28600 |
| BMGC39me | 定制机型-GPU型 | T0-GG69XM-25GS | 8255c × 2/768G(32G × 24)/SSD-480G × 2 HBA/NVMe-SSD 3.84T × 2/3090 × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 37800 |
| BMTGC39me | 定制机型-特惠GPU型 | T0-GG69XM-25GS | 8255c × 2/768G(32G × 24)/SSD-480G × 2 HBA/NVMe-SSD 3.84T × 2/3090 × 8 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 18900 |
| BMS5c | 定制机型-标准型 | T0-CS52XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 1 NO-RAID | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 10896 |
| BMI5c | 定制机型-高IO型 | T0-CS53XM-25GS | 8255c × 2/384G(32G × 12)/SSD-480G × 1 NO-RAID/NVMe-SSD 1.92T × 1 | Intel Xeon Cascade Lake 2.5GHz | 24 | 96 | Stingary SmartNIC | 11759 |

## 已 EOL 机型

最后是四款已经 EOL 的机型，源数据里只保留了机型、内部代号和刊例价，配置信息已经不再维护。这四款不再新售，列出来只是为了存量客户续费和历史订单核对时能对上号。

| 机型 | 类型 | 内部代号 | 刊例价 |
|---|---|---|---|
| BMS4 | 已EOL机型-标准型 | Y0-MS41M-25G | 14096 |
| BMSC4 | 已EOL机型-标准型 | Y0-MS47M-25G | 7680 |
| BMD3s | 已EOL机型-大数据型 | Y0-MD53M-25G | 18500 |
| BMD2 | 已EOL机型-大数据型 | Y0-MD41M-25G | 16376 |

## 选型速记

全清单一共三十九款机型。按用途分：通用负载看标准型和定制标准型；单机推理、图形渲染看 GPU 型；多机分布式训练看高性能 GPU 型；低延迟数据库看高主频 IO 型和高 IO 型；离线存储与数仓看大数据型；缓存和内存计算看内存型；国产化替代看 Arm 型；成本敏感、能接受单盘无冗余的场景看定制机型。同一档里的机型差异，往往只在存储的 RAID 方式、GPU 卡型、内存容量和网卡代次上，光看机型名很容易看混——BMG5t 和 BMG5tu、BMIA2m 和 BMIA2、BMGC39me 和 BMTGC39me 都是例子，报价时一定对准内部代号。
