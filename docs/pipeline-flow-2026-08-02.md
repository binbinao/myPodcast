# myPodcast 全流程 Mermaid 图集（2026-08-02 review）

> 从一篇 markdown 文章到可订阅的播客站，完整流水线。
> 全部 8 张 mermaid 图已用 mermaid-cli 11.15 实测渲染通过，语法零错误。
> 代码与 README 交叉核对，反映当前真实行为（含三决策门、draft 只读契约、断点续传）。

## 渲染环境

| 查看器 | mermaid 支持 |
|---|---|
| GitHub / GitHub Issues | ✅ 原生渲染 |
| Obsidian | ✅ 原生渲染 |
| Typora | ✅ 原生渲染 |
| VS Code | 需装扩展：Markdown Preview Mermaid Support（或 md-mermaid） |
| mermaid.live | ✅ 粘贴代码即渲染（改图首选） |
| 纯文本查看器 | ❌ 显示为代码块，属正常 |

---

## 图 1 · 全景总览（End-to-End）

```mermaid
flowchart TD
    subgraph IN["① 输入层 raw/"]
        A1["📄 文章 MD<br/>frontmatter: title / date / format /<br/>series_slug / voice / split_strategy"]
    end

    subgraph PREP["② prepare（src.prepare）"]
        B1["naming_enforce 硬门<br/>自动 rename 违规物理名"]
        B2["三决策门<br/>format / voice / split_strategy<br/>AI 推荐 + 用户拍板"]
        B3["plan_episodes 分集<br/>by_h2 / by_chars / by_duration"]
        B4["generate_script<br/>LLM 全自动 or 骨架半自动"]
    end

    subgraph DRAFT["③ 评审门 drafts/"]
        C1["drafts/&lt;date-slug&gt;/ep-XX.md<br/>+ _decisions.json 审计"]
        C2["人工编辑 [host]/[guest]<br/>--mark-reviewed / --freeze"]
    end

    subgraph BUILD["④ build（src.build）"]
        D1["5 步 pipeline<br/>read → parse → validate<br/>→ TTS → shownotes/RSS"]
    end

    subgraph OUT["⑤ 输出层 output/"]
        E1["series/&lt;slug&gt;/ep-NN/<br/>episode.mp3 + shownotes.md"]
        E2["feed.xml + index.html<br/>+ manifest.json"]
    end

    subgraph DEP["⑥ 发布"]
        F1["git push → CI 单测 → naming_enforce<br/>→ build --skip-audio → gh-pages"]
        F2["https://binbinao.github.io/myPodcast/"]
    end

    A1 --> B1 --> B2 --> B3 --> B4 --> C1 --> C2 --> D1 --> E1 & E2
    E1 & E2 --> F1 --> F2
```

**要点**
- 三层数据层：`raw/`（源文章）→ `drafts/`（评审门）→ `output/`（最终产物，入库 git 跟踪）。
- `prepare` 只产出脚本不进音频；`build` 是通往 `output/` 的唯一路径。
- `build` 对 draft **只读**——正文逐字节来自 draft，不再二次 LLM 改写。

---

## 图 2 · prepare 内部流程

```mermaid
flowchart TD
    RAW["raw/ 文章"] --> ENF["naming_enforce 硬门<br/>enforce_raw_files + enforce_drafts_dirs"]
    ENF --> META["解析 frontmatter<br/>title / format / episodes / date / slug"]

    META --> CHECK{"frontmatter 三件套齐？<br/>format + voice + split_strategy"}
    CHECK -- 齐 --> RESPECT["尊重用户既定决策<br/>跳过交互门，不打扰"]
    CHECK -- 缺任一 --> GATE["collect_decisions 三决策门<br/>AI 推荐 + 用户拍板"]
    GATE -->|"--yes / --auto（CI 直通）"| AUTO["直接采纳 AI 推荐<br/>CI / 批处理用"]

    RESPECT --> SAVE["写 _decisions.json 审计<br/>与 draft 同目录"]
    AUTO --> SAVE
    GATE --> SAVE
    SAVE --> SPLIT["plan_episodes(strategy)<br/>返回真实集数 EpisodePlan<br/>（含短引言合并进第 1 集）"]

    SPLIT --> GEN{"llm.enable 且<br/>resolve_api_key 有 key?"}
    GEN -- 是 --> LLM["_auto：LLM 改写成口播稿<br/>solo 全 [host] / duo [host]+[guest]"]
    LLM --> CLEAN["validate BLOCK 校验<br/>命中 → heuristic_clean 二次清洗"]
    CLEAN --> WRAP
    GEN -- 否 --> SKEL["_skeleton：纯 [host] 骨架<br/>ai_stage = skeleton（无需 key）"]
    SKEL --> WRAP["_wrap 组装 frontmatter<br/>title / chapter / format / series / voice<br/>split_strategy / source / ai_stage"]
    WRAP --> DRAFTS["drafts/&lt;date-slug&gt;/ep-XX.md"]
```

**要点**
- **三决策门原则**：AI 先给推荐 + 理由，用户永远有最终决定权；`--yes`/`--auto` 全自动采纳（默认交互）。
- frontmatter 三件套（`format`/`voice`/`split_strategy`）齐全时尊重用户，不重复打扰。
- `voice` 与 `split_strategy` 会写进 draft frontmatter，build 重渲时按 draft 脏值复现——**commit 前必须人工 review draft frontmatter**。

---

## 图 3 · 三决策门交互详图（src/decisions.py）

```mermaid
flowchart TD
    START["collect_decisions(article, cfg, auto_accept)"] --> QF{"门 1 · format？"}
    QF --> RF["AI 推荐：启发式 / LLM 推断<br/>solo 单人 or duo 双人"]
    RF --> UF{"用户输入（stdin）"}
    UF -- 回车 --> ACF["采纳推荐"]
    UF -- 1/2/3/4 --> CHF["选其他候选"]
    UF -- r --> RERUN1["重新分析"]
    ACF --> QV{"门 2 · voice？"}
    CHF --> QV
    RERUN1 --> QF
    QV --> RV["AI 推荐：voicecaster 音色<br/>5 类文章信号 → 音色映射"]
    RV --> UV{"用户输入（stdin）"}
    UV -- 回车 --> ACV["采纳推荐"]
    UV -- 1/2/3/4 --> CHV["选其他"]
    UV -- r --> RERUN2["重新分析"]
    RERUN2 --> QV
    ACV --> QS{"门 3 · split_strategy？"}
    CHV --> QS
    QS --> RS["AI 推荐：直接调 plan_episodes(strategy)<br/>实测返回真实集数（保证推荐与生成一致）"]
    RS --> US{"用户输入（stdin）"}
    US -- 回车 --> ACS["采纳推荐"]
    US -- 1/2/3 --> CHS["选其他"]
    US -- r --> RERUN3["重新分析"]
    RERUN3 --> QS
    ACS --> DONE["决策写入 draft frontmatter<br/>format / voice / split_strategy<br/>+ 落 _decisions.json"]
    CHS --> DONE
```

**要点**
- 每门都是「AI 推荐 → 用户拍板」，`r` 可重新分析，全程不猜用户。
- `recommend_split` 与最终生成走同一 `plan_episodes`，杜绝「推荐 3 集实际生成 5 集」的偏差。

---

## 图 4 · 分集策略决策树（src/split.py）

```mermaid
flowchart TD
    ARTICLE["文章正文"] --> S{"split_strategy"}
    S -- by_h2 --> H2["按 H2 章节拆集<br/>（默认：多章节每章一集）"]
    H2 --> C1{"章节 &lt; min_episode_chars(600)？"}
    C1 -- 是 --> MERGE["并入上一集"]
    C1 -- 否 --> KEEP["独立成集"]
    MERGE --> L1{"单集 &gt; max_episode_chars(3000)？"}
    KEEP --> L1
    L1 -- 是 --> SUB["超长单章按 H3 / 段落再切"]
    L1 -- 否 --> PLAN["EpisodePlan 列表"]
    SUB --> PLAN
    S -- by_chars --> CH["按固定字数切分<br/>max_episode_chars 控制单集上限"]
    CH --> PLAN
    S -- by_duration --> DU["按时长切分<br/>max_duration_min + chars_per_minute(250)"]
    DU --> PLAN
    PLAN --> INTRO{"存在短引言？"}
    INTRO -- 是 --> M1["合并进第 1 集"]
    INTRO -- 否 --> FINAL["最终分集方案<br/>prepare 落盘即事实源"]
    M1 --> FINAL
```

**要点**
- 分集原则：多章节每章一集、不按字数合并；仅单块长文按 `max_episode_chars` 切，超长单章再按 H3/段落细分。
- 关键坑：`split._strip_md` 必须剔除水平线 `---`（raw 用它分节但残留成段落，edge-tts 对纯 `---` 返回 `No audio was received`）。

---

## 图 5 · build 5 步 pipeline + 断点续传（src/build.py）

```mermaid
flowchart TD
    C0["读 manifest.json<br/>existing_keys: series_slug::ep-XX → source_hash"] --> C1{"key 已注册 且<br/>source_hash 未变 且<br/>mp3 存在？"}
    C1 -- 是 --> SKIP["跳过整集 ⊝<br/>产物 0 变更（幂等）"]
    C1 -- 否 --> R1["[1/5] 读取 draft<br/>stage 告警：reviewed/frozen 静默<br/>legacy 无字段只告警"]
    R1 --> R2["[2/5] parse_script 解析<br/>frontmatter + [host]/[guest] 分段"]
    R2 --> R3["[3/5] validate_script 质量门禁<br/>emoji / 零宽 / md 残留 / 长度 / 角色标签"]
    R3 -- BLOCK --> FAIL["PipelineError → 计入 failed"]
    R3 -- 通过 --> R4{"--skip-audio？"}
    R4 -- 是 --> R4B{"mp3 已存在？"}
    R4B -- 是 --> R5["ffprobe 读现有时长<br/>跳过 TTS（CI 重渲模式）"]
    R4B -- 否 --> WARN["⚠ 无产物，跳过本集<br/>先跑一次正常 build 生音频"]
    R4 -- 否 --> TTS["TTS 合成 episode.mp3<br/>voicecaster 选音色（仅 solo/minimax）<br/>prosody 注入 emotion"]
    R5 --> S1["[4/5] 写 shownotes.md"]
    TTS --> S1
    S1 --> S2["[5/5] register_episode → manifest"]
    FAIL --> FIN{"failed 非空？"}
    FIN -- 是 --> EXIT1["sys.exit(1)<br/>不重建 RSS/index（防残缺站点）"]
    FIN -- 否 --> OK["重建 feed.xml + index.html ✓"]
    SKIP --> FIN
```

**要点**
- 断点续传：`source_hash = sha256(source)[:16]` 未变即跳过；`--only ep-XX` / `--from` / `--retry-failed` / `--force` 控制粒度。
- **`--skip-audio` 在 manifest 已注册集上幂等跳过整个 ep**——真正验证要用 `--only ep-XX --force`（真 TTS）或 `--skip-audio --force`（重渲）。
- 验证信号：**git status 有变化才算真通过**，不能凭「build 没报错」。

---

## 图 6 · TTS 内部（后端路由 + 音频拼接）

```mermaid
flowchart TD
    SEG["segments 分段列表"] --> BK{"cfg.tts.backend"}
    BK -- minimax --> EN["_enrich_with_emotion<br/>prosody.plan_sentences 每句打标签<br/>段 emotion = 首句标签"]
    EN --> BMIN["backends.minimax.build_episode<br/>speech-2.8-hd"]
    BK -- edge-tts --> BED["backends.edge.build_episode<br/>免费 / 开发烟雾测试"]
    BMIN --> PER["逐段 TTS 合成<br/>_speak 内置 3 次重试<br/>hex 解码 mp3"]
    BED --> PER2["逐段 edge-tts<br/>3 次重试"]
    PER --> CON["ffmpeg concat filter 拼接"]
    PER2 --> CON
    CON --> NORM["aformat 归一化<br/>fltp / 32000Hz / mono<br/>解决 mp4a 标签 exit 234"]
    NORM --> OUT["output/series/&lt;slug&gt;/ep-NN/episode.mp3<br/>返回 (path, duration)"]
```

**要点**
- 后端切换**只改 config**（`tts.backend`），业务代码零改动（`@register` 抽象）。
- MiniMax 的 mp3 响应 mime 标签是 `mp4a`（实际编码 mp3），与 silence 拼接时 ffmpeg 会 exit 234——concat filter 前加 `aformat` 归一化解决。
- 韵律：heuristic（零依赖，按标点）输出 emotion 给 minimax 用；edge-tts 只吃 rate/pitch。

---

## 图 7 · 发布部署（CI + gh-pages）

```mermaid
flowchart LR
    PUSH["git push main<br/>（触发含 src/** 路径）"] --> TEST["单测 142 case"]
    TEST --> NAMING["naming_enforce 守护<br/>exit 2 → workflow fail"]
    NAMING --> BUILD["build --skip-audio<br/>只重渲 shownotes / RSS / index<br/>不动 mp3"]
    BUILD --> GH["peaceiris/actions-gh-pages@v4<br/>推 output/ → gh-pages 分支"]
    GH --> URL["https://binbinao.github.io/myPodcast/"]
```

**要点**
- 改 `src/**` 会触发 CI 重跑——改 `src/build.py` 等必须本地测通再 push。
- mp3 是付费 TTS 交付物，随仓库走；CI 永远 skip-audio。

---

## 图 8 · draft 生命周期状态机（ai_stage）

```mermaid
stateDiagram-v2
    [*] --> skeleton: prepare 无 LLM key，纯骨架稿
    skeleton --> generated: generate._auto LLM 改写产出
    generated --> reviewed: prepare --mark-reviewed 人工审阅通过
    reviewed --> frozen: prepare --freeze 锁稿
    skeleton --> frozen: 人工直接锁稿
    generated --> generated: 重新 prepare 覆盖
    reviewed --> [*]
    generated --> [*]
    frozen --> [*]
```

**要点**
- `set_stage` 只改 frontmatter 的 `ai_stage` 一行，正文逐字节保留。
- build 按 stage 告警：`reviewed`/`frozen` 静默；`skeleton`/`generated` 提示先审再 build。

---

## 数据层与契约速查

| 层 | 物理路径 | 字段来源 | 角色 |
|---|---|---|---|
| raw/ | `raw/YYYY-MM-DD-slug.md` | frontmatter `series_slug` → `slug` → ascii(title) | 源文章 |
| drafts/ | `drafts/<date-slug>/ep-XX.md` | 同上 | 评审门（可改 [host]/[guest]） |
| output/ | `output/series/<slug>/ep-NN/episode.mp3 + shownotes.md` | `series_slug` 字段 | 最终产物 |

**硬契约清单**
1. 新增 raw 后必须先跑 `scripts/normalize_raw_filenames.py` 验证三层物理名一致。
2. **build 永不调 polish()**——由 `tests/test_stages.py::TestBuildReadOnlyContract` AST 扫描机械 enforce。
3. API Key 不写 config/code/git，`resolve_api_key`：cfg → env `LLM_API_KEY`/`MINIMAX_API_KEY`/`OPENAI_API_KEY`。
4. MiniMax chat 必须发 `reasoning_split: true` + `thinking: {type: "disabled"}`，否则 tokens 全烧 reasoning。
5. commit 前必跑 `python -m src.build drafts/<某系列> --skip-audio --force` 必须绿。

---

## mermaid 语法注意事项（已实测）

- edge label 文本**不要以 `--` 开头**（会被 mermaid 解析成边语法报错），用管道形式显式界定：
  `A -->|"--yes / --auto"| B` ✅ / `A -- --yes --> B` ❌
- 节点文本里 `<` `>` 用 HTML 实体 `&lt;` `&gt;`；换行用 `<br/>`。
- 菱形条件节点用 `{"...？"}`，引号内可用中文与标点。
- 状态机用 `stateDiagram-v2`（图 8），不是旧 `stateDiagram`。
- 修改图后验证：粘贴到 mermaid.live，或本地 `npx -y @mermaid-js/mermaid-cli -i fig.mmd -o /tmp/out.svg`。
