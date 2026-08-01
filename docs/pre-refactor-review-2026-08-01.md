# myPodcast 接手前系统 Review 总评（7 角色联合）

> 生成日期：2026-08-01
> 评审团队：大湾区靓仔(总监) + 许清楚(PM) + 颜好看(设计) + 高见远(架构) + 贾思敏(前端) + 贝洛奇(后端) + 严过关(QA) + 卜宕机(运维)
> 范围：重构前的全角色 review，只出意见不动代码
> 方法：7 位专家独立实读代码库（`src/*.py` / `templates/style.css` / `output/index.html` / `config.yaml` / `.github/workflows/publish.yml`），交叉核对后合并去重

---

## 0. 一句话结论

**骨架选型正确、契约意识超出个人项目平均水准，但"契约写了、代码没兑现"——大量 P0 是同一根断裂链：build.py 吞异常 + 失败不返回退出码 + BLOCK 门不拦 + 命名门禁 CI 参数写反 + CI 缺 ffmpeg。测试只盖安全区（实测总覆盖 44%），真正会炸的编排层、外部边界、发布产物几乎裸奔。**

重构第一刀**不是重写**，而是：
1. 把"失败变得可见"（修退出码契约 + 命名门禁参数）
2. 建测试安全网（端到端快照 + backends mock）
3. 把悬空契约逐条落地（BLOCK 硬门、draft 不可变、密钥单点）

**总 verdict：fail（不阻断团队开工，但阻断"直接进代码重构"）。**

---

## 1. 角色结论速览

| 角色 | 总评 | P0 数 | 最关键发现 |
|------|------|-------|-----------|
| 架构(高见远) | 骨架对、契约空转 | 3 | 构建不幂等致 shownotes/音频漂移；feed.py 353 行零测试；BLOCK 门半扇 |
| 后端(贝洛奇) | 控制流全线失灵 | 6 | prosody 正则写错实测吞英文；SystemExit 绕过 except；缺 key 静默降级 |
| 前端(贾思敏) | 生成方式之罪 | 2 | HTML 属性注入(PoC 复现)；双 ▶ 图标 |
| QA(严过关) | 高风险 44% 覆盖 | 6 | BLOCK 拦截是装饰品；全失败仍 exit 0；零集成测试 |
| 运维(卜宕机) | 绿灯是运气 | 3 | 命名门禁写反从不拦；build 吞异常假绿；CI 缺 ffmpeg |
| 设计(颜好看) | 工程>设计完成度 | 3 | 字符图标混 SVG；Hero 标签/内容/播放三方打架；移动端字体失效 |
| 产品(许清楚) | 核心价值没兑现 | 3 | 产物中位 141s 不是播客；评审门被二次 polish 吃掉；README 缺定位 |

**跨角色交叉验证**：前端/后端/QA/运维/架构 5 人独立打到同一条断裂链（"失败不可见"），PM/设计打到同一条（"产物不可听/人味缺"）——说明问题不是分散的，是系统性控制流缺陷。

---

## 2. 合并后 P0 清单（去重 + 标注来源）

> 标注：[架构]/[后端]/[前端]/[QA]/[运维]/[设计]/[产品] = 哪位专家独立发现

### P0-A 构建失败不可见（"假绿"根因，5 人共识）
- [后端] `build.py:33/135/143/147` + `base.py:69` 抛 `SystemExit`，而 `build.py:187` 的 `except Exception` **抓不到 BaseException** → 单集坏炸整批
- [后端] `build.py:193-204` 5/5 全失败也不 `sys.exit`，只 `log.warning` → CI 永远绿
- [运维] `publish.yml:48` 跑 `naming_enforce` 无 `--dry-run` → `naming_enforce.py:244` 只有 dry_run 才 return 2，CI 永远 return 0（README 写的 exit 2 失败是假的）
- [运维] `publish.yml` 全文无 `apt install ffmpeg`，ubuntu-latest 不保证自带；当前绿只因所有集命中 manifest 跳过从没走到 ffprobe，**新增一集即 FileNotFoundError 被假绿吞掉**
- [QA] 实测 100% 集失败时 `run()` 正常返回，CI 判绿继续 deploy 空站
- **修复**：定义 `PipelineError(Exception)`，`SystemExit` 只留 `main()`；`failed` 非空 → `sys.exit(1)`；CI 加 `--dry-run`；加 ffmpeg 安装 + 启动期探测

### P0-B BLOCK 门在 build 侧是装饰品
- [后端] `build.py:43-44` 只 `report_and_warn`，从不调 `has_blocking()`
- [QA] 实测 `heuristic_clean` 7 类 BLOCK 只修得掉 1 类（`**加粗**`），emoji/md链接/HTML/零宽/pipe表/`>`引用全修不掉；坏样本 15 个漏 13 个
- [QA] 实测 `has_blocking(validate_script({}, "")) == False` → 空 body 落盘
- [前端] 同根：`feed.py` 用 `xml.sax` 不转义引号（见 P0-D）
- **修复**：build 入口 `if has_blocking(w): raise PipelineError`；validate 坏样本语料库参数化补全

### P0-C HTML 属性注入（PoC 已复现）
- [前端] `feed.py:79,366,372,392,432,542-547` 用 `xml.sax.saxutils.escape()`，**默认不转义引号**；PoC：`data-slug="标题" onmouseover="alert(1)"` 属性被击穿
- **修复**：全量换 `html.escape(s, quote=True)`，或迁 Jinja2 `autoescape=True`（一次性根治）

### P0-D 字符图标当功能图标 + 双 ▶ 渲染
- [前端] `feed.py:435` 文本 `▶`(U+25B6) + `style.css:157` `::before content:"▶"` 叠加，output 内 7 处双字形；`_ICON_LIB["play"]` 已存在却未使用
- [设计] 同：`▶` ×7 + `content:"▶"`，与 3 个 Feather SVG 混用，跨平台可能渲染成彩色 ▶️
- **修复**：删 `::before`，HTML 内注入 `{play}` SVG；锁定 Feather 一套 16/20/24

### P0-E 构建不幂等 / 二次 polish 吃掉人工修改
- [架构] `build.py:27-28` 无条件 `polish(raw, cfg)`，但 draft 已是 `generate._auto()` 的 LLM 产物 → 本地每次 rebuild 文案不同
- [产品] `build.py:28` 在 `llm.enable=true` 下**再调一次 LLM 全文重写**，人在 drafts 改的字被吃，LLM 成本 ×2，输出不可复现
- [产品] CI `--skip-audio` 不注入 key → `polish()` 静默降级 heuristic，站上文字(启发式)与耳朵音频(LLM)对不上且无告警
- **修复**：draft 落盘即不可变事实源，build 只读不改写；polish 全前移 prepare；drafts frontmatter 加 `reviewed: true`，build 见到跳过

### P0-F feed.py 上帝文件，零测试
- [架构] `feed.py:306-658` 单函数 353 行，揉 manifest+shownotes+RSS+HTML+SVG 五件事；`templates/` 只有一个 style.css，模板全在 Python 字符串
- [QA] `feed.py` 覆盖 13%，`tts.py` 16%，`backends/*` 0%；全库 0 个 mock
- [前端] `build_index()` 354 行，HTML/CSS/JS 三种语言焊进 f-string，无 lint/无单测
- **修复**：Phase 1 拆 `manifest.py`/`shownotes.py`/`rss.py`/`site/`(模板引擎)，先补快照测试

### P0-G prosody emoji 正则写错（实测复现吞英文）
- [后端] `prosody.py:21-24` `\u1F000-\u1FAFF` 中 `\u` 只吃 4 位 → 实际生成 `U+0030–U+1FAF`；实测 `GPT-4 的 API 在 2025 年涨价了30%` → `- 的  在  年涨价了%`，所有 ASCII 字母数字被删
- **修复**：改 `\U0001F000-\U0001FAFF`；目前仅污染 emotion 选型，一旦用于合成即毁音频

### P0-H 断点续传 key 两套算法
- [后端] `build.py:163` 查 key 用 `meta.series_slug` 无兜底；`build.py:97`/`feed.py:145` 写 key 用 `slugify(title)` → 两边不一致永远命中不了，每次重跑重烧 TTS 钱
- [产品] manifest 7 集中 4 集 `source_hash=null`，剩 3 集共用同 hash → 每次 build 全量重跑付费 TTS
- **修复**：抽 `episode_key(meta)` 单一函数，两处共用

### P0-I 缺 key 静默降级
- [后端] `polish.py:112` / `generate.py:100` 拿不到 key 不报错，直接退化成 heuristic/骨架稿，仍走 TTS 付费合成垃圾内容
- **修复**：`llm.enable=true` 但无 key → fail fast

### P0-J Hero 标签/内容/播放三方矛盾
- [设计] `feed.py:338` 取最新系列**第 1 集**，`:401` 标"最新一期"；CTA JS `querySelector('#latest audio')` 命中 #latest 首卡 = **EP03**（latest 按日期倒序）
- 结果：标签说最新、内容是 EP01、点下去播 EP03
- **修复**：featured 统一取真正最新集，CTA href 与播放目标绑同一 ep

### P0-K 移动端字体整体失效
- [设计] `feed.py:550` + `index.html:15` 字体 link 挂 `media="(min-width:1024px) and (prefers-reduced-motion: no-preference)"` → <1024px 及所有开 reduced-motion 用户拿不到 Web 字体，排版分裂
- [前端] 同（P1-6）
- **修复**：去掉 media 条件，用 `display=swap` + preconnect

### P0-L 产物不可听 / 分集粒度失控（核心价值）
- [产品] manifest 实测 7 集 = 37/42/58/106/141/242/294 秒；index.html 自显"知识管理 3 集 · 总时长 2:17"；18,738 字被切 22 个 draft，每集仅 743–1140 字符
- 根因：`split.max_episode_chars=3000` + `llm.max_tokens=1500` + LLM 改写压缩三重叠加
- **修复**：按**目标时长**拆集（中文口播 ~250 字/分，15 分钟集需产出 ≥3000 字），max_tokens 提 4000+，prompt 明令"不得压缩、逐段展开"

---

## 3. 合并后 P1 清单（关键项）

| # | 问题 | 来源 | 位置 |
|---|------|------|------|
| P1-1 | 密钥优先级反：`cfg.api_key` 压过 env；`${MINIMAX_API_KEY}` 会被当真 token 发 | [架构][后端][运维] | `polish.py:16-23` / `backends/minimax.py:48-53`(两行重复) |
| P1-2 | `TTS_BACKEND` 死变量：`publish.yml:56` 设 edge-tts 但全库无代码读；生效的是 `config.yaml:39 minimax` | [架构][运维] | `publish.yml:56` |
| P1-3 | config 键重复/静默取后：`config.yaml:84-85` max_tokens/temperature 从未读；`:87` 与 `:92` 重复 `prompt` 键 | [架构][后端] | `config.yaml` |
| P1-4 | 触摸目标 <44px：`.series-ep-play` 28×28 违反 WCAG 2.5.5 | [前端][设计] | `style.css:146-148` |
| P1-5 | Series / Latest 100% 重复：7 集列两次，标题字符串完全一致 | [设计][产品] | `feed.py:453` 注释写"最近6"实际渲染7含featured |
| P1-6 | 订阅区被 `subscribe.enabled: false` 关掉 → 转化路径缺失（注：是 feature flag 非死代码，[前端]已纠正[设计]误判） | [设计] | `config.yaml:13` / `feed.py:469-494` |
| P1-7 | subprocess 无 timeout：6 处 ffmpeg 卡死永久挂起 | [后端] | `minimax.py` / `edge.py` |
| P1-8 | ep 标题截断到无法区分：系列前缀被省略号吃掉 | [设计] | `style.css:134-141` |
| P1-9 | 原生 `<audio controls>` 破坏暗色主题，跨浏览器不一致 | [设计] | 7 处原生控件 |
| P1-10 | `漏 f 前缀`：无封面兜底分支 `feed.py:394` else 漏 f → 字面输出 `{mic}` | [前端] | `feed.py:394` |
| P1-11 | 移动端 hero 封面撑爆：断点内约束错元素(.hero-art 而非 .hero-media) | [前端] | `style.css:208` |
| P1-12 | mp3 入 git 定时炸弹：现 7 集/.git 15M，30分钟/集后单篇 ~30MB 撞 GitHub 1GB | [架构][运维][产品] | `output/` |
| P1-13 | gh-pages 不可回滚 + 零 health check：`force_orphan` 历史只剩 1 commit | [运维] | `publish.yml:66` |
| P1-14 | tagline 复读 7 次 + About 无人味（个人播客最致命） | [设计][产品] | `index.html` / `feed.py` |
| P1-15 | RSS 缺 RFC 822 pubDate + itunes 标签（Apple 提交必需） | [前端][架构] | `feed.py:193` |

---

## 4. 合并后 P2 清单（顺手做）

- 引 Jinja2 模板引擎 + `autoescape=True`（[前端][架构]共识，根治 P0-C，拆 feed.py 上帝文件）
- Token 四层化：`design-tokens.json` 供构建期注入，CSS 内零裸 hex（仅留 #fff/#000）；紫 `#7c5cff` 要么升正式 token 要么删
- 断点补 3 档（640/1024/1280）
- 死代码清理（真死只有 `.series-cta`、`.ep-title a`、`featured_slug`、`_slugify_series`；[前端]已纠正[设计]把 subscribe/hero-art 误判为死代码）
- 字号收敛 8 档、间距 4 倍数白名单
- SEO：og:url / twitter:card / canonical / sitemap.xml
- cover.jpg 504KB → WebP + 显式尺寸（CLS + 移动流量）
- `pip-compile --generate-hashes` 真 lock；ffmpeg 换 imageio-ffmpeg 或 apt 固定版本
- gitleaks pre-commit + CI secret scan
- `--retry-failed` 名不副实（build.py:168 仅关跳过=全量重跑），与 help 矛盾
- `prosody.py:126-127` 裸 `except: pass` 吞 LLM 异常无日志

---

## 5. 重构路线图（综合架构/后端/运维/QA）

**顺序不可调换**——Phase 0 缺席则 Phase 1 无法验证，Phase 3 依赖 Phase 2 配置单点。

| Phase | 内容 | 不做的后果 |
|-------|------|-----------|
| **Phase 0 建安全网** | ① 端到端快照：raw→prepare→build --skip-audio，对 feed.xml/index.html/shownotes 快照断言 ② backends mock HTTP 契约测试 ③ validate 坏样本语料库 ④ build.run() 编排契约（失败不中断/退出码/过滤矩阵） | 后面每一步都是盲改 |
| **Phase 1 拆上帝文件** | feed.py → manifest.py / shownotes.py / rss.py / site/(Jinja2 模板 + 独立 icon 模块，图标继续用现有 SVG 库) | 改一行无回归信号 |
| **Phase 2 统一横切** | config.py(schema 校验+启动报未知/未读键) / secrets.py(唯一密钥入口，env 优先) / media.py(ffprobe/ffmpeg 唯一封装+timeout) | P1-1/2/3/7 源头 |
| **Phase 3 修流水线语义** | draft 不可变；polish 前移 prepare；build 接 BLOCK 硬门；干掉 SKIP_AUDIO 全局改显式参数；run_one 返结构化对象；修 P0-A/B/C/G/H/I | 契约落地 |
| **Phase 4 资产与产物** | 决策 mp3 托管(LFS/对象存储/Releases)，output/ 退出 git 主干；gh-pages 可回滚+health check | 定时炸弹拆弹 |

---

## 6. 待你拍板的开放决策（Open Decisions）

| # | 决策 | 两难 | 我的倾向 |
|---|------|------|---------|
| OD-1 | **分集策略**：按目标时长拆集 vs 现状 | 现状产物不可听，但改策略要动 split+prompt | 必须改（P0-L），否则所有分发投入负收益 |
| OD-2 | **评审门**：drafts 加 `reviewed:true` 锁稿，build 跳过 polish？ | 单模式更干净，但失去"build 再润色"灵活性 | 加锁稿（P0-E 修复核心） |
| OD-3 | **双模式**：砍 skeleton 收敛单模式？ | 全自动分支又在 build 二次覆写吃人工修改，skeleton 几乎无人走 | 砍 skeleton（[产品]建议） |
| OD-4 | **mp3 托管**：LFS / 对象存储 / Releases / 仍入 git | 现在 15M，放大必炸；但加托管要引新依赖 | Phase 4 前必须定，倾向对象存储+CDN |
| OD-5 | **站点拆分**：本轮做 Jinja2 迁移吗 | [架构][前端]说必须先拆才能安全改；[产品]说用户价值 0、先别动 | 做，但只拆不重写样式（视觉已收敛） |
| OD-6 | **吸底 mini player**：做不做 | [设计]提把 7 个原生 audio 收敛单播放器；[前端]说工作量≈前面所有修复之和 | 拆 M1(修 P0/P1+Jinja2) / M2(单独评估 mini player) |
| OD-7 | **订阅区**：启用 `subscribe.enabled` 吗 | 现 4 入口整段不渲染，Hero 右侧空落 | 先启用占位（低成本），内容后填 |

---

## 7. 各角色完整 review 索引

- 架构：P0×3（不幂等/上帝文件/BLOCK半扇）+ P1×6 + P2×6，含 4 阶段重构路线图
- 后端：P0×6（正则吞字符实测/prosody/SystemExit/续传key/静默降级/BLOCK不拦/无exit）+ P1×14 + P2，含 `src/` 重模块划分
- 前端：P0×2（属性注入/双图标）+ P1×6 + P2，含 Jinja2 迁移方案；已与[设计]对齐纠正 2 处误判
- QA：P0×6（BLOCK装饰品/SystemExit击穿/全失败exit0/零集成测试/规则漏网/空返回）+ 覆盖率 44% 实测 + 安全网清单
- 运维：P0×3（门禁写反/假绿/缺ffmpeg）+ 生产就绪记分卡 Bronze 以下 + CI 两段 job 改造
- 设计：P0×3（字符图标/Hero三方矛盾/移动字体）+ P1×6 + Token 四层化建议（已纠正 subscribe/hero-art 误判）
- 产品：P0×3（不可听/评审门失效/缺定位）+ RICE 优先级（先动 reviewed 锁稿>source_hash>README 定位）

**交叉共识最强的 3 条**（≥4 角色独立命中，重构最该先动）：
1. 失败不可见（P0-A）— 架构/后端/前端/QA/运维 5 人
2. BLOCK 门不拦（P0-B）— 后端/QA/前端/架构 4 人
3. feed.py 上帝文件（P0-F）— 架构/前端/QA 3 人 + 是 P0-A/B/C 的共同催生器

---

## 8. 第二轮增补（交叉验证 + 纠错，2026-08-01 晚）

> 架构/设计在首轮后基于交叉验证做了实质更正与增补。与上文冲突处**以本节为准**。

### 8.1 新增 P0：命名 gate 在 CI 里是反的（架构 P0-4，与运维 P0-1 同根，机制更深）
- `publish.yml:48` 跑 naming_enforce **没带 `--dry-run`**；`naming_enforce.py:244-246` 只在 `dry_run and total > 0` 时 return 2 → CI 里**永远 return 0**
- 副作用：CI workspace 里真的 `shutil.move` 改 raw/drafts/output 三层（`:120/:224`），改完的树直接喂 build + 部署 → **main 与 gh-pages 静默分叉**
- 触发即 RSS 全量 404：`enforce_output_series` 改物理目录但不更新 manifest，enclosure URL 来自 manifest（`feed.py:169→196`）——它 docstring 声称防的事正是它自己会造成的
- 当前没炸纯属侥幸：`write_shownotes`（`feed.py:101-121`）不写 frontmatter，解析结果 `{}` 退化成"目录名自比"恒等；**任何含大写/非 ASCII 的 series 目录名进来即引爆**
- **止血（一行）**：CI 加 `--dry-run`，排在 Phase 0 之前立即做
- frontmatter 双解析器注入向量（升级）：`naming_enforce._parse_frontmatter_text`（`:36-59`）不懂 YAML 块标量，实测 `desc: |` 块内缩进的 `series_slug: HIJACKED` 会被当顶层键吃掉 → 驱动带 `shutil.move` 的门禁被注入

### 8.2 架构×后端分歧裁决（架构实跑数据）
| 分歧点 | 后端定级 | 架构裁决（实测） |
|--------|----------|------------------|
| `_key` 双算法 | P0 断点续传永久失效 | **P1 高危潜伏**：现有 drafts 全带 series_slug 当前不触发；触发条件=手改 draft 漏 series_slug（`validate.py:127` 只 WARN）→ 读侧 `::ep-01` vs 写侧 slugify 永不匹配，重烧钱无告警 |
| SystemExit 绕过 | P0 四处 | **收窄为两处**：`build.py:135/143/147` 在 CLI 参数校验层抛是对的；真泄漏只有 `build.py:33` + `base.py:69`（run_one 内部，穿透 `build.py:187` 的 except Exception 炸整批） |
| frontmatter 双解析器 | P1 | **坐实且升级**：实测 4 例中 2 例分歧，含块标量注入向量 |

### 8.3 系统性根因：所有"门"都只写了姿势没接线
BLOCK 门 build 侧只 warn、命名门 CI 侧永不 fail、`TTS_BACKEND` 无人读取——不是三个孤立 bug，是同一个缺陷：**规范停留在注释/文档，没有可执行的强制点**。
→ 重构第一性原则：**每条规范必须配机械守卫**。落地方式：测试扫 `src/`，除 `core/paths.py` 外出现字面量 `"series/"`/`f"ep-{` 即 fail；SystemExit 除 `main()` 外出现即 fail。规范能自动执行才叫规范。

### 8.4 模块切分修订（覆盖首轮架构方案）
- 后端原方案把 polish/generate/prosody/voicecaster 塞 `content/` → **会让 P0-1 结构性复活**
- 改为：`authoring/`（polish/generate，prepare 期，draft 落盘即冻结）+ `speech/`（prosody/voicecaster，build 期只决定怎么念、不碰文本）——阶段边界变成结构约束
- `audio/`（concat/probe）与 `tts/` 平级（`build.py:104` 自己也要 probe，嵌套会反向依赖）；`episode_key` 归 `publish/manifest.py`（存储格式读写两侧同源 import）

### 8.5 设计侧纠错与交付（颜好看，已复核认领）
- 认领 2 处误判：`.subscribe*` 是 feature flag 关闭非死代码（`feed.py:332` 读、`:469-494` gate）；`.hero-art` 是无封面兜底分支非死代码（`feed.py:390-395`）
- 更正触摸目标标准：**WCAG 2.5.5 是 AAA；AA 档 2.5.8 = 24×24，现 28×28 已过 AA** → 从"必修"降为"应修"
- 误判挖出的真缺陷：`feed.py:394` 兜底分支漏 f-string 前缀（无封面时字面输出 `{mic}`）；外层 `aria-hidden="true"` 使无封面时 hero 对读屏完全空白 → 建议 QA 补"删除 cover.jpg 后 build"用例
- 图标结论修正：锁 Feather 是错的，`feed.py:8-11` 已声明 Lucide，`_ICON_LIB` 7 个图标且 play 未用。真问题是 **CSS 伪元素 `content:"▶"` 绕过图标体系** → 修复要立规矩：`content:` 禁止非空字面量，进 CI grep 断言
- **已交付 `templates/design-tokens.json`**（新建文件，80 token，对比度全过）：accent 透明度一律由 `--accent-rgb` 派生（CSS 零裸 rgba）；alpha 5→3 档；字号 14→8 档废 10/11px；间距 4px 白名单；新增 900px 断点。状态 **FROZEN**——变量名冻结，改名需 designer 会签

### 8.6 里程碑分级修订（M1/M2/M3）
- **M1 必修**：▶→`_ICON_LIB["play"]` + `content:` CI 断言｜字体 media 条件删除｜Hero 三方矛盾｜feed.py:394 f-prefix + 兜底 a11y｜命名门 CI 加 `--dry-run`（P0-4 止血）
- **M2 应修**：Series/Latest 重复（待 PM 定"全部/最近N"）｜token 化落地（design-tokens.json → CSS）｜触摸目标（AA 已过，做 AA+ 打磨）｜About 人味 + tagline 复读｜shownotes 裸文本落点
- **M3 独立**：吸底 mini player 全套（进度拖拽/倍速/键盘/slider 语义/Media Session）——与 Jinja2 抢同一批模板文件，不进本轮；中间态 `::-webkit-media-controls-panel` 补丁不做（Firefox 无解留三引擎分叉）。代价：7 个原生浅灰控件视觉断裂持续到 M3（产品观感取舍，待 PM/用户定）

### 8.7 评审过程说明（429）
第二轮交叉验证中，架构/后端/设计三位因 API 频率限制（429，重置 2026-08-02 11:46 UTC+8）部分后续轮次失败；其首轮与已回传的增补内容完整有效，未受影响。`design-tokens.json` 在失败前已落盘并核实。
