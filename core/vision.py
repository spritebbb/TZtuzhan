"""图片理解：用独立的视觉模型描述图片/表情包内容。

配置（.env）：
  VISION_BASE_URL / VISION_API_KEY / VISION_MODEL
不配置 VISION_MODEL 时识图关闭，describe_image 返回空字符串。
"""
import base64
import urllib.request

from openai import AsyncOpenAI

from .config import config
from .log import logger

_vision_client: AsyncOpenAI | None = None


def get_vision_client() -> AsyncOpenAI:
    global _vision_client
    if _vision_client is None:
        base = config.vision_base_url or config.llm_base_url
        key = config.vision_api_key or config.llm_api_key
        _vision_client = AsyncOpenAI(base_url=base, api_key=key)
    return _vision_client


def _guess_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


_DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024  # 下载上限 10MB（防超大图片拖垮识别/内存）


def _download(url: str, timeout: int = 20) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(_DOWNLOAD_MAX_BYTES + 1)
    if len(data) > _DOWNLOAD_MAX_BYTES:
        raise ValueError(f"图片超过 {_DOWNLOAD_MAX_BYTES // 1024 // 1024}MB，拒绝识别")
    return data


async def describe_image(url: str) -> str:
    """下载图片并用视觉模型描述其内容；失败或未配置返回空字符串。"""
    if not config.vision_model:
        return ""
    try:
        data = _download(url)
        mime = _guess_mime(data)
        data_url = f"data:{mime};base64," + base64.b64encode(data).decode()
        client = get_vision_client()
        resp = await client.chat.completions.create(
            model=config.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "用一句简短的中文描述这张图片/表情包的内容，突出主题。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=200,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        logger.warning("[识图] 图片描述失败（返回空，按表情包处理）：{}", url)
        return ""
