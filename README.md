# myPodcast

把文章、白皮书、长文，自动变成能听的播客。文字 → 润色 → TTS → RSS/节目站，一条命令跑通。

## 架构

```
myPodcast/
├── config.yaml          # 节目信息 / 角色音色 / TTS 参数 / 可选 LLM 润色
├── episodes/            # 播客脚本（markdown，带 frontmatter + [角色] 标签）
├── src/
│   ├── ingest.py        # 解析脚本：frontmatter 元数据 + [角色] 分段
│   ├── polish.py        # 润色：可选 LLM（OpenAI 兼容），默认启发式清洗
│   ├── tts.py           # edge-tts 逐段生成 + ffmpeg 拼接（多角色、自动停顿）
│   ├── feed.py          # 生成 shownotes / RSS(feed.xml) / 节目站(index.html)
│   └── build.py         # 编排 CLI
└── output/              # 生成产物（每集一个目录 + 全局 feed/index）
```

## 快速开始

```bash
# 1. 装依赖（用隔离 venv，不污染系统）
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. 跑一集
.venv/bin/python -m src.build episodes/00-demo-why-podcast.md

# 输出：
#   output/<标题>/episode.mp3   单集音频
#   output/<标题>/shownotes.md  逐段文稿
#   output/feed.xml             RSS（可直接订阅）
#   output/index.html           节目站（带播放器）
```

依赖：`edge-tts`（TTS）、`PyYAML`（配置），系统需有 `ffmpeg`（macOS: `brew install ffmpeg`）。

## 写一集脚本

`episodes/` 下新建 `.md`，格式：

```markdown
---
title: "节目标题"
description: "一句话简介"
host: "小搭"
guest: "斌哥"          # 没有嘉宾就删掉这行
date: "2026-08-01"
---

[host] 开场白……
[guest] 回应……
[host] 过渡……
```

- 角色标签 `[host]` / `[guest]` 对应 `config.yaml` 里的 `voices` 映射。
- 不加标签的行归入 `default` 角色（单人播客场景）。

## 润色：让书面文变口播稿

- **默认（启发式）**：只做轻量清洗（去 markdown 标记、去列表符），假设输入已是口播稿。
- **LLM 润色（推荐）**：在 `config.yaml` 填 `llm.api_key` 并设 `llm.enable: true`，
  会把书面正文改写成 `[host]`/`[guest]` 交替的口语脚本。支持任何 OpenAI 兼容接口
  （改 `llm.base_url` 可用 Azure / 本地模型）。

## 换音色

`config.yaml` 的 `voices` 改成任意 edge-tts 中文音色，例如：

- `zh-CN-XiaoxiaoNeural`（女，温暖）
- `zh-CN-YunxiNeural`（男，活力）
- `zh-CN-YunyangNeural`（男，新闻）
- `zh-CN-XiaoyiNeural`（女，温柔）

## 发布

`output/index.html` 是现成节目站，`output/feed.xml` 是标准播客 RSS。
把 `output/` 部署到任意静态托管（GitHub Pages / CloudStudio / Vercel），
并把 `config.yaml` 里 `podcast.website` 改成你的域名即可被苹果播客、小宇宙等订阅。

## 备注

- edge-tts 免费但走微软公共端点，偶发抖动已内置 3 次重试。
- 对音质/稳定性有更高要求时，把 `tts.py` 换成 Azure / ElevenLabs 等付费 TTS 即可，接口不变。
