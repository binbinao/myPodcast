# qwen3-tts-local

本机 TTS 服务：**Qwen3-TTS-12Hz-1.7B-CustomVoice**（Apache-2.0，可商用），跑在 Apple Silicon 上，零边际成本、离线可用。

给 `myPodcast` 当 `backend: qwen3-local`，也可给任何需要本地语音合成的项目用（OpenAI 兼容 HTTP 接口）。

---

## 实测数据（本机 M1 Pro 32GB，2026-09-21）

| 指标 | 实测值 | 说明 |
|---|---|---|
| 设备 / 精度 | `mps` / `float16` / `sdpa` | 开箱即用，无需 flash-attn |
| 模型加载 | **2.1–3.8 s** | 本地磁盘读取，进程内常驻一次 |
| **RTF（热态）** | **2.2** | 9 个音色 × 3 种语言实测 2.17–2.30，非常稳定 |
| RTF（冷启动首句） | 3.5–4.3 | 含 MPS kernel 编译，服务启动已预热掉 |
| 输出 | 24 000 Hz / 单声道 / 零削顶 | 峰值 0.26–0.76，RMS 0.04–0.11 |
| 进程内存 | ~880 MB | 模型权重 4.2 GB 在磁盘，按需 mmap |
| 磁盘占用 | 4.21 GB | 含 12Hz speech tokenizer |

**换算成工期**：RTF 2.2 → 一集 15 分钟的播客约需 **33 分钟**生成。这是这台机器的硬上限，与音色/文本无关（算力瓶颈，不是 IO 瓶颈）。

参考对比：MiniMax 云 API 约 1–3 分钟出 15 分钟音频，但按量计费、音色不可完全自定义。**本地方案买的是"可控 + 零成本 + 离线"，代价是时间。**

---

## 系统要求

- macOS on Apple Silicon（M 系列）。Intel Mac 只能跑 CPU，会更慢（未实测）
- **不需要** NVIDIA GPU / CUDA
- 磁盘 ≥ 5 GB（模型 4.21 GB）
- `ffmpeg`（转 mp3、拼接）：`brew install ffmpeg`
- Python 3.12（独立环境，见下）

---

## 安装

### 1. Python 环境

模型依赖与项目环境隔离，用独立 venv：

```bash
VENV=/Users/jiduobin/.workbuddy/binaries/python/envs/qwen-tts
python3.12 -m venv "$VENV"
"$VENV/bin/pip" install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
"$VENV/bin/pip" install torch torchaudio qwen-tts -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> **坑**：`pip` 走国内镜像时**不要**设 `ALL_PROXY`/`HTTPS_PROXY` 为 `socks5h://`——pip 缺 PySocks 会直接报
> `Missing dependencies for SOCKS support`。代理只在拉 HuggingFace 权重时需要。

### 2. 模型权重（4.21 GB）

已下载至 `/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice`。

重新下载时的**最佳通道组合**（实测，2026-09-21）：

| 通道 | 适合 | 实测速度 |
|---|---|---|
| `hf-mirror.com` 的 LFS 文件 | 大权重（会 302 到 xet CDN） | **28–34 MB/s** |
| `hf-mirror.com` 的普通小文件 | ❌ 慢 | ~21 KB/s |
| ModelScope | 小文件（config/vocab/merges） | 快 |
| `huggingface.co` 走 socks5 代理 | 兜底 | 1.2 MB/s |

```bash
REPO=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
DEST=/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice
# 大文件走 hf-mirror
curl -L -C - -o "$DEST/model.safetensors" \
  "https://hf-mirror.com/$REPO/resolve/main/model.safetensors"
# 小文件走 ModelScope
curl -sL -o "$DEST/vocab.json" \
  "https://www.modelscope.cn/api/v1/models/$REPO/repo?Revision=master&FilePath=vocab.json"
```

**必须校验 sha256**（HF API 的 LFS oid）：

```
model.safetensors                  3833402552  B  38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137
speech_tokenizer/model.safetensors  682293092  B  836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258
```

> **坑**：`curl -C -`（断点续传）+ 「文件存在就跳过」这两个逻辑叠加，会**静默保留截断文件**。
> 本次安装就中招：`vocab.json` 停在 2 555 904 B（应 2 776 833 B），因为它是上一次被中断的残留，
> 续传脚本看到非空就跳过了。**下载完必须逐个比对字节数**，别只看"文件在不在"。

---

## 用法

### 起服务

```bash
# 这个实现体就住在播客仓库里，从仓库根目录用统一入口起（推荐）：
cd <myPodcast 仓库根>
./scripts/start-qwen-tts-local.sh

# 或者直接操作实现体本身：
cd <myPodcast 仓库根>/scripts/qwen3-tts-local
./run.sh --daemon     # 后台启动（日志 logs/server.log，pid logs/server.pid）
./run.sh --status     # 看状态
./run.sh --stop       # 停
./run.sh              # 前台，看实时日志
```

就绪后 <http://127.0.0.1:8100/docs> 有交互式 API 文档。

### HTTP 接口（OpenAI 兼容）

```bash
# 单句合成
curl -X POST http://127.0.0.1:8100/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"大家好，欢迎收听。","voice":"Serena","response_format":"mp3"}' \
  -o out.mp3

# 带语气指令
curl -X POST http://127.0.0.1:8100/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"这不可能！","voice":"Vivian","instruct":"用惊讶的语气"}' -o out.wav

# 列出音色
curl http://127.0.0.1:8100/v1/audio/voices
```

| 端点 | 说明 |
|---|---|
| `GET /health` | 状态、设备、RTF、累计合成时长 |
| `GET /v1/models` | OpenAI 兼容模型列表 |
| `GET /v1/audio/voices` | 9 个音色元信息（性别/母语/描述） |
| `POST /v1/audio/speech` | `{input, voice, language, instruct, response_format, speed}` |
| `POST /v1/audio/segments` | 多角色批量，段间自动插停顿 |

### 命令行

```bash
V=/Users/jiduobin/.workbuddy/binaries/python/envs/qwen-tts/bin/python
$V cli.py voices                                  # 列音色
$V cli.py say "大家好" --voice Serena -o a.wav     # 单句
$V cli.py audition -o voices-demo.mp3             # 9 音色各一段，试听对比
$V cli.py script dialogue.txt -o ep.mp3 \
     --voice-map "小搭=Serena,斌哥=Uncle_Fu" --pause-ms 500
```

---

## 音色表（模型预置，不可自建）

| 音色 | 性别 | 母语 | 定位 |
|---|---|---|---|
| **Vivian** | 女 | 中文 | 明亮微飒，偏活泼 |
| **Serena** | 女 | 中文 | 温暖柔和，适合讲述/陪伴 |
| **Uncle_Fu** | 男 | 中文 | 醇厚低沉，成熟沉稳 |
| **Dylan** | 男 | 中文（北京） | 京腔青年，清亮自然 |
| **Eric** | 男 | 中文（成都） | 成都口音，活泼带沙哑 |
| **Ryan** | 男 | 英文 | 节奏感强 |
| **Aiden** | 男 | 英文 | 阳光美式 |
| **Ono_Anna** | 女 | 日文 | 轻快日系 |
| **Sohee** | 女 | 韩文 | 温暖韩系，情感丰富 |

**这是 CustomVoice 模型的固定 9 个音色，改不了。** 想要专属音色（比如克隆真人、或 VoiceDesign 造一个非人类质感的声音），需要另外的路线：

1. **VoiceDesign + Base 克隆**：用 `Qwen3-TTS-12Hz-1.7B-VoiceDesign` 用文字描述生成一段参考音频 → 用 `Qwen3-TTS-12Hz-1.7B-Base` 的 `create_voice_clone_prompt` 固化成可复用音色。多下 2 个模型（各约 4 GB），但之后完全一致。
2. **微调**：`1.7B-Base` 支持 FT。

---

## 接进 myPodcast

`myPodcast/config.yaml` 已配置好：

```yaml
tts:
  backend: "qwen3-local"
  qwen3_local:
    base_url: "http://127.0.0.1:8100"
    chunk_chars: 200
    use_emotion: true
voices_qwen3local:
  host: "Uncle_Fu"
  guest: "Serena"
  default: "Uncle_Fu"
```

```bash
cd ~/Documents/GitHub/Personal/myPodcast
./scripts/start-qwen-tts-local.sh          # 先起服务（必需）
.venv/bin/python -m src.build drafts/<目录或单集>.md
```

设计要点：

- **逐块请求 + 本地 ffmpeg 拼接**（不是服务的批量端点）：M1 Pro 上 RTF 2.2，一集 15 分钟要跑 33 分钟，
  **必须能看进度**。每块打完打印 `[n/N] 音色 字数 已用/预计剩余`。
- **`chunk_chars: 200`**（约 45 秒音频/块）：块小 → 进度细 → 单块重试代价小。
- **健康检查前置**：服务没起时立刻报错并给出启动命令，不会重试到超时。
- **历史稿件的 minimax 音色 ID 会被自动忽略**：`frontmatter` 里的 `host_voice: audiobook_male_1`
  不是本机音色，`build.py` 会记一行日志并回退到 `voices_qwen3local` 的配置，**已有稿件零改动可跑**。

切回云端：把 `tts.backend` 改回 `minimax`（或 `qwen-tts`）即可，本机服务可以继续挂着不管。

---

## 已知限制

| 限制 | 影响 | 缓解 |
|---|---|---|
| RTF 2.2 | 一集 15 分钟 → 33 分钟机时 | 批量任务挂夜里跑；草稿阶段用 `edge-tts` 快筛 |
| MPS 部分算子回退 CPU | 已在内核层处理（`device_type != "mps"` 则走 cpu），无需干预 | 无 |
| 无 flash-attn | 推理稍慢，但可用 | Apple Silicon 装不了，接受 |
| 9 个固定音色 | 无法自定义 | 走 VoiceDesign + Base 克隆路线 |
| `sox` 二进制缺失 | 只影响 25Hz tokenizer，本模型（12Hz）不用 | 无需处理，报错可忽略 |
| 长文本 | `max_new_tokens` 默认 8192 @12.5 fps ≈ 最长 655 秒/次 | 靠 `chunk_chars` 分块，不会碰到上限 |

---

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `本地 Qwen3-TTS 服务未就绪` | 服务没起 | `./scripts/start-qwen-tts-local.sh` |
| `Unknown speaker` | 音色名不在 9 个里 | 大小写敏感，`Uncle_Fu` 不是 `uncle_fu` |
| `port 8100 already in use` | 残留进程 | `./run.sh --stop` 会清端口 |
| 启动 90s 未就绪 | 模型首次加载慢 / 磁盘冷 | 看 `logs/server.log` |
| `Missing dependencies for SOCKS support` | pip 被 socks 代理污染 | 取消 `ALL_PROXY` 等环境变量 |
| 音色听起来不像中文母语者 | 用了非中文音色说中文 | 模型卡明确建议**用各音色的母语**效果最好 |
