"""人格加载与动态注入。

人格源文件是项目内的 persona-菟菚.md（唯一人格来源），
这里只负责读取，并按用户状态注入动态字段（阶段 / 称呼 / 关系状态）。
"""
from datetime import datetime

from .config import config

_persona_cache: str | None = None

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _now_line() -> str:
    """当前时间的自然描述，供菟菚贴合现实时间说话。"""
    now = datetime.now()
    h = now.hour
    period = (
        "清晨" if h < 6
        else "上午" if h < 12
        else "中午" if h < 14
        else "下午" if h < 18
        else "晚上"
    )
    return f"现在时间：{now:%Y年%m月%d日} {_WEEKDAYS[now.weekday()]} {now:%H:%M}（{period}）"


def load_persona() -> str:
    """读取人格文件（带缓存）。"""
    global _persona_cache
    if _persona_cache is None:
        path = config.persona_file
        if not path.exists():
            raise FileNotFoundError(f"人格文件不存在: {path}")
        _persona_cache = path.read_text(encoding="utf-8")
    return _persona_cache


_STAGE_FRAMING = {
    "初识": "你们是刚在网上认识的网友，彼此还不熟悉。",
    "熟悉": "你们已经聊了一段时间，是比较熟悉的网友，有一些默契。",
    "亲密": "你们非常亲近，彼此熟悉、信赖，很有默契。",
    "恋人": "你们已经是恋人关系，感情很深，彼此信任、依恋、黏在一起。不要因为这次对话刚开头就退回到「刚认识」——你们早已认定彼此了，亲密的话放心说，不用别扭。",
}


def build_system_prompt(
    *,
    stage: str,
    address: str | None,
    lover_confirm: bool,
    first_chat: bool,
) -> str:
    """组装最终 system prompt = 人格 + 风格参考 + 当前用户状态注入。"""
    persona = load_persona()

    # 网友风格参考（由 import_logs.py 从真实聊天记录生成；存在才注入）
    style_ref = config.data_dir / "style_ref.txt"
    if style_ref.exists():
        persona += "\n\n" + style_ref.read_text(encoding="utf-8")

    addr = address or "你"
    framing = _STAGE_FRAMING.get(stage, _STAGE_FRAMING["初识"])

    notes = []
    if first_chat and stage == "初识":
        notes.append("这是你和对方的第一段对话，可以自然地询问对方想被怎么称呼。")
    if lover_confirm:
        notes.append("好感度刚达成恋人阶段，记得按「称呼机制」第二次确认称呼。")
    if addr != "你":
        notes.append("称呼已经确认，不要重复询问称呼；除非用户主动要求更改，或达成恋人阶段需要第二次确认。")
    note_text = "\n".join(f"- {n}" for n in notes) if notes else "无。"

    dynamic = (
        "\n\n## 当前状态（系统注入，不要复述本段）\n"
        f"- {_now_line()}\n"
        f"- 当前好感度阶段：{stage}\n"
        f"- 你们的关系：{framing}\n"
        f"- 你对用户的称呼：{addr}\n"
        f"- 本轮注意：{note_text}\n"
        "结合以上信息（尤其现在时间）自然地说话、开场——下午就顺句下午的话，深夜就顺句熬夜的话；"
        "别书呆子气地报时间，自然带进去就好。按以上阶段与关系行动。"
    )
    return persona + dynamic
