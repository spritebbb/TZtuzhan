"""表情包收藏：主动收集用户发的表情包，存本地 + 记录描述，之后可回发。

- collect(user_id, url)：下载用户发的图片到 data/stickers/，用视觉模型描述后入库（去重）
- pick(user_id, keyword)：按话题从收藏里挑一张表情包（本地路径，用于回发）
- installed(user_id)：是否已有收藏（决定要不要回发）
"""
import base64
import hashlib
import random
import urllib.request
from pathlib import Path

from .config import config
from .log import logger
from .userdb import get_sticker_by_desc, get_stickers, get_sticker_by_emotion, save_sticker, update_sticker_emotion
from .vision import describe_image, _guess_mime

# 收藏上限：避免本地目录无限膨胀
MAX_STICKERS = 200
# 单张表情包下载上限 8MB（防超大图把磁盘/识图拖垮）
_STICKER_MAX_BYTES = 8 * 1024 * 1024

# 情绪关键词 → 情绪标签（从视觉描述推断；借鉴 Maibot emoji_manager 按情绪挑选）
_EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "开心": ("笑", "开心", "高兴", "哈哈", "乐", "可爱", "比心", "耶", "喜"),
    "难过": ("哭", "难过", "伤心", "委屈", "泪", "呜呜", "可怜", "悲伤"),
    "生气": ("生气", "愤怒", "怒", "凶", "发火", "暴躁", "气"),
    "惊讶": ("惊讶", "震惊", "惊", "瞪", "无语", "呆"),
    "撒娇": ("撒娇", "卖萌", "求", "蹭", "依偎", "撒娇"),
    "困倦": ("困", "累", "疲惫", "打哈欠", "睡"),
    "日常": ("日常", "普通", "平静", "淡然", "面无表情", "淡定"),
}


def guess_emotions(desc: str) -> str:
    """从视觉描述推断情绪标签（逗号分隔）；无匹配返回 ''（存库时当日常）。"""
    if not desc:
        return ""
    tags = []
    for label, kws in _EMOTION_KEYWORDS.items():
        if any(k in desc for k in kws):
            tags.append(label)
    return ",".join(tags)


def _download(url: str, timeout: int = 20) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(_STICKER_MAX_BYTES + 1)
    if len(data) > _STICKER_MAX_BYTES:
        raise ValueError("表情包过大，跳过收藏")
    return data


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
    """收藏用户发的表情包；下载图片、视觉描述、情绪推断、入库。失败返回 None（不阻塞对话）。"""
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
        emotion = guess_emotions(desc)
        record_id = save_sticker(user_id, str(path), url, desc, emotion)
        return {"id": record_id, "file": str(path), "desc": desc, "emotion": emotion}
    except Exception:
        logger.warning("[表情收藏] 收集失败：{}", url)
        return None


def pick(user_id: str, keyword: str, limit: int = 30, exclude_files: set[str] | None = None) -> list[dict]:
    """按话题挑收藏的表情包；关键词为空则返回热门几张。

    exclude_files：要排除的本地文件路径集合——通常是**用户刚发的、刚被收藏的**那几张，
    回发时不能把对方刚发的原样奉还，要从收藏里挑「别的、贴合语境」的。
    """
    exclude = set(exclude_files or ())

    def _sift(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r.get("file") not in exclude]

    if keyword:
        hits = _sift(get_sticker_by_desc(user_id, keyword, limit))
        if hits:
            return hits
    # 话题没匹配到 → 返回收藏里出现次数最多的（仍排除刚发的）
    return _sift(get_stickers(user_id, limit))


def pick_by_emotion(user_id: str, emotion: str, limit: int = 5, exclude_files: set[str] | None = None) -> list[dict]:
    """按情绪挑收藏的表情包（情绪匹配回发）。

    emotion 是情绪词（开心/难过/生气/惊讶/撒娇/困倦/日常）。
    无匹配返回 []（调用方回退到话题/热门）。
    """
    exclude = set(exclude_files or ())
    hits = get_sticker_by_emotion(user_id, emotion, limit * 4)
    return [r for r in hits if r.get("file") not in exclude][:limit]


def emotion_tags() -> list[str]:
    """可用的情绪标签（/表情 命令提示用）。"""
    return list(_EMOTION_KEYWORDS.keys())


def get_recent_sticker(user_id: str) -> str | None:
    """随机挑一张用户收藏的表情包（本地路径），用于主动消息带图。

    从热门收藏里随机取一张，避免每次都发"最近收藏的那一张"。
    无收藏返回 None。
    """
    try:
        stickers = get_stickers(user_id, 20)
        if not stickers:
            return None
        return random.choice(stickers)["file"]
    except Exception:
        return None


def count(user_id: str) -> int:
    return len(get_stickers(user_id, 500))
