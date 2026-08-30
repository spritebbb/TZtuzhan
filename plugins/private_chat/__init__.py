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
from core.message_build import _build_message, _maybe_append_emoji, image_file
from core.pipeline import clean_address, process
from core.proactive import send_proactive_now, set_active_user
from core.rhythm import jitter as _jitter
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
mood_cmd = on_command("心情", aliases={"mood", "状态"}, priority=4, block=True)
schedule_cmd = on_command("日程", aliases={"今日安排", "今天干啥", "日程表"}, priority=4, block=True)
profile_cmd = on_command("画像", aliases={"你懂我吗", "你了解我吗", "profile"}, priority=4, block=True)
terms_cmd = on_command("口头禅", aliases={"学到的词", "黑话", "terms"}, priority=4, block=True)
style_cmd = on_command("风格", aliases={"表达方式", "你的观察", "style"}, priority=4, block=True)
emoji_cmd = on_command("表情", aliases={"来张表情", "发个表情"}, priority=4, block=True)
search_cmd = on_command("搜索", aliases={"搜"}, priority=4, block=True)
proactive_cmd = on_command("主动", priority=4, block=True)
dates_cmd = on_command("日子", aliases={"特殊日子", "纪念日"}, priority=4, block=True)
draw_cmd = on_command("画", aliases={"画画", "生成图片", "生图", "图片"}, priority=4, block=True)
diary_cmd = on_command("日记", aliases={"写日记", "看看日记"}, priority=4, block=True)
guess_cmd = on_command("猜数字", aliases={"猜数", "来猜数字"}, priority=4, block=True)
rps_cmd = on_command("石头剪刀布", aliases={"剪刀石头布", "猜拳"}, priority=4, block=True)
story_cmd = on_command("故事", aliases={"睡前故事", "讲个故事", "晚安故事"}, priority=4, block=True)


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
    # 发图前用多样化话术递图（失败回退固定句）
    try:
        from core.speak import before_draw

        pre = await before_draw()
    except Exception:
        pre = ""
    await draw_cmd.send(Message(pre or "嗯……我画给你，稍等一下呀～"))
    path = await generate_image(prompt)
    if not path:
        from core.imagegen import last_error as img_last_error

        hint = img_last_error() or "生图服务没配好或生成失败"
        await draw_cmd.finish(Message(f"……画到一半颜料没了：{hint}"))
        return
    try:
        await draw_cmd.send(Message(MessageSegment.image(file=image_file(path))))
    except Exception:
        logger.exception("[生图] 发送失败")
        await draw_cmd.finish(Message("画好了，但发不出去……"))


# 消息去抖合并：用户连发消息时，等待用户把话说完，再合并成一条整体处理
_pending_items: dict[str, list[dict]] = {}  # user_id → [{text, extras, images}]
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
        {"text": text, "extras": extras, "images": incoming_images}
    )
    task = _debounce_tasks.get(user_id)
    if task:
        task.cancel()
    _debounce_tasks[user_id] = asyncio.create_task(_debounce_flush(user_id))


async def _debounce_flush(user_id: str) -> None:
    """去抖到点后：等用户把话说完，合并成一条整体消息 → pipeline → 精简回复。

    菟菚不会对用户每一句都回应——而是等对方连发的多条消息合成一段话，
    作为"对方一次性说的一段话"整体理解，用一句精简的话回应。
    """
    try:
        await asyncio.sleep(config.debounce_seconds)  # 观察窗口：等用户不再连发
        items = _pending_items.pop(user_id, [])
        _debounce_tasks.pop(user_id, None)
        if not items:
            return
        # 在异步 task 里不能依赖 event.bot（context 已失效），用 get_bot() 取当前 bot
        from nonebot import get_bot

        bot = get_bot()
        if bot is None:
            logger.warning("[去抖] {} 的 bot 引用为空，跳过回复", user_id)
            return
        # 合并连发消息为一段文本（用换行连接，标记成对方连续说的一段话）
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

        # 对话驱动生图：用户回应"想看" → 直接走生图，不跑 pipeline 主回复
        # （避免 pipeline 复述场景 + before_draw 递图双重输出）
        try:
            from core.draw_context import extract_scene, want_to_see

            if want_to_see(merged):
                scene = await extract_scene(user_id)
                if scene:
                    try:
                        from core.speak import before_draw

                        pre = await before_draw()
                    except Exception:
                        pre = ""
                    await bot.send_private_msg(
                        user_id=int(user_id), message=Message(pre or "给你看～我画给你呀")
                    )
                    path = await generate_image(scene)
                    if path:
                        await asyncio.sleep(_jitter(config.think_delay * 0.7))
                        await bot.send_private_msg(
                            user_id=int(user_id),
                            message=Message(MessageSegment.image(file=image_file(path))),
                        )
                        logger.info("[生图] {} 对话生图完成", user_id)
                    else:
                        from core.imagegen import last_error as img_last_error

                        hint = img_last_error() or "生图服务没配好"
                        await bot.send_private_msg(
                            user_id=int(user_id),
                            message=Message(f"……画面在我脑子里，就是画不出来（{hint}）"),
                        )
                    return  # 已处理生图，不再走主回复
        except Exception:
            logger.exception("[生图] 对话生图失败（回退到主回复）")

        # 走 pipeline 主回复
        try:
            reply = await process(user_id, merged, merged_msg=True)
        except Exception as e:
            logger.exception("[去抖] 处理消息失败：{}", merged[:30])
            reply = f"……藤蔓打结了\n（{e}）"
        # 发送回复（用 bot API 直接发，不依赖 matcher）
        await _send_reply_to(bot, user_id, reply)
        logger.info("[去抖] {} 回复完成：{}", user_id, reply[:30])
        # 副动作：收到纯图 → 只说一句话（回应+收藏意图，不叠加第二句配话）
        has_text = bool(items[0]["text"].strip()) or any(it["text"].strip() for it in items)
        if incoming_images and not has_text:
            # ① 收到表情包先回应一句（含"我存了/收进仓库"的收藏意味），失败回退固定话
            try:
                from core.speak import on_receive_img

                first_url = incoming_images[0]
                img_desc = await describe_image(first_url) if first_url else ""
                ack = await on_receive_img(img_desc)
                if ack:
                    await _send_reply_to(bot, user_id, ack)
            except Exception:
                logger.exception("[话术] 收到图片回应失败")
            # ② 收藏（回发时带一句自然话；但用视觉描述作话题，避免固定词）
            just_collected: list[str] = []  # 本次刚收藏的文件路径，回发时排除（不能把对方刚发的原样奉还）
            for url in incoming_images:
                rec = await collect_sticker(user_id, url)
                if rec and rec.get("file"):
                    just_collected.append(rec["file"])
            # ③ 按情绪/语境挑一张「别的」收藏回发：优先情绪匹配（可关），其次同主题，再随机，都排除刚发的
            sticker = None
            try:
                from core.features import flag
                from core.sticker import guess_emotions, pick_by_emotion

                if flag("emotion_sticker_enabled"):
                    emo = guess_emotions(img_desc or "")
                    if emo:
                        sticker = pick_by_emotion(user_id, emo.split(",")[0], 5, exclude_files=set(just_collected))
            except Exception:
                logger.exception("[表情回发] 情绪匹配失败，回退话题")
            if not sticker:
                sticker = pick_sticker(user_id, img_desc or "", 5, exclude_files=set(just_collected))
            if sticker:
                try:
                    from core.speak import with_sticker

                    talk = await with_sticker(img_desc or "你发来的表情包")
                    if talk:
                        await _send_reply_to(bot, user_id, talk)
                except Exception:
                    logger.exception("[话术] 发表情包话术失败")
                await _send_sticker_to(bot, user_id, sticker[0])
    except Exception:
        logger.exception("[去抖] 回复 {} 失败", user_id)
        return


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


async def _send_sticker(event, sticker: dict) -> None:
    """把一张收藏的表情包以 QQ 图片形式发给用户（本地文件路径）。

    sticker: {"file": 本地路径, "desc": 描述}
    """
    try:
        file_path = sticker.get("file")
        if not file_path or not Path(file_path).exists():
            return
        # 酝酿一下，像真人随手发
        await asyncio.sleep(_jitter(config.think_delay * 0.6))
        await private_msg.send(Message(MessageSegment.image(file=image_file(file_path))))
    except Exception:
        logger.exception("[表情回发] 发送失败：{}", sticker.get("file", ""))


async def _send_sticker_to(bot, user_id: str, sticker: dict) -> None:
    """同 _send_sticker，但用 bot API 直接发（用于去抖 task）。"""
    try:
        file_path = sticker.get("file")
        if not file_path or not Path(file_path).exists():
            return
        await asyncio.sleep(_jitter(config.think_delay * 0.6))
        await _bot_send_with_retry(bot, user_id, Message(MessageSegment.image(file=image_file(file_path))))
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


def retcode_1200(exc: Exception) -> bool:
    """判断异常是否是 NapCat 的"消息体无法解析"(retcode=1200)。"""
    from core.message_build import retcode_1200 as _r

    return _r(exc)


def _plain_text(text: str) -> str:
    """把一段文本压成纯文本：剥掉所有 CQ 码/方括号标记/face 段，只留可发送的文字。"""
    from core.message_build import plain_text

    return plain_text(text)


async def _send_reply(reply: str) -> None:
    """像网友发消息一样，把回复拆成多条短消息，带间隔依次发送。

    先"酝酿"一会（模拟真人看到消息、想一下、开始打字），
    再按条带间隔发出；回复越长酝酿越久一点。
    """
    chunks = _split_reply(reply)
    chunks = _maybe_append_emoji(chunks)
    # 酝酿：基础延迟（带随机抖动）+ 每多一条多酝酿一会（但别太久）
    await asyncio.sleep(_jitter(config.think_delay) + 0.5 * max(0, len(chunks) - 1))
    for i, c in enumerate(chunks):
        if i > 0:
            # 间隔随消息稍长一点 + 基础间隔（带抖动），更像真人一条条打
            delay = _jitter(config.send_interval) + 0.02 * len(c)
            await asyncio.sleep(delay)
        await private_msg.send(_build_message(c))


async def _send_reply_to(bot, user_id: str, reply: str) -> None:
    """同 _send_reply，但用 bot API 直接发（不依赖 matcher 上下文，用于去抖 task）。"""
    chunks = _split_reply(reply)
    chunks = _maybe_append_emoji(chunks)
    # 调试：记录每条待发 chunk 的原始内容（排查"消息体无法解析"）
    logger.debug("[发送] {} 待发 {} 条：{}", user_id, len(chunks), [repr(c) for c in chunks])
    await asyncio.sleep(_jitter(config.think_delay) + 0.5 * max(0, len(chunks) - 1))
    for i, c in enumerate(chunks):
        if i > 0:
            delay = _jitter(config.send_interval) + 0.02 * len(c)
            await asyncio.sleep(delay)
        try:
            await _bot_send_with_retry(bot, user_id, _build_message(c))
        except Exception as e:
            # 兜底：若因"消息体无法解析"失败，把该条压成纯文本（剥掉一切 CQ 段/标记）重发一次
            if "消息体无法解析" in str(e) or retcode_1200(e):
                logger.warning("[发送] {} 第{}条被NapCat拒绝，降级为纯文本重试：{!r}", user_id, i + 1, c)
                plain = _plain_text(c)
                if plain:
                    await _bot_send_with_retry(bot, user_id, MessageSegment.text(plain))
                    continue
            logger.error("[发送] {} 第{}条发送失败：{}\n  chunk={!r}", user_id, i + 1, e, c)
            raise


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


@mood_cmd.handle()
async def handle_mood(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    try:
        from core import mood as mood_mod
        from core.config import config

        text = _cmd_arg(event.get_plaintext(), "心情", "mood", "状态")
        clean = text.strip("（）()[]【】。")
        if clean and clean.isdigit():
            # 调试：手动设置心情值
            mood_mod.update_mood(uid, int(clean) - mood_mod.current_mood(uid, city=config.mood_city)[0], city=config.mood_city)
            await mood_cmd.finish(Message("已设置 -> " + mood_mod.describe(uid, city=config.mood_city)))
        await _finish_mood_card(mood_cmd, uid)
    except Exception:
        logger.exception("[心情] 查询失败")
        await mood_cmd.finish(Message("心情系统暂时没反应……过会儿再问我吧"))


async def _finish_mood_card(matcher, uid: str, prefix: str = "当前 ") -> None:
    """发心情图片卡片；渲染失败回退纯文本。"""
    from core import mood as mood_mod
    from core.cards import render_mood_card
    from core.config import config

    try:
        mood, _ = mood_mod.current_mood(uid, city=config.mood_city)
        label, desc = mood_mod.mood_label(mood)
        weather = ""
        if config.mood_city:
            try:
                w, base = mood_mod.today_weather(config.mood_city)
                weather = f"今日天气：{w} · 基线 {base}"
            except Exception:
                weather = ""
        png = render_mood_card(mood=mood, label=label, desc=desc, weather=weather)
        if png:
            try:
                from core.message_build import image_bytes

                await matcher.finish(Message(prefix + MessageSegment.image(file=image_bytes(png))))
                return
            except Exception:
                logger.exception("[心情] 卡片发送失败，回退文本")
    except Exception:
        logger.exception("[心情] 卡片渲染失败，回退文本")
    await matcher.finish(Message(prefix + mood_mod.describe(uid, city=config.mood_city)))


@schedule_cmd.handle()
async def handle_schedule(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    try:
        from core.config import config
        from core.schedule import describe as schedule_describe, ensure_schedule, build_schedule

        # 优先让 LLM 生成当日日程（失败自动退回规则模板）
        await ensure_schedule(uid, city=config.mood_city)
        # 发图片卡片
        from core.schedule import _weather_kind
        from core.cards import render_schedule_card

        sched = build_schedule(uid, city=config.mood_city)
        weather = _weather_kind(config.mood_city)
        head = "今天我是这样安排哒" + (f"（外面：{weather}）" if weather else "")
        png = render_schedule_card(items=sched, head=head)
        if png:
            try:
                from core.message_build import image_bytes

                await schedule_cmd.finish(Message(MessageSegment.image(file=image_bytes(png))))
                return
            except Exception:
                logger.exception("[日程] 卡片发送失败，回退文本")
        await schedule_cmd.finish(Message(schedule_describe(uid, city=config.mood_city)))
    except Exception:
        logger.exception("[日程] 查询失败")
        await schedule_cmd.finish(Message("我的日程表乱成一团了……过会儿再问我吧"))


@profile_cmd.handle()
async def handle_profile(event: PrivateMessageEvent):
    """/画像：查看菟菚对你的了解；/画像 添加 <分类> <内容> 手动补充；/画像 删除 <id>。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    from core.profile import profile_text

    text = _cmd_arg(event.get_plaintext(), "画像", "你懂我吗", "你了解我吗", "profile")

    # 删除
    m_del = re.match(r"^删除\s*(\d+)$", text)
    if m_del:
        ok = db.del_profile(uid, int(m_del.group(1)))
        await profile_cmd.finish(Message("嗯，这条我忘了。" if ok else "没找到那条记录……"))
        return

    # 手动添加：/画像 添加 喜好 用户喜欢猫
    m_add = re.match(r"^(?:添加|记下|记住)\s+(\S+)\s+(.+)$", text)
    if m_add:
        cat = {"喜好": "likes", "厌恶": "dislikes", "习惯": "habits",
               "性格": "personality", "基本": "basic", "基本信息": "basic",
               "其他": "other"}.get(m_add.group(1))
        if not cat:
            await profile_cmd.finish(Message("分类要用：喜好/厌恶/习惯/性格/基本信息/其他"))
            return
        content = m_add.group(2).strip()[:80]
        rid = db.add_profile(uid, cat, content, "manual")
        await profile_cmd.finish(Message(f"嗯，记下了。" if rid is not None else "这条我已经知道了～"))
        return

    await profile_cmd.finish(Message(profile_text(uid)))


@terms_cmd.handle()
async def handle_terms(event: PrivateMessageEvent):
    """/口头禅：查看菟菚记下的你的口头禅/黑话；/口头禅 删除 <id>。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    text = _cmd_arg(event.get_plaintext(), "口头禅", "学到的词", "黑话", "terms")
    m_del = re.match(r"^删除\s*(\d+)$", text)
    if m_del:
        ok = db.del_term(uid, int(m_del.group(1)))
        await terms_cmd.finish(Message("嗯，这个我忘了。" if ok else "没找到那条……"))
        return
    terms = db.get_terms(uid)
    if not terms:
        await terms_cmd.finish(Message("（菟菚还没注意到你爱用的词，多说说话她就知道了）"))
        return
    lines = []
    for t in terms:
        if t["category"] == "slang" and t["meaning"]:
            lines.append(f"· {t['term']}（{t['meaning']}，出现{t['count']}次）")
        else:
            lines.append(f"· {t['term']}（出现{t['count']}次）")
    await terms_cmd.finish(Message("我注意到你爱用的词：\n" + "\n".join(lines)))


@style_cmd.handle()
async def handle_style(event: PrivateMessageEvent):
    """/风格：查看菟菚观察到的你的场景化表达方式。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    from core.style import style_map_text

    await style_cmd.finish(Message(style_map_text(uid)))


@emoji_cmd.handle()
async def handle_emoji(event: PrivateMessageEvent):
    """/表情 <情绪>：按情绪发一张收藏的表情包；不带参数列出可用情绪。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    text = _cmd_arg(event.get_plaintext(), "表情", "来张表情", "发个表情")
    from core.sticker import pick_by_emotion, emotion_tags

    if not text:
        await emoji_cmd.finish(Message("可以用：/表情 " + " / ".join(emotion_tags())))
        return
    clean = text.strip("（ ）()。")
    sticker = pick_by_emotion(uid, clean, 3)
    if not sticker:
        await emoji_cmd.finish(Message(f"（还没有「{clean}」的表情，多发些表情包我就收集了）"))
        return
    await _send_sticker_to(event.bot, uid, sticker[0])


@aff_cmd.handle()
async def handle_aff(event: PrivateMessageEvent):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = _cmd_arg(event.get_plaintext(), "好感度", "好感", "aff")
    uid = str(event.user_id)
    # 无参数，或含"查看/查询/当前"等词（含括号写法如（查看当前））→ 显示当前
    clean = text.strip("（）()[]【】。")
    if not clean or any(k in clean for k in ("查看", "看", "查询", "当前", "是多少", "多少")):
        await _finish_affection_card(aff_cmd, event, uid)
        return
    try:
        affection.set_affection(uid, int(text))
        await _finish_affection_card(aff_cmd, event, uid, prefix="已设置 -> ")
    except ValueError:
        await aff_cmd.finish(Message("用法：/好感 80 或 /好感（查看当前），也可用 /aff"))


async def _finish_affection_card(matcher, event, uid: str, prefix: str = "当前 ") -> None:
    """发好感度图片卡片；渲染失败回退纯文本。"""
    from core.cards import render_affection_card

    u = affection.db.get_user(uid)
    if not u:
        await matcher.finish(Message("尚未有记录"))
        return
    aff = u["affection"]
    stage = affection.stage_of(aff)
    bl = affection.bond_level(aff)
    next_threshold = None
    for t, _s in affection.STAGE_THRESHOLDS:
        if t > aff:
            next_threshold = t
            break
    png = render_affection_card(
        user_id=uid, affection=aff, stage=stage, next_threshold=next_threshold, bond=bl
    )
    if png:
        try:
            from core.message_build import image_bytes

            await matcher.finish(Message(prefix + MessageSegment.image(file=image_bytes(png))))
            return
        except Exception:
            logger.exception("[好感] 卡片发送失败，回退文本")
    await matcher.finish(Message(prefix + affection.describe(uid)))


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


@diary_cmd.handle()
async def handle_diary(event: PrivateMessageEvent):
    """日记：/日记 → 看今天的日记（没有就生成一篇）。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    from core.fun import diary_text, generate_diary

    existing = diary_text(uid)
    if existing != "（今天还没写日记呢……）":
        await diary_cmd.finish(Message(existing))
        return
    await diary_cmd.send(Message("……嗯，让我想想今天的事，写进本子里。"))
    try:
        text = await generate_diary(uid)
    except Exception:
        logger.exception("[日记] 生成失败")
        text = None
    if text:
        await diary_cmd.finish(Message(text))
    else:
        await diary_cmd.finish(Message("……今天的事太碎，还没攒成一页纸，明天再写吧。"))


@guess_cmd.handle()
async def handle_guess(event: PrivateMessageEvent):
    """猜数字：/猜数字 → 开始；直接发数字 → 猜。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    text = _cmd_arg(event.get_plaintext(), "猜数字", "猜数", "来猜数字")
    from core.fun import guess_number, start_guess_game

    if text and text.isdigit():
        reply = guess_number(uid, int(text))
    else:
        reply = start_guess_game(uid)
    await guess_cmd.finish(Message(reply))


@rps_cmd.handle()
async def handle_rps(event: PrivateMessageEvent):
    """石头剪刀布：/石头剪刀布 石头 → 出拳。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    text = _cmd_arg(event.get_plaintext(), "石头剪刀布", "剪刀石头布", "猜拳")
    from core.fun import rps_play

    choice = text if text in ("石头", "剪刀", "布") else (text or "")
    await rps_cmd.finish(Message(rps_play(uid, choice)))


@story_cmd.handle()
async def handle_story(event: PrivateMessageEvent):
    """睡前故事：/故事 → 菟菚讲一篇晚安小故事。"""
    if not isinstance(event, PrivateMessageEvent):
        return
    uid = str(event.user_id)
    await story_cmd.send(Message("嗯……躺好了吗？我讲个故事给你听。"))
    try:
        from core.fun import bedtime_story

        story = await bedtime_story(uid)
    except Exception:
        logger.exception("[故事] 生成失败")
        story = ""
    if story:
        await story_cmd.finish(Message(story))
    else:
        await story_cmd.finish(Message("……故事在风里飘走了，改天再讲给你听吧。"))
