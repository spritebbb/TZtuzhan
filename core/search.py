"""联网搜索：给菟菚接一个信息检索能力（仅作参考，结果可能不准确）。

默认用 Bing（中国大陆可访问、无需 API key）；也可用 DuckDuckGo（SEARCH_ENGINE=ddg）。
失败或关闭时返回空列表，并通过 web_search.last_error 给出原因，便于排查。
"""
import re
import urllib.parse
import urllib.request

from .config import config

web_search_last_error = ""


def last_error() -> str:
    """最近一次搜索失败的原因（供界面显示）。"""
    return web_search_last_error


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """搜索并返回 [{title, snippet, url}]。失败时返回 [] 并在 last_error 记录原因。"""
    global web_search_last_error
    web_search_last_error = ""

    if not config.search_enabled:
        web_search_last_error = "搜索已关闭（SEARCH_ENABLED=0）"
        return []

    engine = getattr(config, "search_engine", "bing")
    order = ["bing", "ddg"] if engine != "ddg" else ["ddg", "bing"]
    errors = []
    for eng in order:
        results, err = (
            _bing_search(query, max_results) if eng == "bing" else _ddg_search(query, max_results)
        )
        if results:
            return results
        if err:
            errors.append(f"{eng}: {err}")
    web_search_last_error = "；".join(errors)
    return []


def _bing_search(query: str, max_results: int, host: str = "www.bing.com"):
    """通过 Bing 网页搜索（国内可访问）。返回 (results, error)。"""
    url = f"https://{host}/search?q=" + urllib.parse.quote(query)
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
    except Exception as e:
        # www 失败就换国内域名 cn.bing.com 再试一次
        if host == "www.bing.com":
            return _bing_search(query, max_results, host="cn.bing.com")
        return [], f"网络错误: {e}"

    results: list[dict] = []
    for block in re.findall(r'<li class="b_algo[^"]*".*?</li>', html, re.S)[:max_results]:
        m_title = re.search(r'<h2[^>]*><a href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.S)
        if not m_title:
            continue
        m_snippet = re.search(r"<(?:p|div)[^>]*>(.*?)</(?:p|div)>", block, re.S)
        title = re.sub(r"<[^>]+>", "", m_title.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", m_snippet.group(1)).strip() if m_snippet else ""
        results.append({"title": title, "snippet": snippet, "url": m_title.group(1)})

    return results, ("" if results else "解析到 0 条（Bing 可能返回了非结果页/验证页）")


def _ddg_search(query: str, max_results: int):
    """通过 DuckDuckGo 搜索（中国大陆可能不可用）。返回 (results, error)。"""
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
        return [], "未安装 ddgs/duckduckgo_search"

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
    except Exception as e:
        return [], f"网络错误: {e}"
    return results, "" if results else "解析到 0 条"
