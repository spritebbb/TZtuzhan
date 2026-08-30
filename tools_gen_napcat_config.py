# -*- coding: utf-8 -*-
"""部署辅助脚本：为 BOT_QQ 生成 NapCat onebot11 正向 WS 配置。

读取 .env（BOT_QQ），写入 Napcat/.../napcat/config/onebot11_<BOT_QQ>.json，
让 bot 开箱即可连接 ws://127.0.0.1:3001。

除空的 token 占位符外不写入任何密钥；用户可稍后自行编辑 token。
若 BOT_QQ 为空，打印提示并以 0 退出（用户可在 .env 填写后重新运行 install）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    env = _read_env()
    bot_qq = env.get("BOT_QQ", "").strip()
    if not bot_qq:
        print("[配置生成] 提示：.env 中 BOT_QQ 为空 - 跳过 onebot11 配置生成。")
        print("[配置生成] 请在 .env 中填写 BOT_QQ=<你的 bot QQ>，然后重新运行 install.bat")
        print("[配置生成] 或手动在 NapCat WebUI 中开启 OneBot11 正向 WS 服务")
        return 0
    if not re.fullmatch(r"\d{5,12}", bot_qq):
        print(f"[配置生成] 提示：BOT_QQ '{bot_qq}' 看起来不是合法 QQ 号 - 已跳过。")
        return 0

    config_dir = ROOT / "Napcat" / "NapCat.Shell.Windows.Node" / "napcat" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / f"onebot11_{bot_qq}.json"

    onebot = {
        "network": {
            "httpServers": [],
            "httpSseServers": [],
            "httpClients": [],
            "websocketServers": [
                {
                    "name": "ws-forward",
                    "enable": True,
                    "host": "0.0.0.0",
                    "port": 3001,
                    "messagePostFormat": "array",
                    "reportSelfMessage": False,
                    "token": "",
                    "debug": False,
                    "heartInterval": 30000,
                    "enableForcePushEvent": False,
                }
            ],
            "websocketClients": [],
            "plugins": [],
        },
        "musicSignUrl": "",
        "enableLocalFile2Url": False,
        "parseMultMsg": False,
        "imageDownloadProxy": "",
        "timeout": {"baseTimeout": 30000, "uploadSpeedKBps": 256, "downloadSpeedKBps": 256, "maxTimeout": 120000},
    }
    target.write_text(json.dumps(onebot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[配置生成] 成功：已写入 {target}")
    print("[配置生成] OneBot11 正向 WS 服务已开启，端口 3001（ws://127.0.0.1:3001）")
    return 0


if __name__ == "__main__":
    sys.exit(main())