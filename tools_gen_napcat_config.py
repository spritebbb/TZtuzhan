# -*- coding: utf-8 -*-
"""Deployment helper: generate NapCat onebot11 forward-WS config for BOT_QQ.

Reads .env (BOT_QQ), writes Napcat/.../napcat/config/onebot11_<BOT_QQ>.json
so the bot can connect on ws://127.0.0.1:3001 out of the box.

No secret values are written except an empty token placeholder; the user may
edit token later. If BOT_QQ is empty, prints a warning and exits 0 (user can
set it in .env and rerun install).
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
        print("[gen-napcat] WARN: BOT_QQ empty in .env - skipping onebot11 config generation.")
        print("[gen-napcat] Set BOT_QQ=<your bot QQ> in .env, then rerun install.bat")
        print("[gen-napcat] (or configure the OneBot11 forward WS server in NapCat WebUI manually)")
        return 0
    if not re.fullmatch(r"\d{5,12}", bot_qq):
        print(f"[gen-napcat] WARN: BOT_QQ '{bot_qq}' does not look like a QQ number - skipping.")
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
    print(f"[gen-napcat] OK: wrote {target}")
    print("[gen-napcat] OneBot11 forward WS server enabled on port 3001 (ws://127.0.0.1:3001)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
