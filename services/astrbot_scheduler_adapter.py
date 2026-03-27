from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Sequence

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from astrbot.api import logger


class SchedulerAdapter(ABC):
    """调度/提醒统一接口。"""

    @abstractmethod
    async def start(self) -> None:
        """启动调度能力。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止调度能力。"""

    @abstractmethod
    async def schedule_once(
        self,
        job_id: str,
        run_date: datetime,
        callback: Callable,
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        """一次性任务调度。"""

    @abstractmethod
    async def schedule_cron(
        self,
        job_id: str,
        cron_kwargs: Dict[str, Any],
        callback: Callable,
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        """Cron 任务调度。"""

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        """取消调度任务。"""

    @abstractmethod
    async def send_reminder(self, session_origin: str, message: str) -> None:
        """发送提醒消息。"""

    @abstractmethod
    def requires_reload_on_start(self) -> bool:
        """启动时是否需要由业务层重新装载任务。"""


class AstrBotSchedulerAdapter(SchedulerAdapter):
    """AstrBot 原生能力优先，APScheduler 兜底。"""

    def __init__(self, context=None):
        self.context = context
        self._fallback_scheduler = AsyncIOScheduler()

    def _get_native_scheduler(self):
        if not self.context:
            return None

        scheduler = getattr(self.context, "scheduler", None)
        if scheduler:
            return scheduler

        getter = getattr(self.context, "get_scheduler", None)
        if callable(getter):
            try:
                return getter()
            except Exception as exc:
                logger.warning(f"Failed to get AstrBot native scheduler: {exc}")

        return None

    async def _maybe_await(self, result):
        if inspect.isawaitable(result):
            await result

    async def start(self) -> None:
        native_scheduler = self._get_native_scheduler()
        if native_scheduler and hasattr(native_scheduler, "start"):
            try:
                await self._maybe_await(native_scheduler.start())
                logger.info("Scheduler adapter started with AstrBot native scheduler")
                return
            except Exception as exc:
                logger.warning(
                    f"AstrBot native scheduler start failed, fallback to APScheduler: {exc}"
                )

        if not self._fallback_scheduler.running:
            self._fallback_scheduler.start()
            logger.info("Scheduler adapter started with APScheduler fallback")

    async def stop(self) -> None:
        native_scheduler = self._get_native_scheduler()
        if native_scheduler and hasattr(native_scheduler, "shutdown"):
            try:
                await self._maybe_await(native_scheduler.shutdown(wait=False))
                return
            except Exception as exc:
                logger.warning(
                    f"AstrBot native scheduler shutdown failed, fallback to APScheduler: {exc}"
                )

        if self._fallback_scheduler.running:
            self._fallback_scheduler.shutdown(wait=False)

    async def schedule_once(
        self,
        job_id: str,
        run_date: datetime,
        callback: Callable,
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        args = list(args or [])
        native_scheduler = self._get_native_scheduler()

        if native_scheduler and hasattr(native_scheduler, "add_job"):
            try:
                await self._maybe_await(
                    native_scheduler.add_job(
                        func=callback,
                        trigger=DateTrigger(run_date=run_date),
                        args=args,
                        id=job_id,
                        replace_existing=True,
                    )
                )
                logger.info(f"Scheduled one-off job with AstrBot native scheduler: {job_id}")
                return
            except Exception as exc:
                logger.warning(
                    f"AstrBot native schedule_once failed, fallback to APScheduler: {exc}"
                )

        if not self._fallback_scheduler.running:
            self._fallback_scheduler.start()

        self._fallback_scheduler.add_job(
            func=callback,
            trigger=DateTrigger(run_date=run_date),
            args=args,
            id=job_id,
            replace_existing=True,
        )

    async def schedule_cron(
        self,
        job_id: str,
        cron_kwargs: Dict[str, Any],
        callback: Callable,
        args: Optional[Sequence[Any]] = None,
    ) -> None:
        args = list(args or [])
        trigger = CronTrigger(**cron_kwargs)
        native_scheduler = self._get_native_scheduler()

        if native_scheduler and hasattr(native_scheduler, "add_job"):
            try:
                await self._maybe_await(
                    native_scheduler.add_job(
                        func=callback,
                        trigger=trigger,
                        args=args,
                        id=job_id,
                        replace_existing=True,
                    )
                )
                logger.info(f"Scheduled cron job with AstrBot native scheduler: {job_id}")
                return
            except Exception as exc:
                logger.warning(
                    f"AstrBot native schedule_cron failed, fallback to APScheduler: {exc}"
                )

        if not self._fallback_scheduler.running:
            self._fallback_scheduler.start()

        self._fallback_scheduler.add_job(
            func=callback,
            trigger=trigger,
            args=args,
            id=job_id,
            replace_existing=True,
        )

    async def cancel(self, job_id: str) -> None:
        native_scheduler = self._get_native_scheduler()
        if native_scheduler and hasattr(native_scheduler, "remove_job"):
            try:
                await self._maybe_await(native_scheduler.remove_job(job_id))
                return
            except Exception:
                pass

        try:
            self._fallback_scheduler.remove_job(job_id)
        except Exception:
            pass

    async def send_reminder(self, session_origin: str, message: str) -> None:
        if not self.context:
            logger.warning("No AstrBot context available to send reminder")
            return

        sender = getattr(self.context, "send_message", None)
        if not callable(sender):
            logger.warning("AstrBot context has no send_message API")
            return

        await self._maybe_await(sender(session_origin, message))

    def requires_reload_on_start(self) -> bool:
        """原生调度器可用时不需要业务层重复加载。"""
        native_scheduler = self._get_native_scheduler()
        return native_scheduler is None

    def get_next_run_time(self, job_id: str) -> Optional[datetime]:
        native_scheduler = self._get_native_scheduler()
        if native_scheduler and hasattr(native_scheduler, "get_job"):
            try:
                job = native_scheduler.get_job(job_id)
                if job and getattr(job, "next_run_time", None):
                    return job.next_run_time
            except Exception:
                pass

        job = self._fallback_scheduler.get_job(job_id)
        if job and job.next_run_time:
            return job.next_run_time
        return None
