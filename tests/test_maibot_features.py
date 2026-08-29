"""四个 Maibot 借鉴功能（用户画像/口头禅/表达风格/表情情绪）的纯逻辑测试。

覆盖：
- 用户画像：分类存取、去重、注入文本、删除
- 口头禅/黑话：即时捕获、次数累计、注入文本、删除
- 场景化表达风格：存取、重复累加、注入文本
- 表情包情绪匹配：情绪推断、按情绪挑选、排除逻辑

LLM 提炼的端到端由真实 E2E 验证（tools_e2e_real.py / 人工对话），这里只测确定逻辑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import sticker
from core import userdb
from core.profile import profile_prompt_text, profile_text
from core.style import style_map_prompt_text, style_map_text
from core.terms import capture_from_message, note_message, terms_prompt_text

db = userdb.db

UID = "pytest-maibot-features"


def _clean():
    db.ensure_user(UID)
    db.clear_profile(UID)
    db.conn.execute("DELETE FROM user_terms WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM user_style_map WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM stickers WHERE user_id=?", (UID,))
    db.conn.commit()


# ---- ① 用户画像 ----

def test_profile_add_dedup():
    _clean()
    assert db.add_profile(UID, "likes", "用户喜欢下雨天") is not None
    # 完全重复应跳过
    assert db.add_profile(UID, "likes", "用户喜欢下雨天") is None
    # 高度重叠（>50%）应跳过
    assert db.add_profile(UID, "likes", "用户喜欢下雨") is None
    assert db.add_profile(UID, "dislikes", "用户讨厌吃香菜") is not None
    rows = db.get_profile(UID)
    assert len(rows) == 2


def test_profile_prompt_text():
    _clean()
    db.add_profile(UID, "likes", "用户喜欢下雨天")
    db.add_profile(UID, "dislikes", "用户讨厌吃香菜")
    pt = profile_prompt_text(UID)
    assert "喜好" in pt and "用户喜欢下雨天" in pt
    assert "厌恶" in pt and "用户讨厌吃香菜" in pt
    # 空画像
    db.clear_profile(UID)
    assert profile_prompt_text(UID) == ""
    assert "还没记下" in profile_text(UID)


def test_profile_delete():
    _clean()
    rid = db.add_profile(UID, "habits", "用户习惯熬夜")
    assert db.del_profile(UID, rid) is True
    assert db.get_profile(UID) == []


# ---- ② 口头禅/黑话 ----

def test_terms_instant_capture():
    _clean()
    assert capture_from_message("绝了，这波操作真行") == ["绝了", "真行"]
    note_message(UID, "绝了，笑死我了哈哈哈")
    note_message(UID, "啊这，绝了，我麻了")
    terms = db.get_terms(UID)
    # 绝了出现2次
    jl = next(t for t in terms if t["term"] == "绝了")
    assert jl["count"] == 2
    assert any(t["term"] == "笑死" for t in terms)


def test_terms_prompt_text():
    _clean()
    db.add_term(UID, "绝了", "catchphrase")
    db.add_term(UID, "yyds", "slang", "永远的神")
    pt = terms_prompt_text(UID)
    assert "绝了" in pt and "yyds" in pt
    assert "永远的神" in pt
    assert terms_prompt_text("no-such-user-xyz") == ""


def test_terms_delete():
    _clean()
    db.add_term(UID, "麻了", "catchphrase")
    t = db.get_terms(UID)[0]
    assert db.del_term(UID, t["id"]) is True


# ---- ③ 场景化表达风格 ----

def test_style_map_add_dedup():
    _clean()
    assert db.add_style_map(UID, "对方倾诉烦恼时", "喜欢用短句+省略号") is True
    # 同场景同风格累加次数（返回 False 表示非新增）
    assert db.add_style_map(UID, "对方倾诉烦恼时", "喜欢用短句+省略号") is False
    db.add_style_map(UID, "对方开玩笑时", "爱用调侃和反问")
    rows = db.get_style_map(UID)
    assert len(rows) == 2
    assert rows[0]["count"] == 2


def test_style_map_prompt_text():
    _clean()
    db.add_style_map(UID, "对方倾诉烦恼时", "喜欢用短句+省略号")
    pt = style_map_prompt_text(UID)
    assert "倾诉烦恼" in pt and "短句" in pt
    assert "还没注意到" in style_map_text("no-such-user-xyz")


# ---- ④ 表情包情绪匹配 ----

def test_emotion_guess():
    assert "开心" in sticker.guess_emotions("一只笑着的小猫，比心")
    assert "难过" in sticker.guess_emotions("流泪的狗狗，很委屈")
    assert "生气" in sticker.guess_emotions("生气的卡通人物")
    assert "惊讶" in sticker.guess_emotions("震惊的表情，瞪大眼睛")
    assert "开心" not in sticker.guess_emotions("哭得很伤心的小熊")
    assert sticker.guess_emotions("") == ""


def test_emoji_pick_by_emotion():
    _clean()
    userdb.save_sticker(UID, "D:/fake/happy.png", "http://x/1.png", "笑着的小猫", "开心")
    userdb.save_sticker(UID, "D:/fake/sad.png", "http://x/2.png", "流泪的狗狗", "难过")
    userdb.save_sticker(UID, "D:/fake/shy.png", "http://x/4.png", "卖萌的小狐狸", "撒娇,可爱")

    hits = sticker.pick_by_emotion(UID, "开心", 5)
    assert hits and "happy" in hits[0]["file"]
    # 排除刚发的
    assert sticker.pick_by_emotion(UID, "难过", 5, exclude_files={"D:/fake/sad.png"}) == []
    # 无匹配
    assert sticker.pick_by_emotion(UID, "困倦", 5) == []
    assert "开心" in sticker.emotion_tags()
