"""功能开关系统：动态控制各功能开启/关闭。

Web UI 面板写入 data/feature_flags.json，bot 在 pipeline 注入前动态检查。
默认全开（文件不存在或未配置的开关视为 True）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import config

_FLAGS_PATH = config.data_dir / "feature_flags.json"
_cache: dict = {"data": {}, "ts": 0.0}
_CACHE_TTL = 5.0
# 写锁：set_flag 是读-改-写，两个请求并发会互相覆盖（丢失其中一个开关的变更）
import threading

_write_lock = threading.Lock()

# 所有可用开关及其默认值
FLAG_DEFAULTS = {
    "profile_enabled": True,       # 用户画像
    "terms_enabled": True,         # 口头禅/黑话
    "style_enabled": True,         # 场景化表达风格
    "emotion_sticker_enabled": True,  # 表情包情绪匹配
}


def _load() -> dict:
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    try:
        with open(_FLAGS_PATH, encoding="utf-8") as f:
            _cache["data"] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _cache["data"] = {}
    _cache["ts"] = now
    return _cache["data"]


def flag(name: str) -> bool:
    """读取某个功能开关；不存在则用默认值（True）。"""
    data = _load()
    return data.get(name, FLAG_DEFAULTS.get(name, True))


def set_flag(name: str, value: bool) -> None:
    """写入开关值（同时清缓存）；原子写避免读到半截 JSON。"""
    if name not in FLAG_DEFAULTS:
        return  # 只接受已知开关名
    with _write_lock:  # 串行化读-改-写，避免并发覆盖
        data = {}
        if _FLAGS_PATH.exists():
            try:
                with open(_FLAGS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}
        data[name] = bool(value)
        # 原子写：写临时文件再替换，防止并发读读到损坏 JSON
        tmp = _FLAGS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_FLAGS_PATH)
        _cache["data"] = data
        _cache["ts"] = time.time()


def all_flags() -> dict[str, bool]:
    """返回所有开关的当前值（含默认值）。"""
    data = _load()
    result = {}
    for k, default in FLAG_DEFAULTS.items():
        result[k] = data.get(k, default)
    return result