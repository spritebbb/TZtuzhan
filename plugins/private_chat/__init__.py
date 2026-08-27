"""私聊主插件：菟菚对话核心（QQ 私聊专用，不处理群消息）。

对话逻辑在 core/pipeline.process，本插件只负责 QQ 事件绑定。
"""
import asyncio
import re

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, MessageSegment, PrivateMessageEvent

from core import affection
from core.config import config
from core.pipeline import clean_address, process
from core.proactive import send_proactive_now, set_active_user
from core.search import last_error as search_last_error, web_search
from core.userdb import db
from core.vision import describe_image

private_msg = on_message(priority=5, block=True)
set_address_cmd = on_command("称呼", priority=4, block=True)
aff_cmd = on_command("好感度", aliases={"好感", "aff"}, priority=4, block=True)
search_cmd = on_command("搜索", aliases={"搜"}, priority=4, block=True)
proactive_cmd = on_command("主动", priority=4, block=True)


@proactive_cmd.handle()
async def handle_proactive(event: PrivateMessageEvent):
    """测试/手动触发：菟菚主动发一条（仅限配置的主动对象）。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    if config.proactive_user_id and str(event.user_id) != config.proactive_user_id:
        await proactive_cmd.finish(Message("……我只对一个人主动。"))
        return
    ok = await send_proactive_now(event.bot, str(event.user_id))
    if not ok:
        await proactive_cmd.finish(Message("……酝酿不出来，下次吧"))


@private_msg.handle()
async def handle_private(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return  # 只处理私聊，不接入群聊
    set_active_user(str(event.user_id))  # 记住最近跟她说话的人，便于主动找她
    text = event.get_plaintext().strip()
    extras = []
    for seg in event.message:
        t = seg.type
        if t == "text":
            continue  # 已在 plaintext 里
        elif t == "face":
            extras.append("[QQ表情]")
        elif t == "image":
            url = seg.data.get("url") if isinstance(seg.data, dict) else None
            desc = await describe_image(url) if url else ""
            extras.append(f"[对方发来一张图片/表情包]" + (f"，内容是：{desc}" if desc else ""))
        elif t == "at":
            extras.append("[@]")
        else:
            extras.append(f"[{t}]")

    full = (text + " " + " ".join(extras)).strip()
    if not full:
        await private_msg.finish(Message("……"))
    try:
        reply = await process(str(event.user_id), full)
    except Exception as e:
        reply = f"……藤蔓打结了\n（{e}）"
    await _send_reply(reply)


def _split_reply(reply: str, max_len: int = 26) -> list[str]:
    """把回复拆成适合逐条发送的短消息：按换行拆，超长句子再按标点拆；最多 3 条。"""
    chunks: list[str] = []
    for part in re.split(r"\n+", reply):
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_len:
            chunks.append(part)
        else:
            for sub in re.split(r"(?<=[。！？，、；：])\s*", part):
                sub = sub.strip()
                if sub:
                    chunks.append(sub)
    if not chunks:
        chunks = [reply]
    if len(chunks) > 3:
        chunks = chunks[:2] + ["".join(chunks[2:])]  # 超出的并进最后一条
    # 网友聊天不用句号：去掉每条消息结尾的句号
    chunks = [c.rstrip("。").strip() or c for c in chunks]
    return chunks


def _build_message(text: str) -> Message:
    """把文本里的 [face:N] 标记转成 QQ 原生表情，构造混合消息。"""
    msg = Message()
    for part in re.split(r"(\[face:\d+\])", text):
        if not part:
            continue
        m = re.fullmatch(r"\[face:(\d+)\]", part)
        if m:
            msg.append(MessageSegment.face(id_=int(m.group(1))))
        else:
            msg.append(MessageSegment.text(part))
    return msg


async def _send_reply(reply: str) -> None:
    """像网友发消息一样，把回复拆成多条短消息，带间隔依次发送。"""
    chunks = _split_reply(reply)
    for i, c in enumerate(chunks):
        if i > 0:
            # 间隔随消息稍长一点 + 基础间隔，更像真人一条条打
            delay = config.send_interval + 0.02 * len(c)
            await asyncio.sleep(delay)
        await private_msg.send(_build_message(c))


@set_address_cmd.handle()
async def handle_set_address(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = event.get_plaintext().strip()
    if not text:
        await set_address_cmd.finish(Message("用法：/称呼 哥哥"))
    name = clean_address(text) or text
    if affection.check_bad_address(name):
        db.update_affection(str(event.user_id), affection.BAD_ADDRESS_PENALTY, "要求不合适的称呼")
        await set_address_cmd.finish(Message("这个称呼，我不喜欢呢……换一个吧。"))
    db.set_nickname(str(event.user_id), name)
    await set_address_cmd.finish(Message(f"好，以后就这么叫你：{name}"))


@aff_cmd.handle()
async def handle_aff(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = event.get_plaintext().strip()
    uid = str(event.user_id)
    if not text or text in ("查看", "看", "查询", "当前"):
        await aff_cmd.finish(Message("当前 " + affection.describe(uid)))
    try:
        affection.set_affection(uid, int(text))
        await aff_cmd.finish(Message("已设置 -> " + affection.describe(uid)))
    except ValueError:
        await aff_cmd.finish(Message("用法：/好感 80 或 /好感（查看当前），也可用 /aff"))


@search_cmd.handle()
async def handle_search(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = event.get_plaintext().strip()
    if not text:
        await search_cmd.finish(Message("用法：/搜索 <关键词>"))
    results = web_search(text)
    if not results:
        await search_cmd.finish(Message(f"没查到什么……（{search_last_error() or '未知原因'}）"))
    lines = [f"{r['title']}：{r['snippet'][:80]}" for r in results[:5]]
    await search_cmd.finish(Message("\n".join(lines)))
