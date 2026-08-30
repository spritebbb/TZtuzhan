"""网络热梗：让菟菚熟知最近的网络热梗并理解其含义，能在对话中自然使用。

- 从网上搜最近的热梗，用 LLM 提炼成 {term, meaning, example} 结构化清单
- 缓存到 data/memes.json，带时间戳；超过有效期由后台任务刷新
- 对话时把热梗清单注入 system prompt，供菟菚自然引用
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .config import config
from .llm import chat
from .log import logger
from .tasks import schedule

# 缓存有效期（小时）：超过则视为过期，下一个对话轮触发后台刷新
_REFRESH_HOURS = 6
# 单次注入对话的热梗数量上限（避免 prompt 过长）
INJECT_MAX = 8

# 刷新 in-flight 锁：防止 meme_refresh_loop 与对话触发的 schedule 并发抓取/写缓存
import threading

_refresh_lock = threading.Lock()

_CACHE_PATH = None


def _cache() -> Path:
    global _CACHE_PATH
    if _CACHE_PATH is None:
        _CACHE_PATH = config.data_dir / "memes.json"
    return _CACHE_PATH


def memes_refresh_key() -> str:
    return "memes:refresh"


def _load_cached() -> dict | None:
    try:
        if not _cache().exists():
            return None
        data = json.loads(_cache().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data  # 返回原始缓存（含 ts、memes），调用方自行判断是否过期
    except Exception:
        return None


def _cache_is_fresh(data: dict) -> bool:
    """返回缓存是否还在有效期内。"""
    ts = data.get("ts", "")
    if not ts:
        return False
    try:
        fresh_until = datetime.fromisoformat(ts) + timedelta(hours=_REFRESH_HOURS)
        return datetime.now() < fresh_until
    except Exception:
        return False


def _save_cached(memes: list[dict]) -> None:
    try:
        # 原子写：先写临时文件再替换，避免并发读读到损坏 JSON / 交错写坏缓存
        tmp = _cache().with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "memes": memes},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_cache())
    except Exception:
        logger.exception("[热梗] 缓存写入失败")


# 用 LLM 从「热搜词 + 自身知识」提炼结构化热梗清单
_REFINE_PROMPT = """你是网络流行语观察员，也是微博热搜的解读员。

下面给你「微博实时热搜词」和「你了解的近期网络流行梗」。

请结合两者，提炼出**最近真正流行、适合菟菚（温柔慵懒的女生）在聊天时自然使用的网络梗/流行语**。

输出要求：JSON 数组，每条：
[{"term": "梗名/流行语（简短，如「city不city」「硬控」「电子榨菜」）",
  "meaning": "它是什么意思、什么梗、背后含义（说清出处/背景/语境）",
  "example": "菟菚（温柔慵懒的女生）对喜欢的人说话时，自然用到的样子"}]

筛选规则：
- 从**你自己了解的近期流行梗**里选 3-6 条（这类是主力，保证有货）
- 从热搜词里**只挑**适合情侣聊天、能当梗/有趣话题的（如趣味话题、能吐槽能撒娇的），纯新闻/严肃事件/体育比分/产品发布跳过
- 数量凑到 {max} 条以内，宁缺毋滥但不许空
- 只输出 JSON 数组"""


async def _fetch_weibo_hot() -> list[str]:
    """抓微博实时热搜词（前 50 条），失败返回空列表。"""
    import asyncio
    import urllib.request
    import json as _json

    def _sync_fetch() -> list[str]:
        try:
            # 优先用环境代理（http_proxy/https_proxy 由系统/env 决定），
            # 无环境代理时直连（不硬编码本地代理，确保 GitHub 用户无代理也能用）。
            proxies = urllib.request.getproxies()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler(proxies) if proxies else urllib.request.ProxyHandler({})
            )
            req = urllib.request.Request(
                "https://weibo.com/ajax/side/hotSearch",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                    "Referer": "https://weibo.com/",
                },
            )
            with opener.open(req, timeout=12) as r:
                data = _json.loads(r.read().decode("utf-8"))
            items = (data.get("data") or {}).get("realtime") or []
            return [it.get("word", "") for it in items if it.get("word")][:50]
        except Exception:
            logger.warning("[热梗] 微博热搜抓取失败")
            return []

    # 同步 urllib 阻塞 → 放线程池，避免卡事件循环
    return await asyncio.to_thread(_sync_fetch)


async def _refine() -> list[dict]:
    """提炼热梗：从微博热搜词 + LLM 自身网络梗知识，生成结构化清单。

    返回 [{term, meaning, example}]。
    """
    # 1) 抓微博热搜（实时，含当天新梗）
    hot_words = await _fetch_weibo_hot()
    hot_str = "\n".join(f"- {w}" for w in hot_words[:30]) if hot_words else "（暂无热搜数据）"

    try:
        resp = await chat(
            [
                {"role": "system", "content": _REFINE_PROMPT.replace("{max}", str(INJECT_MAX))},
                {"role": "user", "content": f"【微博实时热搜词】\n{hot_str}\n\n请结合你了解的近期网络热梗，输出最终清单。"},
            ],
            temperature=0.5,
            max_tokens=700,
        )
        text = resp.strip().strip("```").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        memes = json.loads(text)
        if isinstance(memes, list):
            out = []
            seen_terms: set[str] = set()
            for m in memes:
                if isinstance(m, dict) and m.get("term"):
                    term = _clean_term(str(m["term"]).strip()[:40])
                    if not term or term == "网络热梗" or term in seen_terms:
                        continue  # 去重：占位词与重复项不重复注入
                    seen_terms.add(term)
                    meaning = str(m.get("meaning", "")).strip()[:200]
                    example = str(m.get("example", "")).strip()[:120]
                    if not example:
                        example = f"{term}——{meaning[:40]}"
                    out.append({"term": term, "meaning": meaning, "example": example})
            return out[:INJECT_MAX]
    except Exception:
        logger.warning("[热梗] 提炼失败，退回到纯 LLM 知识")
    # 兜底：纯 LLM 知识
    try:
        resp2 = await chat(
            [{"role": "system", "content": _REFINE_PROMPT.replace("{max}", str(INJECT_MAX))},
             {"role": "user", "content": "请直接列出你近期了解的、正在流行的网络热梗。"}],
            temperature=0.5, max_tokens=700,
        )
        text2 = resp2.strip().strip("```").strip()
        if text2.startswith("json"):
            text2 = text2[4:].strip()
        memes2 = json.loads(text2)
        if isinstance(memes2, list):
            out2 = []
            seen2: set[str] = set()
            for m in memes2:
                if isinstance(m, dict) and m.get("term"):
                    term = _clean_term(str(m["term"]).strip()[:40])
                    if not term or term == "网络热梗" or term in seen2:
                        continue
                    seen2.add(term)
                    meaning = str(m.get("meaning", "")).strip()[:200]
                    example = str(m.get("example", "")).strip()[:120] or f"{term}——{meaning[:40]}"
                    out2.append({"term": term, "meaning": meaning, "example": example})
            return out2[:INJECT_MAX]
    except Exception:
        pass
    return []


def _clean_term(term: str) -> str:
    """去掉「是什么梗」「什么意思」这类搜索词后缀。"""
    term = re.sub(r"(是什么梗|什么意思|是啥|啥意思|什么来源)$", "", term).strip()
    return term or "网络热梗"


async def refresh_memes() -> list[dict]:
    """刷新热梗缓存：微博热搜 + LLM 知识，提炼成最新热梗清单。

    bot 启动后立即刷一次，之后每 1 小时后台定时刷新。
    返回缓存后的清单。并发调用时（循环 + 对话触发）只跑一次，其余直接拿结果。
    """
    with _refresh_lock:
        try:
            memes = await _refine()
            if memes:
                _save_cached(memes)
                return memes
        except Exception:
            logger.exception("[热梗] 刷新失败")
        return []


def get_current_memes(force_refresh: bool = False) -> list[dict]:
    """返回当前热梗（含过期降级：刷新失败时用旧缓存，不让热梗突然消失）。

    force_refresh=True 时即使缓存有效也强制后台刷新（仍返回当前可用清单）。
    """
    data = _load_cached()
    if force_refresh:
        schedule_refresh(force=True)
    if data and isinstance(data.get("memes"), list):
        return data["memes"]
    return []


def has_memes() -> bool:
    return bool(get_current_memes())


def schedule_refresh(force: bool = False) -> None:
    """把热梗刷新放到后台（同 key 去重）；缓存过期或 force 才触发。"""
    if not force:
        data = _load_cached()
        if data is not None and _cache_is_fresh(data):
            return  # 缓存还有效，不刷
    schedule(memes_refresh_key(), refresh_memes)


async def meme_refresh_loop(interval_seconds: int | None = None) -> None:
    """后台循环：每隔 interval 刷新一次热梗（不依赖对话触发）。

    interval_seconds 默认取 _REFRESH_HOURS；刷新失败不崩溃，下次再试。
    由 bot 启动时 create_task 拉起，常驻后台。
    """
    import asyncio

    interval = interval_seconds or (_REFRESH_HOURS * 3600)
    while True:
        try:
            await refresh_memes()
        except Exception:
            logger.exception("[热梗] 定时刷新失败")
        await asyncio.sleep(interval)
