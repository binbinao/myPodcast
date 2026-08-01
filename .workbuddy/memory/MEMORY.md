# myPodcast — 项目长期笔记

## 定位
文字转语音播客流水线：文章/白皮书/长文 → 润色 → TTS → RSS/节目站。个人内容资产的"听化"工具。

## 技术约定（硬约束）
- 运行环境：managed Python 3.13 venv = `/Users/jiduobin/.workbuddy/binaries/python/envs/default`
- **绝不引入 pydub**（3.13 无 audioop）。音频拼接一律用 ffmpeg concat + filter_complex。
- TTS 用 edge-tts，端点偶发抖动，`src/tts.py _speak` 内置 3 次重试。
- 脚本格式：markdown frontmatter + `[host]`/`[guest]` 角色标签，见 README。

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
