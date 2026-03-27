from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
from ..models.task import Task
from .storage_service import StorageService
from .task_service import TaskService
from .astrbot_scheduler_adapter import SchedulerAdapter
from astrbot.api import logger


class ReminderService:
    """定时提醒服务"""

    def __init__(
        self,
        storage: StorageService,
        task_service: TaskService,
        scheduler_adapter: SchedulerAdapter,
    ):
        self.storage = storage
        self.task_service = task_service
        self.scheduler_adapter = scheduler_adapter
        self._reminder_callbacks: Dict[
            str, Callable
        ] = {}  # task_id -> callback function
        self._started = False

    async def start(self):
        """启动调度器（幂等）。"""
        if self._started:
            return

        await self.scheduler_adapter.start()
        logger.info("Reminder scheduler started")

        # 仅在 fallback 调度器场景由业务层重载任务；
        # 原生调度器可持久化时避免重复装载。
        if self.scheduler_adapter.requires_reload_on_start():
            await self._reload_reminders()

        self._started = True

    async def stop(self):
        """停止调度器"""
        if not self._started:
            return

        await self.scheduler_adapter.stop()
        logger.info("Reminder scheduler stopped")
        self._started = False

    async def _reload_reminders(self):
        """重新加载所有待提醒任务"""
        tasks = await self.task_service.get_pending_tasks()
        for task in tasks:
            if task.start_time:
                await self.schedule_reminder(task)

    async def schedule_reminder(self, task: Task, callback: Optional[Callable] = None):
        """为任务创建定时提醒"""
        if not task.start_time:
            return

        remind_time = task.start_time - timedelta(minutes=task.remind_before)

        # 如果提醒时间已过，跳过
        if remind_time <= datetime.now():
            # 如果任务还没开始，仍然发送一个立即提醒
            if task.start_time > datetime.now():
                remind_time = datetime.now() + timedelta(seconds=5)
            else:
                return

        job_id = f"reminder_{task.id}"

        # 先取消同 ID 任务，确保在原生调度器下也不会重复注册
        await self.scheduler_adapter.cancel(job_id)

        await self.scheduler_adapter.schedule_once(
            job_id=job_id,
            run_date=remind_time,
            callback=self._send_reminder,
            args=[task.id],
        )

        if callback:
            self._reminder_callbacks[task.id] = callback

        logger.info(f"Scheduled reminder for task {task.name} at {remind_time}")

    async def _send_reminder(self, task_id: str):
        """发送提醒消息"""
        try:
            task = await self.task_service.get_task(task_id)
            if not task:
                logger.warning(f"Task not found for reminder: {task_id}")
                return

            if task.status != "pending":
                logger.info(f"Task {task.name} is no longer pending, skipping reminder")
                return

            # 构建提醒消息
            message = self._build_reminder_message(task)

            # 通过callback发送消息
            if task_id in self._reminder_callbacks:
                await self._reminder_callbacks[task_id](message)
            elif task.session_origin:
                await self.scheduler_adapter.send_reminder(task.session_origin, message)

            logger.info(f"Reminder sent for task: {task.name}")

        except Exception as e:
            logger.error(f"Error sending reminder for task {task_id}: {e}")

    def _build_reminder_message(self, task: Task) -> str:
        """构建提醒消息"""
        start_str = task.start_time.strftime("%H:%M") if task.start_time else "未知"
        duration_str = f"{task.duration_minutes}分钟"
        emoji = self._get_task_emoji(task.name)

        message = f"""🔔 提醒
━━━━━━━━━━━━━━━
{emoji} {task.name}
⏰ {start_str} - {duration_str}

💡 距离开始还有 {task.remind_before} 分钟"""

        return message

    def _get_task_emoji(self, task_name: str) -> str:
        """根据任务名获取emoji"""
        keywords = {
            "开会": "💼",
            "报告": "📝",
            "代码": "👨‍💻",
            "写代码": "👨‍💻",
            "学习": "📚",
            "运动": "🏃",
            "吃饭": "🍽️",
            "睡觉": "🛌",
            "休息": "☕",
            "阅读": "📖",
            "写作": "✍️",
            "项目": "📁",
            "复习": "📖",
            "考试": "📋",
            "面试": "🎯",
            "电话": "📞",
        }
        for keyword, emoji in keywords.items():
            if keyword in task_name:
                return emoji
        return "📌"

    async def cancel_reminder(self, task_id: str):
        """取消任务提醒"""
        job_id = f"reminder_{task_id}"
        await self.scheduler_adapter.cancel(job_id)

        if task_id in self._reminder_callbacks:
            del self._reminder_callbacks[task_id]

    async def update_reminder(self, task: Task):
        """更新任务提醒"""
        await self.cancel_reminder(task.id)
        if task.status == "pending":
            await self.schedule_reminder(task)

    async def schedule_recurring_reminder(
        self, recurring_task_id: str, time_str: str, message: str, repeat_pattern: str
    ):
        """为循环任务创建定时提醒

        Args:
            recurring_task_id: 循环任务ID
            time_str: 时间字符串，格式 "HH:MM"
            message: 提醒消息
            repeat_pattern: 重复模式 "daily", "weekly", "monthly", "workdays"
        """
        hour, minute = map(int, time_str.split(":"))

        cron_kwargs = {"hour": hour, "minute": minute}
        if repeat_pattern == "weekly":
            cron_kwargs["day_of_week"] = "mon-fri"
        elif repeat_pattern == "workdays":
            cron_kwargs["day_of_week"] = "mon-fri"
        elif repeat_pattern == "monthly":
            cron_kwargs["day"] = "1-28"

        job_id = f"recurring_{recurring_task_id}"

        # 先取消同 ID 任务，确保重复调用时保持幂等
        await self.scheduler_adapter.cancel(job_id)

        await self.scheduler_adapter.schedule_cron(
            job_id=job_id,
            cron_kwargs=cron_kwargs,
            callback=self._send_recurring_reminder,
            args=[recurring_task_id, message],
        )

        logger.info(f"Scheduled recurring reminder {recurring_task_id} at {time_str}")

    async def _send_recurring_reminder(self, recurring_task_id: str, message: str):
        """发送循环任务提醒"""
        try:
            logger.info(f"Recurring reminder sent: {message}")
        except Exception as e:
            logger.error(f"Error sending recurring reminder: {e}")

    def get_next_reminder_time(self, task_id: str) -> Optional[datetime]:
        """获取任务下一次提醒时间"""
        job_id = f"reminder_{task_id}"
        getter = getattr(self.scheduler_adapter, "get_next_run_time", None)
        if callable(getter):
            return getter(job_id)
        return None
