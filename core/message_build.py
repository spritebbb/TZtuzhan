"""QQ 消息构建：把文本里的 [face:N] 标记安全地转为原生表情。

单独拆到这里避免把 NoneBot 插件级初始化牵连进纯逻辑测试。
核心：只相信白名单 _EMOJI_POOL 里的 face id，其它（尤其 LLM 乱填的 [face:44]）
一律按普通文本处理，绝不让 NapCat 收到不支持的 face id 而报"消息体无法解析"。
"""
import random
import re

from nonebot.adapters.onebot.v11 import Message, MessageSegment

# 菟菚偶尔附带的表情（QQ face id；只放验证过 NapCat 支持的、慵懒温柔/轻微病娇/黏人的调调）
_EMOJI_POOL = [109, 111, 122, 176, 178, 179, 186, 214, 277, 311, 319, 324, 326]
# 触发概率：每条回复里加表情的概率（调高更爱用表情）
_EMOJI_PROB = 0.4


def _build_message(text: str) -> Message:
    """把文本里**合法的** [face:N] 标记转成 QQ 原生表情，构造混合消息。

    只相信白名单 _EMOJI_POOL 里的 id：不在白名单的（如 LLM 乱写的 [face:44]）
    一律剥离标记、只留文字，绝不生成 face 段，避免 NapCat 报错。
    """
    allowed = set(_EMOJI_POOL)
    msg = Message()
    for part in re.split(r"(\[face:\d+\])", text):
        if not part:
            continue
        m = re.fullmatch(r"\[face:(\d+)\]", part)
        if m and int(m.group(1)) in allowed:
            msg.append(MessageSegment.face(id_=int(m.group(1))))
        else:
            # 不合法的 face 标记：去标记只留文字
            clean = re.sub(r"\[face:\d+\]", "", part)
            if clean:
                msg.append(MessageSegment.text(clean))
    return msg


def _maybe_append_emoji(chunks: list[str]) -> list[str]:
    """给回复的某一条末尾随机加一个 QQ 表情；偶尔加（概率 _EMOJI_PROB）。"""
    if not chunks or random.random() >= _EMOJI_PROB:
        return chunks
    idx = random.randrange(len(chunks))
    fid = random.choice(_EMOJI_POOL)
    chunks[idx] = f"{chunks[idx]}[face:{fid}]"
    return chunks
