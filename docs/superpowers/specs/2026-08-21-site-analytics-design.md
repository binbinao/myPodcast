# 站点访问统计 — 设计文档

- **状态**: 已批准，待写实现计划
- **日期**: 2026-08-21
- **分支**: `feature/site-analytics`
- **作者**: brainstorming session
- **相关 issue**: 用户需求"为 https://binbinao.github.io/myPodcast/ 站点增加功能记录来访用于统计来访用户uv和pv数量"

---

## Context

当前 https://binbinao.github.io/myPodcast/ 站点没有访问统计，无法回答"有多少人听过这个电台"这个最基本的问题。站点已部署到 GitHub Pages（纯静态），**没有服务器**承载计数后端，只能：

1. 客户端采集 + 第三方 hosted 分析服务
2. 构建时拉第三方 API 嵌入 HTML
3. 客户端实时拉第三方 API 渲染（每次访问多一次请求）

考虑到站点现状（个人项目、低流量、已经走 build.py 渲染一切）+ 已有的"GH Pages 静态部署"约束，本设计走方案 A（**构建时拉取并嵌入**），选用 GoatCounter 作为分析服务（免费 hobby 档、隐私优先、无 cookie、脚本 <3KB）。

---

## Goals

- ✅ 站点可统计独立访客（UV）与页面浏览（PV）
- ✅ 隐私优先：无 cookie、无 PII、GDPR/CCPA 合规
- ✅ build.py 集成，无侵入：默认 disabled，配置开启后才生效
- ✅ 错误兜底：网络/认证失败不阻断 build，warn 后 widget 隐身
- ✅ 国内 CI 网络风险可控：5s 超时 + 1 重试
- ✅ 维护现有契约：`build` 不调 `polish`，`drafts/` 只读

## Non-Goals（YAGNI）

- ❌ per-episode 播放追踪（仅 track index.html 全站）
- ❌ 多 provider 抽象（umami / plausible 留未来扩展点，但不实现）
- ❌ widget 主题/位置切换（footer 唯一位置，样式固定）
- ❌ Time range 切换（仅 all-time 累计）
- ❌ 自建后端（无服务器，纯第三方）

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  config.yaml                                                  │
│    analytics: {                                               │
│      enabled: bool,        # 默认 false，零侵入              │
│      provider: "goatcounter",                                │
│      code: str,           # 8 字符 site code                  │
│      api_key: str,        # GC "Allow API access" token      │
│    }                                                          │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  src/feed.py:build_index()                                    │
│    1. 读 podcast.analytics                                    │
│    2. if enabled && code:                                     │
│         analytics.fetch_stats(code, api_key)  ←── 5s + 1 retry│
│    3. stats = {"pv": N, "uv": M}  | None                     │
│    4. 把 stats + analytics 塞 Jinja ctx                       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  模板渲染                                                      │
│  templates/site/base.html                                     │
│    <head>                                                     │
│      {% if analytics.enabled and code %}                     │
│        <script data-goatcounter="..." async src="...">       │
│      {% endif %}                                              │
│                                                               │
│  templates/site/partials/footer.html                          │
│    {% if stats and (stats.pv or stats.uv) %}                 │
│      <span class="footer-stats">                              │
│        {{ "{:,}".format(pv) }} 次访问 ·                       │
│        {{ "{:,}".format(uv) }} 位独立访客                      │
│      </span>                                                 │
│    {% endif %}                                                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  output/index.html (构建产物, 含 <script> + footer stats)     │
└──────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. `config.yaml`（修改）

新增 `analytics:` 段：

```yaml
# 站点访问统计
# provider: goatcounter (https://www.goatcounter.com, 免费 hobby 档)
# 不配置或 enabled=false 时整个统计模块完全 pass-through,零侵入
analytics:
  enabled: false                        # 默认 false；用户注册 GC 后改为 true
  provider: "goatcounter"               # 留作未来扩展点（umami/plausible）
  code: ""                              # 8 字符 site code，注册后从 GC dashboard 复制
  api_key: ""                           # GC Settings → "Allow API access" 开关后生成的 token
```

### 2. `src/analytics.py`（新增，约 80 行）

```python
"""站点访问统计：从 GoatCounter API 拉取 UV/PV。"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Any

GOATCOUNTER_API = "https://{code}.goatcounter.com/api/v0/stats/total"
TIMEOUT_SEC = 5
RETRY = 1


def fetch_stats(code: str, api_key: str) -> dict[str, int] | None:
    """拉取 GC total stats。

    返回 {"pv": int, "uv": int} 或 None（任意错误）。
    """
    url = GOATCOUNTER_API.format(code=code)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    for attempt in range(RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                return _parse(data)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as e:
            if attempt < RETRY:
                continue
            from .log import logger as log
            log.warning(f"[analytics] fetch_stats 失败: {e}")
            return None
    return None  # unreachable


def _parse(data: dict[str, Any]) -> dict[str, int] | None:
    """GC 返回结构差异较多，做宽容解析。"""
    pv = data.get("total_visits")
    uv = data.get("total_accepted")  # GC 把 unique visitors 叫 total_accepted（去 bot 后）
    if not isinstance(pv, int) or not isinstance(uv, int):
        return None
    return {"pv": pv, "uv": uv}
```

### 3. `src/feed.py:build_index()`（修改，约 +20 行）

在 `_group_by_series(episodes)` 之后、模板渲染之前，插入：

```python
# ---- 站点统计 ----
analytics_cfg = podcast.get("analytics", {})
stats: dict[str, int] | None = None
if analytics_cfg.get("enabled") and analytics_cfg.get("code"):
    from .analytics import fetch_stats
    stats = fetch_stats(
        analytics_cfg["code"],
        analytics_cfg.get("api_key", ""),
    )
```

然后在 `template.render(...)` 里加 `analytics=analytics_cfg, stats=stats`。

### 4. `templates/site/base.html`（修改）

在 `</head>` 前插入：

```html
{% if analytics and analytics.enabled and analytics.code %}
<script data-goatcounter="https://{{ analytics.code }}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
{% endif %}
```

### 5. `templates/site/partials/footer.html`（修改）

在 footer 末尾（版权/RSS 行附近）插入：

```html
{% if stats and (stats.pv or stats.uv) %}
<span class="footer-stats">{{ "{:,}".format(stats.pv) }} 次访问 · {{ "{:,}".format(stats.uv) }} 位独立访客</span>
{% endif %}
```

加 CSS（在 `templates/style.css` 末尾）：

```css
.footer-stats {
  margin-left: 1rem;
  font-size: 0.85em;
  opacity: 0.7;
}
```

### 6. `tests/test_analytics.py`（新增，约 150 行）

8 个 test case，全部 `unittest.mock`，无真实 HTTP：

| Case | 覆盖路径 |
|---|---|
| `test_fetch_stats_success_returns_pv_uv` | mock 200 + 正常 JSON → 返回 dict |
| `test_fetch_stats_401_returns_none` | mock 401 → 返回 None |
| `test_fetch_stats_timeout_returns_none` | mock `URLError(timeout)` → 返回 None |
| `test_fetch_stats_malformed_json_returns_none` | mock 200 但非 JSON → 返回 None |
| `test_fetch_stats_missing_keys_returns_none` | mock 200 但字段缺失 → 返回 None |
| `test_build_index_emits_script_when_enabled` | enabled + code → output/index.html 有 `<script data-goatcounter>` |
| `test_build_index_no_script_when_disabled` | enabled=false → 无 script 标签 |
| `test_build_index_widget_hidden_when_stats_none` | enabled=true 但 API 失败 → footer 无 `.footer-stats` |

### 7. `README.md`（修改）

新增"站点访问统计"章节，5 步 onboarding：

```markdown
## 站点访问统计（GoatCounter）

5 分钟接入：

1. 访问 [goatcounter.com/start](https://www.goatcounter.com/start) 注册（免费 hobby 档）
2. 添加站点 `binbinao.github.io/myPodcast` → 拿 8 字符 site code
3. Settings → "Allow API access" 开 → 复制 token
4. 填 `config.yaml`：
   ```yaml
   analytics:
     enabled: true
     code: "<your_code>"
     api_key: "<your_token>"
   ```
5. `python -m src.build drafts/<某系列>` → push → 看 `output/index.html` `<head>` 有 GC script、footer 有 stats

**失败兜底**：API key 错 / 网络超时 → widget 不渲染，build warn 但继续（不影响发布）。
```

---

## Data Flow

### 关键路径（happy path）

```
1. 用户 `python -m src.build drafts/<series>`
2. build.py → src/feed.py:build_index()
3. 读 config.yaml → analytics: {enabled: true, code: "abc12345", api_key: "tk_xxx"}
4. fetch_stats("abc12345", "tk_xxx")
   ↓
   urllib GET https://abc12345.goatcounter.com/api/v0/stats/total
   Authorization: Bearer tk_xxx
   ↓
   200 {"total_visits": 1234, "total_accepted": 567, ...}
   ↓
   _parse → {"pv": 1234, "uv": 567}
5. ctx = {..., analytics: {...}, stats: {"pv": 1234, "uv": 567}}
6. Jinja 渲染 base.html + partials/footer.html
   - base.html <head> → 注入 <script data-goatcounter="...">
   - footer.html → 渲染 <span class="footer-stats">1,234 次访问 · 567 位独立访客</span>
7. output/index.html 写盘
8. CI: build --skip-audio → 部署到 gh-pages
9. 访客 GET https://binbinao.github.io/myPodcast/
   - 浏览器执行 <script data-goatcounter> → 上报一次 PV（GC 在服务端算 UV）
   - 看到 footer "1,234 次访问 · 567 位独立访客"（构建期快照）
```

### 数据形状

**配置（config.yaml）**

```yaml
analytics:
  enabled: bool          # 必填，默认 false
  provider: str          # 必填，目前唯一值 "goatcounter"
  code: str              # enabled=true 时必填，8 字符
  api_key: str           # enabled=true 时必填
```

**fetch_stats 返回值**

```python
dict | None
# 成功: {"pv": int, "uv": int}
# 失败: None
```

**模板 ctx**

```python
{
    "analytics": dict,  # 整个 analytics 配置块
    "stats": dict | None,  # fetch_stats 结果
}
```

---

## Error Handling

| 场景 | 检测 | 行为 |
|---|---|---|
| `enabled = false` | 配置读 | 跳过 fetch_stats，模板不渲染 script + widget |
| `code` 留空 | 配置读 | 同上 |
| `api_key` 留空 | 配置读 | fetch_stats 仍调用，GC 返 401 → 返回 None → widget 不渲染 |
| GC 返回 401 | HTTPError 401 | 返回 None，widget 不渲染 |
| GC 返回 200 但非 JSON | JSONDecodeError | 返回 None |
| GC 返回 200 但字段缺失 | KeyError / type check fail | 返回 None |
| 网络超时 | URLError / TimeoutError | 重试 1 次，仍失败返回 None |
| 国内 CI 拉 GC 受限 | URLError | 同上，build warn 不 fail |
| 新站点 PV=0 / UV=0 | 模板条件 `stats.pv or stats.uv` | widget 仍渲染（透明诚实："0 次访问 · 0 位独立访客"） |

**契约**：`fetch_stats` 任何错误 → 返回 None（绝不 raise）。`build_index` 不感知失败细节，只看 stats 是否 None。

---

## Testing

### 单元测试（`tests/test_analytics.py`）

全部 `unittest.mock.patch`，无真实网络：

```python
class TestFetchStats(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"total_visits": 1234, "total_accepted": 567}'
        )
        result = fetch_stats("code12345", "tk_xxx")
        self.assertEqual(result, {"pv": 1234, "uv": 567})

    @patch("urllib.request.urlopen")
    def test_401_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))

    # ... 其余 6 case
```

### 端到端验证（本地）

1. 临时把 `analytics.enabled` 设为 `true`，填真实 GC code + token
2. `python -m src.build drafts/<某系列>`
3. 检查 `output/index.html`：
   - `<head>` 含 `<script data-goatcounter="https://<code>.goatcounter.com/count"`
   - footer 含 `<span class="footer-stats">`
4. 部署后浏览器查看

### CI 守护

- 现有 `tests/test_stages.py::TestBuildReadOnlyContract` 已守住"build 不调 polish"，本设计不引入新契约
- 新增 `tests/test_analytics.py` 8 case → CI 自动跑

---

## Risks & Mitigations

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 国内 CI 拉 GC 网络超时 | 高 | widget 不渲染 | 5s timeout + 1 retry + warn not fail（与 fish-speech 策略一致） |
| GC API 字段未来变更 | 低 | fetch_stats 返回 None | 宽容解析，缺失字段返回 None 不抛 |
| API key 泄漏到 git | 低 | 别人可改数据 | README 强调走 env var；可选支持 `analytics.api_key: ${ANALYTICS_API_KEY}` 引用（YAGNI 暂不实现） |
| GC 服务本身挂掉 | 低 | widget 不显示 | fetch_stats 返回 None + widget 隐身 |
| 误把 GC code 当 API key | 中 | GC 不工作 | README onboarding 步骤明确；测试覆盖 401 |
| `build.py` TestBuildReadOnlyContract 被破坏 | 极低 | 测试 fail | 本设计不调 polish，沿用 build 只读契约 |

---

## Privacy

- **无 cookie**：GoatCounter 默认不上 cookie
- **无 PII**：不收集 IP（开启 "Don't store the IP" 选项后）、UA、指纹
- **GDPR/CCPA 合规**：GoatCounter 在 EU 有数据中心
- **客户端脚本 ~3KB**：async 加载，不阻塞首屏渲染
- **数据所有权**：用户持有 GC 账号，数据可导出 CSV

---

## Out of Scope（明确不做）

- per-episode 播放追踪（不 hook player.js）
- 多 provider 抽象（umami / plausible 仅留 `provider` 字段，不实现 adapter）
- 自定义 widget 位置/样式（footer 唯一，样式固定）
- Time range 切换（仅 all-time 累计）
- 自建后端（无服务器资源）
- API key env var 注入（config.yaml 直接写，未来按需加）

---

## File Manifest（落地清单）

```
feature/site-analytics 分支:
├── config.yaml                                 # + 8 行
├── src/analytics.py                            # NEW ~80 行
├── src/feed.py                                 # + ~20 行
├── templates/site/base.html                    # + 3 行
├── templates/site/partials/footer.html         # + 5 行
├── templates/style.css                         # + 6 行
├── tests/test_analytics.py                     # NEW ~150 行
├── README.md                                   # + ~25 行
└── docs/superpowers/specs/2026-08-21-site-analytics-design.md  # 本文件
```

**预计改动规模**：
- 新增：~230 行
- 修改：~70 行
- 总体：~300 行（含测试）

---

## Setup / Onboarding 摘要（README 章节副本）

5 分钟接入：

1. 访问 https://www.goatcounter.com/start 注册（免费 hobby 档）
2. 添加站点 `binbinao.github.io/myPodcast` → 拿 8 字符 site code
3. Settings → "Allow API access" 开 → 复制 token
4. 填 `config.yaml`：
   ```yaml
   analytics:
     enabled: true
     code: "<your_code>"
     api_key: "<your_token>"
   ```
5. `python -m src.build drafts/<某系列>` → push → 看 `output/index.html` `<head>` 有 GC script、footer 有 stats

**失败兜底**：API key 错 / 网络超时 → widget 不渲染，build warn 但继续（不影响发布）。

---

## 决策记录

| 决策 | 选项 | 选定 | 理由 |
|---|---|---|---|
| 分析服务 | Plausible / Umami / GoatCounter / Cloudflare / GA | **GoatCounter** | 免费 hobby 档 + 隐私优先 + 国内访问稳定 + 轻量 |
| 实现方式 | A 构建时拉 / B 客户端拉 / C 折中 | **A 构建时拉** | 与 build.py 现有数据驱动模式一致 + GH Pages 静态 + 最少代码 |
| Widget 位置 | footer / about / hero | **footer** | 最不抢戏，符合现有低调设计 |
| 显示内容 | UV+PV / +节目数 / +热门 | **仅 UV+PV** | YAGNI，完成需求 |
| 失败兜底 | 隐身 / 占位 / fail build | **隐身**（不渲染） | 不引入视觉噪点 + 不阻断发布 |
| 错误级别 | warn / fail | **warn** | 国内 CI 拉 GC 网络风险高，fail build 会让站点永久红 |

---

## 后续可能（future work）

- API key env var 注入（`${ANALYTICS_API_KEY}`）
- 多 provider 抽象（Umami Cloud / Plausible）当 GoatCounter 不够用
- per-episode 播放追踪（hook player.js 的 audio play 事件）
- Top 3 热门节目 widget（拉 `/api/v0/stats/hits`）
- 自定义 widget 主题切换