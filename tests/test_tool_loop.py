"""流式工具调用循环（方向 D）的纯逻辑测试。

覆盖：
- parse_tool_blocks：解析 ```tool``` 代码块（含多工具/非法块/全角容错）
- execute_tool：web_search / get_weather / 未知工具
- run_tool_loop：mock 模式直接返回；真实模式解析→执行→注入→最终回复
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import tool_loop


# ---- parse_tool_blocks ----

def test_parse_single_block():
    text = '你好\n```tool\n{"tool": "web_search", "args": {"query": "今日新闻"}}\n```\n回复'
    clean, calls = tool_loop.parse_tool_blocks(text)
    assert len(calls) == 1
    assert calls[0]["tool"] == "web_search"
    assert calls[0]["args"]["query"] == "今日新闻"
    assert "```tool" not in clean
    assert "你好" in clean


def test_parse_multiple_blocks():
    text = (
        '```tool\n{"tool": "web_search", "args": {"query": "a"}}\n```\n'
        '```tool\n{"tool": "get_weather"}\n```'
    )
    clean, calls = tool_loop.parse_tool_blocks(text)
    assert len(calls) == 2
    assert calls[1]["tool"] == "get_weather"


def test_parse_unknown_tool_filtered():
    text = '```tool\n{"tool": "hack_system", "args": {}}\n```\n正常回复'
    clean, calls = tool_loop.parse_tool_blocks(text)
    assert calls == []  # 白名单外工具被过滤
    assert "正常回复" in clean


def test_parse_fullwidth_json():
    text = '```tool\n{"tool": "web_search", "args": {"query": "天气"}}\n```'
    # 全角引号容错
    text2 = "```tool\n｛＂tool＂：＂web_search＂，＂args＂：｛＂query＂：＂天气＂｝｝\n```"
    _, calls2 = tool_loop.parse_tool_blocks(text2)
    assert len(calls2) == 1


def test_parse_no_blocks():
    text = "今天天气不错呀"
    clean, calls = tool_loop.parse_tool_blocks(text)
    assert calls == []
    assert clean == text


def test_parse_bad_json():
    text = '```tool\n不是json{{{}\n```\n照常'
    clean, calls = tool_loop.parse_tool_blocks(text)
    assert calls == []


# ---- execute_tool ----

def test_execute_web_search_missing_query():
    import asyncio

    out = asyncio.run(tool_loop.execute_tool({"tool": "web_search", "args": {}}))
    assert "缺少关键词" in out


def test_execute_unknown_tool():
    import asyncio

    out = asyncio.run(tool_loop.execute_tool({"tool": "nope", "args": {}}))
    assert "未知工具" in out


# ---- run_tool_loop ----

def test_run_tool_loop_mock():
    async def fake_llm(messages):
        return "这是回复"

    import asyncio

    out = asyncio.run(
        tool_loop.run_tool_loop([{"role": "user", "content": "hi"}], fake_llm, mock=True)
    )
    assert out == "这是回复"


def test_run_tool_loop_one_tool_then_final():
    """第一轮 LLM 输出工具调用 → 执行 → 第二轮输出最终回复。"""
    calls = []

    async def fake_llm(messages):
        calls.append(len(messages))
        if len(calls) == 1:
            return '```tool\n{"tool": "web_search", "args": {"query": "test"}}\n```'
        return "根据查到的信息，答案是 X"

    import asyncio

    out = asyncio.run(tool_loop.run_tool_loop([{"role": "user", "content": "查一下"}], fake_llm))
    assert "X" in out
    assert "```tool" not in out
    assert len(calls) >= 2  # 至少两轮


def test_run_tool_loop_max_loops():
    """一直输出工具调用 → 循环上限兜底，最终仍能拿到文本。"""
    calls = []

    async def fake_llm(messages):
        calls.append(1)
        return '```tool\n{"tool": "web_search", "args": {"query": "again"}}\n```'

    import asyncio

    out = asyncio.run(tool_loop.run_tool_loop([{"role": "user", "content": "x"}], fake_llm, max_loops=2))
    assert len(calls) >= 2
    assert out is not None


def test_run_tool_loop_final_instruction_appended():
    """最终轮会追加 final_instruction。"""
    seen_final = []

    async def fake_llm(messages):
        contents = [m.get("content", "") for m in messages if m.get("role") == "system"]
        if any("最终指令标记" in c for c in contents):
            seen_final.append(True)
        return "最终回复"

    import asyncio

    out = asyncio.run(
        tool_loop.run_tool_loop(
            [{"role": "user", "content": "x"}],
            fake_llm,
            final_instruction=[{"role": "system", "content": "最终指令标记"}],
        )
    )
    assert out == "最终回复"
    assert seen_final