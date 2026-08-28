"""消息构建：_build_message 的 face 过滤 + image_file 路径转换测试。

背景：NapCat 对不支持的 face id 会报"消息体无法解析/不支持的ID"，
因此默认白名单 _EMOJI_POOL 为空，所有 [face:N] 一律按文本剥离，绝不生成 face 段。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.message_build import _build_message, _EMOJI_POOL, _maybe_append_emoji, image_file


def test_any_face_stripped_when_pool_empty():
    """白名单为空（默认）时，任何 [face:N] 都不生成 face 段，只留文字。"""
    for fid in (14, 44, 109, 277, 999):
        msg = _build_message(f"求我也没用[face:{fid}]我真不会画")
        segs = list(msg)
        assert not any(s.type == "face" for s in segs)
        joined = "".join(s.data.get("text", "") for s in segs)
        assert "求我也没用" in joined and "我真不会画" in joined
        assert f"[face:{fid}]" not in joined


def test_normal_text_kept():
    """不带方括号的普通文字全部保留为文本。"""
    msg = _build_message("襄阳挺远的，十五个小时够你睡一觉")
    segs = list(msg)
    assert all(s.type == "text" for s in segs)
    assert "".join(s.data.get("text", "") for s in segs) == "襄阳挺远的，十五个小时够你睡一觉"


def test_maybe_append_emoji_noop_when_pool_empty():
    """_EMOJI_POOL 为空时，_maybe_append_emoji 不追加任何 face 标记。"""
    for _ in range(50):
        out = _maybe_append_emoji(["你好"])
        assert all("[face:" not in c for c in out)


def test_image_file_converts_windows_path():
    """本地 Windows 路径转成 file:/// URI，正斜杠。"""
    uri = image_file(r"D:\DSH\TZtuzhan\data\stickers\x.gif")
    assert uri.startswith("file:///")
    assert uri.endswith("/DSH/TZtuzhan/data/stickers/x.gif")
    # 不再含反斜杠
    assert "\\" not in uri


def test_image_file_passthrough_remote():
    """http/https/file URL 原样返回，不乱改。"""
    assert image_file("https://example.com/a.jpg") == "https://example.com/a.jpg"
    assert image_file("file:///D:/x.jpg") == "file:///D:/x.jpg"
