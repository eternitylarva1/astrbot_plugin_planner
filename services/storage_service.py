import json
import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api import logger


class StorageService:
    """JSON文件存储服务"""

    def __init__(self, plugin_name: str = "astrbot_plugin_planner"):
        self.plugin_name = plugin_name
        # 确保路径是 Path 对象，兼容字符串返回的情况（重载时可能出现）
        base_path = get_astrbot_data_path()
        if isinstance(base_path, str):
            base_path = Path(base_path)
        self.data_dir = base_path / "plugin_data" / plugin_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

        # 数据文件路径
        self.tasks_file = self.data_dir / "tasks.json"
        self.learning_file = self.data_dir / "learning.json"
        self.recurring_file = self.data_dir / "recurring.json"
        self.goals_file = self.data_dir / "goals.json"
        self.history_file = self.data_dir / "history.json"
        self.planning_events_file = self.data_dir / "planning_events.json"

        # 初始化文件
        self._init_files()

    def _init_files(self):
        """初始化数据文件"""
        for file_path in [
            self.tasks_file,
            self.learning_file,
            self.recurring_file,
            self.goals_file,
            self.history_file,
            self.planning_events_file,
        ]:
            if not file_path.exists():
                file_path.write_text(
                    "[]"
                    if "tasks" in str(file_path)
                    or "recurring" in str(file_path)
                    or "goals" in str(file_path)
                    or "history" in str(file_path)
                    or "events" in str(file_path)
                    else "{}"
                )

    async def read_json(self, file_path: Path) -> Any:
        """读取JSON文件"""
        async with self._lock:
            try:
                content = file_path.read_text(encoding="utf-8")
                if not content.strip():
                    return (
                        []
                        if "tasks" in str(file_path)
                        or "recurring" in str(file_path)
                        or "goals" in str(file_path)
                        or "history" in str(file_path)
                        or "events" in str(file_path)
                        else {}
                    )
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in {file_path}: {e}")
                return (
                    []
                    if "tasks" in str(file_path)
                    or "recurring" in str(file_path)
                    or "goals" in str(file_path)
                    or "history" in str(file_path)
                    or "events" in str(file_path)
                    else {}
                )
            except Exception as e:
                logger.error(f"Error reading {file_path}: {e}")
                return (
                    []
                    if "tasks" in str(file_path)
                    or "recurring" in str(file_path)
                    or "goals" in str(file_path)
                    or "history" in str(file_path)
                    or "events" in str(file_path)
                    else {}
                )

    async def write_json(self, file_path: Path, data: Any):
        """写入JSON文件"""
        async with self._lock:
            try:
                content = json.dumps(data, ensure_ascii=False, indent=2)
                file_path.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.error(f"Error writing {file_path}: {e}")
                raise

    # ========== 任务操作 ==========

    async def get_all_tasks(self) -> List[Dict]:
        """获取所有任务"""
        return await self.read_json(self.tasks_file)

    async def save_task(self, task_dict: Dict):
        """保存任务"""
        tasks = await self.get_all_tasks()
        # 检查是否存在
        task_id = task_dict.get("id")
        for i, t in enumerate(tasks):
            if t.get("id") == task_id:
                tasks[i] = task_dict
                break
        else:
            tasks.append(task_dict)
        await self.write_json(self.tasks_file, tasks)

    async def delete_task(self, task_id: str):
        """删除任务"""
        tasks = await self.get_all_tasks()
        tasks = [t for t in tasks if t.get("id") != task_id]
        await self.write_json(self.tasks_file, tasks)

    async def update_task_status(
        self, task_id: str, status: str, completed_at: Optional[str] = None
    ):
        """更新任务状态"""
        tasks = await self.get_all_tasks()
        for t in tasks:
            if t.get("id") == task_id:
                t["status"] = status
                if completed_at:
                    t["completed_at"] = completed_at
                break
        await self.write_json(self.tasks_file, tasks)

    # ========== 学习数据操作 ==========

    async def get_learning_data(self) -> Dict:
        """获取学习数据"""
        return await self.read_json(self.learning_file)

    async def save_learning_data(self, data: Dict):
        """保存学习数据"""
        await self.write_json(self.learning_file, data)

    # ========== 历史记录操作 ==========

    async def get_history(self) -> List[Dict]:
        """获取历史记录"""
        return await self.read_json(self.history_file)

    async def add_history(self, record: Dict):
        """添加历史记录"""
        history = await self.get_history()
        history.append(record)
        # 只保留最近100条
        if len(history) > 100:
            history = history[-100:]
        await self.write_json(self.history_file, history)

    # ========== 规划事件流 ==========

    async def get_planning_events(self) -> List[Dict]:
        """获取规划事件流"""
        return await self.read_json(self.planning_events_file)

    async def add_planning_event(self, event: Dict):
        """追加一条规划事件"""
        events = await self.get_planning_events()
        events.append(event)
        # 避免无限膨胀，保留最近 5000 条
        if len(events) > 5000:
            events = events[-5000:]
        await self.write_json(self.planning_events_file, events)

    # ========== 循环任务操作 ==========

    async def get_recurring_tasks(self) -> List[Dict]:
        """获取循环任务"""
        return await self.read_json(self.recurring_file)

    async def save_recurring_task(self, task_dict: Dict):
        """保存循环任务"""
        tasks = await self.get_recurring_tasks()
        task_id = task_dict.get("id")
        for i, t in enumerate(tasks):
            if t.get("id") == task_id:
                tasks[i] = task_dict
                break
        else:
            tasks.append(task_dict)
        await self.write_json(self.recurring_file, tasks)

    async def delete_recurring_task(self, task_id: str):
        """删除循环任务"""
        tasks = await self.get_recurring_tasks()
        tasks = [t for t in tasks if t.get("id") != task_id]
        await self.write_json(self.recurring_file, tasks)

    # ========== 目标状态操作 ==========

    async def get_goals(self) -> List[Dict]:
        """获取所有目标"""
        return await self.read_json(self.goals_file)

    async def save_goal(self, goal_dict: Dict):
        """保存目标"""
        goals = await self.get_goals()
        session_id = goal_dict.get("session_id")
        for i, g in enumerate(goals):
            if g.get("session_id") == session_id:
                goals[i] = goal_dict
                break
        else:
            goals.append(goal_dict)
        await self.write_json(self.goals_file, goals)

    async def delete_goal(self, session_id: str):
        """删除目标"""
        goals = await self.get_goals()
        goals = [g for g in goals if g.get("session_id") != session_id]
        await self.write_json(self.goals_file, goals)

    async def get_goal_by_session(self, session_id: str) -> Optional[Dict]:
        """根据会话ID获取目标"""
        goals = await self.get_goals()
        for g in goals:
            if g.get("session_id") == session_id:
                return g
        return None
