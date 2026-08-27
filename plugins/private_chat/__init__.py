"""私聊主插件：菟菚对话核心（QQ 私聊专用，不处理群消息）。

对话逻辑在 core/pipeline.process，本插件只负责 QQ 事件绑定。
"""
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent

from core import affection
from core.pipeline import clean_address, process
from core.search import last_error as search_last_error, web_search
from core.userdb import db

private_msg = on_message(priority=5, block=True)
set_address_cmd = on_command("称呼", priority=4, block=True)
aff_cmd = on_command("好感度", aliases={"好感", "aff"}, priority=4, block=True)
search_cmd = on_command("搜索", aliases={"搜"}, priority=4, block=True)


def _describe_message(event: PrivateMessageEvent) -> str:
    """把消息转成可读文本，含表情/图片等非文字段的描述，让菟菚能读到。"""
    text = event.get_plaintext().strip()
    parts = []
    for seg in event.message:
        t = seg.type
        if t == "text":
            continue  # 已在 plaintext 里
        elif t == "face":
            parts.append("[QQ表情]")
        elif t == "image":
            parts.append("[图片/表情包]")
        elif t == "at":
            parts.append("[@]")
        else:
            parts.append(f"[{t}]")
    non_text = " ".join(parts)
    return (text + " " + non_text).strip()


@private_msg.handle()
async def handle_private(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return  # 只处理私聊，不接入群聊
    text = _describe_message(event)
    if not text:
        await private_msg.finish(Message("……"))
    try:
        reply = await process(str(event.user_id), text)
    except Exception as e:
        reply = f"……藤蔓打结了\n（{e}）"
    await private_msg.finish(Message(reply))


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
