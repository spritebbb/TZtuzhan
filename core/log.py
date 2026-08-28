"""日志：loguru 写入 data/bot.log，并镜像到 stderr（NoneBot 控制台）。"""
import sys

from loguru import logger

from .config import config

logger.remove()
config.data_dir.mkdir(parents=True, exist_ok=True)
logger.add(
    config.data_dir / "bot.log",
    rotation="10 MB",
    retention=7,
    encoding="utf-8",
    level="INFO",
    enqueue=True,  # 线程安全：后台任务与主循环都可能写日志
)
logger.add(sys.stderr, level="INFO")

__all__ = ["logger"]
