"""表情包收藏：主动收集用户发的表情包，存本地 + 记录描述，之后可回发。

- collect(user_id, url)：下载用户发的图片到 data/stickers/，用视觉模型描述后入库（去重）
- pick(user_id, keyword)：按话题从收藏里挑一张表情包（本地路径，用于回发）
- installed(user_id)：是否已有收藏（决定要不要回发）
"""
import base64
import hashlib
import urllib.request
from pathlib import Path

from .config import config
from .log import logger
from .userdb import get_sticker_by_desc, get_stickers, save_sticker
from .vision import describe_image, _guess_mime

# 收藏上限：避免本地目录无限膨胀
MAX_STICKERS = 200


def _download(url: str, timeout: int = 20) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ext(url: str, data: bytes) -> str:
    """按图片二进制猜扩展名。"""
    try:
        mime = _guess_mime(data)
    except Exception:
        mime = "image/jpeg"
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}.get(mime, ".jpg")


def _stickers_dir() -> Path:
    d = config.data_dir / "stickers"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def collect(user_id: str, url: str) -> dict | None:
    """收藏用户发的表情包；下载图片、视觉描述、入库。失败返回 None（不阻塞对话）。"""
    if not url:
        return None
    try:
        data = _download(url)  # 同步下载（线程内阻塞可接受）
        if not data:
            return None
        digest = hashlib.md5(data).hexdigest()[:16]
        ext = _ext(url, data)
        path = _stickers_dir() / f"{digest}{ext}"
        path.write_bytes(data)  # 幂等：同 digest 覆盖写入同一文件
        desc = await describe_image(url)
        record_id = save_sticker(user_id, str(path), url, desc)
        return {"id": record_id, "file": str(path), "desc": desc}
    except Exception:
        logger.warning("[表情收藏] 收集失败：{}", url)
        return None


def pick(user_id: str, keyword: str, limit: int = 30) -> list[dict]:
    """按话题挑收藏的表情包；关键词为空则返回热门几张。"""
    if keyword:
        hits = get_sticker_by_desc(user_id, keyword, limit)
        if hits:
            return hits
    # 话题没匹配到 → 返回收藏里出现次数最多的
    return get_stickers(user_id, limit)


def get_recent_sticker(user_id: str) -> str | None:
    """挑一张用户最近收藏的表情包（本地路径），用于主动消息带图。

    优先挑近期收藏（靠后的记录），返回文件路径；无收藏返回 None。
    """
    try:
        stickers = get_stickers(user_id, 10)
        if not stickers:
            return None
        # 取最后一张（最近收藏的）
        return stickers[-1]["file"]
    except Exception:
        return None


def count(user_id: str) -> int:
    return len(get_stickers(user_id, 500))
