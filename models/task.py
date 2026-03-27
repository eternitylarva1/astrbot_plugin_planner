from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List
import uuid
import json


@dataclass
class Task:
    """任务模型"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""  # 任务名称
    start_time: Optional[datetime] = None  # 开始时间
    duration_minutes: int = 60  # 持续时长（分钟）
    status: str = "pending"  # pending/done/cancelled
    remind_before: int = 10  # 提前提醒分钟数
    repeat: Optional[str] = None  # null/daily/weekly/monthly/workdays
    repeat_end: Optional[datetime] = None  # 循环结束日期
    is_part_of_goal: Optional[str] = None  # 所属目标ID
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    session_origin: str = ""  # 创建时所属会话

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        if self.completed_at:
            d["completed_at"] = self.completed_at.isoformat()
        if self.repeat_end:
            d["repeat_end"] = self.repeat_end.isoformat()
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        if d.get("start_time"):
            d["start_time"] = datetime.fromisoformat(d["start_time"])
        if d.get("completed_at"):
            d["completed_at"] = datetime.fromisoformat(d["completed_at"])
        if d.get("repeat_end"):
            d["repeat_end"] = datetime.fromisoformat(d["repeat_end"])
        if d.get("created_at"):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        # 确保数值类型正确
        if d.get("duration_minutes"):
            d["duration_minutes"] = int(d["duration_minutes"])
        if d.get("remind_before"):
            d["remind_before"] = int(d["remind_before"])
        return cls(**d)

    def get_end_time(self) -> Optional[datetime]:
        """获取结束时间"""
        if self.start_time:
            from datetime import timedelta

            return self.start_time + timedelta(minutes=self.duration_minutes)
        return None

    def is_time_conflict(self, other: "Task") -> bool:
        """检测时间冲突"""
        if not self.start_time or not other.start_time:
            return False
        self_end = self.get_end_time()
        other_end = other.get_end_time()
        if not self_end or not other_end:
            return False
        return self.start_time < other_end and other.start_time < self_end


@dataclass
class DurationStats:
    """时长统计"""

    default_minutes: int = 60  # 用户指定的默认时长
    actual_samples: List[int] = field(default_factory=list)  # 实际完成时长样本
    actual_avg: float = 0.0  # 实际平均时长
    count: int = 0  # 样本数量

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DurationStats":
        # 确保类型正确
        if "actual_samples" in d and d["actual_samples"]:
            d["actual_samples"] = [
                int(x) if not isinstance(x, int) else x for x in d["actual_samples"]
            ]
        else:
            d["actual_samples"] = []
        if "actual_avg" in d:
            d["actual_avg"] = float(d["actual_avg"]) if d["actual_avg"] else 0.0
        else:
            d["actual_avg"] = 0.0
        if "default_minutes" in d:
            d["default_minutes"] = int(d["default_minutes"])
        else:
            d["default_minutes"] = 60
        if "count" in d:
            d["count"] = int(d["count"])
        else:
            d["count"] = 0
        return cls(**d)


@dataclass
class LearningData:
    """学习数据"""

    task_durations: dict = field(default_factory=dict)
    task_aliases: dict = field(default_factory=dict)
    time_patterns: dict = field(default_factory=dict)
    remind_preferences: dict = field(default_factory=dict)
    feedback_rules: dict = field(default_factory=dict)
    feedback_history: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "task_durations": {},
            "task_aliases": self.task_aliases,
            "time_patterns": self.time_patterns,
            "remind_preferences": self.remind_preferences,
            "feedback_rules": self.feedback_rules,
            "feedback_history": self.feedback_history,
        }
        for k, v in self.task_durations.items():
            if hasattr(v, "to_dict"):
                d["task_durations"][k] = v.to_dict()
            else:
                d["task_durations"][k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "LearningData":
        durations = {}
        for k, v in d.get("task_durations", {}).items():
            if isinstance(v, dict):
                durations[k] = DurationStats.from_dict(v)
            else:
                durations[k] = v
        return cls(
            task_durations=durations,
            task_aliases=d.get("task_aliases", {}),
            time_patterns=d.get("time_patterns", {}),
            remind_preferences=d.get("remind_preferences", {}),
            feedback_rules=d.get("feedback_rules", {}),
            feedback_history=d.get("feedback_history", []),
        )


@dataclass
class GoalTask:
    """目标中的子任务建议"""

    name: str
    estimated_minutes: int
    suggested_time: Optional[str] = None


@dataclass
class GoalState:
    """目标拆解状态"""

    session_id: str
    user_id: str
    goal: str
    parsed_tasks: List = field(default_factory=list)
    suggested_schedule: dict = field(default_factory=dict)
    status: str = "awaiting_goal"
    conversation_history: List = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GoalState":
        d["parsed_tasks"] = [
            GoalTask(**t) if isinstance(t, dict) else t
            for t in d.get("parsed_tasks", [])
        ]
        return cls(**d)
