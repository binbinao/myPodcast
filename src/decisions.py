"""prepare 阶段三决策门：format / voice / split。

设计原则：
- AI 先给推荐 + 理由；用户永远有最终决定权。
- 默认走交互（stdin 提问，回车=接受推荐）。
- 加 auto_accept=True 时无人值守，全接受 AI 推荐（CI / 脚本用）。
- 决策落到 draft frontmatter + 同目录 _decisions.json（可追溯）。

三门：
1. format   : solo / duo    推荐源 = 文章对话/独白信号加权
2. voice    : voice_id      推荐源 = voicecaster.cast() + 备选
3. split    : by_h2/by_chars/by_duration + max_chars/max_duration
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .log import logger as log


# =============================================================================
# AI 推荐（纯函数，便于测试）
# =============================================================================


def recommend_format(article_text: str) -> tuple[str, float, str]:
    """推荐 solo/duo。

    返回 (choice, confidence 0-1, reason)。

    信号（每千字加权打分）：
      duo 倾向：引号密度、对话词、Q&A 标记、问答句
      solo 倾向：第一人称代词密度、独白/反思词
    """
    n = max(len(article_text), 1)

    # duo 信号
    n_quotes = len(re.findall(r'["""「」『』]', article_text))
    n_dialogue = sum(
        article_text.count(w)
        for w in ("你说", "他问", "她答", "对话", "采访", "访谈", "聊一聊", "Q&A", "Q & A")
    )
    n_qa_marks = len(re.findall(r'(问|提问)[：:]|(答|回复)[：:]', article_text))

    # solo 信号
    n_first_person = len(re.findall(r'我[们]?[一-龥]{0,2}', article_text))
    n_monologue = sum(
        article_text.count(w)
        for w in ("那一刻", "回想", "反思", "独白", "心路", "事后看", "回过头",
                 "我意识到", "我承认", "我意识到")
    )

    # 每千字归一化分
    duo_per_k = (n_quotes * 10 + n_dialogue * 5 + n_qa_marks * 8) / n * 1000
    solo_per_k = (n_first_person * 2 + n_monologue * 8) / n * 1000

    diff = duo_per_k - solo_per_k
    if n < 200:
        return ("duo", 0.5, f"文章太短（{n}字），信号不足；用兜底 duo")

    if abs(diff) < 0.4:
        return ("duo", 0.5,
                f"信号中性（duo={duo_per_k:.1f} / solo={solo_per_k:.1f}），走兜底 duo")

    if diff > 0:
        conf = min(0.95, 0.55 + diff / 12)
        return ("duo", round(conf, 2),
                f"对话感强：引号 {n_quotes} / 对话词 {n_dialogue} / Q&A {n_qa_marks}；"
                f"推荐双人")
    else:
        conf = min(0.95, 0.55 + (-diff) / 12)
        return ("solo", round(conf, 2),
                f"独白感强：第一人称 {n_first_person} / 反思词 {n_monologue}；"
                f"推荐单人")


def recommend_voice(article_text: str, cfg: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    """推荐 voice_id。

    返回 (voice_id, article_type, reason, alternatives)。

    调 voicecaster.cast() 拿首选；同 article_type 下的备选 = voices[1:]。
    """
    from .voicecaster import cast as vc_cast, _load_types, _score_article, _best_type

    chosen = vc_cast(article_text, cfg, explicit="")
    types = _load_types(cfg)
    scores = _score_article(article_text, types)
    typ = _best_type(scores) or "reflective"

    # 备选 = 同类型其他 voices
    typ_voices = types.get(typ, {}).get("voices", [])
    alternatives = typ_voices[1:] if typ else []

    # 构造 reason
    if scores:
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:2]
        score_str = " / ".join(f"{k}={v}" for k, v in top if v > 0)
    else:
        score_str = "无信号"
    reason = f"归类「{typ}」（{score_str}）"

    return (chosen, typ, reason, alternatives)


def recommend_duo_voices(
    article_text: str,
    cfg: dict[str, Any],
) -> tuple[str, str, str, list[tuple[str, str, str]]]:
    """为 duo 推荐 host/guest 音色组合。

    返回 (host_voice, guest_voice, reason, alternatives)。
    alternatives 每项为 (host, guest, label)。推荐优先保证角色反差，避免两个
    相近男声在长对话里难以区分。
    """
    primary, typ, reason, same_type = recommend_voice(article_text, cfg)
    voice_cfg = cfg.get("voices_minimax", {})

    # 教程/商业内容优先专业男声 + 成熟女声，角色辨识度高。
    female_candidates = [v for v in same_type if v.startswith("female-") or "female" in v]
    if typ in ("tutorial", "business"):
        host = primary
        guest = female_candidates[0] if female_candidates else "female-yujie"
    elif typ == "reflective":
        host, guest = "audiobook_male_1", "female-chengshu"
    else:
        host = primary or str(voice_cfg.get("host", "audiobook_male_1"))
        guest = str(voice_cfg.get("guest", "male-qn-qingse"))

    candidates = [
        (host, guest, f"内容匹配：{typ}"),
        ("audiobook_male_1", "female-chengshu", "沉稳耐听：有声书男声 + 成熟女声"),
        ("male-qn-jingying", "male-qn-daxuesheng", "全男声：专业主讲 + 年轻追问"),
    ]
    # 去重，推荐组合不重复出现在备选里。
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for h, g, label in candidates:
        if h == g or (h, g) in seen:
            continue
        seen.add((h, g))
        unique.append((h, g, label))

    return host, guest, f"{reason}；双人节目用明显声线反差保证角色可辨", unique[1:]


def recommend_split(
    article_text: str,
    cfg: dict[str, Any],
    series_title: str = "",
    fmt: str = "duo",
    series_slug: str = "",
) -> tuple[str, dict[str, Any], int, str]:
    """推荐切分策略 + 预估集数（用 plan_episodes 实际跑一遍拿真实集数）。

    返回 (strategy, params, episode_count, reason)。

    策略：
      by_h2        - H2 章节切（一章一集，超长按 H3/段落再切）
      by_chars     - 按 max_chars 切
      by_duration  - 按 max_duration（分钟）切，按 ~250 字/分 估字数
    """
    from .split import plan_episodes, _count

    split_cfg = cfg.get("split", {})
    min_c = int(split_cfg.get("min_episode_chars", 600))
    max_c = int(split_cfg.get("max_episode_chars", 3000))
    default_max_dur = int(split_cfg.get("default_max_duration_min", 12))
    chars_per_min = int(split_cfg.get("chars_per_minute", 250))
    total_chars = _count(article_text)

    # 跑 by_h2 拿真实集数（含引言合并 + 长章节细分）
    plans_h2 = plan_episodes(
        article_text, cfg, series_title or "tmp", fmt,
        series_slug=series_slug, strategy="by_h2",
        max_chars_override=max_c,
    )
    n_h2 = len(plans_h2)

    if n_h2 >= 2:
        avg = total_chars / max(n_h2, 1)
        strategy, params = "by_h2", {"min_episode_chars": min_c, "max_episode_chars": max_c}
        reason = (f"{n_h2} 个 H2 章节（含引言合并）平均 {avg:.0f} 字/集；"
                  f"推荐按章节切")
        return (strategy, params, n_h2, reason)

    # 回退：按字数
    n_by_chars = max(1, (total_chars + max_c - 1) // max_c)
    strategy, params = "by_chars", {"min_episode_chars": min_c, "max_episode_chars": max_c}
    reason = (f"H2 章节不足（n={n_h2}）；总 {total_chars} 字按 {max_c} 字/集 "
              f"→ {n_by_chars} 集")
    return (strategy, params, n_by_chars, reason)


def _split_alternatives(
    article_text: str,
    cfg: dict[str, Any],
    n_h2_eps: int,
    series_title: str = "",
    fmt: str = "duo",
    series_slug: str = "",
) -> list[tuple[str, dict[str, Any], int, str]]:
    """生成切分策略的所有备选（供交互菜单）。与 recommend_split 用同源的 plan_episodes。"""
    from .split import plan_episodes, _count

    split_cfg = cfg.get("split", {})
    min_c = int(split_cfg.get("min_episode_chars", 600))
    max_c = int(split_cfg.get("max_episode_chars", 3000))
    default_max_dur = int(split_cfg.get("default_max_duration_min", 12))
    chars_per_min = int(split_cfg.get("chars_per_minute", 250))
    total_chars = _count(article_text)

    plans_h2 = plan_episodes(
        article_text, cfg, series_title or "tmp", fmt,
        series_slug=series_slug, strategy="by_h2",
        max_chars_override=max_c,
    )
    n_h2 = len(plans_h2)

    plans_chars = plan_episodes(
        article_text, cfg, series_title or "tmp", fmt,
        series_slug=series_slug, strategy="by_chars",
        max_chars_override=max_c,
    )
    n_by_chars = len(plans_chars)

    plans_dur = plan_episodes(
        article_text, cfg, series_title or "tmp", fmt,
        series_slug=series_slug, strategy="by_duration",
        max_duration_min=default_max_dur, chars_per_minute=chars_per_min,
    )
    n_by_dur = len(plans_dur)

    alts = []
    if n_h2 >= 2:
        alts.append(("by_h2",
                     {"min_episode_chars": min_c, "max_episode_chars": max_c},
                     n_h2,
                     f"按 H2 章节（{n_h2} 集）"))
    alts.append(("by_chars",
                 {"min_episode_chars": min_c, "max_episode_chars": max_c},
                 n_by_chars,
                 f"按 {max_c} 字/集（{n_by_chars} 集）"))
    alts.append(("by_duration",
                 {"max_duration_min": default_max_dur,
                  "chars_per_minute": chars_per_min,
                  "min_episode_chars": min_c,
                  "max_episode_chars": max_c},
                 n_by_dur,
                 f"按 {default_max_dur} 分钟/集（{n_by_dur} 集）"))
    return alts


# =============================================================================
# CLI 交互（stdin 提问，回车=接受推荐；auto_accept=True 全自动）
# =============================================================================


def _prompt(label: str, default: str = "") -> str:
    """单行输入提示。带默认值时显示 [default]。空输入 = 接受默认。"""
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"  → {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default


def ask_format(ai_choice: str, ai_reason: str, auto_accept: bool = False) -> str:
    """返回 'solo' 或 'duo'。"""
    print()
    print(f"━━━ 1/3  FORMAT  单人/双人 ━━━")
    print(f"  AI 推荐: {ai_choice}")
    print(f"  理由: {ai_reason}")
    print(f"  [1] solo   [2] duo   [3] 重新分析")
    if auto_accept:
        log.info(f"    → 自动接受: {ai_choice}")
        return ai_choice
    while True:
        raw = _prompt("选 (回车=接受推荐)", "1" if ai_choice == "solo" else "2")
        if raw == "":
            return ai_choice
        if raw == "1":
            return "solo"
        if raw == "2":
            return "duo"
        if raw == "3":
            # 重新分析 — 让调用方再跑一遍
            return "__reanalyze__"
        print("    输入 1/2/3，或直接回车")


def ask_voice(
    ai_choice: str,
    ai_type: str,
    ai_reason: str,
    alternatives: list[str],
    all_voices: list[str],
    auto_accept: bool = False,
) -> str:
    """返回 voice_id。"""
    print()
    print(f"━━━ 2/3  VOICE  音色 ━━━")
    print(f"  AI 推荐: {ai_choice}  (类型: {ai_type})")
    print(f"  理由: {ai_reason}")
    if alternatives:
        alt_str = " / ".join(alternatives)
        print(f"  [2] 同类型备选: {alt_str}")
    print(f"  [3] 浏览全部 voice_id")
    print(f"  [4] 重新分析")
    if auto_accept:
        log.info(f"    → 自动接受: {ai_choice}")
        return ai_choice
    while True:
        default = "1"
        raw = _prompt("选 (回车=接受推荐)", default)
        if raw == "" or raw == "1":
            return ai_choice
        if raw == "2" and alternatives:
            # 同类型备选：让用户再选一个
            print(f"    同类型备选: " + " / ".join(f"[{i+1}] {v}" for i, v in enumerate(alternatives)))
            sub_raw = _prompt("选备选编号", "1")
            try:
                idx = int(sub_raw) - 1
                if 0 <= idx < len(alternatives):
                    return alternatives[idx]
            except ValueError:
                pass
            print("    无效编号，保持推荐")
            return ai_choice
        if raw == "3":
            print(f"    全部 voice_id: " + " / ".join(all_voices))
            sub_raw = _prompt("输入 voice_id", ai_choice)
            if sub_raw in all_voices or sub_raw:
                return sub_raw
            return ai_choice
        if raw == "4":
            return "__reanalyze__"
        print("    输入 1/2/3/4，或直接回车")


def ask_duo_voices(
    ai_host: str,
    ai_guest: str,
    ai_reason: str,
    alternatives: list[tuple[str, str, str]],
    all_voices: list[str],
    auto_accept: bool = False,
) -> tuple[str, str]:
    """返回 (host_voice, guest_voice)，保证 duo 的音色选择实际可执行。"""
    print()
    print("━━━ 2/3  VOICE  双人音色 ━━━")
    print(f"  AI 推荐: host={ai_host} / guest={ai_guest}")
    print(f"  理由: {ai_reason}")
    print(f"  [1] 推荐组合")
    for i, (host, guest, label) in enumerate(alternatives, start=2):
        print(f"  [{i}] {host} / {guest}（{label}）")
    print("  [m] 手动输入 host / guest voice_id")
    print("  [r] 重新分析")
    if auto_accept:
        log.info(f"    → 自动接受: host={ai_host} / guest={ai_guest}")
        return ai_host, ai_guest

    while True:
        raw = _prompt("选 (回车=接受推荐)", "1")
        if raw == "" or raw == "1":
            return ai_host, ai_guest
        if raw == "r":
            return "__reanalyze__", "__reanalyze__"
        if raw == "m":
            print("    可用 voice_id: " + " / ".join(all_voices))
            host = _prompt("host voice_id", ai_host) or ai_host
            guest = _prompt("guest voice_id", ai_guest) or ai_guest
            if host == guest:
                print("    host 与 guest 不能相同，保持推荐")
                return ai_host, ai_guest
            return host, guest
        try:
            idx = int(raw) - 2
            if 0 <= idx < len(alternatives):
                host, guest, _label = alternatives[idx]
                return host, guest
        except ValueError:
            pass
        print("    输入编号、m 或 r，或直接回车")


def _customize_split_params(
    strategy: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """当用户选按字数/时长时，让阈值也由用户拍板。"""
    out = dict(params)
    if strategy == "by_duration":
        default = int(out.get("max_duration_min", 12))
        raw = _prompt("每集目标时长（分钟）", str(default))
        try:
            minutes = int(raw or default)
            if minutes < 3 or minutes > 60:
                raise ValueError
            out["max_duration_min"] = minutes
        except ValueError:
            print(f"    无效时长，保持 {default} 分钟")
            out["max_duration_min"] = default
    elif strategy == "by_chars":
        default = int(out.get("max_episode_chars", 3000))
        raw = _prompt("每集最大字数", str(default))
        try:
            chars = int(raw or default)
            if chars < 500 or chars > 20000:
                raise ValueError
            out["max_episode_chars"] = chars
        except ValueError:
            print(f"    无效字数，保持 {default} 字")
            out["max_episode_chars"] = default
    return out


def ask_split(
    ai_choice: str,
    ai_params: dict[str, Any],
    ai_count: int,
    ai_reason: str,
    alts: list[tuple[str, dict[str, Any], int, str]],
    auto_accept: bool = False,
) -> tuple[str, dict[str, Any]]:
    """返回 (strategy, params)。"""
    print()
    print(f"━━━ 3/3  SPLIT  切分 ━━━")
    print(f"  AI 推荐: {ai_choice} → {ai_count} 集")
    print(f"  理由: {ai_reason}")
    # 列出备选项
    print(f"  [1] {ai_choice}（推荐，{ai_count} 集）")
    for i, (s, _p, n, label) in enumerate(alts, start=2):
        if s == ai_choice:
            continue
        print(f"  [{i}] {label}")
    print(f"  [r] 重新分析")
    if auto_accept:
        log.info(f"    → 自动接受: {ai_choice}")
        return ai_choice, ai_params

    # 编号 → (strategy, params)
    choices: list[tuple[str, dict[str, Any]]] = [(ai_choice, ai_params)]
    for s, p, _n, _label in alts:
        if s == ai_choice:
            continue
        choices.append((s, p))

    while True:
        raw = _prompt("选 (回车=接受推荐)", "1")
        if raw == "" or raw == "1":
            return choices[0]
        if raw == "r":
            return "__reanalyze__", {}  # type: ignore
        try:
            idx = int(raw) - 2
            if 0 <= idx < len(choices) - 1:
                return choices[idx + 1]
        except ValueError:
            pass
        print("    输入编号或 r，或直接回车")


# =============================================================================
# 主流程：把三门串起来（prepare_file 调用）
# =============================================================================


@dataclass
class Decisions:
    format: str
    voice: str
    voice_type: str
    host_voice: str = ""
    guest_voice: str = ""
    split_strategy: str = ""
    split_params: dict[str, Any] = None  # type: ignore[assignment]
    split_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def collect_decisions(
    article_text: str,
    cfg: dict[str, Any],
    auto_accept: bool = False,
    series_title: str = "",
    fmt_default: str = "duo",
    series_slug: str = "",
) -> Decisions:
    """跑完三门（必要时让用户重分析），落定 Decisions。"""
    from .voicecaster import _load_types

    # 列一下全部 voice_id 给 ask_voice 用
    types = _load_types(cfg)
    all_voices: list[str] = []
    for info in types.values():
        for v in info["voices"]:
            if v not in all_voices:
                all_voices.append(v)

    while True:
        fmt, fmt_conf, fmt_reason = recommend_format(article_text)
        fmt_choice = ask_format(fmt, fmt_reason, auto_accept=auto_accept)
        if fmt_choice == "__reanalyze__":
            continue
        # 切分依赖 format（影响 plan_episodes 的 plan.format），第一次循环里 fmt 还没敲定
        # 用 fmt_default 作为 placeholder；正式 plan_episodes 在 prepare.py 用 fmt_choice 跑
        fmt_for_split = fmt_choice or fmt_default

        if fmt_for_split == "duo":
            h, g, vreason, alts_pair = recommend_duo_voices(article_text, cfg)
            h_choice, g_choice = ask_duo_voices(
                h, g, vreason, alts_pair, all_voices,
                auto_accept=auto_accept,
            )
            if h_choice == "__reanalyze__":
                continue
            voice_choice = f"host={h_choice} / guest={g_choice}"
            vtype = "duo"
        else:
            voice, vtype, vreason, valts = recommend_voice(article_text, cfg)
            voice_choice = ask_voice(voice, vtype, vreason, valts, all_voices,
                                     auto_accept=auto_accept)
            if voice_choice == "__reanalyze__":
                continue
            h_choice, g_choice = "", ""

        strategy, params, count, reason = recommend_split(
            article_text, cfg, series_title=series_title, fmt=fmt_for_split,
            series_slug=series_slug,
        )
        alts = _split_alternatives(
            article_text, cfg, count, series_title=series_title, fmt=fmt_for_split,
            series_slug=series_slug,
        )
        strat, params_choice = ask_split(strategy, params, count, reason, alts,
                                          auto_accept=auto_accept)
        if strat == "__reanalyze__":
            continue
        # 阈值也由用户拍板：按字数 / 时长才让改；按章节就跳过。
        if strat in ("by_chars", "by_duration") and not auto_accept:
            params_choice = _customize_split_params(strat, params_choice)
        elif strat in ("by_chars", "by_duration") and auto_accept:
            # 自动模式下，记录一下用了默认阈值（备查）
            log.info(f"    auto-accept: 阈值默认 {params_choice}")

        print()
        print(f"✓ 锁定决策 →")
        print(f"    format:        {fmt_choice}")
        if fmt_for_split == "duo":
            print(f"    host voice:    {h_choice}")
            print(f"    guest voice:   {g_choice}")
        else:
            print(f"    voice:         {voice_choice}  ({vtype})")
        print(f"    split:         {strat} → {count} 集")
        return Decisions(
            format=fmt_choice,
            voice=voice_choice,
            voice_type=vtype,
            host_voice=h_choice,
            guest_voice=g_choice,
            split_strategy=strat,
            split_params=params_choice,
            split_count=count,
        )


# =============================================================================
# 持久化
# =============================================================================


def save_decisions(out_dir: Path, decisions: Decisions) -> Path:
    """把决策写到 out_dir/_decisions.json（含 AI 推荐 + 用户最终选 + 时间戳）。

    设计：单独文件，不污染 frontmatter，方便事后审计 / 重决策。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "_decisions.json"
    data = {
        "decisions": decisions.to_dict(),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p