# myPodcast — 项目长期笔记

## 定位
文字转语音播客流水线：文章/白皮书/长文 → 润色 → TTS → RSS/节目站。个人内容资产的"听化"工具。

## 技术约定（硬约束）
- 运行环境：managed Python 3.13 venv = `/Users/jiduobin/.workbuddy/binaries/python/envs/default`
- **绝不引入 pydub**（3.13 无 audioop）。音频拼接一律用 ffmpeg concat + filter_complex。
- TTS 用 edge-tts，端点偶发抖动，`src/tts.py _speak` 内置 3 次重试。
- **edge-tts 的 `Communicate(text=...)` 只接受纯文本，绝不能传完整 `<speak>` SSML**——实测会被错误合成成超长音频（单句 5 字变 36s）。逐句韵律必须用「每句一次 `Communicate(text=单句, rate=, pitch=)`，ffmpeg 拼 + 句间静音」实现。
- 脚本格式：markdown frontmatter + `[host]`/`[guest]` 角色标签，见 README。

## 单人播客语调单调问题（档 A 已落地）
- 根因：旧 `tts.py` 整段用同一全局 rate/pitch，无句间起伏。
- 档 A（已做，零成本）：新增 `src/prosody.py` 韵律规划器 + `tts.py` 改逐句 `Communicate` 带各自 rate/pitch，句间/段间静音用 ffmpeg。
  - heuristic 模式（默认零依赖）：问句升调略慢、感叹加重、省略放慢、分号紧凑、连续句号句叠加轻微正弦波形(-4%~+4% rate / ±3Hz pitch)避免全平。
  - llm 模式：`config.yaml prosody.mode=llm` + `llm.enable=true` + api_key，调 LLM 给每句打情绪标签(neutral/happy/excited/...)→映射 prosody。
  - 必须清洗 emoji/零宽字符（否则被 TTS 念出/乱读）。
- 待评估档 B（治本）：换 **Fish Audio**（中文 TTS-Arena 2026 #1，文本内 `(excited)(whisper)` 行内切情绪，50+ 情绪，$11/月），只改 tts.py backend 抽象，接口不变。相比 edge-tts 能在句内前半严肃后半激动。

## 流水线设计决策（斌哥拍板）
- 文章→播客：长文按 H2 章节拆多集，短文单集，支持 solo/duo。
- **双模式**：半自动(小搭写稿/骨架，无需 key) 与 全自动(LLM API) 都支持，目标全自动。
- **评审门**：prepare 把脚本落 `drafts/`，不直接出音频；审完 `build drafts/<系列>` 才生成。
- 分集原则：**多章节每章一集，不按字数合并**；仅单块长文按 max_episode_chars 切，超长单章按 H3/段落再切。
- 单/双人：每篇 frontmatter `format:` 指定，全局 `config.yaml format` 兜底。

## 下一步可能方向
- LLM 润色接入（配置 api_key 即可，接口已留）。
- 接付费 TTS（Azure/ElevenLabs）提升音质，只改 tts.py，接口不变。
- 部署 output/ 到静态托管，改 config.yaml 的 podcast.website 供订阅。
