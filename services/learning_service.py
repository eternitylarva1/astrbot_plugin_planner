from typing import Optional, List, Dict, Any
from datetime import datetime
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
        self._AUTO_LEARNING_KEY = "__auto_learning__"

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

    @staticmethod
    def _summarize_data(data: LearningData) -> Dict[str, int]:
        """汇总学习数据规模，用于删除前后对比"""
        duration_count = len(data.task_durations)
        alias_count = len(data.task_aliases)
        complex_slots = len(data.time_patterns.get("complex", []))
        simple_slots = len(data.time_patterns.get("simple", []))
        return {
            "durations": duration_count,
            "aliases": alias_count,
            "time_complex": complex_slots,
            "time_simple": simple_slots,
            "time_total": complex_slots + simple_slots,
        }

    async def append_event(self, event: Dict[str, Any]):
        """追加行为事件到事件流"""
        event_type = str(event.get("type", "")).strip()
        if not event_type:
            return
        payload = dict(event.get("payload", {}) or {})
        record = {
            "timestamp": event.get("timestamp") or datetime.now().isoformat(),
            "type": event_type,
            "payload": payload,
        }
        await self.storage.add_planning_event(record)

    async def rebuild_profile_from_events(self, apply_delete_events: bool = False) -> Dict[str, int]:
        """从事件流重建学习画像

        默认忽略删除类事件，用于误删后的恢复。
        """
        events = await self.storage.get_planning_events()
        current = await self._ensure_data()
        auto_flag = 1 if self._is_auto_learning_enabled_from_data(current) else 0

        rebuilt = LearningData()
        rebuilt.remind_preferences[self._AUTO_LEARNING_KEY] = auto_flag
        self._data = rebuilt

        replayed = 0
        for e in events:
            event_type = str(e.get("type", "")).strip()
            payload = dict(e.get("payload", {}) or {})
            task_name = str(payload.get("task_name", "")).strip()

            if event_type == "task_created":
                duration = _safe_int(payload.get("duration_minutes"), 0)
                slot = payload.get("time_slot")
                if task_name and duration > 0:
                    await self.record_task_creation_pattern(task_name, slot, duration)
                    replayed += 1
            elif event_type == "task_completed":
                actual = _safe_int(payload.get("actual_duration_minutes"), 0)
                if task_name and actual > 0:
                    await self.record_duration(task_name, actual)
                    replayed += 1
            elif event_type == "task_rescheduled":
                slot = payload.get("new_time_slot")
                if task_name and slot:
                    await self.record_time_pattern(task_name, str(slot))
                    replayed += 1
            elif event_type == "habit_deleted":
                if apply_delete_events:
                    await self.delete_habit(
                        str(payload.get("habit_key", "")).strip(),
                        str(payload.get("delete_type", "all")).strip() or "all",
                        record_event=False,
                    )
                    replayed += 1

        await self._save_data()
        return {"events_total": len(events), "events_replayed": replayed}

    def _is_auto_learning_enabled_from_data(self, data: LearningData) -> bool:
        """从学习数据中读取自动学习开关（默认开启）"""
        raw = data.remind_preferences.get(self._AUTO_LEARNING_KEY, 1)
        return _safe_int(raw, 1) == 1

    async def is_auto_learning_enabled(self) -> bool:
        """自动学习是否开启"""
        data = await self._ensure_data()
        return self._is_auto_learning_enabled_from_data(data)

    async def set_auto_learning_enabled(self, enabled: bool):
        """设置自动学习开关"""
        data = await self._ensure_data()
        data.remind_preferences[self._AUTO_LEARNING_KEY] = 1 if enabled else 0
        await self._save_data()

    async def record_duration(self, task_name: str, duration_minutes: int):
        """记录任务实际完成时长"""
        data = await self._ensure_data()
        if not self._is_auto_learning_enabled_from_data(data):
            return
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
        if not self._is_auto_learning_enabled_from_data(data):
            return
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
        if not self._is_auto_learning_enabled_from_data(data):
            return
        complex_keywords = ["写代码", "写报告", "写文档", "项目", "学习", "复习"]
        is_complex = any(k in task_name for k in complex_keywords)
        pattern_key = "complex" if is_complex else "simple"

        if pattern_key not in data.time_patterns:
            data.time_patterns[pattern_key] = []
        if time_slot not in data.time_patterns[pattern_key]:
            data.time_patterns[pattern_key].append(time_slot)

        await self._save_data()
        logger.info(f"Learned time pattern: {pattern_key} tasks prefer {time_slot}")

    async def record_task_creation_pattern(
        self, task_name: str, time_slot: Optional[str], duration_minutes: int
    ):
        """在任务创建时自动学习用户习惯（时长 + 时间段 + 别名）"""
        data = await self._ensure_data()
        if not self._is_auto_learning_enabled_from_data(data):
            return

        clean_name = task_name.strip()
        await self.record_user_specified_duration(clean_name, duration_minutes)
        if time_slot:
            await self.record_time_pattern(clean_name, time_slot)

        # 自动学习别名：将长句简化到短词，避免同义任务分散
        canonical = clean_name
        alias = clean_name
        for sep in ["，", "。", "；", ";", "并且", "然后", "再", "接着"]:
            if sep in canonical:
                canonical = canonical.split(sep)[0].strip()
        for prefix in ["安排", "计划", "准备", "需要", "想要", "想", "我要"]:
            if canonical.startswith(prefix):
                canonical = canonical[len(prefix) :].strip()
        if canonical and alias and canonical != alias and len(canonical) >= 2:
            await self.learn_alias(alias, canonical)

    async def suggest_duration_minutes(
        self, task_name: str, fallback_minutes: int = 45
    ) -> int:
        """给任务推荐时长"""
        learned = await self.get_default_duration(task_name)
        if learned:
            return learned

        complex_keywords = ["项目", "复习", "学习", "写代码", "写文档", "训练", "整理"]
        if any(k in task_name for k in complex_keywords):
            return 90
        return _safe_int(fallback_minutes, 45)

    async def suggest_time_slot(self, task_name: str) -> str:
        """给任务推荐时间段（如 morning/afternoon/evening）"""
        text = task_name.lower()
        if any(k in text for k in ["早上", "上午", "晨"]):
            return "morning"
        if any(k in text for k in ["下午", "午后"]):
            return "afternoon"
        if any(k in text for k in ["晚上", "夜", "晚"]):
            return "evening"

        patterns = await self.get_time_preference()
        complex_keywords = ["项目", "复习", "学习", "写代码", "写文档", "训练", "整理"]
        key = "complex" if any(k in task_name for k in complex_keywords) else "simple"
        preferred = patterns.get(key) or []
        if preferred:
            slot = preferred[0]
            if slot in {"morning", "afternoon", "evening"}:
                return slot
        return "evening" if key == "complex" else "morning"

    @staticmethod
    def _is_complex_task(task_name: str) -> bool:
        complex_keywords = ["项目", "复习", "学习", "写代码", "写文档", "训练", "整理", "深度"]
        return any(k in task_name for k in complex_keywords)

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

    async def ensure_default_remind_preference(self, default_minutes: int) -> int:
        """确保存在全局默认提醒值；若缺失则写入。"""
        data = await self._ensure_data()
        if "default" not in data.remind_preferences:
            data.remind_preferences["default"] = _safe_int(default_minutes, 10)
            await self._save_data()
        return _safe_int(
            data.remind_preferences.get("default"), _safe_int(default_minutes, 10)
        )

    async def get_remind_preference(
        self,
        task_name: Optional[str] = None,
        fallback_minutes: int = 10,
    ) -> int:
        """获取提醒提前时间"""
        data = await self._ensure_data()
        if task_name and task_name in data.remind_preferences:
            return _safe_int(data.remind_preferences[task_name])
        return _safe_int(data.remind_preferences.get("default"), fallback_minutes)

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

    async def delete_duration_pattern(self, task_name: str) -> Dict[str, Any]:
        """删除单个任务时长习惯。"""
        data = await self._ensure_data()
        key = task_name.strip()
        before = self._summarize_data(data)
        removed = key in data.task_durations
        removed_payload = data.task_durations.pop(key, None)
        await self._save_data()
        after = self._summarize_data(data)
        if removed:
            await self.append_event(
                {
                    "type": "habit_deleted",
                    "payload": {
                        "habit_key": key,
                        "delete_type": "duration",
                        "removed_duration": 1,
                        "removed_alias": 0,
                    },
                }
            )
        return {
            "removed": removed,
            "key": key,
            "removed_payload": removed_payload.to_dict()
            if hasattr(removed_payload, "to_dict")
            else removed_payload,
            "before": before,
            "after": after,
        }

    async def delete_alias(self, alias: str) -> Dict[str, Any]:
        """删除单个任务别名习惯。"""
        data = await self._ensure_data()
        key = alias.strip()
        before = self._summarize_data(data)
        removed = key in data.task_aliases
        removed_payload = data.task_aliases.pop(key, None)
        await self._save_data()
        after = self._summarize_data(data)
        if removed:
            await self.append_event(
                {
                    "type": "habit_deleted",
                    "payload": {
                        "habit_key": key,
                        "delete_type": "alias",
                        "removed_duration": 0,
                        "removed_alias": 1,
                    },
                }
            )
        return {
            "removed": removed,
            "key": key,
            "removed_payload": removed_payload,
            "before": before,
            "after": after,
        }

    async def delete_time_pattern(self, key_or_task: str) -> Dict[str, Any]:
        """删除时间段偏好（complex/simple/任务名推断）。"""
        data = await self._ensure_data()
        raw = key_or_task.strip()
        normalized = raw.lower()
        if normalized in {"complex", "simple"}:
            target_key = normalized
        else:
            complex_keywords = ["写代码", "写报告", "写文档", "项目", "学习", "复习"]
            target_key = "complex" if any(k in raw for k in complex_keywords) else "simple"

        before = self._summarize_data(data)
        removed_payload = list(data.time_patterns.get(target_key, []))
        removed = target_key in data.time_patterns and len(removed_payload) > 0
        data.time_patterns.pop(target_key, None)
        await self._save_data()
        after = self._summarize_data(data)
        if removed:
            await self.append_event(
                {
                    "type": "habit_deleted",
                    "payload": {
                        "habit_key": raw,
                        "delete_type": "time",
                        "time_key": target_key,
                        "removed_duration": 0,
                        "removed_alias": 0,
                    },
                }
            )
        return {
            "removed": removed,
            "key": target_key,
            "source": raw,
            "removed_payload": removed_payload,
            "before": before,
            "after": after,
        }

    async def reset_learning_data(self, scope: str = "all") -> Dict[str, Any]:
        """重置学习数据。默认清空全部学习数据。"""
        data = await self._ensure_data()
        scope_key = (scope or "all").strip().lower()
        before = self._summarize_data(data)

        if scope_key == "durations":
            data.task_durations = {}
        elif scope_key == "aliases":
            data.task_aliases = {}
        elif scope_key in {"time", "time_patterns"}:
            data.time_patterns = {}
        else:
            auto_flag = data.remind_preferences.get(self._AUTO_LEARNING_KEY)
            data.task_durations = {}
            data.task_aliases = {}
            data.time_patterns = {}
            data.remind_preferences = {}
            if auto_flag is not None:
                data.remind_preferences[self._AUTO_LEARNING_KEY] = auto_flag
            scope_key = "all"

        await self._save_data()
        after = self._summarize_data(data)
        return {"scope": scope_key, "before": before, "after": after}

    async def estimate_learning_confidence(self, task_name: str) -> float:
        """估算该任务的学习置信度（0~1）"""
        data = await self._ensure_data()
        normalized_name = task_name.strip()
        confidence = 0.0

        stats = data.task_durations.get(normalized_name)
        if stats:
            confidence += min(_safe_int(getattr(stats, "count", 0), 0) / 5.0, 1.0) * 0.6
        elif data.task_durations:
            # 没有精确命中时，仅给予很小的全局置信度
            confidence += 0.15

        key = "complex" if self._is_complex_task(task_name) else "simple"
        patterns = data.time_patterns.get(key) or []
        if patterns:
            confidence += 0.25

        feedback_rules = data.feedback_rules or {}
        if feedback_rules.get("prefer_complex_slot") and key == "complex":
            confidence += 0.15

        return max(0.0, min(1.0, confidence))

    async def _slot_adjustments_from_feedback(self, task_name: str) -> Dict[str, float]:
        """把反馈规则转为时间段加权分。"""
        data = await self._ensure_data()
        rules = data.feedback_rules or {}
        scores: Dict[str, float] = {"morning": 0.0, "afternoon": 0.0, "evening": 0.0}
        key = "complex" if self._is_complex_task(task_name) else "simple"
        text = task_name.strip()

        prefer_complex_slot = rules.get("prefer_complex_slot")
        if prefer_complex_slot and key == "complex" and prefer_complex_slot in scores:
            scores[prefer_complex_slot] += 0.8

        avoid_by_keyword = rules.get("avoid_slot_by_keyword") or {}
        for keyword, slot in avoid_by_keyword.items():
            if keyword in text and slot in scores:
                scores[slot] -= 1.0

        return scores

    async def score_slot(
        self,
        task_name: str,
        slot: str,
        habit_weight: float = 0.7,
        habit_enabled: bool = True,
        confidence_threshold: float = 0.35,
    ) -> float:
        """给时间段打分，供规划器选择。"""
        if slot not in {"morning", "afternoon", "evening"}:
            return -999.0

        if not habit_enabled:
            return 0.0 if slot == "afternoon" else -0.05

        confidence = await self.estimate_learning_confidence(task_name)
        if confidence < confidence_threshold:
            return 0.0 if slot == "afternoon" else -0.05

        learned = await self.suggest_time_slot(task_name)
        learned_score = 1.0 if slot == learned else 0.0
        feedback_scores = await self._slot_adjustments_from_feedback(task_name)
        feedback_score = feedback_scores.get(slot, 0.0)
        data = await self._ensure_data()
        negative_bias = _safe_float(
            (data.feedback_rules or {}).get("negative_feedback_bias", 0.0)
        )
        effective_habit_weight = max(0.0, min(1.0, habit_weight * (1 - negative_bias)))
        return (
            effective_habit_weight * learned_score
            + (1 - effective_habit_weight) * 0.1
            + feedback_score
        )

    async def record_planning_feedback(self, feedback_text: str) -> Dict[str, Any]:
        """记录用户对计划建议的反馈并更新规则。"""
        data = await self._ensure_data()
        text = (feedback_text or "").strip()
        if not text:
            return {"ok": False, "message": "反馈内容为空"}

        rules = data.feedback_rules or {}
        feedback_history = list(data.feedback_history or [])
        feedback_history.append(text)
        data.feedback_history = feedback_history[-50:]

        updates: List[str] = []

        if "晚上" in text and any(k in text for k in ["深度", "复杂", "专注", "高强度"]):
            rules["prefer_complex_slot"] = "evening"
            updates.append("复杂任务优先安排在晚上")
        elif "早上" in text and any(k in text for k in ["不要", "别", "不想"]):
            slot = "morning"
            keyword = "学习" if "学习" in text else ("复习" if "复习" in text else "任务")
            avoid_by_keyword = rules.get("avoid_slot_by_keyword") or {}
            avoid_by_keyword[keyword] = slot
            rules["avoid_slot_by_keyword"] = avoid_by_keyword
            updates.append(f"避免在早上安排「{keyword}」")
        elif "不准" in text or "不准确" in text:
            old_bias = _safe_float(rules.get("negative_feedback_bias", 0.0))
            rules["negative_feedback_bias"] = max(0.0, min(1.0, old_bias + 0.2))
            updates.append("降低习惯推断强度（减少强干预）")
        else:
            notes = list(rules.get("free_text_notes") or [])
            notes.append(text)
            rules["free_text_notes"] = notes[-20:]
            updates.append("已记录为偏好备注")

        data.feedback_rules = rules
        await self._save_data()

        return {"ok": True, "message": "；".join(updates), "updates": updates}

    async def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近行为事件"""
        events = await self.storage.get_planning_events()
        safe_limit = max(1, min(_safe_int(limit, 10), 50))
        return list(events)[-safe_limit:]

    async def delete_habit(
        self, habit_key: str, delete_type: str = "all", record_event: bool = True
    ) -> Dict[str, int]:
        """删除习惯数据（时长/别名/全部）"""
        data = await self._ensure_data()
        key = habit_key.strip()
        mode = (delete_type or "all").strip().lower()
        removed_duration = 0
        removed_alias = 0
        if not key:
            return {"removed_duration": 0, "removed_alias": 0}

        if mode in {"all", "duration"} and key in data.task_durations:
            del data.task_durations[key]
            removed_duration = 1

        if mode in {"all", "alias"}:
            if key in data.task_aliases:
                del data.task_aliases[key]
                removed_alias = 1
            else:
                matched = [a for a, c in data.task_aliases.items() if c == key]
                for a in matched:
                    del data.task_aliases[a]
                    removed_alias += 1

        await self._save_data()

        if record_event and (removed_duration > 0 or removed_alias > 0):
            await self.append_event(
                {
                    "type": "habit_deleted",
                    "payload": {
                        "habit_key": key,
                        "delete_type": mode,
                        "removed_duration": removed_duration,
                        "removed_alias": removed_alias,
                    },
                }
            )

        return {
            "removed_duration": removed_duration,
            "removed_alias": removed_alias,
        }

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

        if data.feedback_rules:
            parts.append("\n用户即时反馈规则：")
            prefer_complex_slot = data.feedback_rules.get("prefer_complex_slot")
            if prefer_complex_slot:
                parts.append(f"- 复杂任务优先安排在: {prefer_complex_slot}")
            avoid_map = data.feedback_rules.get("avoid_slot_by_keyword") or {}
            for keyword, slot in list(avoid_map.items())[:10]:
                parts.append(f"- 避免在 {slot} 安排: {keyword}")
            notes = data.feedback_rules.get("free_text_notes") or []
            for note in notes[-3:]:
                parts.append(f"- 备注: {note}")

        return "\n".join(parts) if parts else ""

    async def organize_habits(self) -> Dict[str, Any]:
        """整理习惯数据：用 LLM 识别相似任务并归类
        
        返回归类建议，供 LLM 或用户确认后执行
        """
        data = await self._ensure_data()
        
        if not data.task_durations:
            return {
                "ok": False,
                "message": "暂无习惯数据可整理",
                "groups": []
            }
        
        # 收集所有任务名和统计
        task_list = []
        for name, stats in data.task_durations.items():
            task_list.append({
                "name": name,
                "count": _safe_int(stats.count),
                "avg_duration": round(_safe_float(stats.actual_avg)),
                "default": _safe_int(stats.default_minutes),
            })
        
        # 按出现次数排序
        task_list.sort(key=lambda x: x["count"], reverse=True)
        
        # 构建 LLM 分析用的提示
        prompt = self._build_organize_prompt(task_list)
        
        return {
            "ok": True,
            "prompt": prompt,
            "task_count": len(task_list),
            "tasks": task_list
        }
    
    def _build_organize_prompt(self, task_list: List[Dict]) -> str:
        """构建整理习惯的 LLM 分析提示"""
        task_lines = []
        for i, t in enumerate(task_list):
            task_lines.append(f"{i+1}. {t['name']} (出现{t['count']}次, 平均{t['avg_duration']}分钟)")
        
        tasks_text = "\n".join(task_lines)
        
        return f"""你是一个任务习惯分析专家。请分析以下任务列表，识别出可能是同一个习惯的任务，并给出归类建议。

任务列表：
{tasks_text}

请按以下格式输出分析结果：

## 习惯分组

对于每组相似任务，给出：
- 合并后的标准名称
- 包含的原始任务名
- 合并理由

## 需要删除的别名

列出应该删除的冗余别名。

## 建议

给出其他优化建议。

请确保：
1. 只有真正相似的任务才合并（语义相同或非常接近）
2. 保留有意义的区分（如"晨跑"和"夜跑"是不同的）
3. 合并时选择一个最能代表该习惯的名称作为主名称"""
