"""人格加载与动态注入。

人格源文件是项目内的 persona-菟菚.md（唯一人格来源），
这里只负责读取，并按用户状态注入动态字段（阶段 / 称呼 / 关系状态）。
"""
from .config import config

_persona_cache: str | None = None


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
    "恋人": "你们已经是恋人关系，感情很深，彼此信任、依恋、黏在一起。",
}


def build_system_prompt(
    *,
    stage: str,
    address: str | None,
    lover_confirm: bool,
    first_chat: bool,
) -> str:
    """组装最终 system prompt = 人格 + 当前用户状态注入。"""
    persona = load_persona()
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
        f"- 当前好感度阶段：{stage}\n"
        f"- 你们的关系：{framing}\n"
        f"- 你对用户的称呼：{addr}\n"
        f"- 本轮注意：{note_text}\n"
        "按以上阶段与关系行动。"
    )
    return persona + dynamic
