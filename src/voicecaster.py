"""音色选型：按文章类型自动选 voice_id。

策略：
- frontmatter `voice:` 显式 > LLM 推断（mode=llm 且 llm.api_key 配了）> 启发式规则 > default_voice

5 类文章类型：reflective / tutorial / business / casual / interview。
关键词词典和音色映射可在 config.yaml 的 `voicecaster.keywords` 与
`voicecaster.voices` 段自定义；未配时使用下方的 DEFAULT_*。
"""
from __future__ import annotations

import re
from typing import Any

from .log import logger as log
from .polish import llm_complete


# 默认词典（config.yaml 没配 voicecaster.* 时使用）
DEFAULT_ARTICLE_TYPES: dict[str, dict[str, Any]] = {
    "reflective": {  # 反思/独白/心路历程
        "voices": ["audiobook_male_1", "female-chengshu", "audiobook_male_2"],
        "keywords": [
            "反思", "复盘", "那年", "当时", "事后看", "回头看", "回过头", "回想",
            "被碾压", "被折叠", "被淘汰", "心路", "心路历程", "当时我", "后来我才",
            "感悟", "感概", "感触", "体会", "感受", "个人的一点", "个人的一些",
            "默默", "悄悄地", "那一刻", "我意识到", "我承认", "我想起",
        ],
    },
    "tutorial": {  # 行业资讯/科普/教程
        "voices": ["male-qn-jingying", "female-yujie", "male-qn-daxuesheng"],
        "keywords": [
            "架构", "性能", "算法", "原理", "对比", "测评", "评测", "实测",
            "教程", "指南", "如何", "怎么", "步骤", "实现", "源码", "代码",
            "为什么", "区别", "选型", "分析", "解析", "底层", "机制",
            "协议", "接口", "API", "SDK", "版本", "升级", "迁移",
        ],
    },
    "business": {  # 商业/财经/市场
        "voices": ["male-qn-jingying", "female-yujie"],
        "keywords": [
            "增长", "变现", "估值", "融资", "上市", "市值", "营收", "净利润",
            "现金流", "毛利率", "增长曲线", "商业模式", "付费", "订阅", "ARR",
            "PMF", "市场份额", "用户量", "DAU", "MAU", "复购",
        ],
    },
    "casual": {  # 软文/随笔/生活
        "voices": ["male-qn-qingse", "female-tianmei", "female-shaonv"],
        "keywords": [
            "今天", "周末", "晚饭", "随手", "试了试", "试了一下", "新发现",
            "生活", "散步", "做饭", "买了", "入手", "拆箱", "开箱", "体验",
            "随手记", "碎碎念", "日记", "随笔",
        ],
    },
    "interview": {  # 对话/采访/Q&A
        "voices": ["audiobook_male_2", "female-shaonv"],
        "keywords": [
            "你怎么看", "采访", "对话", "我问", "回答", "问答", "Q&A", "QA",
            "访谈", "专访", "嘉宾", "主持", "聊聊", "聊一聊",
        ],
    },
}

# 标题加权（标题里的词计 2 分；正文里的词计 1 分）
_TITLE_BOOST = 2


def _load_types(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从 cfg.voicecaster.keywords / voices 合并默认词典。

    合并策略：config 配的覆盖默认；未配项保留默认。
    """
    vc_cfg = cfg.get("voicecaster", {})
    custom_kw = vc_cfg.get("keywords", {})
    custom_voices = vc_cfg.get("voices", {})

    merged: dict[str, dict[str, Any]] = {}
    for typ, defaults in DEFAULT_ARTICLE_TYPES.items():
        d = dict(defaults)
        if typ in custom_kw:
            d["keywords"] = list(custom_kw[typ])
        if typ in custom_voices:
            d["voices"] = list(custom_voices[typ])
        merged[typ] = d
    # 用户自定义的额外类型（如 "engineering"）也加入
    for typ in custom_kw.keys() | custom_voices.keys():
        if typ not in merged:
            merged[typ] = {
                "voices": list(custom_voices.get(typ, ["female-yujie"])),
                "keywords": list(custom_kw.get(typ, [])),
            }
    return merged


def _score_article(text: str, types: dict[str, dict[str, Any]]) -> dict[str, int]:
    """返回 {article_type: score}。"""
    title = ""
    body = text
    fm = re.search(r"^---\n(.*?)\n---\n", text, flags=re.S | re.M)
    if fm:
        body = text[fm.end():]
    h1 = re.search(r"^#\s+(.+)$", body, flags=re.M)
    if h1:
        title = h1.group(1)
        body = (body[:h1.start()] + body[h1.end():])

    scores: dict[str, int] = {}
    for typ, tcfg in types.items():
        s = 0
        for kw in tcfg["keywords"]:
            if not kw:
                continue
            s += body.count(kw)
            if title and kw in title:
                s += _TITLE_BOOST
        scores[typ] = s
    return scores


def _best_type(scores: dict[str, int]) -> str | None:
    if not scores or max(scores.values()) == 0:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[0][0]


def _rule_cast(article_text: str, cfg: dict[str, Any]) -> str | None:
    types = _load_types(cfg)
    scores = _score_article(article_text, types)
    typ = _best_type(scores)
    if not typ:
        return None
    log.debug(f"voicecaster rule: type={typ} scores={scores}")
    return types[typ]["voices"][0]


def _llm_cast(article_text: str, cfg: dict[str, Any]) -> str | None:
    types = _load_types(cfg)
    types_str = " | ".join(types.keys())
    voices = "; ".join(
        f"{t}={'/'.join(tcfg['voices'])}" for t, tcfg in types.items()
    )
    sys_prompt = (
        "你是播客音色规划器。下面给一段文章，请判断它属于哪一类，"
        f"只能从 [{types_str}] 中选一个，输出英文标签即可，不要解释。\n"
        f"音色映射参考：{voices}。"
    )
    snippet = article_text[:2000]
    try:
        label = llm_complete(sys_prompt, snippet, cfg).strip().lower()
    except Exception as e:  # noqa: BLE001
        log.warning(f"voicecaster LLM 失败，回退 rule: {e}")
        return _rule_cast(article_text, cfg)
    if label not in types:
        log.warning(f"voicecaster LLM 返回未知类型 '{label}'，回退 rule")
        return _rule_cast(article_text, cfg)
    return types[label]["voices"][0]


def cast(article_text: str, cfg: dict[str, Any], explicit: str = "") -> str:
    """主入口：返回 voice_id。

    优先级：
      1) frontmatter 显式 voice 字段（explicit 参数）
      2) voicecaster.mode == "llm" 时调 LLM
      3) 启发式规则
      4) config voicecaster.default_voice / voices_minimax.default
    """
    if explicit:
        return explicit

    vc = cfg.get("voicecaster", {})
    mode = str(vc.get("mode", "rule")).lower()
    if mode == "llm" and cfg.get("llm", {}).get("enable") and cfg["llm"].get("api_key"):
        v = _llm_cast(article_text, cfg)
        if v:
            return v

    v = _rule_cast(article_text, cfg)
    if v:
        return v

    # 兜底
    return (
        vc.get("default_voice")
        or cfg.get("voices_minimax", {}).get("default")
        or "audiobook_male_1"
    )