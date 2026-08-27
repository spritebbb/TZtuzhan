"""图像生成：用 SiliconFlow 文生图，把用户的描述画成一张图，发到 QQ。

- generate(prompt) → 下载图片到 data/imgs/，返回本地文件路径；失败返回 None
- 通过 IMAGE_API_KEY / IMAGE_MODEL / IMAGE_BASE_URL 配置
- 不配置 key 则生图关闭
"""
import hashlib
import urllib.request
import json
from pathlib import Path

from .config import config
from .log import logger


def enabled() -> bool:
    return bool(config.image_api_key)


def _imgs_dir() -> Path:
    d = config.data_dir / "imgs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, timeout: int = 60) -> bytes:
    if url.startswith("data:"):
        import base64
        return base64.b64decode(url.split(",", 1)[1])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _guess_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def generate_sync(prompt: str, size: str = "1024x1024") -> str | None:
    """同步生成一张图并下载到本地；返回本地路径，失败返回 None。"""
    if not enabled():
        logger.warning("[生图] 未配置 IMAGE_API_KEY，跳过")
        return None
    if not prompt.strip():
        return None
    try:
        payload = json.dumps(
            {
                "model": config.image_model,
                "prompt": prompt,
                "image_size": size,
                "batch_size": 1,
                "num_inference_steps": 20,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{config.image_base_url.rstrip('/')}/images/generations",
            data=payload,
            headers={
                "Authorization": f"Bearer {config.image_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        images = data.get("images") or []
        if not images:
            logger.warning("[生图] 返回无图片：{}", str(data)[:200])
            return None
        url = images[0].get("url") or ""
        if not url:
            logger.warning("[生图] 返回无 url：{}", str(images[0])[:200])
            return None
        # 下载落盘（用 prompt 哈希命名，避免重复）
        raw = _download(url)
        digest = hashlib.md5(raw).hexdigest()[:16]
        path = _imgs_dir() / f"{digest}{_guess_ext(raw)}"
        path.write_bytes(raw)
        return str(path)
    except Exception:
        logger.exception("[生图] 生成失败：{}", prompt[:50])
        return None


async def generate(prompt: str, size: str = "1024x1024") -> str | None:
    """异步入口（生成是 CPU/网络阻塞，直接同步执行即可；保持 async 便于调用方 await）。"""
    return generate_sync(prompt, size)
