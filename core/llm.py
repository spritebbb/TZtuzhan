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


async def chat(
    messages: list[dict],
    *,
    mock: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """非流式整条回复。mock=True 时返回占位回复，便于无 API key 调试。"""
    if mock:
        last = messages[-1]["content"]
        return f"[模拟回复] 收到啦：{last[:30]}……(￣▽￣)"
    client = get_client()
    resp = await client.chat.completions.create(
        model=config.llm_model,
        messages=messages,
        temperature=config.llm_temperature if temperature is None else temperature,
        max_tokens=config.llm_max_tokens if max_tokens is None else max_tokens,
    )
    return resp.choices[0].message.content or ""


_ADDRESS_EXTRACT_PROMPT = (
    "你是称呼提取器。用户在给菟菚设置自己希望被称呼的名字。"
    "请从用户的这句话里提取用户希望被称呼的称呼，只取一个最合适的，"
    "只输出这一个词本身，不要输出任何其他文字、符号、引号或解释。\n"
    "如果没有明确的称呼，或用户只是在聊天，就输出空。\n"
    "例子：\n"
    "『就叫我以实玛利吧』→ 以实玛利\n"
    "『叫我良秀也行』→ 良秀\n"
    "『你随便，我都可以』→ \n"
    "『你好』→ \n"
    "『叫我哥哥』→ 哥哥"
)


async def extract_address(text: str) -> str | None:
    """用 LLM 从用户消息中精确提取称呼；无明确称呼时返回 None。"""
    resp = await chat(
        [
            {"role": "system", "content": _ADDRESS_EXTRACT_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=20,
    )
    name = resp.strip().strip("「」『』\"'“”《》 ")
    return name or None
