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

if __name__ == "__main__":
    nonebot.run()
