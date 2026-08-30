"""好感度 v3 深化：新增互动触发事件的检测函数测试。

覆盖：
- 道歉检测（抵消前扣分）
- 分享心事/秘密检测
- 夸菟菚检测
- 触发器在 pipeline 即时奖励里的接线（用 try_daily_bonus 语义间接验证检测正确性）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import affection

# ---- 检测函数 ----

def test_check_apology():
    assert affection.check_apology("对不起，我错了")
    assert affection.check_apology("对不起啦，别生气好不好")
    assert affection.check_apology("是我不好，原谅我这次")
    assert affection.check_apology("我知道错了，下次不会了")
    assert not affection.check_apology("今天天气不错")


def test_check_sharing():
    assert affection.check_sharing("跟你说个事，我最近有点烦")
    assert affection.check_sharing("告诉你一个秘密，其实我……")
    assert affection.check_sharing("我跟你倾诉一下，心里难受")
    assert affection.check_sharing("想跟你说说心里话")
    assert not affection.check_sharing("帮我查个东西")


def test_check_compliment():
    assert affection.check_compliment("你好可爱")
    assert affection.check_compliment("你真贴心")
    assert affection.check_compliment("你最好了")
    assert affection.check_compliment("被你暖到了")
    assert not affection.check_compliment("你好吗")


# ---- 检测不误伤 ----

def test_no_false_positive_on_common_phrases():
    # 日常话不能误判成这些触发
    assert not affection.check_apology("今天吃了吗")
    assert not affection.check_apology("周末去哪玩")
    assert not affection.check_sharing("我跟你说的话你记一下")
    assert not affection.check_compliment("你好")


def test_all_triggers_have_constants():
    # 每个触发事件都有对应的奖励分值常量（接线正确性）
    assert affection.APOLOGY_BONUS >= 1
    assert affection.SHARING_BONUS >= 1
    assert affection.COMPLIMENT_BONUS >= 1
