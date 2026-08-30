"""流式工具调用循环：让 LLM 在回复里用 ```tool``` 代码块发起工具调用，
解析后执行并把结果注入下一轮，最多 N 轮直到不再需要工具。

参考 NagaAgent 的 agentic_tool_loop，但只内置菟菚需要的几个工具：
- web_search：联网搜索（复用 core/search）
- get_weather：查今日天气（复用 core/mood）

设计原则：
- 工具调用以 ```tool {json}``` 代码块形式嵌入 LLM 输出（不依赖 Function Calling API）
- 默认关闭（只有主流程显式开启时才启用工具循环），保证普通对话 100% 不受影响
- 任何解析/执行失败都静默降级为普通回复，绝不阻塞对话
"""
import json
import re

from .log import logger

# 工具循环轮次上限（防止无限调用）
MAX_LOOPS = 3

# 工具提示词（注入 system 时用）
TOOL_HINT = """你可以按需使用 ```tool``` 代码块调用工具获取实时信息（如搜索、查天气）。格式：
```tool
{"tool": "web_search", "args": {"query": "搜索关键词"}}
```
也可以一次发起多个工具调用（多个代码块）。工具结果会在下一轮返回给你，你再据此组织回复。
不需要工具时，不要输出任何 ```tool``` 代码块。"""

# 可执行工具白名单
_TOOLS = {"web_search", "get_weather"}

# 只匹配闭合的 ```tool 代码块；未闭合块（LLM 截断）不吞尾部文本，标记单独清理
_TOOL_BLOCK_RE = re.compile(r"```tool[ \t]*(?:\n| )([\s\S]*?)```", re.MULTILINE)
_STRAY_TOOL_RE = re.compile(r"```tool[^\n]*\n?")


def parse_tool_blocks(text: str) -> tuple[str, list[dict]]:
    """从 LLM 输出中提取 ```tool``` 代码块，返回 (清理后的文本, 工具调用列表)。

    Args:
        text: LLM 原始输出

    Returns:
        (clean_text, tool_calls) — clean_text 是移除代码块后的纯文本
    """
    calls: list[dict] = []
    for match in _TOOL_BLOCK_RE.finditer(text):
        block = match.group(1).strip()
        if not block:
            continue
        try:
            obj = json.loads(block)
        except Exception:
            # 全角字符容错（引号/冒号/逗号/花括号）
            try:
                fixed = (
                    block.replace("：", ":")
                    .replace("，", ",")
                    .replace("｛", "{")
                    .replace("｝", "}")
                    .replace("＂", '"')
                    .replace("“", '"')
                    .replace("”", '"')
                    .replace("‘", "'")
                    .replace("’", "'")
                )
                obj = json.loads(fixed)
            except Exception:
                logger.warning("[工具循环] 无法解析工具代码块: {}", block[:80])
                continue
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str) and obj["tool"] in _TOOLS:
            args = obj.get("args")
            if not isinstance(args, dict):
                args = {}
            calls.append({"tool": obj["tool"], "args": args})
    clean_text = _TOOL_BLOCK_RE.sub("", text).strip()
    # 清理残留的未闭合 ```tool 标记（LLM 截断时可能只有开标记）
    clean_text = _STRAY_TOOL_RE.sub("", clean_text).strip()
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    return clean_text, calls


async def execute_tool(call: dict) -> str:
    """执行单个工具调用，返回结果文本（失败返回友好错误）。"""
    import asyncio

    tool = call.get("tool", "")
    args = call.get("args", {})
    try:
        if tool == "web_search":
            query = (args.get("query") or args.get("q") or "").strip()
            if not query:
                return "（搜索缺少关键词）"
            from .search import web_search

            # web_search 是同步 urllib 阻塞 → 放线程池，避免卡事件循环
            hits = await asyncio.to_thread(web_search, query)
            if not hits:
                return "（没有搜到相关内容）"
            lines = []
            for h in hits[:5]:
                lines.append(f"- {h.get('title', '')}：{h.get('snippet', '')}")
            return "搜索结果：\n" + "\n".join(lines)

        if tool == "get_weather":
            from .config import config
            from .mood import today_weather

            weather, base = await asyncio.to_thread(today_weather, config.mood_city)
            return f"今日天气：{weather}（心情基线 {base}）"
    except Exception as e:
        logger.exception("[工具循环] 工具 {} 执行失败", tool)
        return f"（{tool} 调用失败：{e}）"
    return "（未知工具）"


async def run_tool_loop(
    messages: list[dict],
    call_llm,
    *,
    max_loops: int = MAX_LOOPS,
    mock: bool = False,
    final_instruction: list[dict] | None = None,
) -> str:
    """执行完整工具循环，返回最终 LLM 文本（已清理工具代码块）。

    Args:
        messages: 当前对话消息（最后一条是 user；含人格/记忆/上下文等注入）
        call_llm: 异步函数，接收 messages 返回 LLM 输出文本
        max_loops: 最大循环轮次
        mock: 测试模式（不真正调用 LLM/工具，直接返回一次调用结果）
        final_instruction: 仅在「最终生成回复」那一轮追加的 system 消息列表
            （如【思考】/【回复】指令、话题锚定），避免中间工具轮次重复输出

    Returns:
        最终文本（不含工具代码块）
    """
    if mock:
        # 测试模式：直接调用一次 LLM，不做工具解析
        return await call_llm(messages)

    # 注入工具提示（追加一条 system）
    work = list(messages)
    work.append({"role": "system", "content": TOOL_HINT})

    loop_count = 0
    while loop_count < max_loops:
        loop_count += 1
        raw = await call_llm(work)
        clean, calls = parse_tool_blocks(raw)

        if not calls:
            # 没有工具调用 → 进入最终生成（追加最终指令后调用一次）
            if final_instruction:
                work.extend(list(final_instruction))
            final_raw = await call_llm(work)
            final_clean, _ = parse_tool_blocks(final_raw)
            return final_clean or final_raw

        # 执行工具（并行）
        import asyncio

        results = await asyncio.gather(*[execute_tool(c) for c in calls])
        # 把工具结果注入下一轮（作为 system 消息，避免角色错乱）
        result_block = "\n\n".join(
            f"[工具结果 {i + 1}/{len(results)} - {calls[i]['tool']}]\n{r}"
            for i, r in enumerate(results)
        )
        work.append({"role": "assistant", "content": clean or "（我查一下）"})
        work.append(
            {
                "role": "system",
                "content": (
                    "你刚调用的工具返回了这些结果（可能有误，只作为参考）：\n"
                    + result_block
                    + "\n请根据结果组织你的回复（保持慵懒温柔、口语化，别报告腔、别列清单）。"
                    "如果还需要更多信息，可以再调用工具；否则直接给出最终回复。"
                ),
            }
        )

    # 循环用尽：最后一次尝试拿到完整回复（带最终指令）
    if final_instruction:
        work.extend(list(final_instruction))
    raw = await call_llm(work)
    clean, _ = parse_tool_blocks(raw)
    return clean or raw