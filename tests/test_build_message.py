"""消息构建：_build_message 的 face 白名单校验测试（防 NapCat '不支持的ID' 报错）。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.message_build import _build_message, _EMOJI_POOL, _maybe_append_emoji


def test_legal_face_convert():
    """白名单内 [face:N] 转成 face 段。"""
    msg = _build_message(f"好呀[face:{_EMOJI_POOL[0]}]")
    segs = list(msg)
    assert segs[-1].type == "face"
    assert segs[-1].data["id"] == str(_EMOJI_POOL[0])


def test_illegal_face_stripped():
    """LLM 乱填的 [face:44]（不在白名单）不生成 face 段，只留文字。"""
    msg = _build_message("求我也没用[face:44]我真不会画")
    segs = list(msg)
    assert not any(s.type == "face" for s in segs)
    joined = "".join(s.data.get("text", "") for s in segs)
    assert "求我也没用" in joined and "我真不会画" in joined
    assert "[face:44]" not in joined


def test_no_face_segment_for_unknown():
    """不带方括号的普通文字全部保留为文本。"""
    msg = _build_message("襄阳挺远的，十五个小时够你睡一觉")
    segs = list(msg)
    assert all(s.type == "text" for s in segs)
    assert "".join(s.data.get("text", "") for s in segs) == "襄阳挺远的，十五个小时够你睡一觉"


def test_maybe_append_emoji_uses_pool_only():
    """追加表情只从白名单池取 id（若确实加了）。"""
    for _ in range(50):
        for c in _maybe_append_emoji(["你好"]):
            for fid in re.findall(r"\[face:(\d+)\]", c):
                assert int(fid) in _EMOJI_POOL
