"""对话驱动生图：菟菚在聊天里描述"眼前画面"，用户说想看，就生成对应图。

闭环：
1. pipeline 回复 prompt 已引导菟菚：聊到可配图的意象时，自然描述并问用户要不要看
2. 用户回应"想看" → want_to_see() 判断意图
3. 从最近对话提炼"菟菚描述的眼前画面" → extract_scene()
4. 用提取到的画面描述生图
"""
import re

from .llm import chat
from .log import logger
from .userdb import db

# 用户表达"想看"的意图词（只匹配真正要看图的强烈意图，避免"好呀"等通用附和误触发）
_WANT_RE = re.compile(r"(想看|我要看|给我看|给我看看|发我|发给我|发来看|看看呗)")
# 排除"不想看/别看/不想/不要"的否定（不用裸"别"——会误配"特别想看"等常见词）
_NOT_WANT_RE = re.compile(r"(不想看|别看|不要看|不用看|不想|不要|算了|才不|没兴趣|不看)")

# 从对话里提炼画面描述
_SCENE_PROMPT = """你是「菟菚」的助手。下面是一段菟菚和用户的对话，最近菟菚在聊天里**描述了一个她"眼前看到的"画面/景象**（比如一片花田、窗外的雨、桌上的猫、夕阳、星空等），并可能问用户要不要看。

请你从对话里找出这个画面的**具体描述**，输出一个适合文生图的简洁画面描述（60字以内，只描述画面本身，不要人物动作、不要评价）。

规则：
- 只提取菟菚描述&用户想看的那个画面，不要臆造
- 用中性、具体的画面描述（如"一片开到天际的粉色花田，午后阳光，微风吹动"）
- 如果对话里**没有**菟菚描述的可配图画面，输出 {"scene": ""}

只输出 JSON：{"scene": "画面描述"}"""


def _parse_scene(resp: str) -> str:
    text = resp.strip().strip("```").strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        import json
        data = json.loads(text)
        return (data.get("scene") or "").strip() if isinstance(data, dict) else ""
    except Exception:
        return ""


def want_to_see(user_text: str) -> bool:
    """用户是否在回应"想看"某个画面。"""
    t = user_text.strip()
    if not t:
        return False
    if _NOT_WANT_RE.search(t):
        return False
    return bool(_WANT_RE.search(t))


async def extract_scene(user_id: str, *, mock: bool = False) -> str:
    """从最近对话提炼菟菚描述的"眼前画面"；无则返回空串。"""
    if mock:
        return ""
    rows = db.recent_messages(user_id, 8)
    if len(rows) < 2:
        return ""
    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows[-8:])
    try:
        resp = await chat(
            [
                {"role": "system", "content": _SCENE_PROMPT},
                {"role": "user", "content": f"对话：\n{transcript}"},
            ],
            temperature=0.2,
            max_tokens=100,
        )
        return _parse_scene(resp)
    except Exception:
        logger.warning("[生图] 画面提炼失败")
        return ""
