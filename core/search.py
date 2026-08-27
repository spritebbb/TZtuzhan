"""联网搜索：给菟菚接一个信息检索能力（仅作参考，结果可能不准确）。

默认用 Bing（中国大陆可访问、无需 API key）；也可用 DuckDuckGo（SEARCH_ENGINE=ddg）。
失败或关闭时返回空列表，不阻塞对话。
"""
import re
import urllib.parse
import urllib.request

from .config import config


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """搜索并返回 [{title, snippet, url}]。

    按配置的引擎优先，失败（空结果）时自动回退到另一个引擎。
    """
    if not config.search_enabled:
        return []

    engine = getattr(config, "search_engine", "bing")
    order = ["bing", "ddg"] if engine != "ddg" else ["ddg", "bing"]
    for eng in order:
        results = _bing_search(query, max_results) if eng == "bing" else _ddg_search(query, max_results)
        if results:
            return results
    return []


def _bing_search(query: str, max_results: int) -> list[dict]:
    """通过 Bing 网页搜索（国内可访问）。"""
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
    except Exception:
        return []

    results: list[dict] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S)[:max_results]:
        m_title = re.search(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.S)
        if not m_title:
            continue
        m_snippet = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        title = re.sub(r"<[^>]+>", "", m_title.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", m_snippet.group(1)).strip() if m_snippet else ""
        results.append({"title": title, "snippet": snippet, "url": m_title.group(1)})
    return results


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """通过 DuckDuckGo 搜索（中国大陆可能不可用）。"""
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
