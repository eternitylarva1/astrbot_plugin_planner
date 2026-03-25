from typing import Optional, List, Dict, Any
from ..models.task import LearningData, DurationStats
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class LearningService:
    """学习服务 - 从用户行为中学习偏好"""

    def __init__(self, storage: StorageService):
        self.storage = storage
        self._data: Optional[LearningData] = None

    async def _ensure_data(self) -> LearningData:
        """确保学习数据已加载"""
        if self._data is None:
            data_dict = await self.storage.get_learning_data()
            if data_dict:
                self._data = LearningData.from_dict(data_dict)
            else:
                self._data = LearningData()
        return self._data

    async def _save_data(self):
        """保存学习数据"""
        if self._data:
            await self.storage.save_learning_data(self._data.to_dict())

    async def record_duration(self, task_name: str, duration_minutes: int):
        """记录任务实际完成时长"""
        data = await self._ensure_data()
        normalized_name = task_name.strip()
        duration = _safe_int(duration_minutes)

        if normalized_name in data.task_durations:
            stats = data.task_durations[normalized_name]
            samples = [_safe_int(s) for s in stats.actual_samples]
            samples.append(duration)
            stats.actual_samples = samples
            if samples:
                stats.actual_avg = sum(samples) / len(samples)
            else:
                stats.actual_avg = float(duration)
            stats.count = _safe_int(stats.count) + 1
            logger.info(
                f"Updated duration stats for '{normalized_name}': avg={stats.actual_avg:.0f}min"
            )
        else:
            data.task_durations[normalized_name] = DurationStats(
                default_minutes=duration,
                actual_samples=[duration],
                actual_avg=float(duration),
                count=1,
            )
            logger.info(f"Created new duration stats for '{normalized_name}'")

        await self._save_data()

    async def record_user_specified_duration(
        self, task_name: str, duration_minutes: int
    ):
        """记录用户指定的任务时长"""
        data = await self._ensure_data()
        normalized_name = task_name.strip()
        duration = _safe_int(duration_minutes)

        if normalized_name in data.task_durations:
            stats = data.task_durations[normalized_name]
            stats.default_minutes = duration
            if stats.actual_avg == 0:
                stats.actual_avg = float(duration)
        else:
            data.task_durations[normalized_name] = DurationStats(
                default_minutes=duration,
                actual_samples=[],
                actual_avg=float(duration),
                count=0,
            )

        await self._save_data()
        logger.info(
            f"Recorded specified duration for '{normalized_name}': {duration}min"
        )

    async def get_default_duration(self, task_name: str) -> Optional[int]:
        """获取任务默认时长"""
        data = await self._ensure_data()
        normalized_name = task_name.strip()

        if normalized_name in data.task_durations:
            stats = data.task_durations[normalized_name]
            actual = _safe_float(stats.actual_avg)
            default = _safe_int(stats.default_minutes)
            return int(actual if actual > 0 else default)

        for alias, canonical in data.task_aliases.items():
            if alias == normalized_name and canonical in data.task_durations:
                stats = data.task_durations[canonical]
                actual = _safe_float(stats.actual_avg)
                default = _safe_int(stats.default_minutes)
                return int(actual if actual > 0 else default)

        for known_name, stats in data.task_durations.items():
            if known_name in normalized_name or normalized_name in known_name:
                actual = _safe_float(stats.actual_avg)
                default = _safe_int(stats.default_minutes)
                return int(actual if actual > 0 else default)

        for alias in data.task_aliases.keys():
            if alias in normalized_name:
                canonical = data.task_aliases[alias]
                if canonical in data.task_durations:
                    stats = data.task_durations[canonical]
                    actual = _safe_float(stats.actual_avg)
                    default = _safe_int(stats.default_minutes)
                    return int(actual if actual > 0 else default)

        return None

    async def learn_alias(self, alias: str, canonical: str):
        """学习任务别名"""
        data = await self._ensure_data()
        data.task_aliases[alias.strip()] = canonical.strip()
        await self._save_data()
        logger.info(f"Learned alias: '{alias}' -> '{canonical}'")

    async def record_time_pattern(self, task_name: str, time_slot: str):
        """记录时间段偏好"""
        data = await self._ensure_data()
        complex_keywords = ["写代码", "写报告", "写文档", "项目", "学习", "复习"]
        is_complex = any(k in task_name for k in complex_keywords)
        pattern_key = "complex" if is_complex else "simple"

        if pattern_key not in data.time_patterns:
            data.time_patterns[pattern_key] = []
        if time_slot not in data.time_patterns[pattern_key]:
            data.time_patterns[pattern_key].append(time_slot)

        await self._save_data()
        logger.info(f"Learned time pattern: {pattern_key} tasks prefer {time_slot}")

    async def get_time_preference(self) -> Dict[str, List[str]]:
        """获取时间段偏好"""
        data = await self._ensure_data()
        return data.time_patterns

    async def record_remind_preference(self, task_name: Optional[str], minutes: int):
        """记录提醒偏好"""
        data = await self._ensure_data()
        if task_name:
            data.remind_preferences[task_name] = _safe_int(minutes)
        else:
            data.remind_preferences["default"] = _safe_int(minutes)
        await self._save_data()

    async def get_remind_preference(self, task_name: Optional[str] = None) -> int:
        """获取提醒提前时间"""
        data = await self._ensure_data()
        if task_name and task_name in data.remind_preferences:
            return _safe_int(data.remind_preferences[task_name])
        return _safe_int(data.remind_preferences.get("default", 10))

    async def get_all_learned_durations(self) -> Dict[str, Dict]:
        """获取所有学习到的时长统计"""
        data = await self._ensure_data()
        result = {}
        for name, stats in data.task_durations.items():
            result[name] = {
                "default": _safe_int(stats.default_minutes),
                "actual_avg": round(_safe_float(stats.actual_avg))
                if _safe_float(stats.actual_avg) > 0
                else _safe_int(stats.default_minutes),
                "samples": list(stats.actual_samples)[-5:]
                if stats.actual_samples
                else [],
                "count": _safe_int(stats.count),
            }
        return result

    async def get_all_aliases(self) -> Dict[str, str]:
        """获取所有别名映射"""
        data = await self._ensure_data()
        return data.task_aliases.copy()

    async def generate_system_prompt(self) -> str:
        """生成系统提示词片段"""
        data = await self._ensure_data()
        parts = []

        if data.task_durations:
            parts.append("用户任务时长偏好：")
            for name, stats in list(data.task_durations.items())[:10]:
                avg = (
                    round(_safe_float(stats.actual_avg))
                    if _safe_float(stats.actual_avg) > 0
                    else _safe_int(stats.default_minutes)
                )
                parts.append(f"- {name}: 通常需要{avg}分钟")

        if data.task_aliases:
            parts.append("\n任务别名：")
            for alias, canonical in list(data.task_aliases.items())[:10]:
                parts.append(f'- "{alias}" 就是 "{canonical}"')

        if data.time_patterns:
            parts.append("\n时间段偏好：")
            if "complex" in data.time_patterns:
                parts.append(
                    f"- 复杂任务偏好: {', '.join(data.time_patterns['complex'])}"
                )
            if "simple" in data.time_patterns:
                parts.append(
                    f"- 简单任务偏好: {', '.join(data.time_patterns['simple'])}"
                )

        return "\n".join(parts) if parts else ""
