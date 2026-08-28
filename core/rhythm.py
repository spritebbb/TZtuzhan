"""回复节奏工具：把固定延迟变成带随机抖动的真人节奏。

背景：bot 回复延迟如果完全固定（如每次都是 2.0s / 3.0s），会呈现明显的
"规律性"——既是机器人感的来源，也容易让风控把账号标记为自动化设备。
这里把 base 延迟 ± jitter 比例随机化，让节奏更像真人。

- jitter(base, ratio)：base * (1-ratio) ~ base * (1+ratio) 均匀随机
- 调用方只需替换原来的固定 sleep 为 jitter 后的值
"""
import random

from .config import config


def jitter(base: float, ratio: float | None = None) -> float:
    """返回带随机抖动的延迟秒数（>=0）。ratio 默认取 config.delay_jitter。"""
    r = config.delay_jitter if ratio is None else ratio
    r = max(0.0, min(1.0, float(r)))
    low = base * (1.0 - r)
    high = base * (1.0 + r)
    return random.uniform(low, high)
