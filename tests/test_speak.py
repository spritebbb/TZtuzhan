"""即兴话术 speak 模块测试（清洗逻辑 + LLM/fallback 分支）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import pytest

from core.speak import _clean, before_draw, with_sticker, on_receive_img


def test_clean_strips_quotes_punct():
    assert _clean("  给你看啦。  ") == "给你看啦"
    assert _clean("“喏，给你”") == "喏，给你"
    assert _clean("'画好了'") == "画好了"


def test_clean_banned_words():
    assert _clean("宝贝你看") == ""  # 含禁词
    assert _clean("亲爱的你想看吗") == ""
    assert _clean("这张图你肯定喜欢") != ""  # 正常话保留


def test_clean_limits_length():
    # 明显超过 24 字 → 清空
    long_line = "这是一句特别特别特别特别特别特别特别特别特别特别特别特别长的话"
    assert len(long_line) > 24
    assert _clean(long_line) == ""
    # 恰好 ≤24 字保留
    short = "给你看这张图"
    assert _clean(short) == "给你看这张图"


def test_functions_fallback_on_mock():
    """mock=True 时 LLM 返回占位，走固定候选（仍返回非空）。"""

    async def _run():
        a = await before_draw(mock=True)
        b = await with_sticker("随便", mock=True)
        c = await on_receive_img("一只猫", mock=True)
        return a, b, c

    a, b, c = asyncio.run(_run())
    assert isinstance(a, str) and a
    assert isinstance(b, str) and b
    assert isinstance(c, str) and c
