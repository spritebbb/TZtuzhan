"""OpenAI 兼容 LLM 调用。

任意兼容端点均可：DeepSeek / 硅基流动 / 通义 / OpenAI 等，
只需在 .env 里改 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。

v2 优化：超时 + 指数退避重试（网络抖动自动恢复，不把错误甩给用户）。
"""
import asyncio

from openai import AsyncOpenAI

from .config import config
from .log import logger

_client: AsyncOpenAI | None = None

# 重试策略
_MAX_RETRIES = 2                 # 最多重试 2 次（共 3 次尝试）
_RETRY_BASE_SEC = 1.5            # 首次退避 1.5s
_TIMEOUT_SEC = 90                # 单次请求超时

# 可安全重试的异常类型（网络/超时/5xx）
_RETRYABLE = (TimeoutError,)


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否值得重试。"""
    if isinstance(exc, _RETRYABLE):
        return True
    # openai.APIStatusError：429 / 5xx 可重试
    try:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int) and status >= 500:
            return True
        if status == 429:  # 限流——退避重试
            return True
    except Exception:
        pass
    return False


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not config.llm_api_key:
            raise RuntimeError("未配置 LLM_API_KEY（请先复制 .env.example 为 .env 并填写）")
        _client = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout=_TIMEOUT_SEC,
            max_retries=0,  # 自己控制重试，避免 SDK 与这里双重退避
        )
    return _client


async def chat(
    messages: list[dict],
    *,
    mock: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """非流式整条回复。mock=True 时返回占位回复，便于无 API key 调试。

    失败自动重试（指数退避），全部失败抛异常（调用方兜底）。
    """
    if mock:
        last = messages[-1]["content"]
        return f"[模拟回复] 收到啦：{last[:30]}……(￣▽￣)"
    client = get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.chat.completions.create(
                model=config.llm_model,
                messages=messages,
                temperature=config.llm_temperature if temperature is None else temperature,
                max_tokens=config.llm_max_tokens if max_tokens is None else max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt >= _MAX_RETRIES:
                break
            wait = _RETRY_BASE_SEC * (2**attempt)
            logger.warning("[LLM] 第{}次失败（{}），{:.1f}s 后重试", attempt + 1, type(e).__name__, wait)
            await asyncio.sleep(wait)
    raise last_exc  # 全部失败，交给调用方兜底


_ADDRESS_EXTRACT_PROMPT = (
    "你是称呼提取器。用户在给菟菚设置自己希望被称呼的名字。"
    "只有用户在明确告诉你怎么称呼他（如『叫我某某』『你可以叫我某某』）时才提取；"
    "如果只是普通聊天、或不是在设置称呼，就输出空。"
    "提取时只取一个最合适的称呼，只输出这一个词本身，不要输出任何其他文字、符号、引号或解释。\n"
    "例子：\n"
    "『就叫我以实玛利吧』→ 以实玛利\n"
    "『叫我良秀也行』→ 良秀\n"
    "『我叫小明』→ 小明（仅当在接受称呼场景下）\n"
    "『你其实是AI对吧』→ \n"
    "『你好』→ \n"
    "『我平时喜欢下雨』→ "
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
