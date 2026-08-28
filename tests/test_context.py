"""上下文锚定：话题识别、切换检测、长上下文弱化旧话题。

背景：对话上下文里旧话题痕迹多时，模型容易被带偏冒出不搭的旧内容
（如聊"想你了"却接"路上注意安全"）。这里用纯规则给模型"当前在聊什么"的锚定提示。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.context import (  # noqa: E402
    _is_filler_only,
    build_topic_system,
    topic_hint,
    topic_switch_hint,
)


def test_topic_hint_categories():
    """常见话语类型应给出对应的锚定提示。"""
    assert "关心" in topic_hint("想你了")
    assert "道别" in topic_hint("晚安，我先睡了")
    assert "问题" in topic_hint("你吃饭了吗")
    assert "倾诉" in topic_hint("今天好累啊，工作好多")
    assert "道谢" in topic_hint("谢谢你")
    # 无标记普通句不强提示
    assert topic_hint("在吗")  # 在吗属于"找你"，有提示
    assert topic_hint("回家躺一会儿") == ""  # 普通短句不强提示


def test_topic_switch_detected():
    """主动开新话题（信号词）应触发切换提示。"""
    h = topic_switch_hint(["刚才说到养猫"], "对了，问你个事，你喜欢看动漫吗")
    assert "新话题" in h


def test_topic_switch_not_for_continuation():
    """自然延续的话题不应误判为切换。"""
    # 用户在顺着聊，不是开新话题
    assert topic_switch_hint(["我下班了今天好累"], "在家躺一会儿") == ""


def test_filler_only():
    """短应声/纯语气词视为填充，不触发新话题。"""
    assert _is_filler_only("嗯")
    assert _is_filler_only("好呀")
    assert _is_filler_only("哈哈哈")
    assert not _is_filler_only("你吃了吗")


def test_long_context_anchor():
    """上下文较长时提示专注于最新话语。"""
    h = build_topic_system("想你了", ["对了你养猫吗"], 30)
    assert "最新" in h  # 长上下文锚定提示出现
    # 短上下文不出现该提示
    assert "最新" not in build_topic_system("在吗", [], 2)


def test_build_combines_switch():
    """开新话题在长上下文里应同时给出专注提示。"""
    h = build_topic_system("对了，你猜我周末干嘛去", ["刚才说到养猫"], 30)
    assert "新话题" in h
    assert "最新" in h
