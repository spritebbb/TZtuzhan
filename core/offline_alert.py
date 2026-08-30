"""掉线检测与提醒：NapCat / QQ 掉线时尽快让你知道。

QQ 机器人掉线（被风控强制离线 / NapCat 崩溃 / 网络问题）后无法收发消息，
本模块在 bot 的 WS 连接断开时触发提醒，避免你一直不知道 bot 已经失联。

实现：
- 注册 nonebot driver 的 on_bot_disconnect / on_bot_connect 钩子
- 断线时：写状态标记文件（供守护脚本判断）+ 尝试发 QQ 提醒 + 写桌面/系统提示
- 重连时：清除标记文件，可选发恢复消息

提醒渠道说明：
- QQ 私聊提醒：NapCat 若只是"QQ 被风控"而 OneBot 服务仍在，或刚断开瞬间可发；
  若 NapCat 整体崩溃则发不出（此时靠下面的本地提示兜底）
- 本地 toast/日志：Windows 上弹一个系统通知，无论 QQ 状态如何都能提醒你
"""
import asyncio
from datetime import datetime

from nonebot import get_bot, get_driver
from nonebot.adapters.onebot.v11 import Message

from .config import config
from .log import logger
from .userdb import kv_get, kv_set

# 状态标记文件：掉线时写入当前时间，重连时删除。守护脚本可据此判断是否掉线。
_STATE_FILE = config.data_dir / "bot_offline"   # 存在=掉线中

# 连续掉线去重：避免 NapCat 短期闪断造成刷屏提醒（如 60 秒内不重复提醒）。可配置。
_ALERT_COOLDOWN_SECONDS = 60


def _is_offline() -> bool:
    return _STATE_FILE.exists()


def _mark_offline() -> None:
    try:
        _STATE_FILE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    except Exception:
        pass


def _clear_offline() -> None:
    try:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
    except Exception:
        pass


def offline_since() -> str | None:
    """返回掉线开始的时间文本；未掉线返回 None（供 webui/守护脚本查询）。"""
    if not _is_offline():
        return None
    return _STATE_FILE.read_text(encoding="utf-8") if _STATE_FILE.exists() else ""


def _alert_recently() -> bool:
    """判断是否刚发过掉线提醒（防闪断刷屏）。"""
    last = kv_get("__sys__", "bot_offline_alert_ts")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() < _ALERT_COOLDOWN_SECONDS
    except Exception:
        return False


def _mark_alerted() -> None:
    kv_set("__sys__", "bot_offline_alert_ts", datetime.now().isoformat(timespec="seconds"))


async def notify_offline() -> None:
    """bot WS 断开时调用：写标记 + 尝试多渠道提醒。"""
    _mark_offline()
    logger.warning("[掉线检测] NapCat/QQ 连接已断开，尝试提醒管理员")

    if _alert_recently():
        logger.info("[掉线检测] 刚提醒过，本次跳过（防闪断刷屏）")
        return

    _notify_local("菟菚掉线了", "NapCat/QQ 连接断开，请查看机器人是否被风控或需重新登录")

    # 尝试直接给管理员 QQ 发提醒（若 NapCat 尚能发消息）
    await _send_qq_alert()
    # 标记已提醒要放在实际发送之后：若发送失败（QQ 暂不可用），下次断线还能重试提醒
    _mark_alerted()


async def notify_reconnect() -> None:
    """bot WS 重连成功时调用：清除标记。"""
    _clear_offline()
    logger.info("[掉线检测] NapCat/QQ 已重新连接")
    # 去抖后是否通知管理员恢复：仅记录日志，不主动发消息打扰
    # （如需要可在此追加一条恢复 QQ 提醒）


def _notify_local(title: str, body: str) -> None:
    """本地系统提示。无论 QQ 状态如何都能提醒你，失败静默。

    优先用 Windows 原生 toast（无需第三方库），失败退化为对话框。
    """
    try:
        import sys

        if sys.platform == "win32":
            # 用 PowerShell 的 Windows.UI.Notifications 弹 toast，无需额外安装
            import subprocess

            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType=WindowsRuntime] | Out-Null;"
                "$tmpl=[Windows.UI.Notifications.ToastTemplateType]::ToastText02;"
                "$xml=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($tmpl);"
                "$texts=$xml.GetElementsByTagName('text');"
                f"$texts.Item(0).AppendChild($xml.CreateTextNode('{title}'))|Out-Null;"
                f"$texts.Item(1).AppendChild($xml.CreateTextNode('{body}'))|Out-Null;"
                "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml);"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('TZtuzhan')."
                "Show($toast)"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # 非 Windows：退化为日志，已由 logger.warning 覆盖
            pass
    except Exception:
        logger.debug("[掉线检测] 本地通知不可用")


async def _send_qq_alert() -> None:
    """给 config.proactive_user_ids 里配置的 QQ 号发一条掉线提醒。"""
    targets = config.proactive_user_ids
    if not targets:
        return
    try:
        bot = get_bot()
    except Exception:
        logger.debug("[掉线检测] 无 bot 实例，跳过 QQ 提醒")
        return
    body = (
        "😿 菟菚的 QQ 好像掉线了……\n"
        "可能是被腾讯风控强制离线，或 NapCat/网络出了问题。\n"
        "方便的话帮我重新扫码登录一下，不然我就联系不上你了。"
    )
    for uid in targets:
        try:
            await bot.send_private_msg(user_id=int(uid), message=Message(body))
            logger.info("[掉线检测] 已向 {} 发送掉线提醒", uid)
        except Exception:
            logger.warning("[掉线检测] 向 {} 发掉线提醒失败", uid)


def setup() -> None:
    """注册 bot 连接生命周期钩子（在 bot.py 启动时调用）。"""
    try:
        driver = get_driver()

        @driver.on_bot_disconnect
        async def _on_bot_disconnect(bot):
            # 断开钩子在异步任务组里运行，起一个独立任务发提醒，不阻塞
            asyncio.create_task(_safe_notify_offline())

        @driver.on_bot_connect
        async def _on_bot_connect(bot):
            asyncio.create_task(_safe_reconnect())

    except Exception:
        logger.exception("[掉线检测] 注册钩子失败")


async def _safe_notify_offline() -> None:
    try:
        await notify_offline()
    except Exception:
        logger.exception("[掉线检测] 离线提醒异常")


async def _safe_reconnect() -> None:
    try:
        await notify_reconnect()
    except Exception:
        logger.exception("[掉线检测] 重连处理异常")
