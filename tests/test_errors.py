"""生图错误分级 + LLM 重试策略测试（纯函数）。"""
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.imagegen import _raise_typed, ImageGenError


def _http_err(code: int, msg: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, msg, None, None)


def test_error_classification_by_code():
    assert "密钥" in _raise_typed(_http_err(401, "Unauthorized")).user_msg
    assert "密钥" in _raise_typed(_http_err(403, "Forbidden")).user_msg
    assert "余额" in _raise_typed(_http_err(402, "Payment")).user_msg
    assert "限流" in _raise_typed(_http_err(429, "Rate limit")).user_msg
    assert "掉线" in _raise_typed(_http_err(500, "Server error")).user_msg
    assert "理解不了" in _raise_typed(_http_err(400, "Bad request")).user_msg


def test_error_classification_fallback():
    # 无状态码的网络错误 → 默认提示
    err = _raise_typed(TimeoutError("timed out"))
    assert isinstance(err, ImageGenError)
    assert "掉线" in err.user_msg


def test_llm_retryable():
    from core.llm import _is_retryable

    assert _is_retryable(TimeoutError("t"))
    # openai 风格的 5xx/429 可重试
    class FakeExc(Exception):
        status_code = 500

    assert _is_retryable(FakeExc("x"))
    FakeExc.status_code = 429
    assert _is_retryable(FakeExc("x"))
    FakeExc.status_code = 400
    assert not _is_retryable(FakeExc("x"))
