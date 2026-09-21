# myPodcast

[![GitHub Pages](https://img.shields.io/badge/GitHub_Pages-Live-1f425f?logo=githubpages&logoColor=white)](https://binbinao.github.io/myPodcast/)

把文章、白皮书、长文，自动变成能听的播客。每篇文章按结构智能拆集，LLM 改写为口播稿，TTS 合成多角色音频，产出一个完整 RSS + 节目站。

特点：**长文按章节拆多集、短文单集、单人/双人形式可配**；**LLM 全自动与人工润色半自动双模式**；TTS 后端可切换——默认走**本机 Qwen3-TTS**（零边际成本 / 离线 / Apache-2.0 可商用），也可切 edge-tts（免费轻量）、MiniMax Speech 2.8 HD（8 种情绪 + 22 拟声词）、SCNet Qwen3-TTS、Fish Audio。

---

## 5 分钟跑通

```bash
# 0. 准备 venv（隔离，不污染系统）
# 0. 准备 venv（隔离，不污染系统）。需要 Python 3.13+
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 1. 一篇 markdown 扔进 raw/（frontmatter 可加 format: solo|duo、series_slug: <英文>）
# 2. 准备脚本（评审门，审完再生成音频）
.venv/bin/python -m src.prepare
# 3. 编辑 drafts/ 里的脚本（按你的口吻调整 [host]/[guest]），审完标记
.venv/bin/python -m src.prepare --mark-reviewed drafts/<系列目录>
# 4. 生成音频 + 刷新 RSS / 节目站（build 只读 drafts，不会覆盖你的修改）
.venv/bin/python -m src.build drafts/<系列目录>
```

输出：`output/series/<series_slug>/ep-NN/episode.mp3 + shownotes.md`，加 `feed.xml` / `index.html` / `manifest.json`。
节目站自动部署到 GitHub Pages：<https://binbinao.github.io/myPodcast/>。

---

## 架构：raw → drafts → output 三层评审门

```
                        ┌─────────────┐
   raw/ 文章             │             │        drafts/ 脚本
  (YAML frontmatter      │  src.prepare│        (评审门)
   + markdown body)  ───▶│   +split    │───▶     [host]/[guest] ──▶  src.build ─▶ output/
                        │   +generate │                                    │
                        │  (LLM/skel) │                                    ▼
                        └─────────────┘                              TTS + shownotes
                                                                     + feed.xml + 站点
                                                                   (src/tts + src/feed)
```

| 层 | 角色 | 关键决策 |
|---|---|---|
| **raw/** | 源文章（MD + frontmatter） | frontmatter：`title` / `date` / `format` / `series_slug` / `source` |
| **drafts/** | **评审门**，半成品脚本 | `LLM 全文产出` 或 `骨架`；人可以改 `[host]/[guest]` 文案；`ai_stage` 记录审阅状态 |
| **output/** | 已审完的最终产物 | mp3 + shownotes + manifest，**入库 git 跟踪**（CI skip-audio 模式必需） |

### 关键模块

| 模块 | 职责 |
|---|---|
| `src/split.py` | 按 H2 章节拆集；单块长文按 `max_episode_chars` 切；过长单章再按 H3/段落细分；产出 `EpisodePlan` |
| `src/generate.py` | 脚本生成。全自动（LLM，按 `format` 出 solo/duo）/ 半自动（骨架）。**auto 模式调 llm.llm_complete**，产出的 draft 自带 `ai_stage` |
| `src/stages.py` | **draft 生命周期**：`ai_stage` = skeleton → generated → reviewed → frozen。build 据此告警；`set_stage` 只改这一行，正文逐字节保留 |
| `src/llm.py` | LLM 调用工具（OpenAI 兼容）+ 文本清洗；`resolve_api_key` 支持 cfg-first + env-兜底；自动给 MiniMax 加 `reasoning_split + thinking.disabled`；payload 读 cfg 的 `max_tokens` / `temperature`。（原名 `polish.py`，2026-09-21 更名——`polish()` 已随 build 只读契约废弃） |
| `src/prepare.py` | `raw/` → `drafts/` 流水线入口；`--mark-reviewed` / `--freeze` 改 stage |
| `src/build.py` | `drafts/` → `output/`。**draft 只读**（不再做 LLM 二次改写）。**支持断点续传**：manifest 含 `source_hash`，未变跳过；`--only ep-XX` / `--from ep-XX` / `--retry-failed` / `--force` |
| `src/tts.py` | TTS backend registry：`@register` 抽象。支持 qwen3-local（本机，默认）/ edge-tts / minimax / qwen-tts（SCNet 云）/ fish-speech |
| `src/backends/{qwen3_local,edge,minimax,qwen_tts,fishspeech}.py` | TTS 后端实现 |
| `src/backends/qwen3_local.py` | 本机 Qwen3-TTS 后端（客户端）；服务实现体在 `scripts/qwen3-tts-local/` |
| `src/prosody.py` | 韵律规划。heuristic（零依赖，按标点） / llm（按情绪打标）；缓解单人播客单调 |
| `src/voicecaster.py` | 智能音色选型。frontmatter `voice` > LLM 推断 > 启发式 5 类文章分类 > 默认 |
| `src/feed.py` | shownotes / RSS(`feed.xml`) / 暗色节目站(`index.html`) |
| `src/validate.py` | 脚本质量门禁：emoji / 零宽字符 / markdown 残留 / 长度 / 角色标签完整性 |
| `src/log.py` | `--log-file` + `--log-level` 标准化日志（idempotent configure） |
| `src/naming.py` | `chinese_to_ascii` / `drafts_dir_for` / `ep_output_dir` |

---

## 命名规则（三层都用 slug 而非中文）— **hard gate 自动 enforce**

| 层 | 路径 | 字段来源 |
|---|---|---|
| raw/ | `raw/YYYY-MM-DD-slug.md` | frontmatter `series_slug` → `slug` → 标题自动（pinyin 兜底） |
| drafts/ | `drafts/YYYY-MM-DD-slug/ep-XX.md` | 同上 |
| output/ | `output/series/<series_slug>/ep-NN/episode.mp3 + shownotes.md` | `series_slug` 字段 |

**Hard gate**：`python -m src.prepare` 与 CI 在 push 时都会先跑 `naming_enforce`，
把不合规的物理 rename 自动修对：

- 入口钩子：`src/prepare.py:run()` 在扫描 raw/ 前调 `enforce_raw_files` + `enforce_drafts_dirs`
- CI 守护：`.github/workflows/publish.yml` 单测后跑 `naming_enforce`（exit 2 → workflow fail）
- 冲突保护：目标已存在则 skip + log，绝不覆盖

```bash
# 本地手动 enforce（dry-run 不修改）
.venv/bin/python -m src.naming_enforce --dry-run

# 实测：CI 命中违规时的修复方式
.venv/bin/python -m src.naming_enforce    # 自动改名
git status                                # 看到 rename 改动
git add -A && git commit -m "fix(raw): enforce naming" && git push
```

迁移脚本：`scripts/migrate_naming.py` 处理存量命名一致性。
src 实现：`src/naming.py:pick_series_slug()` 给 naming/ 场景（series 目录名），
`pick_slug()` 给 generate/split 场景（文件级 KV）—— 优先级不同。

---

## 关键设计决策（与坑）

### 评审门：raw → drafts → output

- `prepare` 把脚本落 `drafts/`，**不**直接出音频——防止 LLM 一次性把浪费 TTS 资源出成不可改的成稿。
- `build` 读 `drafts/`，是唯一通往 `output/` 的路径。
- `manifest.json` 的 `source_hash = sha256(source)[:16]` 让 build 知道哪些集已合成、可断点续传。

### draft 只读 + `ai_stage` 生命周期

`drafts/` 是评审门，落盘即事实源。**build 只读，绝不改写正文。**

```
skeleton  ── prepare 时无 LLM key，未口语化的骨架稿
generated ── LLM 改写产出，未经人工审阅
reviewed  ── 人工审阅通过
frozen    ── 锁稿：同 reviewed，额外声明不再重生成
```

build 消费 draft 时按 stage 告警（`reviewed`/`frozen` 静默，其余提示下一步动作）。
无 `ai_stage` 的 legacy draft 只告警不阻断。

```bash
# 审完 drafts/ 里的脚本后标记，消除 build 告警
.venv/bin/python -m src.prepare --mark-reviewed drafts/<系列目录>
.venv/bin/python -m src.prepare --freeze drafts/<系列目录>      # 锁稿
```

**为何 build 不能改写**：重构前 `build.py` 无条件跑 `polish()` 二次 LLM 改写，
而 draft 本身已是 `generate._auto()` 的 LLM 产物 —— 后果是人工在 `drafts/` 的修改被吃、
LLM 成本翻倍、同一 draft 每次 build 输出不同（不可复现）。
这条契约由 `tests/test_stages.py::TestBuildReadOnlyContract` AST 扫描机械 enforce：
`build.py` 一旦重新 import `llm`、或调用 `llm_complete()` / `heuristic_clean()`，测试立即 fail。
（那个已被废弃的 `polish()` 整篇改写入口本身也已删除，不会复活。）

### TTS 后端切换

| 后端 | 代价 | 优势 | 何时用 |
|---|---|---|---|
| **qwen3-local** | **零边际成本**（本机算力） | 可商用(Apache-2.0)、离线、9 个跨语种音色、自然语言控制语气 | **当前默认**：日常出片 |
| edge-tts | 免费 | 零 key、低延迟、稳定性已加 3 次重试 | 开发 / 烟雾测试 / CI 默认（TTS_BACKEND=edge-tts） |
| MiniMax Speech 2.8 HD | 按字符 | 8 种情绪 + 22 拟声词、HD 拟人化 | 要最快出片 / 高拟人度时 |
| qwen-tts | 按字符（SCNet） | Instruct 自然语言控语气 | 云上的 Qwen 路线 |
| fish-speech | 按量（Fish Audio） | OpenAudio S2，可自建音色 | 需要专属克隆音色时 |

`src/tts.py` backend 路由 `cfg.tts.backend → backends.<name>`。切换**只改 config**，不改业务代码。
加新后端只需在 `src/backends/` 新建文件用 `@register` 注册。

MiniMax 的 `mp3` 响应 mime 标签是 `mp4a`（实际编码是 mp3），ffmpeg concat filter 会 exit 234；已通过 `aformat=sample_fmts=fltp:sample_rates=32000:channel_layouts=mono` 归一化每段解决。

#### qwen3-local（本机 Qwen3-TTS，当前默认）

跑本机 `Qwen3-TTS-12Hz-1.7B-CustomVoice`，独立 Python 环境 + 常驻 HTTP 服务，
与仓库 `.venv` 完全隔离（模型要 torch 2.14 + transformers 4.57，塞进仓库会污染依赖）。

```bash
./scripts/start-qwen-tts-local.sh          # 必需：先起服务（127.0.0.1:8100）
.venv/bin/python -m src.build drafts/<...> 
```

实现与部署细节见 `scripts/qwen3-tts-local/README.md`。要点：

- **实测 RTF 2.2**（M1 Pro 32GB / MPS / float16）→ 一集 15 分钟约需 **33 分钟**机时，与音色/文本无关。
  因为是算力瓶颈，进度可见性很关键：backend 按 `chunk_chars` 分块逐块请求，每块打印
  `[n/N] 音色 字数 已用/预计剩余`。
- **音色**：`voices_qwen3local` 配置 `host/guest/default`。9 个预置音色见服务 `/v1/audio/voices`。
- **历史稿件零改动可跑**：frontmatter 里的 `host_voice: audiobook_male_1` 等 minimax ID
  不是本机音色，`build.py` 会记一行日志并回退到 `voices_qwen3local`，不会报错。
- 服务没起时会**立刻报错并给出启动命令**，不会重试到超时。
- **只影响新出片，不动存量**：切默认后端不会重渲已有 mp3。仓库现有 81 集（≈8.1 小时音频）是 minimax
  时代产物，声线仍是旧的；要统一成"醇厚低沉 + 温暖柔和"这套本机音色，需 `--force` 重跑，
  按 RTF ≈2.1 估算全量约 **17 小时机时**（建议按系列分批，一次一个系列）。
- 守护测试 `tests/test_default_tts_backend.py`：钉住「默认后端 = qwen3-local」、音色路由与 duo 回退
  分支，纯静态断言（不连模型/服务），可进 CI。

### LLM 后端：MiniMax chat（OpenAI 兼容）

`config.yaml` 的 `llm:` 一段：

```yaml
llm:
  enable: true
  base_url: "https://api.minimaxi.com/v1"
  api_key: ""               # 留空：自动用环境变量 MINIMAX_API_KEY
  model: "MiniMax-M2.5"     # 便宜优先；要更强推理换 MiniMax-M3
  max_tokens: 4000          # 单集口播稿 ~3000-4000 字；1500 会截断长稿
  temperature: 0.7
```

**必须传 `reasoning_split: true` + `thinking: {type: "disabled"}`**（llm.py 自动检测 MiniMax 端点自动加）。否则 M2.x 默认开 adaptive thinking，把 tokens 全烧在 reasoning，`message.content` 为空。

### 密钥不落盘

`src/llm.py:resolve_api_key()` 解析优先级：`cfg.api_key` → env `LLM_API_KEY` → `MINIMAX_API_KEY` → `OPENAI_API_KEY`。`config.yaml` 可以安全提交，敏感 key 全在 zshrc / CI secrets。

zshrc 例：

```sh
export MINIMAX_API_KEY="sk-cp-..."
```

### 智能音色（voicecaster）

5 类文章信号 → 音色映射：

- `reflective`（反思独白）→ `audiobook_male_1`
- `tutorial`（教程）→ `male-qn-jingying`
- `business`（商务）→ `male-qn-badao`
- `casual`（闲谈）→ `female-yujie` / `male-qn-qingse`
- `interview`（访谈）→ 拆分 host/guest

优先级：frontmatter `voice:` 显式 > LLM 推断（mode=llm）> 启发式规则 > `default_voice`。

### 单调语调缓解（prosody）

`src/prosody.py` 把口播文本切成带 prosody 标记的句片段：

- `heuristic`（默认，零依赖）：按句末标点（问句 / 感叹 / 省略 / 分号 / 连续句号）给每句 `rate` / `pitch` / `break_ms` 注入变化 + 轻微正弦波形
- `llm`：调 LLM 给每句打情绪标签（neutral/happy/excited/...）→ 映射 prosody

TTS 后端消费：`edge-tts` 用 rate/pitch；`minimax` 用 emotion 字段。

### 脚本质量门禁（src/validate.py）

`src/build` 自动化每集校验：

- 无 emoji（避免被 TTS 念出 / 视觉垃圾）
- 无零宽字符
- markdown 残留（标题、列表符）已清
- 长度上下界
- `format` 对应的角色标签完整性

P0 缺陷直接拒生成，下到草稿。

### Git 工作流

- `raw/`、`drafts/`、`output/` **全部入库**（commit fd94ce4 起）。mp3 是付费 TTS 的最终交付物，必须随仓库走，CI 用 `--skip-audio` 不重新合成。
- `.gitignore` 只排 `__pycache__/`、`.venv/`、`output/manifest.json.bak`、`.DS_Store`、`.workbuddy/`。
- 推荐工作流：本地 test → `prepare` → 审 `drafts/` → `build` → `git add -A && git commit -m "..." && git push` 触发 gh-pages 部署。

### CI 部署（.github/workflows/publish.yml）

push 到 main 自动构建并部署到 gh-pages，**走 skip-audio 模式**：不动 mp3，只重渲 `feed.xml` / `index.html` / `style.css` / `shownotes.md`。

---

## 站点访问统计（GoatCounter）

5 分钟接入，默认关闭，无副作用：

1. 访问 [goatcounter.com/start](https://www.goatcounter.com/start) 注册（免费 hobby 档）
2. 添加站点 `binbinao.github.io/myPodcast` → 拿 8 字符 site code
3. Settings → "Allow API access" 开 → 复制 token
4. 填 `config.yaml` 的 `podcast.analytics` 块：

   ```yaml
   podcast:
     # ... 其他字段
     analytics:
       enabled: true
       code: "<your_code>"
       api_key: "<your_token>"
   ```

5. `python -m src.build drafts/<某系列>` → push → 看 `output/index.html` `<head>` 有 GC script、footer 有 stats

**失败兜底**：API key 错 / 网络超时 → widget 不渲染，build warn 但继续（不影响发布）。
**国内 CI 提示**：如果 build 时拉 GC 超时，fetch_stats 失败但 build 仍绿，部署的 HTML 不带 footer 数字。属预期行为。

---

## 单测

```bash
.venv/bin/python -m unittest discover -s tests -v
```

234 个 case，覆盖命名 / 校验 / voicecaster / split / stage 契约 / 血缘 / output 契约 / 续传判定等模块。零外部依赖。

其中 `test_stages.py::TestBuildReadOnlyContract` 是**机械守卫**：AST 扫描 `build.py`，
一旦重新 import `llm`、或调用 `llm_complete()` / `heuristic_clean()` 就 fail ——
让"draft 只读"这条规范不只是注释。
`test_lineage.py` 与 `test_output_contract.py` 是另两条同类守卫，分别守
raw→drafts→output 的血缘登记、以及 output/ 作为发布件的完整性。

---

## 项目约定

- **代码组织**：单文件 ≤ 300 行；目录分层（routes / controllers / services / repositories，依赖只向下）；入口文件只装配零业务。
- **Shell 入口**：`python -m src.xxx`；不写 `scripts/` 启动器。
- **依赖**：`requirements.lock` 由 `pip freeze | grep ...` 自动生成，CI 用它精确钉版本。
- **Python 版本**：3.13（managed venv，不引 pydub——3.13 缺 audioop，音频拼接一律 ffmpeg）。
- **emoji / 紫粉渐变 / 空洞占位文案** 是 P0 绝对禁用。图标统一 SVG。
