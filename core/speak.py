"""即兴话术：让菟菚发表情包/生图时说的话自然多样，而不是固定模板。

- before_draw()      生图前说一句（"给你看～我画给你呀"的多样化）
- with_sticker()     发表情包/收藏回发前配一句自然的话（结合话题）
- on_receive_img()   收到用户图片/表情包时先回应一句再收藏回发

全部 LLM 生成，失败时回退到固定候选（随机选一条），绝不抛异常。
"""
import random

from .llm import chat
from .log import logger

# 人物/称呼黑名单：生成话术禁止出现（避免肉麻或出戏）
_BANNED = ("宝宝", "宝贝", "亲爱的", "老公", "老婆", "亲亲", "抱抱", "吻")


def _clean(line: str, extra_banned: tuple[str, ...] = ()) -> str:
    """清洗 LLM 输出：去引号/句号、去黑名单词、限长；不合格返回空串。"""
    line = line.strip().strip("「」“”\"'。 ")
    if not line:
        return ""
    for b in _BANNED + extra_banned:
        if b in line:
            return ""
    if len(line) > 24:
        return ""
    return line


# ---- 生图前 ----
_BEFORE_DRAW_FALLBACK = [
    "给你看～我画给你呀",
    "喏，画好了，给你康康",
    "刚想到这个画面，画给你啦",
    "脑子里浮现的样子，就长这样～",
    "看！我把那个画面画出来了",
]

_BEFORE_DRAW_PROMPT = """你是「菟菚」，一个温柔慵懒、带点病娇的菟丝子娘，正对喜欢的人说话。她刚生好一张(或正要生成)一张想给对方的图。

请用一句短话（≤18字，别用句号）自然地把图递给对方。要符合她慵懒温柔又带点撒娇的口气，别太正式、别喊"宝宝/亲爱的"这类肉麻词。

结合你（菟菚）当下描述画面时的语气，即兴说一句，不要和示例雷同。
只输出这一句话，不要别的内容。"""


async def before_draw(*, mock: bool = False) -> str:
    """生图前/后递给对方的一句话。失败回退固定候选。"""
    try:
        line = await chat(
            [
                {"role": "system", "content": _BEFORE_DRAW_PROMPT},
                {"role": "user", "content": "给喜欢的人递一张自己画/找到的图。"},
            ],
            temperature=0.9,
            max_tokens=30,
            mock=mock,
        )
        line = _clean(line)
        if line:
            return line
    except Exception:
        logger.warning("[话术] 生图前话术生成失败，用固定候选")
    return random.choice(_BEFORE_DRAW_FALLBACK)


# ---- 发表情包 / 收藏回发 ----
_WITH_STICKER_FALLBACK = [
    "这个适合你",
    "你上次那个表情，我存下来了",
    "想到你就想发这个",
    "喏，这个送你",
    "这表情你肯定喜欢",
    "存了好久了，终于用上",
]

_WITH_STICKER_PROMPT = """你是「菟菚」，一个温柔慵懒、带点病娇的菟丝子娘，正对喜欢的人说话。她打算给对方发一张表情包/收藏的图。

请用一句短话（≤18字，别用句号）自然地配在表情包前面，让发图显得有由头、不突兀。要符合她随意、可爱、带点黏人的口气。

你可能知道对方最近在聊的话题或情绪（如有给出），结合它自然带一句；没给就随口感性发挥。

只输出这一句话，不要别的内容。"""


async def with_sticker(topic: str = "", *, mock: bool = False) -> str:
    """发表情包前配的一句话。topic 是近期话题/情绪线索。"""
    try:
        ctx = f"\n（对方最近聊到/在意的：{topic}）" if topic else ""
        line = await chat(
            [
                {"role": "system", "content": _WITH_STICKER_PROMPT},
                {"role": "user", "content": f"要发一张表情包给喜欢的人。{ctx}".strip()},
            ],
            temperature=0.9,
            max_tokens=30,
            mock=mock,
        )
        line = _clean(line)
        if line:
            return line
    except Exception:
        logger.warning("[话术] 发表情包话术生成失败，用固定候选")
    return random.choice(_WITH_STICKER_FALLBACK)


# ---- 收到用户图片/表情包 ----
_ON_RECEIVE_IMG_FALLBACK = [
    "这张不错诶，我存了",
    "你这个表情好戳我",
    "哈哈这张我喜欢",
    "哪淘来的，有点意思",
    "叮，收进我的小仓库啦",
]

_ON_RECEIVE_IMG_PROMPT = """你是「菟菚」，一个温柔慵懒、带点病娇的菟丝子娘，正对喜欢的人说话。对方刚发来一张图片/表情包（可能有简单描述或你的想法）。

请在收藏/回发前，用一句短话（≤18字，别用句号）自然地回应对方这张图。要符合她慵懒可爱、会收藏对方表情的调调。

对方这张图的内容/你的感受（如有给出）作为参考，自然接一句，别复述。

只输出这一句话，不要别的内容。"""


async def on_receive_img(desc: str = "", *, mock: bool = False) -> str:
    """收到用户图片/表情包时先说的一句。desc 是视觉模型对该图的描述。"""
    try:
        ref = f"（这张图的大致内容：{desc}）" if desc else ""
        line = await chat(
            [
                {"role": "system", "content": _ON_RECEIVE_IMG_PROMPT},
                {"role": "user", "content": f"对方发来一张图片/表情包。{ref}".strip()},
            ],
            temperature=0.9,
            max_tokens=30,
            mock=mock,
        )
        line = _clean(line)
        if line:
            return line
    except Exception:
        logger.warning("[话术] 接收图片话术生成失败，用固定候选")
    return random.choice(_ON_RECEIVE_IMG_FALLBACK)
