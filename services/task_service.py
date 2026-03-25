from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from ..models.task import Task
from .storage_service import StorageService
from astrbot.api import logger


def _safe_int(value: Any, default: int = 0) -> int:
    """安全转换为整数"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class TaskService:
    """任务管理服务"""

    def __init__(self, storage: StorageService):
        self.storage = storage

    async def create_task(self, task: Task) -> Task:
        """创建任务"""
        await self.storage.save_task(task.to_dict())
        logger.info(f"Task created: {task.name} at {task.start_time}")
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取单个任务"""
        tasks = await self.storage.get_all_tasks()
        for t in tasks:
            if t.get("id") == task_id:
                return Task.from_dict(t)
        return None

    async def get_tasks_by_date(self, target_date: date) -> List[Task]:
        """获取指定日期的所有任务"""
        tasks = await self.storage.get_all_tasks()
        result = []
        for t in tasks:
            if t.get("status") in ["pending", "done"]:
                task = Task.from_dict(t)
                if task.start_time and task.start_time.date() == target_date:
                    result.append(task)
        return sorted(result, key=lambda x: x.start_time or datetime.max)

    async def get_tasks_by_date_range(
        self, start_date: date, end_date: date
    ) -> List[Task]:
        """获取日期范围内的所有任务"""
        tasks = await self.storage.get_all_tasks()
        result = []
        for t in tasks:
            if t.get("status") in ["pending", "done"]:
                task = Task.from_dict(t)
                if task.start_time:
                    task_date = task.start_time.date()
                    if start_date <= task_date <= end_date:
                        result.append(task)
        return sorted(result, key=lambda x: x.start_time or datetime.max)

    async def get_pending_tasks(self) -> List[Task]:
        """获取所有待办任务"""
        tasks = await self.storage.get_all_tasks()
        result = []
        for t in tasks:
            if t.get("status") == "pending":
                result.append(Task.from_dict(t))
        return sorted(result, key=lambda x: x.start_time or datetime.max)

    async def complete_task(self, task_id: str) -> Optional[Task]:
        """完成任务"""
        task = await self.get_task(task_id)
        if not task:
            return None
        task.status = "done"
        task.completed_at = datetime.now()
        await self.storage.update_task_status(
            task_id, "done", task.completed_at.isoformat()
        )
        logger.info(f"Task completed: {task.name}")
        return task

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        """取消任务"""
        task = await self.get_task(task_id)
        if not task:
            return None
        task.status = "cancelled"
        await self.storage.update_task_status(task_id, "cancelled")
        logger.info(f"Task cancelled: {task.name}")
        return task

    async def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        await self.storage.delete_task(task_id)
        logger.info(f"Task deleted: {task_id}")
        return True

    async def update_task(
        self, task_id: str, updates: Dict[str, Any]
    ) -> Optional[Task]:
        """更新任务"""
        task = await self.get_task(task_id)
        if not task:
            return None
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self.storage.save_task(task.to_dict())
        return task

    async def get_next_available_slot(
        self,
        target_date: date,
        duration_minutes: int,
        start_hour: int = 9,
        end_hour: int = 22,
    ) -> datetime:
        """获取下一个可用时间段"""
        tasks = await self.get_tasks_by_date(target_date)

        # 如果没有任务，从start_hour开始
        if not tasks:
            return datetime(
                target_date.year, target_date.month, target_date.day, start_hour
            )

        # 检查从start_hour开始是否可用
        slot_start = datetime(
            target_date.year, target_date.month, target_date.day, start_hour
        )
        slot_end = slot_start + timedelta(minutes=_safe_int(duration_minutes))

        # 如果结束时间超过end_hour，往后推一天
        if slot_end.hour > end_hour:
            return datetime(
                target_date.year, target_date.month, target_date.day, start_hour
            )

        # 遍历所有任务，找空闲时间段
        for task in tasks:
            if task.start_time and task.status != "cancelled":
                task_end = task.get_end_time()
                # 如果当前时段在任务之前
                if slot_end <= task.start_time:
                    return slot_start
                # 如果当前时段与任务重叠，调整到任务结束后
                if slot_start < task_end:
                    slot_start = task_end
                    slot_end = slot_start + timedelta(
                        minutes=_safe_int(duration_minutes)
                    )
                    # 如果结束时间超过end_hour，往后推一天
                    if slot_end.hour > end_hour or slot_end.date() > target_date:
                        # 递归检查下一天
                        return await self.get_next_available_slot(
                            target_date + timedelta(days=1),
                            duration_minutes,
                            start_hour,
                            end_hour,
                        )

        return slot_start

    async def check_conflict(
        self,
        start_time: datetime,
        duration_minutes: int,
        exclude_task_id: Optional[str] = None,
    ) -> List[Task]:
        """检查时间冲突"""
        target_date = start_time.date()
        tasks = await self.get_tasks_by_date(target_date)
        conflicts = []

        new_start = start_time
        new_end = start_time + timedelta(minutes=_safe_int(duration_minutes))

        for task in tasks:
            if exclude_task_id and task.id == exclude_task_id:
                continue
            if task.start_time and task.status != "cancelled":
                task_end = task.get_end_time()
                if new_start < task_end and task.start_time < new_end:
                    conflicts.append(task)

        return conflicts

    async def get_free_hours(self, target_date: date) -> float:
        """获取指定日期的空闲小时数"""
        tasks = await self.get_tasks_by_date(target_date)
        busy_minutes = 0
        for task in tasks:
            if task.status == "pending":
                busy_minutes += _safe_int(task.duration_minutes)
        # 假设9:00-22:00是可用时间，共13小时
        total_minutes = 780
        return max(0, float(total_minutes - busy_minutes) / 60.0)

    async def get_completion_stats(self, target_date: date) -> Dict[str, int]:
        """获取完成统计"""
        tasks = await self.get_tasks_by_date(target_date)
        total = len([t for t in tasks if t.status != "cancelled"])
        completed = len([t for t in tasks if t.status == "done"])
        return {
            "total": total,
            "completed": completed,
            "pending": total - completed,
            "rate": int(float(completed) / float(total) * 100) if total > 0 else 0,
        }
