"""联网搜索：给菟菚接一个信息检索能力（仅作参考，结果可能不准确）。

默认用 DuckDuckGo（无需 API key）。失败或未启用时返回空列表，不阻塞对话。
可在 .env 里用 SEARCH_ENABLED=0 关闭。
"""
from .config import config


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """搜索并返回 [{title, snippet, url}]。"""
    if not config.search_enabled:
        return []

    text_fn = None
    try:
        from ddgs import DDGS

        text_fn = DDGS().text
    except Exception:
        try:
            from duckduckgo_search import DDGS

            text_fn = DDGS().text
        except Exception:
            text_fn = None

    if text_fn is None:
        return []

    results: list[dict] = []
    try:
        for r in text_fn(query, max_results=max_results):
            results.append(
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("body") or r.get("snippet") or "",
                    "url": r.get("href") or r.get("link") or "",
                }
            )
    except Exception:
        pass
    return results
