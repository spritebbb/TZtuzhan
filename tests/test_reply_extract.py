"""对话回复提取：_extract_reply / strip_actions 对括号变体的处理。

背景：LLM 输出"先思考后发言"时可能用不同括号——全角【】、六角〔〕、或「回复:」。
若只认【回复】，六角〔回复〕会漏掉，导致〔思考〕〔回复〕整段暴露给用户。
"""
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import _extract_reply, strip_actions  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 全角方头（标准格式）
        ("【思考】这人是挺会撩的。\n【回复】我们才认识多久呀", "我们才认识多久呀"),
        # 六角括号（此前 bug 漏掉）
        ("〔思考〕又来这句，保持距离。\n〔回复〕你这话是不是对谁都说", "你这话是不是对谁都说"),
        # 「回复:」冒号标注
        ("思考：这人挺有意思。\n回复：你今天怎么突然想我了", "你今天怎么突然想我了"),
        # 无标记 → 整段当回复
        ("今天天气不错", "今天天气不错"),
        # 思考在前、正文在后（无回复标注，保留正文、丢弃思考段）
        ("【思考】对方在敷衍我。\n嗯，那我先不吵你了", "嗯，那我先不吵你了"),
        # 思考段吞掉整段（无正文）→ 不泄漏思考，返回空
        ("【思考】对方在敷衍我。", ""),
    ],
)
def test_extract_reply_variants(raw, expected):
    assert _extract_reply(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("偷偷看你（我有点害羞）", "偷偷看你"),
        ("〔思考〕轻点〔回复〕知道了", "知道了"),
        ("【思考】无语【回复】别这样", "别这样"),
    ],
)
def test_strip_actions_removes_brackets(raw, expected):
    assert strip_actions(raw) == expected


def test_extract_then_strip_combined():
    """完整流程：先取回复正文再剥旁白。"""
    raw = "〔思考〕这人有点烦但得温柔〔回复〕嗯（轻叹）那我不吵你了"
    reply = strip_actions(_extract_reply(raw))
    assert "嗯" in reply and "那我不吵你了" in reply
    assert "思考" not in reply and "回复" not in reply and "〔" not in reply
