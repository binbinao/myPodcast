# myPodcast

[![GitHub Pages](https://img.shields.io/badge/GitHub_Pages-Live-1f425f?logo=githubpages&logoColor=white)](https://binbinao.github.io/myPodcast/)

把文章、白皮书、长文，自动变成能听的播客。文章 → 分集切分 → 脚本生成 → TTS → RSS/节目站，一条命令跑通。

支持：**长文按章节拆多集、短文单集、单人/双人形式可配**。

## 架构

```
原始文章(raw/) ─┐
                ├─→ [prepare] 分集切分 + 脚本生成 ─→ drafts/(评审门) ─→ [build] TTS ─→ output/ + RSS/站点
腾讯文档/粘贴  ─┘        （全自动走 LLM / 半自动出骨架）
```

| 模块 | 职责 |
|------|------|
| `src/split.py` | 按 H2 章节拆集；单块长文按长度切；过长单章再按 H3/段落细分 |
| `src/generate.py` | 脚本生成：全自动(LLM，按 solo/duo 出 `[host]`/`[guest]`) / 半自动(骨架) |
| `src/prepare.py` | `raw/` 文章 → `drafts/` 草稿（评审门，不直接出音频） |
| `src/build.py` | 把脚本（单文件或目录）生成音频 + shownotes + 刷新 RSS/站点 |
| `src/feed.py` | 生成 shownotes / RSS(`feed.xml`) / 节目站(`index.html`) |
| `src/tts.py` | edge-tts 逐段生成 + ffmpeg 拼接（多角色、自动停顿） |
| `src/polish.py` | LLM 调用封装（OpenAI 兼容） |

## 快速开始

```bash
# 1. 装依赖（隔离 venv，不污染系统）
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. 把文章丢进 raw/（markdown，可带 H2 章节，可写 format: solo/duo）

# 3. 分集 + 生成脚本（落 drafts/，先审）
.venv/bin/python -m src.prepare

# 4. 审 drafts/ 里的脚本，改完再生成音频
.venv/bin/python -m src.build drafts/<系列名>

# 输出：output/<标题>/episode.mp3 + shownotes.md，以及 feed.xml / index.html
```

## 工作流：从文章到节目

1. **放文章**：`raw/你的文章.md`。带 `format: solo|duo` 可指定单人/双人，否则用 `config.yaml` 的 `format` 默认。
2. **分集+生成**：`python -m src.prepare`
   - 有 H2 章节 → 每章一集；无章节的单块长文 → 按 `split.max_episode_chars` 切。
   - 全自动（开 `llm.enable` + `api_key`）直接出高质量口播稿；半自动出 `[host]` 骨架，等人工润色。
   - 结果落到 `drafts/<系列>/ep-01.md …`，**不直接出音频**——这就是评审门。
3. **审 + 改**：编辑 `drafts/` 里的脚本（调口吻、补 `[guest]` 做双人、删冗余）。
4. **生成音频**：`python -m src.build drafts/<系列>` 把整季生成并刷新 RSS。

> 想跳过分集、直接做单集？手写一个带 frontmatter + `[host]`/`[guest]` 标签的脚本，直接 `python -m src.build 它.md` 即可（兼容旧用法）。

## 脚本格式

```markdown
---
title: "节目标题"
format: duo            # solo / duo
series: "系列名"        # 多集时填，用于 RSS 排序
episode: 1
total: 3
description: "一句话简介"
---

[host] 开场白……
[guest] 回应……          # duo 时交替；solo 时全部 [host]
```

## 配置（config.yaml）

- `format`：默认单人/双人。
- `raw_dir` / `drafts_dir`：文章源 / 草稿目录。
- `split.min_episode_chars` / `max_episode_chars`：分集阈值。
- `voices`：角色→edge-tts 音色映射（host/guest/default）。
- `tts`：语速/音量/停顿。
- `llm`：全自动脚本生成的接口（OpenAI 兼容，支持 Azure/本地模型）。

## 换音色 / 发布 / 备注

见旧版说明：edge-tts 中文音色任选（`zh-CN-XiaoxiaoNeural` 女温暖 / `zh-CN-YunxiNeural` 男活力 …）；
`output/index.html` + `feed.xml` 部署到静态托管并把 `podcast.website` 改成域名即可被小宇宙/苹果播客订阅；
edge-tts 公共端点偶发抖动已内置 3 次重试。
