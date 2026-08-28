"""私聊主插件：菟菚对话核心（QQ 私聊专用，不处理群消息）。

对话逻辑在 core/pipeline.process，本插件只负责 QQ 事件绑定。
"""
import asyncio
import random
import re
from pathlib import Path

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, MessageSegment, PrivateMessageEvent

from core import affection
from core.config import config
from core.imagegen import generate as generate_image
from core.log import logger
from core.pipeline import clean_address, process
from core.proactive import send_proactive_now, set_active_user
from core.search import last_error as search_last_error, web_search
from core.sticker import collect as collect_sticker, pick as pick_sticker
from core.userdb import (
    db,
    delete_important_date,
    get_all_important_dates,
    get_today_important_dates,
    save_important_date,
)
from core.vision import describe_image

private_msg = on_message(priority=5, block=True)
set_address_cmd = on_command("称呼", priority=4, block=True)
aff_cmd = on_command("好感度", aliases={"好感", "aff"}, priority=4, block=True)
search_cmd = on_command("搜索", aliases={"搜"}, priority=4, block=True)
proactive_cmd = on_command("主动", priority=4, block=True)
dates_cmd = on_command("日子", aliases={"特殊日子", "纪念日"}, priority=4, block=True)
draw_cmd = on_command("画", aliases={"画画", "生成图片", "生图", "图片"}, priority=4, block=True)


def _cmd_arg(plain: str, *names: str) -> str:
    """从 on_command 事件纯文本里剥离命令词（含别名），只返回后面的参数。

    NoneBot 的 event.get_plaintext() 对命令事件返回「命令词+参数」整句
    （如「好感 80」「好感度」「aff」），直接当参数用会失配。
    这里把 / 前缀 + 任一命令名/别名 剥掉，只留参数部分。
    """
    text = plain.strip()
    for name in names:
        # 命令名可能带 / 前缀（NoneBot 默认命令前缀），也可能不带
        for prefix in (f"/{name}", name):
            if text.startswith(prefix):
                return text[len(prefix):].strip()
    return text


@proactive_cmd.handle()
async def handle_proactive(event: PrivateMessageEvent):
    """测试/手动触发：菟菚主动发一条（仅限配置的主动对象）。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    if config.proactive_user_ids and str(event.user_id) not in config.proactive_user_ids:
        await proactive_cmd.finish(Message("……我只对特定的人主动。"))
        return
    ok = await send_proactive_now(event.bot, str(event.user_id))
    if not ok:
        await proactive_cmd.finish(Message("……酝酿不出来，下次吧"))


@draw_cmd.handle()
async def handle_draw(event: PrivateMessageEvent):
    """画图：/画 <描述> → 菟菚生成一张图发过来。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    plain = event.get_plaintext().strip()
    prompt = _cmd_arg(plain, "画", "画画", "生成图片", "生图", "图片")
    if not prompt:
        await draw_cmd.finish(Message("想让我画什么呀？说个画面给我，比如：画 一只趴在窗台上的猫"))
        return
    await draw_cmd.send(Message("嗯……我画给你，稍等一下呀～"))
    # 在 prompt 里强化菟菚的风格：温暖、治愈、在线感
    enhanced = f"温暖治愈系插画风格，{prompt}，色调柔和，可爱，有生活气息"
    path = await generate_image(enhanced)
    if not path:
        from core.imagegen import last_error as img_last_error

        hint = img_last_error() or "生图服务没配好或生成失败"
        await draw_cmd.finish(Message(f"……画到一半颜料没了：{hint}"))
        return
    try:
        await draw_cmd.send(Message(MessageSegment.image(file=path)))
    except Exception:
        logger.exception("[生图] 发送失败")
        await draw_cmd.finish(Message("画好了，但发不出去……"))


# 消息去抖合并：用户连发消息时，短暂等待后合并为一条处理
_DEBOUNCE_SECONDS = 2.2  # 连发窗口（此时间内到达的消息合并为一条）
_pending_items: dict[str, list[dict]] = {}  # user_id → [{text, extras, images, event}]
_debounce_tasks: dict[str, asyncio.Task] = {}  # user_id → asyncio.Task


@private_msg.handle()
async def handle_private(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return  # 只处理私聊，不接入群聊
    set_active_user(str(event.user_id))  # 记住最近跟她说话的人，便于主动找她
    user_id = str(event.user_id)
    text = event.get_plaintext().strip()
    extras = []
    incoming_images: list[str] = []  # 用户这次发来的图片 URL（用于收藏）
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
            if url:
                incoming_images.append(url)
        elif t == "at":
            extras.append("[@]")
        else:
            extras.append(f"[{t}]")

    # ③ 消息去抖：入队 + 重置计时器
    _pending_items.setdefault(user_id, []).append(
        {"text": text, "extras": extras, "images": incoming_images, "event": event}
    )
    task = _debounce_tasks.get(user_id)
    if task:
        task.cancel()
    _debounce_tasks[user_id] = asyncio.create_task(_debounce_flush(user_id))


async def _debounce_flush(user_id: str) -> None:
    """去抖到点后：合并连发消息 → 走 pipeline → 发回复 → 副动作（收藏/生图）。"""
    await asyncio.sleep(_DEBOUNCE_SECONDS)
    items = _pending_items.pop(user_id, [])
    _debounce_tasks.pop(user_id, None)
    if not items:
        return
    bot = items[0]["event"].bot
    # 合并连发消息
    merged_parts: list[str] = []
    incoming_images: list[str] = []
    for it in items:
        full = (it["text"] + " " + " ".join(it["extras"])).strip()
        if full:
            merged_parts.append(full)
        incoming_images.extend(it["images"])
    merged = "\n".join(merged_parts).strip() if merged_parts else ""
    if not merged:
        await bot.send_private_msg(user_id=int(user_id), message="……")
        return
    # 走 pipeline
    try:
        reply = await process(user_id, merged)
    except Exception as e:
        reply = f"……藤蔓打结了\n（{e}）"
    # 发送回复（用 bot API 直接发，不依赖 matcher）
    await _send_reply_to(bot, user_id, reply)
    # 副动作：收藏表情包（纯图才收藏）
    has_text = bool(items[0]["text"].strip()) or any(it["text"].strip() for it in items)
    if incoming_images and not has_text:
        for url in incoming_images:
            await collect_sticker(user_id, url)
        sticker = pick_sticker(user_id, "", 1)
        if sticker:
            await _send_sticker_to(bot, user_id, sticker[0])
    # 对话驱动生图：用户回应"想看"
    try:
        from core.draw_context import extract_scene, want_to_see

        if want_to_see(merged):
            scene = await extract_scene(user_id)
            if scene:
                await bot.send_private_msg(
                    user_id=int(user_id), message=Message("给你看～我画给你呀")
                )
                path = await generate_image(scene)
                if path:
                    await asyncio.sleep(config.think_delay * 0.7)
                    await bot.send_private_msg(
                        user_id=int(user_id),
                        message=Message(MessageSegment.image(file=path)),
                    )
                else:
                    from core.imagegen import last_error as img_last_error

                    hint = img_last_error() or "生图服务没配好"
                    await bot.send_private_msg(
                        user_id=int(user_id),
                        message=Message(f"……画面在我脑子里，就是画不出来（{hint}）"),
                    )
    except Exception:
        logger.exception("[生图] 对话生图失败")


def _split_reply(reply: str, max_len: int = 26) -> list[str]:
    """把回复拆成适合逐条发送的短消息：按换行拆，一行就是一条（允许单长句）；
    最多 3 条；超出的并进最后一条。"""
    chunks: list[str] = []
    for part in re.split(r"\n+", reply):
        part = part.strip()
        if not part:
            continue
        chunks.append(part)
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


# 菟菚偶尔附带的表情（QQ face id；慵懒温柔/轻微病娇/黏人的调调）
_EMOJI_POOL = [109, 111, 122, 176, 178, 179, 186, 214, 277, 311, 319, 324, 326]
# 触发概率：每条回复里加表情的概率（调高更爱用表情）
_EMOJI_PROB = 0.4


def _maybe_append_emoji(chunks: list[str]) -> list[str]:
    """给回复的某一条末尾随机加一个 QQ 表情；偶尔加（概率 _EMOJI_PROB）。"""
    if not chunks or random.random() >= _EMOJI_PROB:
        return chunks
    idx = random.randrange(len(chunks))
    fid = random.choice(_EMOJI_POOL)
    chunks[idx] = f"{chunks[idx]}[face:{fid}]"
    return chunks


async def _send_sticker(event, sticker: dict) -> None:
    """把一张收藏的表情包以 QQ 图片形式发给用户（本地文件路径）。

    sticker: {"file": 本地路径, "desc": 描述}
    """
    try:
        file_path = sticker.get("file")
        if not file_path or not Path(file_path).exists():
            return
        # 酝酿一下，像真人随手发
        await asyncio.sleep(config.think_delay * 0.6)
        await private_msg.send(Message(MessageSegment.image(file=file_path)))
    except Exception:
        logger.exception("[表情回发] 发送失败：{}", sticker.get("file", ""))


async def _send_sticker_to(bot, user_id: str, sticker: dict) -> None:
    """同 _send_sticker，但用 bot API 直接发（用于去抖 task）。"""
    try:
        file_path = sticker.get("file")
        if not file_path or not Path(file_path).exists():
            return
        await asyncio.sleep(config.think_delay * 0.6)
        await _bot_send_with_retry(bot, user_id, Message(MessageSegment.image(file=file_path)))
    except Exception:
        logger.exception("[表情回发] 发送失败：{}", sticker.get("file", ""))


async def _bot_send_with_retry(bot, user_id: str, message, retries: int = 2) -> None:
    """用 bot API 发私聊消息，失败重试（指数退避）；全部失败抛异常。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            await bot.send_private_msg(user_id=int(user_id), message=message)
            return
        except Exception as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(1.0 * (2**attempt))
    raise last_exc


async def _send_reply(reply: str) -> None:
    """像网友发消息一样，把回复拆成多条短消息，带间隔依次发送。

    先"酝酿"一会（模拟真人看到消息、想一下、开始打字），
    再按条带间隔发出；回复越长酝酿越久一点。
    """
    chunks = _split_reply(reply)
    chunks = _maybe_append_emoji(chunks)
    # 酝酿：基础延迟 + 每多一条多酝酿一会（但别太久）
    await asyncio.sleep(config.think_delay + 0.5 * max(0, len(chunks) - 1))
    for i, c in enumerate(chunks):
        if i > 0:
            # 间隔随消息稍长一点 + 基础间隔，更像真人一条条打
            delay = config.send_interval + 0.02 * len(c)
            await asyncio.sleep(delay)
        await private_msg.send(_build_message(c))


async def _send_reply_to(bot, user_id: str, reply: str) -> None:
    """同 _send_reply，但用 bot API 直接发（不依赖 matcher 上下文，用于去抖 task）。"""
    chunks = _split_reply(reply)
    chunks = _maybe_append_emoji(chunks)
    await asyncio.sleep(config.think_delay + 0.5 * max(0, len(chunks) - 1))
    for i, c in enumerate(chunks):
        if i > 0:
            delay = config.send_interval + 0.02 * len(c)
            await asyncio.sleep(delay)
        await _bot_send_with_retry(bot, user_id, _build_message(c))


@set_address_cmd.handle()
async def handle_set_address(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = _cmd_arg(event.get_plaintext(), "称呼")
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
    text = _cmd_arg(event.get_plaintext(), "好感度", "好感", "aff")
    uid = str(event.user_id)
    # 无参数，或含"查看/查询/当前"等词（含括号写法如（查看当前））→ 显示当前
    clean = text.strip("（）()[]【】。")
    if not clean or any(k in clean for k in ("查看", "看", "查询", "当前", "是多少", "多少")):
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
    text = _cmd_arg(event.get_plaintext(), "搜索", "搜")
    if not text:
        await search_cmd.finish(Message("用法：/搜索 <关键词>"))
    results = web_search(text)
    if not results:
        await search_cmd.finish(Message(f"没查到什么……（{search_last_error() or '未知原因'}）"))
    lines = [f"{r['title']}：{r['snippet'][:80]}" for r in results[:5]]
    await search_cmd.finish(Message("\n".join(lines)))


_DATES_RE = re.compile(
    r"^\s*(?:删除|删)\s*(\d+)|^\s*(\d{1,2})[-/\.](\d{1,2})\s+(.+)$|^\s*(查看|看看|列表|都有什么)$"
)


@dates_cmd.handle()
async def handle_dates(event: PrivateMessageEvent):
    """特殊日子管理：/日子 查看；/日子 12-25 你的生日；/日子 删除 1"""
    if not isinstance(event, PrivateMessageEvent):
        return
    text = _cmd_arg(event.get_plaintext(), "日子", "特殊日子", "纪念日")
    uid = str(event.user_id)

    # 查看
    if not text or text in ("查看", "看看", "列表", "都有什么"):
        all_dates = get_all_important_dates(uid)
        if not all_dates:
            await dates_cmd.finish(Message("还没有记下什么特别的日子……你可以说：/日子 08-28 我的生日"))
        lines = [f"{d['id']}. {d['date']} {d['label']}" for d in all_dates]
        today = get_today_important_dates(uid)
        extra = f"\n（今天就是：{'、'.join(d['label'] for d in today)}）" if today else ""
        await dates_cmd.finish(Message("记着的日子：\n" + "\n".join(lines) + extra))

    # 删除
    m_del = re.match(r"^删除\s*(\d+)$", text)
    if m_del:
        delete_important_date(int(m_del.group(1)))
        await dates_cmd.finish(Message("嗯，这个日子我忘掉了。"))

    # 设置：日期 + 名称
    m_set = re.match(r"^(\d{1,2})[-/\.](\d{1,2})\s+(.+)$", text)
    if m_set:
        month, day, label = int(m_set.group(1)), int(m_set.group(2)), m_set.group(3).strip()
        if not (1 <= month <= 12 and 1 <= day <= 31):
            await dates_cmd.finish(Message("日期不对哦，格式要像：/日子 12-25 你的生日"))
        date_str = f"{month:02d}-{day:02d}"
        save_important_date(uid, date_str, label)
        await dates_cmd.finish(Message(f"记住了：{date_str} {label}。到那天我会记得的。"))
        return

    await dates_cmd.finish(Message("用法：/日子（查看）｜/日子 12-25 你的生日｜/日子 删除 1"))
