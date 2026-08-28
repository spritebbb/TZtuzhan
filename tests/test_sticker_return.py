"""表情包回发：不能把用户刚发的原样奉还，要从收藏里挑别的、贴合语境的。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import sticker
from core.userdb import db

uid = "pytest-sticker-excl2"
db.ensure_user(uid)
for t in ("stickers",):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.commit()


def _seed():
    """造两个收藏：A 是用户刚发的（将被排除），B 是旧的。"""
    db.conn.execute(
        "INSERT INTO stickers (user_id, file, url, desc, count, ts) VALUES (?,?,?,?,?,datetime('now'))",
        (uid, "D:/fake/A.jpg", "urlA", "一个歪头比赞的大头娃娃", 3),
    )
    db.conn.execute(
        "INSERT INTO stickers (user_id, file, url, desc, count, ts) VALUES (?,?,?,?,?,datetime('now'))",
        (uid, "D:/fake/B.jpg", "urlB", "一只眯眼笑的猫咪", 2),
    )
    db.conn.commit()


def test_pick_excludes_just_collected():
    """回发时排除用户刚发的图，返回别的收藏。"""
    _seed()
    just_collected = {"D:/fake/A.jpg"}
    r = sticker.pick(uid, "", 5, exclude_files=just_collected)
    files = [x["file"] for x in r]
    assert "D:/fake/A.jpg" not in files
    assert "D:/fake/B.jpg" in files


def test_pick_context_prefers_topic_but_excludes():
    """带语境关键词时也不能返回刚发的图。"""
    _seed()
    r = sticker.pick(uid, "歪头比赞 玩偶", 5, exclude_files={"D:/fake/A.jpg"})
    files = [x["file"] for x in r]
    assert "D:/fake/A.jpg" not in files


def test_pick_all_excluded_returns_empty():
    """全部收藏都被排除时返回空（此时只说话不甩图）。"""
    _seed()
    r = sticker.pick(uid, "", 5, exclude_files={"D:/fake/A.jpg", "D:/fake/B.jpg"})
    assert r == []


def test_pick_backward_compatible_no_exclude():
    """不传 exclude_files 时兼容旧行为（能选中热门那张）。"""
    _seed()
    r = sticker.pick(uid, "", 5)
    files = [x["file"] for x in r]
    # 热门靠前，A 的 count 更高所以有 A
    assert files and "D:/fake/A.jpg" in files
