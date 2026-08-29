"""图片卡片渲染：把好感度 / 心情 / 日程 状态渲染成漂亮的图片卡片（maibot 风格可视化）。

用 Pillow 绘制，中文用 Windows 系统字体（msyh / simhei）。所有渲染失败时
返回 None，调用方回退到纯文本输出，保证不影响 bot 稳定性。
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---- 字体（Windows）----
_FONT_DIR = Path("C:/Windows/Fonts")
_BOLD = _FONT_DIR / "msyhbd.ttc"  # 微软雅黑粗体
_REGULAR = _FONT_DIR / "msyh.ttc"  # 微软雅黑
_FALLBACK = _FONT_DIR / "simhei.ttf"  # 黑体


def _font(bold: bool = False, size: int = 24) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _BOLD if bold else _REGULAR
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        try:
            return ImageFont.truetype(str(_FALLBACK), size)
        except OSError:
            return ImageFont.load_default()


# ---- 颜色工具 ----
def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore


def _gradient(size: tuple[int, int], c1: tuple, c2: tuple) -> Image.Image:
    """垂直渐变背景。"""
    w, h = size
    img = Image.new("RGB", size)
    for y in range(h):
        t = y / max(h - 1, 1)
        img.paste(_lerp(c1, c2, t), (0, y, w, y + 1))
    return img


def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _draw_progress(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    ratio: float,
    color: tuple,
    bg: tuple = (40, 40, 50),
) -> None:
    """圆角进度条。"""
    ratio = max(0.0, min(1.0, ratio))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    fw = int(w * ratio)
    if fw > 0:
        draw.rounded_rectangle([x, y, x + fw, y + h], radius=h // 2, fill=color)


def _card_base(size: tuple[int, int], c1: tuple, c2: tuple, radius: int = 28) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = _gradient(size, c1, c2)
    mask = _round_mask(size, radius)
    out = Image.new("RGB", size, (20, 20, 28))
    out.paste(img, (0, 0), mask)
    return out, ImageDraw.Draw(out)


def _finalize(img: Image.Image) -> bytes | None:
    """PNG 编码成 bytes；失败返回 None。"""
    try:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ---- 主题色（阶段 / 心情）----
_STAGE_COLORS = {
    "初识": ("#7c8db5", "#55607f"),
    "熟悉": ("#8fb98a", "#5a8057"),
    "亲密": ("#e8a0b4", "#c06a86"),
    "恋人": ("#f08aa8", "#d75f8a"),
}
_MOOD_COLORS = {
    "雀跃": ("#f7c873", "#e89a3d"),
    "开心": ("#8fc8a8", "#5ba07f"),
    "平淡": ("#b8b8c0", "#8a8a94"),
    "低落": ("#8a9bb5", "#5a6a85"),
    "慵懒": ("#c9a6e0", "#9a6fc0"),
}


def _theme(colors: dict, key: str, default: tuple = ("#8a9bb5", "#5a6a85")) -> tuple[tuple, tuple]:
    c1, c2 = colors.get(key, default)
    return _hex(c1), _hex(c2)


# =====================================================================
#  好感度卡片
# =====================================================================
def render_affection_card(
    user_id: str,
    *,
    affection: int,
    stage: str,
    next_threshold: int | None,
    bond: tuple | None,
) -> bytes | None:
    """渲染好感度卡片。affection/stage/bond 由调用方传入（避免依赖循环）。"""
    try:
        W, H = 480, 260
        c1, c2 = _theme(_STAGE_COLORS, stage)
        img, d = _card_base((W, H), c1, c2)

        # 标题
        d.text((36, 30), "💕  好感度", font=_font(True, 30), fill=(255, 255, 255))

        # 大数值
        d.text((36, 78), f"{affection}", font=_font(True, 64), fill=(255, 255, 255))

        # 阶段 + 羁绊（右侧）
        d.text((170, 92), f"阶段 · {stage}", font=_font(True, 28), fill=(255, 255, 255))
        if bond:
            d.text((170, 132), f"羁绊 · {bond[0]}", font=_font(False, 22), fill=(255, 240, 245))

        # 进度条（占满宽度）
        bar_y = 182
        d.text((36, bar_y - 2), "0", font=_font(False, 14), fill=(255, 255, 255, 180))
        _draw_progress(d, 56, bar_y - 2, W - 120, 18, affection / 100, (255, 255, 255))
        d.text((W - 64, bar_y - 2), "100", font=_font(False, 14), fill=(255, 255, 255, 180))

        # 下一阶段提示
        tip = ""
        if next_threshold:
            tip = f"距「恋人」还需 {next_threshold - affection} 点"
        else:
            tip = "已是最高阶段，感情圆满 💞"
        d.text((36, H - 42), tip, font=_font(False, 20), fill=(255, 235, 240))

        return _finalize(img)
    except Exception:
        return None


# =====================================================================
#  心情卡片
# =====================================================================
def render_mood_card(
    *,
    mood: int,
    label: str,
    desc: str,
    weather: str = "",
) -> bytes | None:
    """渲染心情卡片。"""
    try:
        W, H = 480, 280
        c1, c2 = _theme(_MOOD_COLORS, label)
        img, d = _card_base((W, H), c1, c2)

        d.text((36, 30), "🎭  心情", font=_font(True, 30), fill=(255, 255, 255))

        # 大数值
        d.text((36, 78), f"{mood}", font=_font(True, 64), fill=(255, 255, 255))
        d.text((150, 92), label, font=_font(True, 30), fill=(255, 255, 255))

        # 进度条
        bar_y = 178
        _draw_progress(d, 36, bar_y, W - 72, 18, mood / 100, (255, 255, 255))

        # 描述（自动换行）
        d.text((36, 214), desc, font=_font(False, 20), fill=(255, 245, 248))
        if weather:
            d.text((36, 248), weather, font=_font(False, 18), fill=(255, 235, 240))

        return _finalize(img)
    except Exception:
        return None


# =====================================================================
#  日程卡片
# =====================================================================
_PERIOD_EMOJI = {
    "凌晨": "🌌", "早上": "🌅", "上午": "☀️", "中午": "🍚",
    "下午": "🌤", "傍晚": "🌆", "晚上": "🌙", "深夜": "🌃",
}


def render_schedule_card(*, items: list[dict], head: str = "") -> bytes | None:
    """渲染日程卡片。items: [{period, todo}, ...]"""
    try:
        # 动态高度：头 + 每行
        row_h = 44
        head_h = 64 if head else 40
        W = 520
        H = head_h + len(items) * row_h + 40
        c1, c2 = _hex("#7c8db5"), _hex("#55607f")
        img, d = _card_base((W, H), c1, c2)

        y = 24
        d.text((32, y), "📅  今日日程", font=_font(True, 30), fill=(255, 255, 255))
        y += 52
        if head:
            d.text((32, y), head, font=_font(False, 18), fill=(255, 240, 245))
            y += 34

        for s in items:
            period = s.get("period", "")
            todo = s.get("todo", "")
            emoji = _PERIOD_EMOJI.get(period, "🕐")
            d.text((32, y), f"{emoji} {period}", font=_font(True, 22), fill=(255, 235, 245))
            d.text((150, y + 2), todo, font=_font(False, 21), fill=(255, 255, 255))
            y += row_h

        return _finalize(img)
    except Exception:
        return None
