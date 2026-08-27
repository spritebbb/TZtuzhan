"""NoneBot2 入口：python bot.py

启动前：
1. 复制 .env.example 为 .env 并填写（LLM key / OneBot WS 地址）
2. 部署 NapCat 并开启正向 WS（见 napcat-guide.md）
"""
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
nonebot.load_plugin("plugins.private_chat")


@driver.on_startup
async def _start_background_tasks():
    """启动后台定时任务：主动发消息 + 定时刷新热梗。"""
    import asyncio

    from core.memes import meme_refresh_loop
    from core.proactive import run_scheduler

    asyncio.create_task(run_scheduler())
    # 热梗定时刷新：启动后立即刷一次，之后每小时刷（不依赖用户对话触发）
    asyncio.create_task(meme_refresh_loop(3600))


if __name__ == "__main__":
    nonebot.run()
