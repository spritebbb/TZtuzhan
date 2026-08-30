"""后台任务调度：把不阻塞主对话的耗时任务（每日总结、事实提炼）放到后台执行。

- 同 key 在跑则跳过（避免重复触发同一批总结）
- 失败只记日志，绝不抛回主流程（对话不能被后台任务搞挂）
- 用 asyncio 事件循环的 create_task，单线程内与 SQLite 同步操作天然无锁竞争
"""
import asyncio
from typing import Awaitable, Callable

from .log import logger

_inflight: set[str] = set()
# 持有运行中任务的强引用，避免 pending task 被 GC 销毁（"Task was destroyed but it is pending"）
_tasks: set[asyncio.Task] = set()


def schedule(key: str, coro_factory: Callable[[], Awaitable]) -> None:
    """调度一个后台协程；同 key 正在运行则跳过。

    coro_factory 返回协程（注意不是协程对象本身，保证捕获正确的 key/day 闭包）。
    """
    if key in _inflight:
        return
    _inflight.add(key)

    async def _runner() -> None:
        try:
            await coro_factory()
        except Exception:
            logger.exception("[后台任务] {} 失败", key)
        finally:
            _inflight.discard(key)
            _tasks.discard(asyncio.current_task())

    try:
        task = asyncio.get_running_loop().create_task(_runner())
        _tasks.add(task)
    except RuntimeError:
        # create_task 失败（如 loop 关闭时不创建任务），清理 inflight 防永久跳过
        _inflight.discard(key)


def pending(key: str) -> bool:
    """该 key 是否有后台任务在跑（供测试/调试）。"""
    return key in _inflight
