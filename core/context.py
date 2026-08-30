"""上下文锚定：帮菟菚抓住"现在在聊什么"，避免回复跑题、话题切换不自然。

现象：当上下文里有太多旧话题的痕迹（历史消息、记忆、热梗等），模型容易被
带偏，冒出旧话题的尾巴（如聊"想你了"却接一句"路上注意安全"）。

思路（不改角色结构，只做标记与提示）：
1. topic_hint(text, ctx)：给模型明确「对方这句在表达什么/现在聊的主题是什么」，
   让回复紧扣当前话语，而不是被旧上下文带偏。
2. topic_switch_hint(recent_texts)：检测对方是否明显切换了话题——若上一个话题
   已结束、这句开了新话题，提示模型「此刻是新的主题，别再把旧话题扯回来」。
3. compact_hint(ctx)：当上下文较长时，提示模型"前面是背景，最新的这几句才是
   当前语境，重点接最新的"。
全部纯规则、可 mock、失败不影响对话。
"""
import re

# 句末语气词/收尾词：用户话语里若几乎全是这些，说明是闲聊/短应声，不是开新话题
_FILLER = "嗯啊哦唉哈哎哟嘿嘿好吧行呀嘛啦呢诶喂"

# 话题切换的强烈信号词：用户用这些开头/包含，多半是主动开新话题
_TOPIC_OPENERS = (
    "对了", "说起来", "话说", "诶你", "哎对", "问你", "你知道吗", "你猜",
    "换个", "不说这个", "那啥", "突然想到", "问你个", "还有个事", "对了对了",
)

# 结束上一个话题的信号词：用户想打住现话题
_TOPIC_CLOSERS = (
    "不说了", "就这样", "算了", "先这样", "不聊这个", "跳过", "换个话题",
)


def _strip(text: str) -> str:
    return re.sub(r"[\s。，、！？…~～""''「」『』（）()【】]", "", text or "")


def _is_filler_only(text: str) -> bool:
    """这句是否近乎纯语气词（短应声），不值得当新话题。"""
    t = _strip(text)
    return len(t) <= 3 and all(ch in _FILLER for ch in t) if t else True


def topic_hint(text: str) -> str:
    """针对用户当前消息，生成一句"现在在聊什么"的锚定提示。

    用于注入 system prompt：明确当前话语的核心，避免回复被旧上下文带偏。
    纯规则去判断：问候/道别/倾诉/提问/分享/指令等，给出最贴切的一句话。
    """
    t = _strip(text)
    if not t:
        return ""
    if any(w in text for w in _TOPIC_CLOSERS):
        return "对方在打住这个话题，语气是收尾/不继续了，顺着轻轻收一下即可，别再多说或硬接新话题。"
    if any(w in text for w in ("晚安", "再见", "拜拜", "明天见", "睡了", "先睡", "告辞")):
        return "对方在道别/结束对话，简短道别一句即可，不要找新话题、不要追问。"
    if any(w in text for w in ("谢谢", "谢谢你", "辛苦", "感谢")):
        return "对方在向你道谢，自然回应一句就好，干脆利落，不必太隆重。"
    if any(w in text for w in ("你还好吗", "你没事吧", "累不累", "想你了", "在吗", "在不在", "想我没", "在干嘛", "忙吗")):
        return "对方在关心你/想你了/找你，重点放在回应这份牵挂上，自然接住、别跑题。"
    # 疑问句：剥掉标点后以疑问词/句尾语气词收尾 → 是问题
    tq = _strip(text)
    if tq and (tq.endswith(("吗", "么", "呢", "呀", "吧", "没")) or any(w in text for w in ("什么", "怎么", "为啥", "为什么", "哪"))):
        return "对方在问你一个问题，认真回答它，别绕开、别打岔。"
    # 倾诉开头（"好累/好烦/好难受/今天..."带情绪词的长句）
    if any(w in text for w in ("好累", "好烦", "好难受", "好烦啊", "好烦哦", "累死", "烦死", "太难了", "好辛苦", "受不了", "有点累", "有点烦", "好委屈", "好难过")) or len(t) >= 14:
        return "对方在倾诉/分享一件比较具体的事（带着情绪），认真听、顺着他的内容回应，别跳到无关话题。"
    if len(t) >= 12:
        return "对方在分享一件比较具体的事，顺着他的内容接，别跳到无关话题。"
    return ""


def topic_switch_hint(prev_texts: list[str], cur_text: str) -> str:
    """判断当前是否明显开了新话题（与上一条/上几条不同）。

    命中时返回一条提示：让模型专注新话题，别把旧话题扯回来。
    """
    cur_stripped = _strip(cur_text)
    if not cur_stripped or _is_filler_only(cur_text):
        return ""
    # 用户主动开了新话题（信号词）
    if any(w in cur_text for w in _TOPIC_OPENERS):
        return (
            "对方在开启一个新话题（有别于刚才聊的内容），请**专注回应这个新话题**，"
            "不要顺着前面的旧话题继续说，也不要把旧话题的内容扯回来。"
        )
    # 对比上一条：若这条与上一条内容差异大、且上一条已明显收尾，视为切换
    if prev_texts:
        prev = _strip(prev_texts[-1])
        if prev and _is_filler_only(prev_texts[-1]):
            return ""  # 上一条本就是短应声，无明确主题，不算切换
        # 用简单的字符重叠率判断主题是否接近
        overlap = len(set(cur_stripped) & set(prev)) / max(1, len(set(cur_stripped) | set(prev)))
        # overlap 很低且当前句较长 → 大概率换了话题
        if overlap < 0.15 and len(cur_stripped) >= 8:
            return (
                "你注意到对方换了话题（这句和刚才聊的不太一样）。"
                "请自然跟上新的内容，别再提刚才那个话题，别让它串进现在的对话里。"
            )
    return ""


def context_anchor_hint(ctx_len: int) -> str:
    """上下文较长时提示模型：最新的话语才是当前语境，别被前面的背景淹没。"""
    if ctx_len <= 6:
        return ""
    if ctx_len >= 20:
        return (
            "这里有一段较长的聊天历史作为背景。**最新这几句才是当前正在聊的语境**，"
            "你要重点接最新的内容；前面的只是背景，别让很早以前的话题片段干扰你现在的回复，"
            "尤其别冒出跟当前话语无关的旧话题。"
        )
    return ""


def build_topic_system(text: str, recent_texts: list[str], ctx_len: int) -> str:
    """组装给模型的话题锚定 system 提示（多条合并成一句；无则返回空串）。"""
    parts: list[str] = []
    hint = topic_hint(text)
    if hint:
        parts.append(hint)
    sw = topic_switch_hint(recent_texts, text)
    if sw:
        parts.append(sw)
    anchor = context_anchor_hint(ctx_len)
    if anchor:
        parts.append(anchor)
    return "\n".join(parts)
