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
async def _start_proactive_scheduler():
    """启动「菟菚主动发消息」后台定时任务。"""
    import asyncio

    from core.proactive import run_scheduler

    asyncio.create_task(run_scheduler())


if __name__ == "__main__":
    nonebot.run()
