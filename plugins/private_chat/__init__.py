"""私聊主插件：菟菚对话核心（QQ 私聊专用，不处理群消息）。

对话逻辑在 core/pipeline.process，本插件只负责 QQ 事件绑定。
"""
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent

from core.pipeline import process
from core.userdb import db

private_msg = on_message(priority=5, block=True)
set_address_cmd = on_command("称呼", priority=4, block=True)


@private_msg.handle()
async def handle_private(event: PrivateMessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        await private_msg.finish(Message("……"))
    try:
        reply = await process(str(event.user_id), text)
    except Exception as e:
        reply = f"……藤蔓打结了\n（{e}）"
    await private_msg.finish(Message(reply))


@set_address_cmd.handle()
async def handle_set_address(event: PrivateMessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        await set_address_cmd.finish(Message("用法：/称呼 哥哥"))
    db.set_nickname(str(event.user_id), text)
    await set_address_cmd.finish(Message(f"好，以后就这么叫你：{text}"))
