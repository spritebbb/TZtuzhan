"""OpenAI 兼容 LLM 调用。

任意兼容端点均可：DeepSeek / 硅基流动 / 通义 / OpenAI 等，
只需在 .env 里改 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。
"""
from openai import AsyncOpenAI

from .config import config

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not config.llm_api_key:
            raise RuntimeError("未配置 LLM_API_KEY（请先复制 .env.example 为 .env 并填写）")
        _client = AsyncOpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)
    return _client


async def chat(messages: list[dict], *, mock: bool = False) -> str:
    """非流式整条回复。mock=True 时返回占位回复，便于无 API key 调试。"""
    if mock:
        last = messages[-1]["content"]
        return f"[模拟回复] 收到啦：{last[:30]}……(￣▽￣)"
    client = get_client()
    resp = await client.chat.completions.create(
        model=config.llm_model,
        messages=messages,
        temperature=config.llm_temperature,
        max_tokens=config.llm_max_tokens,
    )
    return resp.choices[0].message.content or ""
