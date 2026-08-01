"""音色规划器：基于文章内容选择合适的 TTS 音色。

优先级（高 → 低）：
1. frontmatter 显式 voice: <voice_id>    （作者指定，最高优先）
2. LLM 推断模式（mode=llm 且 llm.api_key 配了）→ 返回 voice_id
3. 启发式规则：5 类文章信号关键词计分，取最高分类
4. 兜底：config.yaml tts.minimax.default_voice（默认 audiobook_male_1）

模型与 prosody.py 同构：rule/llm 双模式，LLM 失败自动回退 rule。
"""
from __future__ import annotations

import re
from typing import Any

from .polish import llm_complete

# 文章类型 -> (候选音色, 关键词权重表)
# 候选音色用列表：按文章内容偏好顺序，越靠前越适合
ARTICLE_TYPES: dict[str, dict[str, Any]] = {
    "reflective": {  # 反思/独白/心路历程
        "voices": ["audiobook_male_1", "female-chengshu", "audiobook_female_1"],
        "keywords": [
            # 强信号：自我叙事/反思动词
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
            "为什么", "区别", "选型", "对比", "分析", "解析", "底层", "机制",
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


def _score_article(text: str) -> dict[str, int]:
    """返回 {article_type: score}。"""
    title = ""
    body = text
    # 简单抽出 frontmatter 与首个 # 标题（如果有）
    fm = re.search(r"^---\n(.*?)\n---\n", text, flags=re.S | re.M)
    if fm:
        body = text[fm.end():]
    h1 = re.search(r"^#\s+(.+)$", body, flags=re.M)
    if h1:
        title = h1.group(1)
        body = (body[:h1.start()] + body[h1.end():])

    scores: dict[str, int] = {}
    for typ, cfg in ARTICLE_TYPES.items():
        s = 0
        for kw in cfg["keywords"]:
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
    # 排序：分数高的优先；并列时按字典序稳定
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[0][0]


def _rule_cast(article_text: str, cfg: dict[str, Any]) -> str | None:
    """启发式规则：扫正文，按评分最高的文章类型返回首选 voice_id。"""
    scores = _score_article(article_text)
    typ = _best_type(scores)
    if not typ:
        return None
    return ARTICLE_TYPES[typ]["voices"][0]


def _llm_cast(article_text: str, cfg: dict[str, Any]) -> str | None:
    """LLM 推断：让 LLM 给文章类型打标签，从映射表返回 voice_id。失败回退 rule。"""
    types = " | ".join(ARTICLE_TYPES.keys())
    voices = "; ".join(
        f"{t}={'/'.join(cfg_['voices'])}"
        for t, cfg_ in ARTICLE_TYPES.items()
    )
    sys_prompt = (
        "你是播客音色规划器。下面给一段文章，请判断它属于哪一类，"
        f"只能从 [{types}] 中选一个，输出英文标签即可，不要解释。\n"
        f"音色映射参考：{voices}。"
    )
    # 截断到前 2000 字避免 token 浪费
    snippet = article_text[:2000]
    try:
        label = llm_complete(sys_prompt, snippet, cfg).strip().lower()
        # 容错：去掉句末标点 + 取最后一个 token
        label = re.sub(r"[^a-z_]", "", label)
        if label in ARTICLE_TYPES:
            return ARTICLE_TYPES[label]["voices"][0]
    except Exception:
        pass
    return _rule_cast(article_text, cfg)


def cast(article_text: str, cfg: dict[str, Any], explicit: str | None = None) -> str:
    """选择最终 voice_id。

    参数:
        article_text: 原始文章正文（带 frontmatter）
        cfg: 整体配置
        explicit: frontmatter 显式 voice 字段（最高优先）

    返回:
        voice_id 字符串
    """
    if explicit:
        return explicit
    vc = cfg.get("voicecaster", {})
    default = (
        vc.get("default_voice")
        or cfg.get("tts", {}).get("minimax", {}).get("default_voice")
        or cfg.get("voices_minimax", {}).get("default")
        or "audiobook_male_1"
    )
    mode = str(vc.get("mode", "rule")).lower()
    if mode == "llm" and cfg.get("llm", {}).get("enable") and cfg["llm"].get("api_key"):
        picked = _llm_cast(article_text, cfg)
        if picked:
            return picked
    picked = _rule_cast(article_text, cfg)
    return picked or default