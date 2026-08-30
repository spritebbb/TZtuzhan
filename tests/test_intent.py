"""意图路由（方向 B）的纯逻辑测试。

覆盖：
- 闲聊短句 → chitchat=True（少注入）
- 搜索/生图/回忆/情感关键词 → 对应 need_* 触发
- 普通长句 → 全量注入（安全默认）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.intent import classify


def test_chitchat_short():
    for msg in ("嗯", "好的", "哈哈", "在吗", "晚安", "拜拜"):
        r = classify(msg)
        assert r["chitchat"] is True, f"{msg} 应判闲聊"


def test_search_triggers():
    for msg in ("帮我搜一下今天的新闻", "查查明天天气怎么样", "百度一下这个词的意思"):
        r = classify(msg)
        assert r["need_search"] is True, f"{msg} 应触发搜索"


def test_draw_triggers():
    for msg in ("给我画一只猫", "画个星空给我看看"):
        r = classify(msg)
        assert r["need_draw"] is True, f"{msg} 应触发生图"


def test_recall_triggers():
    for msg in ("你还记得上次我们聊什么吗", "我们上次说好的事情呢", "你还记得我说过的话吗"):
        r = classify(msg)
        assert r["need_recall"] is True, f"{msg} 应触发回忆"


def test_emotional_triggers():
    for msg in ("我今天好烦啊", "心里有点难受", "跟你说个事，我最近压力好大"):
        r = classify(msg)
        assert r["need_emotional"] is True, f"{msg} 应触发情感注入"


def test_normal_long_message_full_injection():
    # 普通长句 → 不判闲聊，保留全量注入（安全默认）
    r = classify("周末想去爬山，你有什么推荐的地方吗")
    assert r["chitchat"] is False


def test_chitchat_takes_priority():
    # "好的" 即使短也是闲聊
    r = classify("好的")
    assert r["chitchat"] is True
    # 搜索优先于闲聊判定
    r2 = classify("好，帮我搜一下新闻")
    assert r2["need_search"] is True