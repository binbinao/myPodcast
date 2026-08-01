# myPodcast — 项目长期笔记

## 定位
文字转语音播客流水线：文章/白皮书/长文 → 润色 → TTS → RSS/节目站。个人内容资产的"听化"工具。

## 技术约定（硬约束）
- 运行环境：managed Python 3.13 venv = `/Users/jiduobin/.workbuddy/binaries/python/envs/default`
- **绝不引入 pydub**（3.13 无 audioop）。音频拼接一律用 ffmpeg concat + filter_complex。
- TTS 用 edge-tts，端点偶发抖动，生成需带重试。
- 脚本格式：markdown frontmatter + `[host]`/`[guest]` 角色标签，见 README。

## 下一步可能方向
- LLM 润色接入（配置 api_key 即可，接口已留）。
- 接付费 TTS（Azure/ElevenLabs）提升音质，只改 tts.py，接口不变。
- 部署 output/ 到静态托管，改 config.yaml 的 podcast.website 供订阅。
