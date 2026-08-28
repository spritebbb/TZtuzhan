"""中国节日系统：公历固定节日 + 农历节日换算 + 除夕特殊处理。"""
import datetime
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import holidays  # noqa: E402


def _mock_today(month: int, day: int):
    return mock.patch(
        "core.holidays.date",
        wraps=datetime.date,
    ), None


def _today(month: int, day: int) -> list[str]:
    with mock.patch("core.holidays.date") as md:
        md.today.return_value = datetime.date(2026, month, day)
        return holidays.today_holidays()


def test_solar_holidays():
    """固定公历节日应识别。"""
    assert "元旦" in _today(1, 1)
    assert "劳动节" in _today(5, 1)
    assert "国庆节" in _today(10, 1)
    assert "妇女节" in _today(3, 8)
    assert "儿童节" in _today(6, 1)


def test_lunar_holidays_2026():
    """2026 农历节日应换算到正确公历日期。"""
    assert "春节" in _today(2, 17)
    assert "元宵节" in _today(3, 3)
    assert "端午节" in _today(6, 19)
    assert "七夕节" in _today(8, 19)
    assert "中秋节" in _today(9, 25)
    assert "重阳节" in _today(10, 18)


def test_chuxi_is_day_before_spring_festival():
    """除夕应是春节前一天。"""
    assert "除夕" in _today(2, 16)  # 2026 春节 2-17，除夕 2-16


def test_no_holiday_on_normal_day():
    """普通日子无节日。"""
    assert _today(8, 28) == []


def test_holiday_prompt_nonempty_on_festival():
    """节日当天 holiday_prompt 非空且含节日名。"""
    with mock.patch("core.holidays.date") as md:
        md.today.return_value = datetime.date(2026, 9, 25)  # 中秋
        p = holidays.holiday_prompt()
    assert "中秋节" in p


def test_holiday_prompt_empty_on_normal_day():
    """普通日子 holiday_prompt 为空。"""
    with mock.patch("core.holidays.date") as md:
        md.today.return_value = datetime.date(2026, 8, 28)
        p = holidays.holiday_prompt()
    assert p == ""
