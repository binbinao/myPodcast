# Site Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add UV/PV tracking to https://binbinao.github.io/myPodcast/ via GoatCounter, build-time API fetch embedded in HTML, footer widget showing "X 次访问 · Y 位独立访客".

**Architecture:** New `src/analytics.py` calls GoatCounter `/api/v0/stats/total` at build time via stdlib `urllib`. `src/feed.py:build_index()` passes the result (or `None`) to Jinja templates. `templates/site/base.html` injects GC's `<script data-goatcounter>` when enabled; `templates/site/partials/footer.html` renders the widget. Default disabled — zero-impact when not configured. Any API failure → warn + widget hidden, build continues.

**Tech Stack:** Python 3.13 stdlib only (`urllib.request`, `json`), Jinja2 (already a dep), `unittest.mock` for tests. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-08-21-site-analytics-design.md](../specs/2026-08-21-site-analytics-design.md)

---

## File Structure

**Files created:**
- [src/analytics.py](../../../src/analytics.py) — `fetch_stats(code, api_key) -> dict | None`. Stdlib HTTP client to GoatCounter. ~80 lines.
- [tests/test_analytics.py](../../../tests/test_analytics.py) — 10 test cases covering `fetch_stats` (6) and `build_index` integration (4). ~150 lines.

**Files modified:**
- [config.yaml](../../../config.yaml) — add `analytics:` block (8 lines).
- [src/feed.py](../../../src/feed.py) — `build_index()` reads `podcast.analytics`, calls `fetch_stats`, passes to template (~20 lines).
- [templates/site/base.html](../../../templates/site/base.html) — conditional `<script data-goatcounter>` in `<head>` (3 lines).
- [templates/site/partials/footer.html](../../../templates/site/partials/footer.html) — conditional `<span class="footer-stats">` (5 lines).
- [templates/style.css](../../../templates/style.css) — `.footer-stats` rule (6 lines).
- [README.md](../../../README.md) — "站点访问统计（GoatCounter）" onboarding section (~25 lines).

**File boundaries** (one responsibility per file):
- `src/analytics.py` — only knows how to talk to GoatCounter API. No template, no config knowledge.
- `src/feed.py` (existing) — orchestrates: reads config, calls analytics, passes to template. Existing responsibilities unchanged.
- Templates — pure rendering, conditional logic lives in Jinja.

---

## Conventions

- Test framework: `unittest` (project standard, see [tests/test_hescape.py](../../../tests/test_hescape.py))
- Test discovery: `python -m unittest discover -s tests -v`
- All test files import via `sys.path.insert(0, str(ROOT))` pattern (see [tests/test_feed_snapshot.py:24-25](../../../tests/test_feed_snapshot.py#L24-L25))
- `build` is read-only on drafts (`tests/test_stages.py::TestBuildReadOnlyContract` enforces). Plan does NOT modify this contract.

---

## Task 1: TDD fetch_stats — happy path

**Files:**
- Create: [src/analytics.py](../../../src/analytics.py)
- Create: [tests/test_analytics.py](../../../tests/test_analytics.py)

- [ ] **Step 1: Write failing test for fetch_stats happy path**

Create [tests/test_analytics.py](../../../tests/test_analytics.py):

```python
"""站点访问统计：从 GoatCounter API 拉取 UV/PV。

所有测试走 unittest.mock,无真实 HTTP。
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analytics import fetch_stats  # noqa: E402


def _mock_urlopen_response(body: bytes) -> MagicMock:
    """构造 mock context manager + read() 返回 body。"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    return mock_cm


class TestFetchStats(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_success_returns_pv_uv(self, mock_urlopen: MagicMock) -> None:
        """GC 返回 total_visits + total_accepted → fetch_stats 返回 dict。"""
        body = json.dumps({
            "total_visits": 1234,
            "total_accepted": 567,
            "starts": 999,
        }).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        result = fetch_stats("code12345", "tk_xxx")
        self.assertEqual(result, {"pv": 1234, "uv": 567})

    @patch("urllib.request.urlopen")
    def test_passes_bearer_auth_header(self, mock_urlopen: MagicMock) -> None:
        """Authorization header 必须带 Bearer token。"""
        body = json.dumps({"total_visits": 1, "total_accepted": 1}).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        fetch_stats("code12345", "tk_xxx")
        # urlopen 收到 Request 对象,验证 header
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertEqual(req.headers["Authorization"], "Bearer tk_xxx")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails (no implementation yet)**

Run: `.venv/bin/python -m unittest tests.test_analytics -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.analytics'`

- [ ] **Step 3: Implement fetch_stats (happy path)**

Create [src/analytics.py](../../../src/analytics.py):

```python
"""站点访问统计：从 GoatCounter API 拉取 UV/PV。

- 单一职责: 只懂 GC API,不知道模板/配置
- 任何错误返回 None,绝不 raise
- 5s 超时 + 1 重试,国内 CI 拉 GC 受限时 warn 不 fail
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

GOATCOUNTER_API = "https://{code}.goatcounter.com/api/v0/stats/total"
TIMEOUT_SEC = 5
RETRY = 1


def fetch_stats(code: str, api_key: str) -> dict[str, int] | None:
    """拉取 GC total stats,返回 {"pv": int, "uv": int} 或 None。

    Args:
        code: 8 字符 GoatCounter site code
        api_key: GC "Allow API access" 生成的 token

    Returns:
        {"pv": visits, "uv": visitors} 或 None(任意错误)
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
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError, OSError) as e:
            if attempt < RETRY:
                continue
            from .log import logger as log
            log.warning(f"[analytics] fetch_stats 失败: {e}")
            return None
    return None  # unreachable,for type checker


def _parse(data: dict[str, Any]) -> dict[str, int] | None:
    """宽容解析 GC 返回结构。

    GC 字段命名约定:
    - total_visits: PV
    - total_accepted: UV(去 bot 后)
    """
    pv = data.get("total_visits")
    uv = data.get("total_accepted")
    if not isinstance(pv, int) or not isinstance(uv, int):
        return None
    return {"pv": pv, "uv": uv}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_analytics -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/analytics.py tests/test_analytics.py
git commit -m "feat(analytics): fetch_stats 拉 GoatCounter total stats + happy path 测试"
```

---

## Task 2: TDD fetch_stats — error paths

**Files:**
- Modify: [tests/test_analytics.py](../../../tests/test_analytics.py)

- [ ] **Step 1: Add 4 failing tests for error paths**

Append to `TestFetchStats` class in [tests/test_analytics.py](../../../tests/test_analytics.py):

```python
    @patch("urllib.request.urlopen")
    def test_401_returns_none(self, mock_urlopen: MagicMock) -> None:
        """API key 错/缺 → GC 401 → 返回 None。"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None,
        )
        self.assertIsNone(fetch_stats("code12345", "wrong_key"))

    @patch("urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen: MagicMock) -> None:
        """网络超时(国内 CI 拉 GC) → 返回 None。"""
        mock_urlopen.side_effect = TimeoutError("timed out")
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))

    @patch("urllib.request.urlopen")
    def test_malformed_json_returns_none(self, mock_urlopen: MagicMock) -> None:
        """200 OK 但 body 非 JSON → 返回 None。"""
        mock_urlopen.return_value = _mock_urlopen_response(b"<html>500 error</html>")
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))

    @patch("urllib.request.urlopen")
    def test_missing_keys_returns_none(self, mock_urlopen: MagicMock) -> None:
        """200 OK + JSON,但缺 total_accepted → 返回 None。"""
        body = json.dumps({"total_visits": 100}).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))
```

- [ ] **Step 2: Run new tests to verify they all pass**

Run: `.venv/bin/python -m unittest tests.test_analytics.TestFetchStats -v`
Expected: 6 tests PASS (4 new + 2 from Task 1)

Note: Task 1's implementation already handles all 4 error paths via the broad `except` clause. These tests confirm the contract.

- [ ] **Step 3: Commit**

```bash
git add tests/test_analytics.py
git commit -m "test(analytics): 覆盖 fetch_stats 4 个错误路径(401/timeout/malformed/missing)"
```

---

## Task 3: TDD build_index — emit GC script tag when enabled

**Files:**
- Modify: [tests/test_analytics.py](../../../tests/test_analytics.py)
- Modify: [src/feed.py](../../../src/feed.py)
- Modify: [templates/site/base.html](../../../templates/site/base.html)

- [ ] **Step 1: Write failing test for build_index script tag**

Add to [tests/test_analytics.py](../../../tests/test_analytics.py) (new class):

```python
class TestBuildIndexAnalytics(unittest.TestCase):
    """build_index 集成:验证 analytics script tag 渲染。"""

    def _setup_out_dir(self) -> tuple[Path, Path]:
        """返回 (tmp_out_dir, project_root)。"""
        tmp = Path(tempfile.mkdtemp(prefix="analytics-test-"))
        # build_index 读 manifest.json(空数组就行)+ 渲染 index.html
        (tmp / "manifest.json").write_text(
            json.dumps({"episodes": []}), encoding="utf-8",
        )
        return tmp, ROOT

    def _podcast_cfg(self, analytics: dict | None) -> dict:
        cfg = {
            "title": "Test",
            "description": "Test",
            "tagline": "T",
            "website": "https://example.com",
            "language": "zh-CN",
            "author": "T",
            "cover": "",
            "subscribe": {"enabled": False},
        }
        if analytics is not None:
            cfg["analytics"] = analytics
        return cfg

    @patch("src.analytics.fetch_stats", return_value={"pv": 100, "uv": 50})
    def test_emits_script_tag_when_enabled(self, mock_fetch: MagicMock) -> None:
        """enabled=true + code 填了 → output/index.html <head> 含 GC script。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                'data-goatcounter="https://abc12345.goatcounter.com/count"',
                html,
            )
            self.assertIn('src="//gc.zgo.at/count.js"', html)
            mock_fetch.assert_called_once_with("abc12345", "tk_x")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.analytics.fetch_stats", return_value={"pv": 100, "uv": 50})
    def test_no_script_when_disabled(self, mock_fetch: MagicMock) -> None:
        """enabled=false → 无 GC script,fetch_stats 不被调用。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": False, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("data-goatcounter", html)
            mock_fetch.assert_not_called()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
```

Add `import tempfile` to the top imports of the file.

- [ ] **Step 2: Run new tests to verify they fail (no wiring yet)**

Run: `.venv/bin/python -m unittest tests.test_analytics.TestBuildIndexAnalytics -v`
Expected: FAIL — `src.feed` doesn't pass `analytics` to template yet (no script tag rendered)

- [ ] **Step 3: Wire analytics into build_index**

Modify [src/feed.py](../../../src/feed.py) `build_index()`. Find the existing `template.render(...)` call (around line 627) and add the analytics block right before it (after `subscribe_html` is generated, so all heavy assembly is done before the optional network call):

```python
    # ---- 站点统计(analytics)----
    # 默认 disabled;enabled + code 都齐才拉 GC,失败 widget 隐身
    # 放在 render 前是为了不让 GC 网络阻塞 build 主体计算
    analytics_cfg = podcast.get("analytics", {}) or {}
    stats: dict[str, int] | None = None
    if analytics_cfg.get("enabled") and analytics_cfg.get("code"):
        from .analytics import fetch_stats
        stats = fetch_stats(
            analytics_cfg["code"],
            analytics_cfg.get("api_key", ""),
        )
```

Then add `analytics=analytics_cfg, stats=stats` to the `template.render(...)` kwargs:

```python
    html = template.render(
        title=title,
        tagline=tagline,
        description=desc,
        base=base,
        cover=cover,
        language=language,
        author=author,
        hero=hero_html,
        about=about_html,
        subscribe=subscribe_html,
        groups=groups_ctx,
        latest=latest_ctx,
        player_js=player_js,
        feed_js=feed_js,
        analytics=analytics_cfg,    # 新增
        stats=stats,                 # 新增
    )
```

- [ ] **Step 4: Add Jinja conditional in base.html**

Modify [templates/site/base.html](../../../templates/site/base.html). Add right before `</head>`:

```html
{% if analytics and analytics.enabled and analytics.code %}
<script data-goatcounter="https://{{ analytics.code }}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_analytics -v`
Expected: 4 tests PASS (2 from Task 1+2 + 2 new)

- [ ] **Step 6: Commit**

```bash
git add src/feed.py templates/site/base.html tests/test_analytics.py
git commit -m "feat(analytics): build_index 集成 fetch_stats + base.html 注入 GC script"
```

---

## Task 4: TDD build_index — footer widget

**Files:**
- Modify: [tests/test_analytics.py](../../../tests/test_analytics.py)
- Modify: [templates/site/partials/footer.html](../../../templates/site/partials/footer.html)
- Modify: [templates/style.css](../../../templates/style.css)

- [ ] **Step 1: Add 2 failing tests for footer widget**

Add to `TestBuildIndexAnalytics` class:

```python
    @patch("src.analytics.fetch_stats", return_value={"pv": 1234, "uv": 567})
    def test_emits_footer_widget_when_stats(self, mock_fetch: MagicMock) -> None:
        """stats 有值 → footer 含 .footer-stats span,数字带千位分隔符。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertIn("footer-stats", html)
            self.assertIn("1,234 次访问", html)
            self.assertIn("567 位独立访客", html)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.analytics.fetch_stats", return_value=None)
    def test_widget_hidden_when_stats_none(self, mock_fetch: MagicMock) -> None:
        """fetch_stats 返回 None(API 失败) → footer 无 .footer-stats。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("footer-stats", html)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_analytics.TestBuildIndexAnalytics -v`
Expected: 2 new tests FAIL — footer.html has no stats span

- [ ] **Step 3: Add footer stats span**

Modify [templates/site/partials/footer.html](../../../templates/site/partials/footer.html):

```html
<footer class="site-footer">
  <p class="footer-credit">由 斌哥 用 <a href="https://github.com/binbinao/myPodcast">myPodcast</a> 流水线制作。{% if stats and (stats.pv or stats.uv) %} <span class="footer-stats">{{ "{:,}".format(stats.pv) }} 次访问 · {{ "{:,}".format(stats.uv) }} 位独立访客</span>{% endif %}</p>
</footer>
```

- [ ] **Step 4: Add .footer-stats CSS**

Append to [templates/style.css](../../../templates/style.css):

```css
.footer-stats {
  margin-left: 1rem;
  font-size: 0.85em;
  opacity: 0.7;
}
```

- [ ] **Step 5: Run tests to verify all pass**

Run: `.venv/bin/python -m unittest tests.test_analytics -v`
Expected: 6 tests PASS (4 from Tasks 1-3 + 2 new)

- [ ] **Step 6: Commit**

```bash
git add templates/site/partials/footer.html templates/style.css tests/test_analytics.py
git commit -m "feat(analytics): footer widget 渲染 UV/PV + 千位分隔符"
```

---

## Task 5: Add config.yaml + README onboarding

**Files:**
- Modify: [config.yaml](../../../config.yaml)
- Modify: [README.md](../../../README.md)

- [ ] **Step 1: Add analytics block to config.yaml**

Append to [config.yaml](../../../config.yaml) at the end:

```yaml

# 站点访问统计 (GoatCounter)
# provider: goatcounter (https://www.goatcounter.com,免费 hobby 档)
# 不配置或 enabled=false 时整个统计模块完全 pass-through,零侵入
# 5 分钟接入:见 README "站点访问统计(GoatCounter)" 章节
analytics:
  enabled: false                        # 默认 false;用户注册 GC 后改为 true
  provider: "goatcounter"               # 留作未来扩展点(umami/plausible)
  code: ""                              # 8 字符 site code,注册后从 GC dashboard 复制
  api_key: ""                           # GC Settings → "Allow API access" 开关后生成的 token
```

- [ ] **Step 2: Add README onboarding section**

In [README.md](../../../README.md), add a new section right before `## 单测`:

```markdown
## 站点访问统计(GoatCounter)

5 分钟接入,默认关闭,无副作用:

1. 访问 [goatcounter.com/start](https://www.goatcounter.com/start) 注册(免费 hobby 档)
2. 添加站点 `binbinao.github.io/myPodcast` → 拿 8 字符 site code
3. Settings → "Allow API access" 开 → 复制 token
4. 填 `config.yaml`:
   ```yaml
   analytics:
     enabled: true
     code: "<your_code>"
     api_key: "<your_token>"
   ```
5. `python -m src.build drafts/<某系列>` → push → 看 `output/index.html` `<head>` 有 GC script、footer 有 stats

**失败兜底**:API key 错 / 网络超时 → widget 不渲染,build warn 但继续(不影响发布)。
**国内 CI 提示**:如果 build 时拉 GC 超时,fetch_stats 失败但 build 仍绿,部署的 HTML 不带 footer 数字。属预期行为。
```

- [ ] **Step 3: Manual smoke test — verify config block parses**

Run:
```bash
.venv/bin/python -c "
import yaml
cfg = yaml.safe_load(open('config.yaml'))
print('analytics:', cfg.get('analytics'))
assert cfg['analytics']['enabled'] is False
assert cfg['analytics']['code'] == ''
print('config parses OK')
"
```
Expected: `analytics: {'enabled': False, 'provider': 'goatcounter', 'code': '', 'api_key': ''}` + `config parses OK`

- [ ] **Step 4: Verify no existing build output breaks**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: ALL tests PASS (existing 142 + new 10 = 152)

- [ ] **Step 5: Commit**

```bash
git add config.yaml README.md
git commit -m "docs(analytics): config.yaml block + README 5 步 onboarding"
```

---

## Task 6: End-to-end manual verification + cleanup

**Files:** none modified (read-only verification)

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: 152 tests PASS (142 existing + 10 new), 0 fail

- [ ] **Step 2: Verify build.py read-only contract still holds**

Run: `.venv/bin/python -m unittest tests.test_stages.TestBuildReadOnlyContract -v`
Expected: PASS — confirms build.py still doesn't import or call `polish`

- [ ] **Step 3: Simulate disabled-mode build (production default)**

Run:
```bash
.venv/bin/python -m src.build drafts --out /tmp/test-output --skip-audio --force 2>&1 | tail -10
```
Expected: build runs, no `data-goatcounter` in `/tmp/test-output/index.html`, no `.footer-stats` in HTML. (默认 analytics.enabled=false,零侵入。)

- [ ] **Step 4: Simulate enabled-mode with mock GC code**

Create temporary override config:

```bash
cat > /tmp/test-config.yaml <<EOF
podcast:
  title: "测试电台"
  description: "test"
  tagline: "t"
  website: "https://example.com"
  language: "zh-CN"
  author: "t"
  cover: ""
  subscribe:
    enabled: false
analytics:
  enabled: true
  provider: "goatcounter"
  code: "fakecode"
  api_key: "faketoken"
voices: {}
tts:
  backend: "edge-tts"
EOF
```

Run:
```bash
.venv/bin/python -m src.build drafts --out /tmp/test-output2 --config /tmp/test-config.yaml --skip-audio --force 2>&1 | tail -10
```

Expected:
- `[analytics] fetch_stats 失败` warning logged (fake code → DNS/connection fail)
- Build still completes with exit 0
- `/tmp/test-output2/index.html` contains `<script data-goatcounter="https://fakecode.goatcounter.com/count"` (script tag rendered when enabled+code set)
- `/tmp/test-output2/index.html` does NOT contain `.footer-stats` (stats=None because fetch failed)

- [ ] **Step 5: Clean up temp files**

```bash
rm -rf /tmp/test-output /tmp/test-output2 /tmp/test-config.yaml
```

- [ ] **Step 6: Final commit if any uncommitted changes**

```bash
git status
```
Expected: clean working tree (or only pre-existing dirty files from before this branch was created).

If any new files show up:
```bash
git add -A
git commit -m "chore: 清理 task 6 验证残留"
```

---

## Task 7: Push branch and create PR

**Files:** none

- [ ] **Step 1: Push feature branch**

Run:
```bash
git push -u origin feature/site-analytics
```
Expected: branch pushed to origin

- [ ] **Step 2: Create PR via gh CLI**

Run:
```bash
gh pr create --base main --title "feat(analytics): GoatCounter 站点访问统计 (UV/PV)" --body "$(cat <<'EOF'
## 概要

为 https://binbinao.github.io/myPodcast/ 站点增加访问统计功能,记录 UV(独立访客)和 PV(页面浏览)。

- **GoatCounter**:免费 hobby 档、隐私优先(无 cookie)、<3KB 脚本、国内访问稳定
- **构建时拉取**:build 期调 GC API,数值嵌入 HTML,无客户端拉取开销
- **零侵入默认**:analytics.enabled=false 时完全不生效

## 设计文档

- spec: docs/superpowers/specs/2026-08-21-site-analytics-design.md
- plan: docs/superpowers/plans/2026-08-21-site-analytics-plan.md

## 改动

新增:
- src/analytics.py (~80 行)
- tests/test_analytics.py (10 case)

修改:
- src/feed.py (+~20 行)
- templates/site/base.html (+3 行)
- templates/site/partials/footer.html (+5 行)
- templates/style.css (+6 行)
- config.yaml (+8 行)
- README.md (+25 行)

## 失败兜底

- API key 错 / 网络超时 → widget 不渲染,build warn 但继续(不影响发布)
- 测试全部 mock,无真实 HTTP

## 用户需手动操作

1. 注册 https://www.goatcounter.com/start
2. 添加站点 → 拿 8 字符 site code
3. Settings → Allow API access → 拿 token
4. 填 config.yaml analytics.code + api_key,设 enabled=true
5. 重新 build → push → 部署生效

详见 README "站点访问统计(GoatCounter)" 章节。

## Test Plan

- [ ] python -m unittest discover -s tests -v 全绿(152 tests)
- [ ] python -m unittest tests.test_stages.TestBuildReadOnlyContract -v 守住 draft 只读契约
- [ ] (可选)用户注册 GC 后,build with enabled=true → 浏览器看 footer 显示 UV/PV
EOF
)"
```
Expected: PR URL returned

- [ ] **Step 3: Reply to user with PR URL**

Tell the user:
- PR 链接
- 5 步 onboarding 副本
- 等 CI 跑通

---

## Summary

Total: **7 tasks**, ~30 bite-sized steps, TDD discipline throughout.

**Test count progression:**
- Start: 142 existing
- After Task 1: +2 (happy path + bearer header) → 144
- After Task 2: +4 (4 error paths) → 148
- After Task 3: +2 (script enabled + disabled) → 150
- After Task 4: +2 (widget present + hidden) → 152
- Tasks 5-7: no new tests

**Total: 152 tests after plan execution.**

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| GC count.js script tag injection | Task 3 |
| fetch_stats happy path | Task 1 |
| fetch_stats 4 error paths | Task 2 |
| build_index wires analytics_cfg + fetch_stats | Task 3 |
| build_index no script when disabled | Task 3 |
| Footer widget shows UV/PV | Task 4 |
| Widget hidden when stats None | Task 4 |
| config.yaml analytics block | Task 5 |
| README 5-step onboarding | Task 5 |
| Failure: warn not fail | Tasks 3, 4, 6 |
| No new dependencies | All (stdlib only) |
| build.py read-only contract preserved | Task 6 (Step 2) |
| YAGNI: no per-episode tracking | Out of scope (not implemented) |
| YAGNI: no multi-provider | Out of scope |

All spec requirements covered. YAGNI items explicitly omitted.

---

## Risks Recap

- **国内 CI 拉 GC 网络超时**:Tasks 1+2+3+4 测试已覆盖,失败 warn 不 fail
- **API key 误提交**:config.yaml 留空,用户手动填;README onboarding 提示
- **GC API 字段未来变更**:宽容解析 + return None,不抛
- **build.py 契约**:Task 6 Step 2 显式回归测试