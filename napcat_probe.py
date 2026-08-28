"""QQ 在线探测：通过 OneBot WS 发 get_status，判断 QQ 是否真正在线。

NapCat 被腾讯风控踢下线时，OneBot WS 可能仍在监听端口（只是 QQ 账号离线），
仅靠端口检测会误判为"在线"。本脚本向 WS 发 get_status，能收到 online=true
才视为 QQ 在线；连不上/超时则返回离线。

用法：python napcat_probe.py [ws_url] [timeout]
退出码：0 = QQ 在线；1 = QQ 离线/未连接；2 = 异常
"""
import asyncio
import sys

import aiohttp

DEFAULT_URL = "ws://127.0.0.1:3001/"
DEFAULT_TIMEOUT = 8  # 秒


async def probe(url: str, timeout: float) -> bool:
    """探测一次，返回 QQ 是否在线。"""
    try:
        async with aiohttp.ClientSession() as s:
            ws = await s.ws_connect(url, timeout=aiohttp.ClientWSTimeout(ws_close=timeout))
            try:
                await ws.send_json({"action": "get_status", "params": {}, "echo": 0})
                # 等待响应：只认与 echo 匹配且 online=True 的那条
                for _ in range(3):
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                    if msg.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        continue
                    import json

                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    if data.get("echo") == 0:
                        d = data.get("data") or {}
                        return bool(d.get("online"))
                return False  # 连上了但没等到 status，视为离线
            finally:
                await ws.close()
    except asyncio.TimeoutError:
        return False
    except aiohttp.ClientConnectionError:
        return False
    except Exception:
        return False


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    try:
        timeout = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TIMEOUT
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    online = asyncio.run(probe(url, timeout))
    if online:
        print("QQ 在线")
        return 0
    print("QQ 离线/未连接")
    return 1


if __name__ == "__main__":
    sys.exit(main())
