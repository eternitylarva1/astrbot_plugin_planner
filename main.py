"""
计划助手插件 - AstrBot插件
智能计划助手，支持自然语言创建任务、定时提醒、可视化日程
"""

import asyncio
import re
import time
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional, List, Dict, Any, AsyncGenerator
import uuid

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
from astrbot.api import logger
import astrbot.api.message_components as Comp
from astrbot.core.utils.session_waiter import session_waiter, SessionController

from .services.storage_service import StorageService
from .services.task_service import TaskService
from .services.reminder_service import ReminderService
from .services.astrbot_scheduler_adapter import AstrBotSchedulerAdapter
from .services.learning_service import LearningService
from .models.task import Task, GoalState, GoalTask
from .utils.time_parser import TimeParser
from .utils.visualizer import Visualizer
from .webui import WebUIServer


def _strip_cmd(text: str, *aliases: str) -> str:
    """移除消息开头的指令词，返回剩余部分。兼容带/和不带/的情况。"""
    if not text:
        return text
    for alias in aliases:
        # 匹配 /alias 或 alias（后面跟空格或字符串开头）
        stripped = re.sub(rf"^(?:/)?{re.escape(alias)}(?:\s+|$)", "", text.strip())
        if stripped != text.strip():
            return stripped.strip()
    return text.strip()


@register(
    "astrbot_plugin_planner",
    "eternitylarva1",
    """智能计划助手

📌 支持的时间表达：
  • 绝对时间：今天、明天、后天、下周一、周三
  • 相对时间：现在、立刻、马上、下午3点、15:30、上午9点

📌 支持的时长表达：
  • 小时：2小时、1.5小时
  • 分钟：30分钟、1小时30分钟

📌 使用方式：
  1. /计划 命令：交互式创建，会询问缺少的时间/时长
  2. create_planner_task 工具：一次性提供完整信息，直接创建（缺时间可自动补全）
  3. plan_with_ai / auto_plan_task：模糊目标自动规划（可选直接创建）
  4. list/complete/cancel_planner_task：自然语言查看/完成/取消任务

📌 示例：
  • /计划 明天下午3点写代码2小时
  • /计划 现在做作业1小时
  • create_planner_task("明天上午9点开会1小时")
  • list_planner_tasks("本周")
""",
    "1.1.2",
    "https://github.com/eternitylarva1/astrbot_plugin_planner",
)
class PlannerPlugin(Star):
    """计划助手插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 初始化服务
        self.storage = StorageService("astrbot_plugin_planner")
        self.learning_service = LearningService(self.storage)
        self.task_service = TaskService(self.storage, self.learning_service)
        self.scheduler_adapter = AstrBotSchedulerAdapter(context)
        self.reminder_service = ReminderService(
            self.storage, self.task_service, self.scheduler_adapter
        )
        self.visualizer = Visualizer()
        
        # 调试：打印 context 属性
        logger.info(f"Context type: {type(context)}")

        # 从配置读取（WebUI 可视化配置，持久化到 data/config/）
        self.config = config
        self._PENDING_TIMEOUT_SECONDS = config.get("timeout_seconds", 120)
        self._default_remind_before = config.get("remind_before", 10)
        self._auto_plan_on_missing_time = config.get("auto_plan_on_missing_time", True)
        self._avoid_past_time = config.get("avoid_past_time", True)
        self._ai_default_duration_minutes = config.get("ai_default_duration_minutes", 45)
        self._habit_planning_enabled = config.get("habit_planning_enabled", True)
        self._habit_weight = float(config.get("habit_weight", 0.7))
        self._suggestion_count = int(config.get("suggestion_count", 3))
        self._max_daily_minutes = int(config.get("max_daily_minutes", 360))
        self._learning_confidence_threshold = float(
            config.get("learning_confidence_threshold", 0.35)
        )

        # WebUI 配置
        self._webui_enabled = config.get("webui_enabled", True)
        self._webui_port = int(config.get("webui_port", 8099))
        self._webui_host = config.get("webui_host", "0.0.0.0")
        self._webui_server: Optional[WebUIServer] = None
        self._webui_start_task: Optional[asyncio.Task] = None
        self._context = context  # 保存 context 供 WebUI 调用 LLM
        self._event_context = None  # 保存最近的事件 context（包含 llm）

        # 状态管理
        self._pending_tasks: Dict[
            str, Dict
        ] = {}  # session_id -> 等待确认的任务（带 pending_at 时间戳）
        self._goal_states: Dict[str, GoalState] = {}  # session_id -> 目标状态
        self._breakdown_plans: Dict[str, Dict] = {}  # session_id -> 拆解方案 {name, tasks, saved}
        self._runtime_init_done = False
        self._runtime_init_lock = asyncio.Lock()

        # 启动 WebUI 服务器
        self._start_webui_server()

        logger.info("计划助手插件已加载")

    async def _ensure_runtime_initialized(self):
        """首次运行前补齐学习系统默认提醒值，避免仅存在内存配置。"""
        if self._runtime_init_done:
            return

        async with self._runtime_init_lock:
            if self._runtime_init_done:
                return

            await self.learning_service.ensure_default_remind_preference(
                self._default_remind_before
            )
            self._runtime_init_done = True

    @staticmethod
    def _filter_tasks_by_session(tasks: List[Task], session_origin: str) -> List[Task]:
        """按会话过滤任务，避免跨会话误操作。"""
        if not session_origin:
            return tasks
        return [t for t in tasks if t.session_origin == session_origin]

    @staticmethod
    def _is_bot_self_message(event: AstrMessageEvent) -> bool:
        """判断是否为机器人自身消息，避免把 bot 输出当成用户回复。"""
        # 兼容不同平台/适配器字段命名
        for flag_attr in ("is_self", "from_self", "self_message"):
            flag = getattr(event, flag_attr, None)
            if isinstance(flag, bool) and flag:
                return True

        sender_id = getattr(event, "sender_id", None) or getattr(event, "user_id", None)
        self_id = getattr(event, "self_id", None) or getattr(event, "bot_id", None)
        if sender_id is not None and self_id is not None and str(sender_id) == str(self_id):
            return True

        return False

    @staticmethod
    def _format_timeout_text(timeout_seconds: int) -> str:
        """将超时时长（秒）格式化为可读文本。"""
        if timeout_seconds < 60:
            return f"{timeout_seconds}秒"

        minutes = timeout_seconds / 60
        if timeout_seconds % 60 == 0:
            return f"{int(minutes)}分钟"

        minute_text = f"{minutes:.1f}".rstrip("0").rstrip(".")
        return f"{minute_text}分钟"

    async def _get_session_pending_tasks(self, session_origin: str) -> List[Task]:
        """获取当前会话的待办任务。"""
        pending_tasks = await self.task_service.get_pending_tasks()
        return self._filter_tasks_by_session(pending_tasks, session_origin)
    
    @staticmethod
    def _parse_batch_targets(target: str) -> List[int]:
        """解析批量目标编号，支持 "1,2,3" 和 "1-3" 格式。
        
        Args:
            target: 目标字符串，如 "1,2,3" 或 "1-3" 或 "1,3-5"
        
        Returns:
            编号列表（从1开始）
        """
        if not target:
            return []
        
        indices = set()
        parts = target.split(",")
        
        for part in parts:
            part = part.strip()
            if "-" in part:
                # 处理范围，如 "1-3"
                try:
                    start, end = part.split("-")
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())
                    # 确保范围有效
                    if start_idx > 0 and end_idx > 0:
                        for i in range(min(start_idx, end_idx), max(start_idx, end_idx) + 1):
                            if i > 0:
                                indices.add(i)
                except (ValueError, AttributeError):
                    continue
            else:
                # 处理单个编号
                try:
                    idx = int(part)
                    if idx > 0:
                        indices.add(idx)
                except ValueError:
                    continue
        
        return sorted(indices)

    async def _resolve_pending_task(
        self, session_origin: str, target: Optional[str], date_text: Optional[str] = None
    ) -> Optional[Task]:
        """按编号/名称解析当前会话待办任务。
        
        Args:
            session_origin: 会话来源
            target: 任务编号或名称
            date_text: 日期范围（如"今天/明天/本周/下周"），用于过滤任务列表
        """
        # 根据 date_text 获取任务列表
        if date_text:
            pending_tasks = await self._get_tasks_by_date_text(session_origin, date_text)
        else:
            pending_tasks = await self._get_session_pending_tasks(session_origin)
        
        if not pending_tasks:
            return None

        if not target:
            return pending_tasks[0]

        # 尝试编号
        try:
            idx = int(target) - 1
            if 0 <= idx < len(pending_tasks):
                return pending_tasks[idx]
            return None
        except ValueError:
            pass

        # 名称包含匹配（优先更短的名字，减少误匹配）
        matched = [t for t in pending_tasks if target in t.name]
        if not matched:
            return None
        matched.sort(key=lambda x: len(x.name))
        return matched[0]
    
    async def _get_tasks_by_date_text(
        self, session_origin: str, date_text: str
    ) -> List[Task]:
        """根据日期文本获取任务列表（与 list_planner_tasks 保持一致）。
        
        Args:
            session_origin: 会话来源
            date_text: 日期范围（如"今天/明天/本周/下周"）
        
        Returns:
            任务列表
        """
        text = date_text.strip().lower()
        today = date.today()

        if "本周" in text:
            days = [today + timedelta(days=i) for i in range(7)]
        elif "下周" in text:
            days = [today + timedelta(days=i) for i in range(7, 14)]
        elif "明天" in text:
            days = [today + timedelta(days=1)]
        elif "后天" in text:
            days = [today + timedelta(days=2)]
        else:
            days = [today]

        all_tasks: List[Task] = []
        for d in days:
            daily_tasks = await self.task_service.get_tasks_by_date(d)
            daily_tasks = self._filter_tasks_by_session(
                daily_tasks, session_origin
            )
            daily_tasks = [t for t in daily_tasks if t.status == "pending"]
            all_tasks.extend(daily_tasks)

        all_tasks.sort(key=lambda t: t.start_time or datetime.max)
        return all_tasks

    async def _prepare_task_creation(
        self,
        event: AstrMessageEvent,
        task_name: str,
        task_time: Optional[datetime],
        duration: int,
        repeat: Optional[str] = None,
        interactive: bool = True,
    ) -> Dict[str, Any]:
        """统一处理创建任务前的冲突检测。

        返回:
        - ok=True 且 task 不为空: 可直接创建
        - ok=False: 已检测到冲突，message 为给用户的提示文案
        """
        await self._ensure_runtime_initialized()
        
        # 如果 task_time 为 None，跳过冲突检测（自动安排时间）
        if task_time is None:
            task = Task(
                id=str(uuid.uuid4()),
                name=task_name,
                start_time=None,
                duration_minutes=duration,
                status="pending",
                remind_before=await self.learning_service.get_remind_preference(
                    task_name, fallback_minutes=self._default_remind_before
                ),
                repeat=repeat,
                created_at=datetime.now(),
                session_origin=event.unified_msg_origin,
            )
            return {"ok": True, "task": task}
        
        conflicts = await self.task_service.check_conflict(task_time, duration)
        if not conflicts:
            task = Task(
                id=str(uuid.uuid4()),
                name=task_name,
                start_time=task_time,
                duration_minutes=duration,
                status="pending",
                remind_before=await self.learning_service.get_remind_preference(
                    task_name, fallback_minutes=self._default_remind_before
                ),
                repeat=repeat,
                created_at=datetime.now(),
                session_origin=event.unified_msg_origin,
            )
            return {"ok": True, "task": task}

        candidate_time = await self.task_service.get_next_available_slot(
            task_time.date(), duration
        )
        conflict_lines = []
        for c in conflicts[:3]:
            if c.start_time:
                end_time = c.get_end_time()
                conflict_lines.append(
                    f"• {c.name}（{c.start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M') if end_time else '?'}）"
                )

        message = f"⚠️ 该时间段存在冲突：{task_time.strftime('%Y-%m-%d %H:%M')}\n"
        if conflict_lines:
            message += "\n".join(conflict_lines) + "\n"
        message += f"💡 候选时间：{candidate_time.strftime('%Y-%m-%d %H:%M')}\n\n"

        if interactive:
            self._pending_tasks[event.unified_msg_origin] = {
                "step": "awaiting_conflict_choice",
                "name": task_name,
                "task_time": task_time,
                "duration": duration,
                "repeat": repeat,
                "candidate_time": candidate_time,
                "pending_at": time.perf_counter(),
            }
            message += (
                "请回复：\n"
                "1) 自动顺延（推荐）\n"
                "2) 候选时间\n"
                "3) 仍然创建\n"
                "4) 取消"
            )
        else:
            message += "如需一键处理，请在描述中加入「自动顺延到下一个空档」。"
        return {"ok": False, "message": message, "candidate_time": candidate_time}

    async def _finalize_task_creation(self, task: Task):
        """统一创建任务后的收尾逻辑。"""
        await self.task_service.create_task(task)
        await self.reminder_service.schedule_reminder(task)
        time_slot = None
        if task.start_time:
            hour = task.start_time.hour
            if hour < 12:
                time_slot = "morning"
            elif hour < 18:
                time_slot = "afternoon"
            else:
                time_slot = "evening"
        await self.learning_service.record_task_creation_pattern(
            task.name, time_slot, task.duration_minutes
        )

    @staticmethod
    def _format_learning_change(before: Dict[str, int], after: Dict[str, int]) -> str:
        """格式化学习数据删除前后对比。"""
        return (
            "删除前后对比：\n"
            f"- 时长习惯：{before.get('durations', 0)} -> {after.get('durations', 0)}\n"
            f"- 别名习惯：{before.get('aliases', 0)} -> {after.get('aliases', 0)}\n"
            f"- 时段习惯：{before.get('time_total', 0)} -> {after.get('time_total', 0)}"
        )

    @staticmethod
    def _extract_plan_task_names(intention: str) -> List[str]:
        """把模糊意图拆成候选任务名列表。"""
        if not intention:
            return []
        segments = re.split(r"[，,。；;\n]|然后|并且|再|接着|以及", intention)
        cleaned: List[str] = []
        for seg in segments:
            s = seg.strip()
            if not s:
                continue
            for prefix in ["帮我", "请", "安排", "计划", "我想", "我需要", "我要", "想要"]:
                if s.startswith(prefix):
                    s = s[len(prefix) :].strip()
            s = re.sub(r"(一下|一下子|吧|呀|哦)$", "", s).strip()
            if s:
                cleaned.append(s)
        return cleaned or [intention.strip()]

    @staticmethod
    def _cleanup_planning_phrase(text: str) -> str:
        """清理“帮我安排一下这周...”等包装语，只保留核心任务语义。"""
        cleaned = (text or "").strip()
        for marker in [
            "这周",
            "本周",
            "下周",
            "今天",
            "明天",
            "后天",
            "帮我",
            "请",
            "安排一下",
            "安排",
            "规划一下",
            "规划",
            "计划一下",
            "计划",
        ]:
            cleaned = cleaned.replace(marker, " ")
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _slot_to_time(slot: str) -> dt_time:
        if slot == "morning":
            return dt_time(hour=9, minute=0)
        if slot == "afternoon":
            return dt_time(hour=15, minute=0)
        return dt_time(hour=20, minute=0)

    @staticmethod
    def _llm_create_task_param_guide() -> str:
        """给 LLM 的 create_planner_task 参数规范。"""
        return (
            "请使用结构化参数重新调用 create_planner_task：\n"
            "{\n"
            '  "task_name": "任务名称(必填)",\n'
            '  "task_time": "明确时间(建议 YYYY-MM-DD HH:MM 或 自然语言时间短语)",\n'
            '  "duration_minutes": 任务时长分钟数(推荐),\n'
            '  "repeat": "daily|weekly|monthly|workdays(可选)"\n'
            "}\n"
            "规则：优先传 duration_minutes；不要把整段闲聊放进 task_name。"
        )

    async def _plan_by_intention(
        self, event: AstrMessageEvent, intention: str, horizon_days: int = 7, max_tasks: int = 5
    ) -> List[Dict[str, Any]]:
        """根据用户模糊意图自动生成计划建议（基于学习习惯 + 冲突检查）。
        
        批量任务之间有时间关联：后续任务会从前一个任务的结束时间开始安排。
        """
        final_max_tasks = min(max_tasks, max(self._suggestion_count, 1))
        names = self._extract_plan_task_names(intention)[:final_max_tasks]
        if not names:
            return []

        today = date.today()
        now_dt = datetime.now()
        suggestions: List[Dict[str, Any]] = []
        daily_minutes_used: Dict[date, int] = {}
        last_task_end_time = None  # 跟踪上一个任务的结束时间
        
        for idx, name in enumerate(names):
            cleaned_name = self._cleanup_planning_phrase(name) or name
            parsed = TimeParser.parse_task_info(name)
            parsed_name = parsed.get("task_name") or cleaned_name
            duration = parsed.get("duration")
            confidence = await self.learning_service.estimate_learning_confidence(parsed_name)
            if not duration:
                if (
                    self._habit_planning_enabled
                    and confidence >= self._learning_confidence_threshold
                ):
                    learned_duration = await self.learning_service.suggest_duration_minutes(
                        parsed_name, self._ai_default_duration_minutes
                    )
                    duration = int(
                        round(
                            self._habit_weight * learned_duration
                            + (1 - self._habit_weight) * self._ai_default_duration_minutes
                        )
                    )
                else:
                    duration = self._ai_default_duration_minutes

            # 确定任务时间
            base_time = parsed.get("datetime")
            
            if base_time:
                # 任务有明确时间，使用该时间
                pass
            elif last_task_end_time:
                # 没有明确时间，从上一个任务的结束时间开始
                base_time = last_task_end_time
                # 检查冲突，找到下一个可用槽
                conflicts = await self.task_service.check_conflict(base_time, duration)
                if conflicts:
                    base_time = await self.task_service.get_next_available_slot(
                        base_time.date(), duration
                    )
            else:
                # 第一个任务且没有明确时间，使用默认逻辑
                candidate_slots = ["morning", "afternoon", "evening"]
                slot_scores = {}
                for candidate in candidate_slots:
                    slot_scores[candidate] = await self.learning_service.score_slot(
                        parsed_name,
                        candidate,
                        habit_weight=self._habit_weight,
                        habit_enabled=self._habit_planning_enabled,
                        confidence_threshold=self._learning_confidence_threshold,
                    )
                slot = max(candidate_slots, key=lambda s: slot_scores.get(s, -999.0))
                target_day = today + timedelta(days=min(idx, max(horizon_days - 1, 0)))
                used_minutes = daily_minutes_used.get(target_day, 0)
                if used_minutes + duration > self._max_daily_minutes:
                    target_day = target_day + timedelta(days=1)
                base_time = datetime.combine(target_day, self._slot_to_time(slot))
            
            # 避免过去时间
            if self._avoid_past_time and base_time <= now_dt:
                base_time = datetime.combine(
                    base_time.date() + timedelta(days=1),
                    base_time.time()
                )
            
            # 检查冲突并调整
            conflicts = await self.task_service.check_conflict(base_time, duration)
            if conflicts:
                base_time = await self.task_service.get_next_available_slot(
                    base_time.date(), duration
                )
                if self._avoid_past_time and base_time <= now_dt:
                    base_time = await self.task_service.get_next_available_slot(
                        base_time.date() + timedelta(days=1), duration
                    )
            
            # 确定时段（用于显示）
            hour = base_time.hour
            if hour < 12:
                slot = "morning"
            elif hour < 18:
                slot = "afternoon"
            else:
                slot = "evening"
            
            suggestions.append(
                {
                    "task_name": parsed_name,
                    "start_time": base_time,
                    "duration": duration,
                    "slot": slot,
                    "confidence": round(confidence, 2),
                }
            )
            
            # 更新上一个任务的结束时间
            last_task_end_time = base_time + timedelta(minutes=duration)
            
            # 更新每日使用时长
            day_key = base_time.date()
            daily_minutes_used[day_key] = daily_minutes_used.get(day_key, 0) + duration
        return suggestions

    async def terminate(self):
        """插件卸载时调用"""
        await self.reminder_service.stop()
        await self._stop_webui_server()
        logger.info("计划助手插件已卸载")

    def _start_webui_server(self):
        """启动 WebUI HTTP 服务器（插件启动时自动运行）"""
        if not self._webui_enabled:
            logger.info("WebUI server is disabled")
            return

        # 在事件循环中启动服务器
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._start_webui_async())
                logger.info(f"WebUI server starting on http://{self._webui_host}:{self._webui_port}")
            else:
                loop.run_until_complete(self._start_webui_async())
        except Exception as e:
            logger.error(f"Failed to start WebUI server: {e}")

    async def _start_webui_async(self):
        """异步启动 WebUI HTTP 服务器"""
        if self._webui_server and self._webui_server._running:
            logger.warning("WebUI server already running")
            return

        try:
            self._webui_server = WebUIServer(
                task_service=self.task_service,
                storage_service=self.storage,
                learning_service=self.learning_service,
                visualizer=self.visualizer,
                port=self._webui_port,
                host=self._webui_host,
                context=self._context,
                plugin=self,  # 传递 plugin 引用以便调用 LLM
            )
            await self._webui_server.start()
            logger.info(f"WebUI server started on http://{self._webui_host}:{self._webui_port}")
        except Exception as e:
            logger.error(f"Failed to start WebUI server: {e}")
            raise

    async def _stop_webui_server(self):
        """停止 WebUI HTTP 服务器"""
        if self._webui_server:
            try:
                await self._webui_server.stop()
                logger.info("WebUI server stopped")
            except Exception as e:
                logger.error(f"Error stopping WebUI server: {e}")

    async def _render_schedule_by_text(
        self, query_text: str, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """根据查询文本渲染可视化日程图。"""
        user_input = (query_text or "").lower()
        chart_style = "timeline"
        style_patterns = {
            "card": ["卡片", "卡片风格", "卡片样式"],
            "compact": ["紧凑", "列表", "简洁"],
            "timeline": ["时间轴", "竖轴", "纵向"],
        }
        for style, patterns in style_patterns.items():
            if any(p in user_input for p in patterns):
                chart_style = style
                for p in patterns:
                    user_input = user_input.replace(p, " ")
                break
        user_input = user_input.strip()
        today = date.today()

        # 解析日期范围
        if not user_input or "今天" in user_input or "今日" in user_input:
            target_date = today
        elif "明天" in user_input:
            target_date = today + timedelta(days=1)
        elif "后天" in user_input:
            target_date = today + timedelta(days=2)
        elif "本周" in user_input:
            tasks_by_date = {}
            for i in range(7):
                d = today + timedelta(days=i)
                tasks = await self.task_service.get_tasks_by_date(d)
                tasks = self._filter_tasks_by_session(tasks, event.unified_msg_origin)
                tasks_by_date[d] = tasks

            html = self.visualizer.render_weekly_schedule(tasks_by_date)
            # t2i 服务使用默认 viewport (1280x720)，CSS 已设置固定尺寸 1400x2800
            image_url = await self.html_render(html, {})
            yield event.image_result(image_url)
            return
        elif "下周" in user_input:
            tasks_by_date = {}
            for i in range(7, 14):
                d = today + timedelta(days=i)
                tasks = await self.task_service.get_tasks_by_date(d)
                tasks = self._filter_tasks_by_session(tasks, event.unified_msg_origin)
                tasks_by_date[d] = tasks

            html = self.visualizer.render_weekly_schedule(tasks_by_date)
            # t2i 服务使用默认 viewport (1280x720)，CSS 已设置固定尺寸 1400x2800
            image_url = await self.html_render(html, {})
            yield event.image_result(image_url)
            return
        elif any(
            w in user_input
            for w in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        ):
            # 星期几
            target_date = today
            for w in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]:
                if w in user_input:
                    weekday = [
                        "周一",
                        "周二",
                        "周三",
                        "周四",
                        "周五",
                        "周六",
                        "周日",
                    ].index(w)
                    days_until = (weekday - today.weekday()) % 7
                    if days_until == 0:
                        days_until = 7
                    target_date = today + timedelta(days=days_until)
                    break
        else:
            target_date = today

        # 获取任务并渲染
        tasks = await self.task_service.get_tasks_by_date(target_date)
        tasks = self._filter_tasks_by_session(tasks, event.unified_msg_origin)
        html = self.visualizer.render_daily_schedule(
            tasks, target_date, style=chart_style
        )
        # 使用 clip 裁剪到 1:2 比例 (720x1440)
        # t2i 服务默认 viewport (1280x720) 会渲染出 1280x1440，用 clip 裁剪
        options = {"clip": {"x": 0, "y": 0, "width": 720, "height": 1440}}
        logger.info(f"渲染图表，任务数: {len(tasks)}，目标尺寸: 720x1440 (1:2)")
        image_url = await self.html_render(html, {}, options=options)
        logger.info(f"图表图片URL: {image_url}")
        yield event.image_result(image_url)

    # ========== 基础指令 ==========

    @filter.command("计划", alias={"添加任务", "新建任务", "安排"})
    async def create_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """创建新任务

        用法：
        /计划 明天下午写代码 2小时
        /计划 明天9点开会 1小时
        /计划 每天早上运动
        """
        # 保存事件 context 供 WebUI 调用 LLM
        self._event_context = event.context
        logger.info(f"Saved event context, has llm: {hasattr(event.context, 'llm')}")
        
        user_input = _strip_cmd(
            event.message_str, "计划", "添加任务", "新建任务", "安排"
        )

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/计划 <任务描述>\n"
                "示例：\n"
                "• /计划 明天下午写代码 2小时\n"
                "• /计划 明天9点开会 1小时\n"
                "• /计划 今天晚上复习 45分钟"
            )
            return

        # 解析任务信息
        parsed = TimeParser.parse_task_info(user_input)

        task_name = parsed["task_name"]
        task_time = parsed["datetime"]
        duration = parsed["duration"]
        repeat = parsed["repeat"]

        # parse_duration 返回 -1 → 只有模糊词（如"大概"）没有具体数字，询问具体时长
        fuzzy_duration = None
        if duration == -1:
            # 提取模糊词中的数字估算（如"大概1小时"中的1小时）
            m = re.search(r"([+-]?\d+\.?\d*)\s*(?:小时|分钟|秒钟)", user_input)
            if m:
                value = float(m.group(1))
                if "小时" in user_input[m.start() : m.end()]:
                    fuzzy_duration = int(value * 60)
                else:
                    fuzzy_duration = int(value)
            duration = None

        # 清理任务名中的模糊词
        task_name = re.sub(r"(大概|左右|估计|差不多|些许)\s*", "", task_name).strip()

        # 如果没有解析出任务名，询问用户
        if not task_name:
            yield event.plain_result("请告诉我任务名称是什么？")
            return

        # 没有指定时长 → 询问用户
        if not duration:
            self._pending_tasks[event.unified_msg_origin] = {
                "name": task_name,
                "task_time": task_time,
                "repeat": repeat,
                "fuzzy_duration": fuzzy_duration,
                "step": "awaiting_duration",
                "pending_at": time.perf_counter(),
            }
            if fuzzy_duration:
                yield event.plain_result(
                    f"📝 创建任务：{task_name}\n\n"
                    f"你说的大概是 {TimeParser.format_duration(fuzzy_duration)}，具体是多少呢？\n"
                    f"例如：45分钟、1小时"
                )
            else:
                yield event.plain_result(
                    f"📝 创建任务：{task_name}\n\n"
                    f"请告诉我预计需要多长时间？\n"
                    f"例如：1小时、30分钟"
                )
            return

        # 没有指定时间 → 询问用户
        if not task_time:
            self._pending_tasks[event.unified_msg_origin] = {
                "name": task_name,
                "duration": duration,
                "repeat": repeat,
                "step": "awaiting_time",
                "pending_at": time.perf_counter(),
            }
            yield event.plain_result(
                f"📝 创建任务：{task_name}\n"
                f"⏱️ 时长：{TimeParser.format_duration(duration)}\n\n"
                f"请告诉我安排在什么时间？\n"
                f"例如：今天下午3点、明天上午9点、下周三"
            )
            return

        prep = await self._prepare_task_creation(
            event, task_name, task_time, duration, repeat
        )
        if not prep["ok"]:
            yield event.plain_result(prep["message"])
            return

        task = prep["task"]
        await self._finalize_task_creation(task)

        # 格式化输出
        response = (
            f"✅ 任务已创建\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 {task.name}\n"
            f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏱️ {TimeParser.format_duration(task.duration_minutes)}\n"
        )
        if repeat:
            repeat_text = {
                "daily": "每天",
                "weekly": "每周",
                "monthly": "每月",
                "workdays": "每个工作日",
            }.get(repeat, repeat)
            response += f"🔁 {repeat_text}\n"
        response += f"\n💡 {task.remind_before}分钟后提醒你"

        yield event.plain_result(response)

    @filter.command("任务", alias={"日程", "查看任务", "计划"})
    async def view_tasks(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看任务日程

        用法：
        /任务 今日
        /任务 明天
        /任务 本周
        /任务 下周
        """
        user_input = _strip_cmd(event.message_str, "任务", "日程", "查看任务", "计划")
        async for msg in self._render_schedule_by_text(user_input, event):
            yield msg

    @filter.command("图表", alias={"可视化", "查看图表", "查看可视化"})
    async def view_chart(self, event: AstrMessageEvent) -> MessageEventResult:
        """主动查看可视化图表

        用法：
        /图表
        /图表 今天
        /图表 本周
        /图表 下周
        /图表 卡片 本周
        /图表 紧凑 明天
        """
        user_input = _strip_cmd(
            event.message_str, "图表", "可视化", "查看图表", "查看可视化"
        )
        async for msg in self._render_schedule_by_text(user_input, event):
            yield msg

    @filter.command("webui", alias={"WebUI", "网页", "手机端"})
    async def webui_command(self, event: AstrMessageEvent) -> MessageEventResult:
        """启动/查看 WebUI 界面

        用法：
        /webui 启动
        /webui 停止
        /webui 状态
        """
        user_input = _strip_cmd(event.message_str, "webui", "WebUI", "网页", "手机端").strip().lower()

        if not user_input or user_input == "启动":
            if self._webui_server and self._webui_server._running:
                yield event.plain_result(
                    f"✅ WebUI 已运行中\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🌐 访问地址：http://你的IP:8099\n\n"
                    f"请将「你的IP」替换为服务器的实际 IP 地址"
                )
            else:
                # 尝试启动
                try:
                    await self._start_webui_async()
                    yield event.plain_result(
                        f"✅ WebUI 已启动\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🌐 访问地址：http://你的IP:8099\n\n"
                        f"请将「你的IP」替换为服务器的实际 IP 地址\n\n"
                        f"注意：如果使用 0.0.0.0，在手机访问需要使用服务器的实际局域网 IP"
                    )
                except Exception as e:
                    yield event.plain_result(f"❌ 启动失败：{e}")
            return

        if user_input == "停止":
            await self._stop_webui_server()
            yield event.plain_result("✅ WebUI 已停止")
            return

        if user_input == "状态":
            if self._webui_server and self._webui_server._running:
                yield event.plain_result(
                    f"✅ WebUI 运行中\n端口：{self._webui_port}\n"
                    f"访问地址：http://你的IP:8099"
                )
            else:
                yield event.plain_result("❌ WebUI 未启动\n使用 /webui 启动 来启动 WebUI")
            return

        yield event.plain_result(
            "📋 WebUI 命令\n"
            "━━━━━━━━━━━━━━━\n"
            "• /webui 启动 - 启动 WebUI\n"
            "• /webui 停止 - 停止 WebUI\n"
            "• /webui 状态 - 查看状态"
        )

    @filter.command("完成", alias={"done", "已完成"})
    async def complete_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """完成任务

        用法：
        /完成 1
        /完成
        """
        user_input = _strip_cmd(event.message_str, "完成", "done", "已完成")

        # 如果没有指定，获取最近的待办任务
        if not user_input:
            pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            # 只取今天的
            today_tasks = [
                t
                for t in pending_tasks
                if t.start_time and t.start_time.date() == date.today()
            ]

            if not today_tasks:
                yield event.plain_result("📋 今天没有待完成的任务")
                return

            # 完成最早的任务
            task = today_tasks[0]
        else:
            # 尝试解析任务编号
            try:
                idx = int(user_input) - 1
                pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
                if 0 <= idx < len(pending_tasks):
                    task = pending_tasks[idx]
                else:
                    yield event.plain_result(f"任务编号 {user_input} 不存在")
                    return
            except ValueError:
                # 尝试按名称匹配
                pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
                matched = [t for t in pending_tasks if user_input in t.name]
                if not matched:
                    yield event.plain_result(f"没有找到包含「{user_input}」的任务")
                    return
                task = matched[0]

        # 完成任务
        completed_task = await self.task_service.complete_task(task.id)

        # 取消提醒
        await self.reminder_service.cancel_reminder(task.id)

        # 记录学习数据
        if completed_task and completed_task.completed_at and completed_task.start_time:
            actual_duration = int(
                (
                    completed_task.completed_at - completed_task.start_time
                ).total_seconds()
                / 60
            )
            if actual_duration > 0:
                await self.learning_service.record_duration(task.name, actual_duration)

        yield event.plain_result(
            f"✅ 已完成：{task.name}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏱️ 实际用时：{TimeParser.format_duration(task.duration_minutes)}"
        )

    @filter.command("取消", alias={"删除任务", "remove"})
    async def cancel_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """取消任务

        用法：
        /取消 1
        /取消 写代码
        /取消 -1  （取消全部待办）
        """
        user_input = _strip_cmd(event.message_str, "取消", "删除任务", "remove")

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/取消 <任务编号|任务名称|-1>\n"
                "示例：\n"
                "• /取消 1\n"
                "• /取消 写代码\n"
                "• /取消 -1"
            )
            return

        # -1 或 all → 取消所有待办
        if user_input in ["-1", "all", "全部", "所有"]:
            pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            if not pending_tasks:
                yield event.plain_result("📋 没有待办任务")
                return
            count = 0
            for task in pending_tasks:
                await self.task_service.cancel_task(task.id)
                await self.reminder_service.cancel_reminder(task.id)
                count += 1
            # 清空多轮对话状态
            if event.unified_msg_origin in self._pending_tasks:
                del self._pending_tasks[event.unified_msg_origin]
            yield event.plain_result(f"❌ 已取消全部 {count} 个待办任务")
            return

        # 尝试解析任务编号
        try:
            idx = int(user_input) - 1
            pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            if 0 <= idx < len(pending_tasks):
                task = pending_tasks[idx]
            else:
                yield event.plain_result(f"任务编号 {user_input} 不存在")
                return
        except ValueError:
            # 尝试按名称匹配
            pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            matched = [t for t in pending_tasks if user_input in t.name]
            if not matched:
                yield event.plain_result(f"没有找到包含「{user_input}」的任务")
                return
            task = matched[0]

        # 取消任务
        await self.task_service.cancel_task(task.id)
        await self.reminder_service.cancel_reminder(task.id)

        yield event.plain_result(f"❌ 已取消：{task.name}")

    @filter.command("待办", alias={"todo", "待办列表", "任务列表"})
    async def list_tasks(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看待办任务列表

        用法：
        /待办
        """
        pending_tasks = await self.task_service.get_pending_tasks()
        pending_tasks = self._filter_tasks_by_session(
            pending_tasks, event.unified_msg_origin
        )

        if not pending_tasks:
            yield event.plain_result("📋 没有待办任务")
            return

        # 显示前10个
        lines = ["📋 待办任务\n━━━━━━━━━━━━━━━"]
        for i, task in enumerate(pending_tasks[:10], 1):
            time_str = (
                task.start_time.strftime("%m-%d %H:%M") if task.start_time else "待定"
            )
            lines.append(f"{i}. {task.name} [{time_str}]")

        if len(pending_tasks) > 10:
            lines.append(f"\n...还有 {len(pending_tasks) - 10} 个任务")

        yield event.plain_result("\n".join(lines))

    # ========== 循环任务 ==========

    @filter.command("循环", alias={"recurring", "每日任务", "定期任务"})
    async def create_recurring(self, event: AstrMessageEvent) -> MessageEventResult:
        """创建循环任务

        用法：
        /循环 每天早上8点运动
        /循环 每周一早上9点开会
        """
        user_input = _strip_cmd(
            event.message_str, "循环", "recurring", "每日任务", "定期任务"
        )

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/循环 <任务描述>\n"
                "示例：\n"
                "• /循环 每天早上8点运动\n"
                "• /循环 每周一早上9点开会\n"
                "• /循环 每个工作日早上7点起床"
            )
            return

        # 解析
        parsed = TimeParser.parse_task_info(user_input)

        task_name = parsed["task_name"]
        task_time = parsed["datetime"]
        repeat = parsed["repeat"]

        if not task_name:
            yield event.plain_result("请告诉我循环任务的名称")
            return

        if not repeat:
            # 判断循环模式
            if "每天" in user_input or "每日" in user_input:
                repeat = "daily"
            elif "每周" in user_input:
                repeat = "weekly"
            elif "工作日" in user_input:
                repeat = "workdays"
            elif "每月" in user_input:
                repeat = "monthly"
            else:
                repeat = "daily"  # 默认每天

        if not task_time:
            task_time = datetime.now().replace(
                hour=8, minute=0, second=0, microsecond=0
            )

        # 创建循环任务
        task = Task(
            id=str(uuid.uuid4()),
            name=task_name,
            start_time=task_time,
            duration_minutes=60,
            status="pending",
            repeat=repeat,
            created_at=datetime.now(),
            session_origin=event.unified_msg_origin,
        )

        await self.task_service.create_task(task)

        repeat_text = {
            "daily": "每天",
            "weekly": "每周",
            "monthly": "每月",
            "workdays": "每个工作日",
        }.get(repeat, repeat)

        yield event.plain_result(
            f"✅ 循环任务已创建\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 {task.name}\n"
            f"⏰ {repeat_text} {task_time.strftime('%H:%M')}"
        )

    # ========== 学习系统 ==========

    @filter.command("学习", alias={"统计", "习惯"})
    async def view_learning(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看学习到的习惯

        用法：
        /学习
        /学习 统计
        """
        user_input = _strip_cmd(event.message_str, "学习", "统计", "习惯").lower()

        if user_input.startswith("查看"):
            user_input = "统计"

        if user_input.startswith("删除"):
            raw_input = _strip_cmd(event.message_str, "学习", "统计", "习惯")
            delete_body = raw_input[len("删除") :].strip() if raw_input.startswith("删除") else ""
            parts = delete_body.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result(
                    "❗参数缺失\n"
                    "用法：\n"
                    "/习惯 删除 时长 <任务名>\n"
                    "/习惯 删除 别名 <alias>\n"
                    "/习惯 删除 时段 <任务名|complex|simple>"
                )
                return

            delete_type = parts[0].strip().lower()
            target = parts[1].strip()
            if not target:
                yield event.plain_result("❗请提供删除目标。")
                return

            if delete_type == "时长":
                result = await self.learning_service.delete_duration_pattern(target)
                if result["removed"]:
                    yield event.plain_result(
                        f"✅ 已删除时长习惯：{result['key']}\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                else:
                    yield event.plain_result(
                        f"未找到时长习惯：{result['key']}\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                return

            if delete_type == "别名":
                result = await self.learning_service.delete_alias(target)
                if result["removed"]:
                    yield event.plain_result(
                        f"✅ 已删除别名：{result['key']}（原映射到 {result['removed_payload']}）\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                else:
                    yield event.plain_result(
                        f"未找到别名：{result['key']}\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                return

            if delete_type == "时段":
                result = await self.learning_service.delete_time_pattern(target)
                if result["removed"]:
                    removed = ", ".join(result["removed_payload"])
                    yield event.plain_result(
                        f"✅ 已删除时段习惯分组：{result['key']}（来源：{result['source']}）\n"
                        f"原有偏好：{removed or '无'}\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                else:
                    yield event.plain_result(
                        f"未找到可删除的时段习惯分组：{result['key']}（来源：{result['source']}）\n"
                        f"{self._format_learning_change(result['before'], result['after'])}"
                    )
                return

            yield event.plain_result(
                "不支持的删除类型，请使用：时长 / 别名 / 时段"
            )
            return

        if user_input.startswith("重置"):
            if "全部" not in user_input:
                yield event.plain_result("目前仅支持：/习惯 重置 全部")
                return
            self._pending_tasks[event.unified_msg_origin] = {
                "step": "awaiting_learning_reset_confirm",
                "pending_at": time.perf_counter(),
            }
            yield event.plain_result(
                "⚠️ 即将清空全部学习数据（时长/别名/时段）。\n"
                "请在 2 分钟内回复「确认重置」继续，回复其他内容将取消。"
            )
            return

        if "自动" in user_input and any(k in user_input for k in ["开", "启用", "关闭", "关", "状态"]):
            if any(k in user_input for k in ["关闭", "关"]):
                await self.learning_service.set_auto_learning_enabled(False)
                yield event.plain_result("🧠 自动学习已关闭。将不再自动更新你的习惯数据。")
                return
            if any(k in user_input for k in ["开", "启用"]):
                await self.learning_service.set_auto_learning_enabled(True)
                yield event.plain_result("🧠 自动学习已开启。后续会持续学习你的时长与时间偏好。")
                return
            enabled = await self.learning_service.is_auto_learning_enabled()
            yield event.plain_result(
                f"🧠 自动学习状态：{'开启' if enabled else '关闭'}\n"
                f"可用命令：/学习 自动开启 或 /学习 自动关闭"
            )
            return

        if "重建" in user_input:
            stats = await self.learning_service.rebuild_profile_from_events()
            yield event.plain_result(
                "🛠️ 已从事件流重建学习画像（默认忽略删除类事件，便于误删恢复）。\n"
                f"📚 事件总数：{stats['events_total']}，已重放：{stats['events_replayed']}"
            )
            return

        if "最近事件" in user_input:
            events = await self.learning_service.get_recent_events(limit=10)
            if not events:
                yield event.plain_result("📭 暂无事件记录。")
                return
            lines = ["🧾 最近事件（最多10条）", "━━━━━━━━━━━━━━━"]
            for idx, item in enumerate(reversed(events), 1):
                ts = str(item.get("timestamp", ""))[:19].replace("T", " ")
                e_type = item.get("type", "unknown")
                payload = item.get("payload", {}) or {}
                task_name = payload.get("task_name") or payload.get("habit_key") or "-"
                lines.append(f"{idx}. [{ts}] {e_type} -> {task_name}")
            yield event.plain_result("\n".join(lines))
            return

        if "统计" in user_input or "习惯" in user_input:
            # 显示学习到的统计
            durations = await self.learning_service.get_all_learned_durations()
            aliases = await self.learning_service.get_all_aliases()

            lines = ["📊 学习统计\n━━━━━━━━━━━━━━━"]

            if durations:
                lines.append("⏱️ 任务时长：")
                for name, stats in list(durations.items())[:10]:
                    lines.append(
                        f"  • {name}: 通常{stats['actual_avg']:.0f}分钟 (记录{stats['count']}次)"
                    )
            else:
                lines.append("  暂无时长记录")

            if aliases:
                lines.append("\n📝 任务别名：")
                for alias, canonical in list(aliases.items())[:10]:
                    lines.append(f"  • {alias} = {canonical}")
            enabled = await self.learning_service.is_auto_learning_enabled()
            lines.append(f"\n🤖 自动学习：{'开启' if enabled else '关闭'}")

            yield event.plain_result("\n".join(lines))
        else:
            # 显示系统提示词
            system_prompt = await self.learning_service.generate_system_prompt()

            if system_prompt:
                yield event.plain_result(
                    "🧠 我已学习到你的习惯：\n"
                    "━━━━━━━━━━━━━━━\n"
                    f"{system_prompt}\n\n"
                    "继续使用，我会越来越懂你~"
                )
            else:
                yield event.plain_result(
                    "🧠 学习数据\n"
                    "━━━━━━━━━━━━━━━\n"
                    "暂无学习数据。\n"
                    "使用越多，我越懂你的习惯~"
                )

    @filter.command("设置提醒", alias={"提醒设置"})
    async def set_reminder(self, event: AstrMessageEvent) -> MessageEventResult:
        """设置提醒提前时间

        用法：
        /设置提醒 15分钟
        /设置提醒 30分钟
        """
        user_input = _strip_cmd(event.message_str, "设置提醒", "提醒设置")

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/设置提醒 <时长>\n"
                "示例：/设置提醒 15分钟"
            )
            return

        # 解析时长
        duration = TimeParser.parse_duration(user_input)
        if not duration:
            yield event.plain_result("请输入正确的时长，如：15分钟、30分钟、1小时")
            return

        await self.learning_service.record_remind_preference(None, duration)

        yield event.plain_result(
            f"✅ 提醒已设置为提前 {TimeParser.format_duration(duration)}"
        )

    @filter.command("计划反馈", alias={"反馈计划", "规划反馈"})
    async def plan_feedback(self, event: AstrMessageEvent) -> MessageEventResult:
        """记录用户对规划建议的即时反馈。

        示例：
        /计划反馈 喜欢晚上做深度任务
        /计划反馈 不要早上安排学习
        /计划反馈 这个建议不准
        """
        feedback_text = _strip_cmd(event.message_str, "计划反馈", "反馈计划", "规划反馈")
        if not feedback_text:
            yield event.plain_result(
                "❗请补充反馈内容\n"
                "示例：/计划反馈 不要早上安排学习"
            )
            return

        result = await self.learning_service.record_planning_feedback(feedback_text)
        if not result.get("ok"):
            yield event.plain_result("⚠️ 反馈记录失败，请稍后重试。")
            return

        yield event.plain_result(
            f"✅ 已记录反馈：{feedback_text}\n"
            f"🔧 生效规则：{result.get('message', '已更新')}\n"
            "下一轮推荐会按该偏好调整。"
        )

    # ========== 帮助 ==========

    @filter.command("规划帮助", alias={"计划帮助", "planner_help", "使用说明"})
    async def help_command(self, event: AstrMessageEvent) -> MessageEventResult:
        """显示帮助信息"""
        yield event.plain_result(
            "📋 计划助手 - 帮助\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 创建任务\n"
            "/计划 明天下午写代码 2小时\n\n"
            "📅 查看日程\n"
            "/任务 今日 /任务 本周\n\n"
            "✅ 完成任务\n"
            "/完成 1\n\n"
            "❌ 取消任务\n"
            "/取消 1  /取消 -1（取消全部）\n\n"
            "📋 待办列表\n"
            "/待办\n\n"
            "🔁 循环任务\n"
            "/循环 每天早上8点运动\n\n"
            "⏰ 提醒设置\n"
            "/设置提醒 15分钟\n\n"
            "⏱️ 超时设置\n"
            "/设置超时 120\n\n"
            "🧠 学习统计\n"
            "/学习 统计\n"
            "/学习 自动开启|自动关闭\n\n"
            "/习惯 查看\n"
            "/习惯 删除 时长 <任务名>\n"
            "/习惯 删除 别名 <alias>\n"
            "/习惯 删除 时段 <任务名|complex|simple>\n"
            "/习惯 重置 全部（需确认）\n\n"
            "🗣️ 计划反馈\n"
            "/计划反馈 不要早上安排学习\n\n"
            "🤖 AI 规划（可输入模糊目标）\n"
            "/ai规划 这周把作品集和算法复习安排一下"
        )

    @filter.command("ai规划", alias={"智能规划", "规划一下", "自动规划"})
    async def ai_plan_command(self, event: AstrMessageEvent) -> MessageEventResult:
        """基于模糊意图自动生成计划建议。"""
        user_input = _strip_cmd(event.message_str, "ai规划", "智能规划", "规划一下", "自动规划")
        if not user_input:
            yield event.plain_result(
                "请告诉我想做什么，例如：/ai规划 这周把作品集和算法复习安排一下"
            )
            return

        suggestions = await self._plan_by_intention(event, user_input, horizon_days=7, max_tasks=5)
        if not suggestions:
            yield event.plain_result("暂时无法生成计划，请再具体一点目标。")
            return

        lines = ["🤖 AI 规划建议（尚未创建任务）", "━━━━━━━━━━━━━━━"]
        for idx, item in enumerate(suggestions, 1):
            lines.append(
                f"{idx}. {item['task_name']} ｜ {item['start_time'].strftime('%m-%d %H:%M')} ｜ {TimeParser.format_duration(item['duration'])}"
            )
        lines.append("\n如需落地，请说：创建第1项，或直接用 create_planner_task。")
        yield event.plain_result("\n".join(lines))

    # ========== LLM 工具 - AI 智能调用 ==========

    @filter.llm_tool(name="create_planner_task")
    async def create_planner_task(
        self,
        event: AstrMessageEvent,
        description: Optional[str] = None,
        task_name: Optional[str] = None,
        task_time: Optional[str] = None,
        duration: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        repeat: Optional[str] = None,
    ) -> str:
        """创建计划任务（强烈建议 LLM 使用结构化参数）。

        当用户想要安排一个任务时调用此工具，一次性完成创建。
        ✅ 最佳实践：优先使用结构化参数 task_name / task_time / duration_minutes。
        ⚠️ description 仅作为兜底，不建议依赖长文本解析。

        支持的时间表达：今天、明天、下周三、下午3点、15:30、现在、立刻 等。
        支持的时长表达：2小时、30分钟、1小时 等。

        注意：此工具只处理完整信息。如果用户只提供了部分信息，
        请告知用户需要补充哪些信息。也可以让用户使用 /计划 命令进行交互式创建。

        Args:
            description(string): 可选。自然语言任务描述，包含任务名称、时间和时长。
                例如："明天下午3点写代码2小时"、"现在做毕业设计4小时"。
            task_name(string): 可选。任务名称，例如"志愿服务"。
            task_time(string): 可选。时间文本，例如"3月28号晚上5点"。
            duration(string): 可选。时长文本，例如"2小时"、"90分钟"、"2-3小时"。
            duration_minutes(int): 可选。时长分钟数（优先级高于 duration）。
            repeat(string): 可选。循环类型，如 daily/weekly/monthly/workdays。
        """
        user_input = (description or "").strip()
        structured_mode = any(
            [
                (task_name or "").strip(),
                (task_time or "").strip(),
                duration_minutes is not None,
                (duration or "").strip(),
            ]
        )

        if not structured_mode and not user_input:
            return "参数为空。\n" + self._llm_create_task_param_guide()

        parsed = TimeParser.parse_task_info(user_input) if user_input else {
            "task_name": "",
            "datetime": None,
            "duration": None,
            "repeat": None,
        }

        merged_task_name = (task_name or "").strip() or parsed["task_name"]
        merged_task_time = (
            TimeParser.parse_datetime(task_time) if task_time else parsed["datetime"]
        )
        merged_duration = (
            int(duration_minutes)
            if duration_minutes is not None
            else (TimeParser.parse_duration(duration) if duration else parsed["duration"])
        )
        merged_repeat = repeat or parsed["repeat"]

        # 没有解析出任务名 → 询问
        if not merged_task_name:
            return "缺少 task_name。\n" + self._llm_create_task_param_guide()

        # 清理任务名中的模糊词
        merged_task_name = re.sub(
            r"(大概|左右|估计|差不多|些许)\s*", "", merged_task_name
        ).strip()
        # 统一任务名格式：若包含长句/标点，二次提炼为核心事件描述
        if any(sep in merged_task_name for sep in ["，", "。", ";", "；"]):
            merged_task_name = TimeParser._extract_task_name(merged_task_name)
            merged_task_name = merged_task_name.strip()

        # 缺少时长 → 提示用户
        if not merged_duration:
            fuzzy_duration = None
            # 尝试提取模糊时长 "大概1小时"
            m = re.search(r"([+-]?\d+\.?\d*)\s*(?:小时|分钟|秒钟)", user_input)
            if m:
                value = float(m.group(1))
                kw_text = user_input[m.start() : m.end()]
                fuzzy_duration = int(value * 60) if "小时" in kw_text else int(value)
            if fuzzy_duration:
                return (
                    f"📝 任务「{merged_task_name}」\n\n"
                    f"你说的大概是 {TimeParser.format_duration(fuzzy_duration)}，具体是多少呢？\n"
                    f"例如：45分钟、1小时\n\n"
                    f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
                )
            if structured_mode:
                return "缺少时长参数（duration_minutes）。\n" + self._llm_create_task_param_guide()
            return (
                f"📝 任务「{merged_task_name}」\n\n"
                f"请告诉我预计需要多长时间？\n"
                f"例如：1小时、30分钟\n\n"
                f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
            )

        # 缺少时间 → 提示用户
        if not merged_task_time:
            if self._auto_plan_on_missing_time:
                suggestions = await self._plan_by_intention(
                    event, merged_task_name, horizon_days=1, max_tasks=1
                )
                if suggestions:
                    one = suggestions[0]
                    merged_task_time = one["start_time"]
                    if not merged_duration:
                        merged_duration = one["duration"]
                else:
                    return "我暂时无法自动安排时间，请补充 task_time。\n" + self._llm_create_task_param_guide()
            else:
                return "缺少 task_time。\n" + self._llm_create_task_param_guide()
        if not merged_task_time:
            return (
                f"📝 任务「{merged_task_name}」\n"
                f"⏱️ 时长：{TimeParser.format_duration(merged_duration)}\n\n"
                f"请告诉我安排在什么时间？\n"
                f"例如：今天下午3点、明天上午9点、下周三\n\n"
                f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
            )

        auto_shift = any(
            kw in user_input for kw in ["自动顺延", "下一个空档", "下个空档", "顺延"]
        )
        if auto_shift:
            conflicts = await self.task_service.check_conflict(merged_task_time, merged_duration)
            if conflicts:
                merged_task_time = await self.task_service.get_next_available_slot(
                    merged_task_time.date(), merged_duration
                )

        prep = await self._prepare_task_creation(
            event,
            merged_task_name,
            merged_task_time,
            merged_duration,
            merged_repeat,
            interactive=False,
        )
        if not prep["ok"]:
            return prep["message"]
        task = prep["task"]
        await self._finalize_task_creation(task)

        return (
            f"✅ 任务已创建\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 {task.name}\n"
            f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏱️ {TimeParser.format_duration(task.duration_minutes)}\n"
        )

    @filter.llm_tool(name="set_planner_config")
    async def set_planner_config(
        self,
        event: AstrMessageEvent,
        timeout_seconds: Optional[int] = None,
        remind_before: Optional[int] = None,
        auto_plan_on_missing_time: Optional[bool] = None,
        avoid_past_time: Optional[bool] = None,
        ai_default_duration_minutes: Optional[int] = None,
        habit_planning_enabled: Optional[bool] = None,
        habit_weight: Optional[float] = None,
        suggestion_count: Optional[int] = None,
        max_daily_minutes: Optional[int] = None,
        learning_confidence_threshold: Optional[float] = None,
    ) -> str:
        """设置计划助手的配置参数（建议 LLM 一次只改一到两个参数）。

        Args:
            timeout_seconds(int): 超时时间，单位为秒。建议范围 60-600 秒（1-10分钟）。
            remind_before(int): 任务开始前多少分钟提醒。
            auto_plan_on_missing_time(bool): 缺少时间时是否自动规划时间。
            avoid_past_time(bool): AI规划是否自动避免过去时间。
            ai_default_duration_minutes(int): AI默认任务时长（分钟）。
            habit_planning_enabled(bool): 是否启用习惯驱动规划。
            habit_weight(float): 习惯权重（0~1），越高越依赖已学习偏好。
            suggestion_count(int): 默认建议任务数上限。
            max_daily_minutes(int): 每日规划总时长上限（分钟）。
            learning_confidence_threshold(float): 学习置信度阈值（0~1），低于阈值时减少干预。
        """
        results = []

        if timeout_seconds is not None:
            if timeout_seconds < 10:
                return "超时时间不能少于 10 秒"
            if timeout_seconds > 3600:
                return "超时时间不能超过 3600 秒（1小时）"
            self._PENDING_TIMEOUT_SECONDS = timeout_seconds
            self.config["timeout_seconds"] = timeout_seconds
            await self.config.save_config()
            results.append(
                f"超时时间设置为 {self._format_timeout_text(timeout_seconds)}"
            )

        if remind_before is not None:
            if remind_before < 0:
                return "提醒时间不能为负数"
            self._default_remind_before = remind_before
            self.config["remind_before"] = remind_before
            await self.config.save_config()
            await self.learning_service.record_remind_preference(None, remind_before)
            results.append(f"提前 {remind_before} 分钟提醒")

        if auto_plan_on_missing_time is not None:
            self._auto_plan_on_missing_time = bool(auto_plan_on_missing_time)
            self.config["auto_plan_on_missing_time"] = self._auto_plan_on_missing_time
            await self.config.save_config()
            results.append(
                f"缺少时间自动规划：{'开启' if self._auto_plan_on_missing_time else '关闭'}"
            )

        if avoid_past_time is not None:
            self._avoid_past_time = bool(avoid_past_time)
            self.config["avoid_past_time"] = self._avoid_past_time
            await self.config.save_config()
            results.append(f"避免过去时间：{'开启' if self._avoid_past_time else '关闭'}")

        if ai_default_duration_minutes is not None:
            if ai_default_duration_minutes < 5:
                return "AI默认时长不能少于 5 分钟"
            if ai_default_duration_minutes > 480:
                return "AI默认时长不能超过 480 分钟（8小时）"
            self._ai_default_duration_minutes = int(ai_default_duration_minutes)
            self.config["ai_default_duration_minutes"] = self._ai_default_duration_minutes
            await self.config.save_config()
            results.append(f"AI默认时长：{self._ai_default_duration_minutes} 分钟")

        if habit_planning_enabled is not None:
            self._habit_planning_enabled = bool(habit_planning_enabled)
            self.config["habit_planning_enabled"] = self._habit_planning_enabled
            await self.config.save_config()
            results.append(
                f"习惯驱动规划：{'开启' if self._habit_planning_enabled else '关闭'}"
            )

        if habit_weight is not None:
            if habit_weight < 0 or habit_weight > 1:
                return "habit_weight 必须在 0~1 之间"
            self._habit_weight = float(habit_weight)
            self.config["habit_weight"] = self._habit_weight
            await self.config.save_config()
            results.append(f"习惯权重：{self._habit_weight:.2f}")

        if suggestion_count is not None:
            if suggestion_count < 1 or suggestion_count > 10:
                return "suggestion_count 必须在 1~10 之间"
            self._suggestion_count = int(suggestion_count)
            self.config["suggestion_count"] = self._suggestion_count
            await self.config.save_config()
            results.append(f"建议数量上限：{self._suggestion_count}")

        if max_daily_minutes is not None:
            if max_daily_minutes < 30 or max_daily_minutes > 1440:
                return "max_daily_minutes 必须在 30~1440 之间"
            self._max_daily_minutes = int(max_daily_minutes)
            self.config["max_daily_minutes"] = self._max_daily_minutes
            await self.config.save_config()
            results.append(f"每日最大规划时长：{self._max_daily_minutes} 分钟")

        if learning_confidence_threshold is not None:
            if learning_confidence_threshold < 0 or learning_confidence_threshold > 1:
                return "learning_confidence_threshold 必须在 0~1 之间"
            self._learning_confidence_threshold = float(learning_confidence_threshold)
            self.config["learning_confidence_threshold"] = (
                self._learning_confidence_threshold
            )
            await self.config.save_config()
            results.append(
                f"学习置信阈值：{self._learning_confidence_threshold:.2f}"
            )

        if not results:
            return "请提供要设置的参数"

        return "✅ " + " | ".join(results)

    @filter.llm_tool(name="plan_with_ai")
    async def plan_with_ai(
        self,
        event: AstrMessageEvent,
        intention: str,
        horizon: str = "本周",
        max_tasks: int = 5,
        auto_create: bool = False,
    ) -> str:
        """让 AstrBot 的 LLM 在用户意图模糊时自动规划（可选直接创建）。

        Args:
            intention(string): 用户目标/意图，可模糊，如“这周把作品集和算法复习安排一下”。
            horizon(string): 规划范围，可填“今天/本周/下周/7天/14天”。
            max_tasks(int): 最大建议任务数，1-10。
            auto_create(bool): 是否直接创建任务。False 为仅建议，True 为创建并排程。

        调用规范：
        - 当用户表达“帮我安排/规划一下”但信息不全时，优先调用本工具。
        - 若用户已给出明确 task_name/task_time/duration_minutes，优先调用 create_planner_task。
        """
        if not intention or not intention.strip():
            return "请提供 intention（要规划的目标描述）。"
        if max_tasks < 1:
            max_tasks = 1
        if max_tasks > 10:
            max_tasks = 10

        horizon_text = (horizon or "本周").strip().lower()
        horizon_days = 7
        if "今天" in horizon_text:
            horizon_days = 1
        elif "下周" in horizon_text or "14" in horizon_text:
            horizon_days = 14

        suggestions = await self._plan_by_intention(
            event, intention, horizon_days=horizon_days, max_tasks=max_tasks
        )
        if not suggestions:
            return "暂时无法生成计划，请补充更多目标细节。"

        if not auto_create:
            lines = ["🤖 AI 规划建议（未创建）"]
            for idx, item in enumerate(suggestions, 1):
                lines.append(
                    f"{idx}. {item['task_name']}｜{item['start_time'].strftime('%Y-%m-%d %H:%M')}｜{TimeParser.format_duration(item['duration'])}"
                )
            lines.append("如需落地，可再次调用并传入 auto_create=true。")
            return "\n".join(lines)

        created = []
        for item in suggestions:
            prep = await self._prepare_task_creation(
                event,
                item["task_name"],
                item["start_time"],
                item["duration"],
                repeat=None,
                interactive=False,
            )
            if not prep["ok"]:
                continue
            task = prep["task"]
            await self._finalize_task_creation(task)
            created.append(task)

        if not created:
            return "⚠️ AI 已生成建议，但由于冲突或信息不足，暂无任务成功创建。"

        lines = [f"✅ 已根据 AI 规划创建 {len(created)} 个任务："]
        for idx, t in enumerate(created, 1):
            lines.append(
                f"{idx}. {t.name}｜{t.start_time.strftime('%m-%d %H:%M')}｜{TimeParser.format_duration(t.duration_minutes)}"
            )
        return "\n".join(lines)

    @filter.llm_tool(name="auto_plan_task")
    async def auto_plan_task(
        self,
        event: AstrMessageEvent,
        user_text: str,
        auto_create: bool = True,
    ) -> str:
        """【高优先级触发】当用户说“帮我安排/规划一下...”时调用。

        触发示例：
        - 今天帮我安排一个小时做视频
        - 这周帮我规划一下作品集和复习
        - 给我排一下明天的学习任务
        """
        return await self.plan_with_ai(
            event=event,
            intention=user_text,
            horizon="本周",
            max_tasks=self._suggestion_count,
            auto_create=auto_create,
        )

    @filter.llm_tool(name="planner_tool_contract")
    async def planner_tool_contract(self, event: AstrMessageEvent) -> str:
        """返回给 LLM 的参数规范与选型规则。"""
        return (
            "Planner 工具选型：\n"
            "1) 用户给了明确任务名+时间+时长 -> create_planner_task\n"
            "2) 用户只说“帮我安排一下...” -> plan_with_ai 或 auto_plan_task\n"
            "3) 修改插件行为 -> set_planner_config\n\n"
            "create_planner_task 推荐参数：task_name, task_time, duration_minutes, repeat。\n"
            "plan_with_ai 推荐参数：intention, horizon, max_tasks, auto_create。\n"
            "set_planner_config 可设：timeout_seconds, remind_before, auto_plan_on_missing_time, avoid_past_time, ai_default_duration_minutes, habit_planning_enabled, habit_weight, suggestion_count, max_daily_minutes, learning_confidence_threshold。"
        )

    @filter.llm_tool(name="organize_habits")
    async def organize_habits(self, event: AstrMessageEvent) -> str:
        """整理习惯数据：用 LLM 分析相似任务并归类。

        当用户说"整理习惯"、"整理任务"、"归类任务"时调用。
        LLM 会分析所有学习到的任务，识别相似任务并给出归类建议。
        """
        result = await self.learning_service.organize_habits()
        
        if not result["ok"]:
            return result["message"]
        
        prompt = result["prompt"]
        
        # 调用 LLM 分析（通过 AstrBot 的 LLM 接口）
        try:
            llm_response = await event.context.llm.generate(
                prompt,
                system="你是一个任务习惯分析专家。请分析任务列表，识别相似任务并给出归类建议。"
            )
            return f"📊 习惯整理分析结果：\n\n{llm_response}"
        except Exception as e:
            logger.error(f"LLM organize_habits failed: {e}")
            return f"❌ 分析失败：{e}\n\n提示：请检查 LLM 配置是否正常。"

    @filter.command("整理习惯", alias={"归类任务", "整理任务"})
    async def cmd_organize_habits(self, event: AstrMessageEvent) -> MessageEventResult:
        """整理习惯数据：分析相似任务并归类"""
        yield event.plain_result("🔄 正在分析习惯数据...")
        
        result = await self.learning_service.organize_habits()
        
        if not result["ok"]:
            yield event.plain_result(result["message"])
            return
        
        prompt = result["prompt"]
        task_count = result["task_count"]
        
        try:
            llm_response = await event.context.llm.generate(
                prompt,
                system="你是一个任务习惯分析专家。请分析任务列表，识别相似任务并给出归类建议。"
            )
            yield event.plain_result(
                f"📊 习惯整理分析（{task_count}个任务）：\n\n{llm_response}\n\n"
                f"💡 如需执行归类合并，请告诉我要合并哪些任务。"
            )
        except Exception as e:
            logger.error(f"organize_habits failed: {e}")
            yield event.plain_result(f"❌ 分析失败：{e}")

    @filter.llm_tool(name="breakdown_task")
    async def breakdown_task(
        self,
        event: AstrMessageEvent,
        task_name: str,
        target_date: Optional[str] = None,
    ) -> str:
        """将大任务拆解为可执行的小任务（LLM 工具）。

        当用户说"拆解xxx"、"分解xxx"、"xxx包含什么"时调用。

        Args:
            task_name(string): 要拆解的任务名称。
            target_date(string): 可选的目标日期，如"今天"、"明天"、"本周"等。
        """
        if not task_name or not task_name.strip():
            return "请提供要拆解的任务名称。"
        
        prompt = self._build_breakdown_prompt(task_name.strip(), target_date)
        
        try:
            llm_response = await event.context.llm.generate(
                prompt,
                system="你是一个任务拆解专家。将大任务拆解成具体可执行的子任务，每个子任务控制在30分钟以内。"
            )
            return f"📋 任务拆解：{task_name}\n\n{llm_response}"
        except Exception as e:
            logger.error(f"LLM breakdown_task failed: {e}")
            return f"❌ 拆解失败：{e}"

    def _build_breakdown_prompt(self, task_name: str, target_date: Optional[str] = None) -> str:
        """构建任务拆解的 LLM 提示"""
        date_hint = f"\n目标完成时间：{target_date}" if target_date else ""
        
        return f"""请将以下任务拆解成具体可执行的子任务：

任务：{task_name}{date_hint}

拆解要求：
1. 每个子任务控制在 15-30 分钟内
2. 按逻辑顺序排列
3. 用「- 任务名 (时长)」格式

输出格式：
- 任务1 (30分钟)
- 任务2 (20分钟)
- 任务3 (25分钟)

只需要输出任务列表，每行一个任务，格式为「- 任务名 (时长)」，不要输出其他内容。"""

    def _parse_breakdown_result(self, text: str) -> List[Dict]:
        """解析拆解结果文本为任务列表"""
        tasks = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line.startswith("-"):
                continue
            # 去除 "- " 前缀
            line = line[2:].strip()
            # 提取时长 (XX分钟)
            import re
            match = re.search(r"\((\d+)分钟\)", line)
            duration = int(match.group(1)) if match else 30
            name = re.sub(r"\(\d+分钟\)", "", line).strip()
            if name:
                tasks.append({"name": name, "duration": duration})
        return tasks

    async def _call_llm_breakdown(self, task_name: str) -> List[Dict]:
        """通过 LLM 拆解任务（供 WebUI 调用）"""
        try:
            # 检查是否有保存的 context
            if not hasattr(self, '_event_context') or not self._event_context:
                logger.warning("No event context available for LLM call")
                return []
            
            prompt = self._build_breakdown_prompt(task_name)
            
            # 使用与命令处理器相同的 LLM API
            llm_response = await self._event_context.llm.generate(
                prompt,
                system="你是一个任务拆解专家。将大任务拆解成具体可执行的子任务，每个15-30分钟。只输出Markdown列表格式。"
            )
            
            logger.info(f"LLM response: {llm_response[:200] if llm_response else 'empty'}...")
            tasks = self._parse_breakdown_result(llm_response)
            logger.info(f"LLM breakdown for '{task_name}': {len(tasks)} tasks")
            return tasks
        except Exception as e:
            logger.error(f"LLM breakdown failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    @filter.command("拆解", alias={"分解", "任务拆解"})
    async def cmd_breakdown_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """将大任务拆解为可执行的小任务"""
        user_input = _strip_cmd(event.message_str, "拆解", "分解", "任务拆解")
        
        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/拆解 <任务名称>\n"
                "示例：\n"
                "• /拆解 完成毕业论文\n"
                "• /拆解 准备技术面试\n"
                "• /拆解 开发用户登录模块"
            )
            return
        
        yield event.plain_result("🔄 正在拆解任务...")
        
        prompt = self._build_breakdown_prompt(user_input.strip())
        
        try:
            llm_response = await event.context.llm.generate(
                prompt,
                system="你是一个任务拆解专家。将大任务拆解成具体可执行的子任务，每个15-30分钟。只输出Markdown列表格式。"
            )
            
            # 解析为任务列表
            tasks = self._parse_breakdown_result(llm_response)
            
            # 格式化输出
            if not tasks:
                yield event.plain_result(f"📋 任务拆解：{user_input}\n\n{llm_response}")
                return
            
            # 保存到会话状态（临时）
            session_id = event.unified_msg_origin
            self._breakdown_plans[session_id] = {
                "parent": user_input.strip(),
                "tasks": tasks,
                "saved": False
            }
            
            lines = [f"📋 任务拆解：{user_input}", "", "序号 | 任务名 | 时长"]
            lines.append("-" * 40)
            for i, t in enumerate(tasks, 1):
                lines.append(f"{i} | {t['name']} | {t['duration']}分钟")
            lines.append("-" * 40)
            lines.append(f"共 {len(tasks)} 个子任务，预计 {sum(t['duration'] for t in tasks)} 分钟")
            lines.append("")
            lines.append("💡 操作指令：")
            lines.append("• 「保存方案」- 保存方案后可编辑")
            lines.append("• 「完成导入」- 直接导入到任务")
            
            yield event.plain_result("\n".join(lines))
            
        except Exception as e:
            logger.error(f"breakdown_task failed: {e}")
            yield event.plain_result(f"❌ 拆解失败：{e}")

    @filter.command("保存方案")
    async def cmd_save_plan(self, event: AstrMessageEvent) -> MessageEventResult:
        """保存拆解方案"""
        session_id = event.unified_msg_origin
        plan = self._breakdown_plans.get(session_id)
        
        if not plan:
            yield event.plain_result("❗ 没有可保存的方案，请先使用 /拆解 命令")
            return
        
        plan["saved"] = True
        tasks = plan.get("tasks", [])
        
        lines = [f"✅ 方案已保存：{plan['parent']}", "", "序号 | 任务名 | 时长"]
        lines.append("-" * 40)
        for i, t in enumerate(tasks, 1):
            lines.append(f"{i} | {t['name']} | {t['duration']}分钟")
        lines.append("-" * 40)
        lines.append(f"共 {len(tasks)} 个子任务")
        lines.append("")
        lines.append("💡 可用指令：")
        lines.append("• 「编辑方案」- 用 AI 编辑方案")
        lines.append("• 「完成导入」- 导入到任务")
        lines.append("• 「取消」- 取消并删除方案")
        
        yield event.plain_result("\n".join(lines))

    @filter.command("编辑方案")
    async def cmd_edit_plan(self, event: AstrMessageEvent) -> MessageEventResult:
        """用 LLM 编辑拆解方案"""
        session_id = event.unified_msg_origin
        plan = self._breakdown_plans.get(session_id)
        
        if not plan or not plan.get("saved"):
            yield event.plain_result("❗ 没有已保存的方案，请先「保存方案」")
            return
        
        user_input = _strip_cmd(event.message_str, "编辑方案")
        if not user_input:
            yield event.plain_result(
                "请说明要如何修改：\n"
                "• 「编辑方案 把任务1和任务2合并」\n"
                "• 「编辑方案 把所有时长改成20分钟」\n"
                "• 「编辑方案 在开头加一个准备任务」"
            )
            return
        
        yield event.plain_result("🔄 正在用 AI 编辑方案...")
        
        # 构建编辑提示
        tasks = plan.get("tasks", [])
        task_list = "\n".join([f"{i+1}. {t['name']} ({t['duration']}分钟)" for i, t in enumerate(tasks)])
        
        edit_prompt = f"""当前方案：
{task_list}

用户要求：{user_input}

请根据用户要求修改方案，输出格式：
- 任务名1 (时长)
- 任务名2 (时长)

只输出修改后的任务列表，每行一个，格式为「- 任务名 (时长)」。"""

        try:
            llm_response = await event.context.llm.generate(
                edit_prompt,
                system="你是一个任务拆解专家。根据用户要求修改任务列表。只输出Markdown列表格式。"
            )
            
            # 解析新任务列表
            new_tasks = self._parse_breakdown_result(llm_response)
            
            if new_tasks:
                plan["tasks"] = new_tasks
                self._breakdown_plans[session_id] = plan
            
            # 显示修改后的方案
            lines = [f"✅ 方案已更新", "", "序号 | 任务名 | 时长"]
            lines.append("-" * 40)
            for i, t in enumerate(new_tasks, 1):
                lines.append(f"{i} | {t['name']} | {t['duration']}分钟")
            lines.append("-" * 40)
            lines.append(f"共 {len(new_tasks)} 个子任务")
            lines.append("")
            lines.append("💡 可继续编辑或「完成导入」")
            
            yield event.plain_result("\n".join(lines))
            
        except Exception as e:
            logger.error(f"edit_plan failed: {e}")
            yield event.plain_result(f"❌ 编辑失败：{e}")

    @filter.command("完成导入")
    async def cmd_finish_import(self, event: AstrMessageEvent) -> MessageEventResult:
        """完成导入，将方案导入到任务"""
        session_id = event.unified_msg_origin
        plan = self._breakdown_plans.get(session_id)
        
        if not plan:
            yield event.plain_result("❗ 没有可导入的方案，请先使用 /拆解 命令")
            return
        
        tasks = plan.get("tasks", [])
        if not tasks:
            yield event.plain_result("❗ 方案为空，无法导入")
            return
        
        added = []
        for t in tasks:
            prep = await self._prepare_task_creation(
                event, t["name"], None, t["duration"], repeat=None, interactive=False
            )
            if prep["ok"]:
                await self._finalize_task_creation(prep["task"])
                added.append(t["name"])
        
        # 清理方案
        del self._breakdown_plans[session_id]
        
        yield event.plain_result(
            f"✅ 已导入 {len(added)} 个任务到计划：\n" +
            "\n".join([f"• {a}" for a in added])
        )

    @filter.command("取消", alias={"取消方案"})
    async def cmd_cancel_plan(self, event: AstrMessageEvent) -> MessageEventResult:
        """取消方案"""
        session_id = event.unified_msg_origin
        
        if session_id in self._breakdown_plans:
            del self._breakdown_plans[session_id]
            yield event.plain_result("✅ 方案已取消")
        else:
            yield event.plain_result("❗ 没有可取消的方案")

    @filter.command("删除", alias={"删除任务", "删除子任务"})
    async def cmd_delete_breakdown_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理拆解结果的删除操作"""
        user_input = _strip_cmd(event.message_str, "删除", "删除任务", "删除子任务")
        
        session_id = event.unified_msg_origin
        breakdown = getattr(self, '_breakdown_results', {}).get(session_id)
        
        if not breakdown:
            yield event.plain_result("❗ 没有可删除的拆解任务")
            return
        
        tasks = breakdown.get("tasks", [])
        import re
        match = re.search(r"第(\d+)项", user_input)
        
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(tasks):
                removed = tasks.pop(idx)
                yield event.plain_result(f"✅ 已删除：{removed['name']}")
                # 更新保存的状态
                self._breakdown_results[session_id]["tasks"] = tasks
                return
            else:
                yield event.plain_result(f"❗ 编号 {idx+1} 不在范围内")
                return
        
        yield event.plain_result("❗ 请指定要删除的任务：\n• 「删除第1项」")

    @filter.command("修改", alias={"修改任务", "修改子任务"})
    async def cmd_modify_breakdown_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理拆解结果的修改操作"""
        user_input = _strip_cmd(event.message_str, "修改", "修改任务", "修改子任务")
        
        session_id = event.unified_msg_origin
        breakdown = getattr(self, '_breakdown_results', {}).get(session_id)
        
        if not breakdown:
            yield event.plain_result("❗ 没有可修改的拆解任务")
            return
        
        tasks = breakdown.get("tasks", [])
        import re
        match = re.search(r"第(\d+)项", user_input)
        
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(tasks):
                # 提取修改内容
                rest = user_input.split("第" + str(idx+1) + "项", 1)
                if len(rest) > 1:
                    new_value = rest[1].strip()
                    # 尝试解析时长
                    time_match = re.search(r"(\d+)\s*分钟", new_value)
                    if time_match:
                        tasks[idx]["duration"] = int(time_match.group(1))
                        self._breakdown_results[session_id]["tasks"] = tasks
                        yield event.plain_result(f"✅ 已修改第{idx+1}项时长为 {time_match.group(1)} 分钟")
                        return
                    # 否则当作名称
                    if new_value:
                        tasks[idx]["name"] = new_value
                        self._breakdown_results[session_id]["tasks"] = tasks
                        yield event.plain_result(f"✅ 已修改第{idx+1}项为：{new_value}")
                        return
                
                yield event.plain_result(f"❗ 请输入修改内容：\n• 「修改第1项 60分钟」\n• 「修改第1项 新名称」")
                return
            else:
                yield event.plain_result(f"❗ 编号 {idx+1} 不在范围内")
                return
        
        yield event.plain_result("❗ 请指定要修改的任务：\n• 「修改第1项 新名称」\n• 「修改第1项 30分钟」")

    @filter.llm_tool(name="list_planner_tasks")
    async def list_planner_tasks(
        self,
        event: AstrMessageEvent,
        date_text: Optional[str] = "今天",
        include_done: bool = False,
        limit: int = 10,
    ) -> str:
        """查看当前会话任务列表（LLM 工具）。

        Args:
            date_text(string): 日期范围，如“今天/明天/本周/下周”。
            include_done(bool): 是否包含已完成任务。
            limit(int): 最多返回条数，范围 1-30。
        """
        if limit < 1:
            limit = 1
        if limit > 30:
            limit = 30

        text = (date_text or "今天").strip().lower()
        today = date.today()

        if "本周" in text:
            days = [today + timedelta(days=i) for i in range(7)]
        elif "下周" in text:
            days = [today + timedelta(days=i) for i in range(7, 14)]
        elif "明天" in text:
            days = [today + timedelta(days=1)]
        elif "后天" in text:
            days = [today + timedelta(days=2)]
        else:
            days = [today]

        all_tasks: List[Task] = []
        for d in days:
            daily_tasks = await self.task_service.get_tasks_by_date(d)
            daily_tasks = self._filter_tasks_by_session(
                daily_tasks, event.unified_msg_origin
            )
            if not include_done:
                daily_tasks = [t for t in daily_tasks if t.status == "pending"]
            all_tasks.extend(daily_tasks)

        if not all_tasks:
            return "📋 当前范围内没有任务。"

        all_tasks.sort(key=lambda t: t.start_time or datetime.max)
        lines = [f"📋 任务列表（{date_text or '今天'}）"]
        for i, task in enumerate(all_tasks[:limit], 1):
            time_str = (
                task.start_time.strftime("%m-%d %H:%M") if task.start_time else "待定"
            )
            status_emoji = "✅" if task.status == "done" else "⏳"
            lines.append(f"{i}. {status_emoji} {task.name} [{time_str}]")

        if len(all_tasks) > limit:
            lines.append(f"... 还有 {len(all_tasks) - limit} 项未展示")
        return "\n".join(lines)

    @filter.llm_tool(name="complete_planner_task")
    async def complete_planner_task(
        self, event: AstrMessageEvent, target: Optional[str] = None, date_text: Optional[str] = None
    ) -> str:
        """完成当前会话中的任务（支持编号、名称或批量编号）。

        Args:
            target(string): 任务编号（如"1"）、任务名关键字，或批量编号（如"1,2,3"或"1-3"）；为空时默认完成最近一项。
            date_text(string): 日期范围（如"今天/明天/本周/下周"），用于指定任务列表范围。
        """
        if not target:
            # 默认完成第一个任务
            task = await self._resolve_pending_task(event.unified_msg_origin, None, date_text)
            if not task:
                return "未找到可完成的任务。请先用 list_planner_tasks 查看任务编号。"
            completed_task = await self.task_service.complete_task(task.id)
            await self.reminder_service.cancel_reminder(task.id)
            if completed_task and completed_task.completed_at and completed_task.start_time:
                actual_duration = int(
                    (completed_task.completed_at - completed_task.start_time).total_seconds()
                    / 60
                )
                if actual_duration > 0:
                    await self.learning_service.record_duration(task.name, actual_duration)
            return f"✅ 已完成：{task.name}"
        
        # 检查是否为批量编号
        batch_indices = self._parse_batch_targets(target)
        if batch_indices:
            # 批量完成
            if date_text:
                pending_tasks = await self._get_tasks_by_date_text(event.unified_msg_origin, date_text)
            else:
                pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            
            completed = []
            for idx in batch_indices:
                if 0 < idx <= len(pending_tasks):
                    task = pending_tasks[idx - 1]
                    completed_task = await self.task_service.complete_task(task.id)
                    await self.reminder_service.cancel_reminder(task.id)
                    if completed_task and completed_task.completed_at and completed_task.start_time:
                        actual_duration = int(
                            (completed_task.completed_at - completed_task.start_time).total_seconds()
                            / 60
                        )
                        if actual_duration > 0:
                            await self.learning_service.record_duration(task.name, actual_duration)
                    completed.append(task.name)
            
            if not completed:
                return "未找到可完成的任务。请先用 list_planner_tasks 查看任务编号。"
            return f"✅ 已完成 {len(completed)} 个任务：{', '.join(completed)}"
        
        # 单个任务
        task = await self._resolve_pending_task(event.unified_msg_origin, target, date_text)
        if not task:
            return "未找到可完成的任务。请先用 list_planner_tasks 查看任务编号。"

        completed_task = await self.task_service.complete_task(task.id)
        await self.reminder_service.cancel_reminder(task.id)

        if completed_task and completed_task.completed_at and completed_task.start_time:
            actual_duration = int(
                (completed_task.completed_at - completed_task.start_time).total_seconds()
                / 60
            )
            if actual_duration > 0:
                await self.learning_service.record_duration(task.name, actual_duration)

        return f"✅ 已完成：{task.name}"

    @filter.llm_tool(name="cancel_planner_task")
    async def cancel_planner_task(self, event: AstrMessageEvent, target: str, date_text: Optional[str] = None) -> str:
        """取消当前会话中的任务（支持编号、名称、批量编号或 all）。

        Args:
            target(string): 任务编号、任务名关键字、批量编号（如"1,2,3"或"1-3"），或 all/-1（取消当前会话全部待办）。
            date_text(string): 日期范围（如"今天/明天/本周/下周"），用于指定任务列表范围。
        """
        target = (target or "").strip()
        if not target:
            return "请提供 target（任务编号/名称，或 all）。"

        if target in {"all", "-1", "全部", "所有"}:
            pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            if not pending_tasks:
                return "📋 没有可取消的待办任务。"
            for task in pending_tasks:
                await self.task_service.cancel_task(task.id)
                await self.reminder_service.cancel_reminder(task.id)
            return f"❌ 已取消当前会话全部待办任务，共 {len(pending_tasks)} 项。"

        # 检查是否为批量编号
        batch_indices = self._parse_batch_targets(target)
        if batch_indices:
            # 批量取消
            if date_text:
                pending_tasks = await self._get_tasks_by_date_text(event.unified_msg_origin, date_text)
            else:
                pending_tasks = await self._get_session_pending_tasks(event.unified_msg_origin)
            
            cancelled = []
            for idx in batch_indices:
                if 0 < idx <= len(pending_tasks):
                    task = pending_tasks[idx - 1]
                    await self.task_service.cancel_task(task.id)
                    await self.reminder_service.cancel_reminder(task.id)
                    cancelled.append(task.name)
            
            if not cancelled:
                return "未找到可取消的任务。请先用 list_planner_tasks 查看任务编号。"
            return f"❌ 已取消 {len(cancelled)} 个任务：{', '.join(cancelled)}"

        # 单个任务
        task = await self._resolve_pending_task(event.unified_msg_origin, target, date_text)
        if not task:
            return "未找到可取消的任务。请先用 list_planner_tasks 查看任务编号。"

        await self.task_service.cancel_task(task.id)
        await self.reminder_service.cancel_reminder(task.id)
        return f"❌ 已取消：{task.name}"

    # ========== 命令 ==========

    @filter.command("设置超时", alias={"超时设置"})
    async def set_timeout(self, event: AstrMessageEvent) -> MessageEventResult:
        """设置待确认任务的超时时间

        用法：
        /设置超时 120
        /设置超时 300
        """
        user_input = _strip_cmd(event.message_str, "设置超时", "超时设置")

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/设置超时 <秒数>\n"
                "示例：/设置超时 120"
            )
            return

        try:
            seconds = int(user_input.strip())
        except ValueError:
            yield event.plain_result("请输入数字，如：/设置超时 120")
            return

        if seconds < 10:
            yield event.plain_result("超时时间不能少于 10 秒")
            return
        if seconds > 3600:
            yield event.plain_result("超时时间不能超过 3600 秒（1小时）")
            return

        self._PENDING_TIMEOUT_SECONDS = seconds
        self.config["timeout_seconds"] = seconds
        await self.config.save_config()

        yield event.plain_result(
            f"✅ 超时时间已设置为 {self._format_timeout_text(seconds)}"
        )

    # ========== 事件监听器 - 处理多轮对话 ==========

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_pending_message(self, event: AstrMessageEvent):
        """处理待确认的消息"""
        if self._is_bot_self_message(event):
            return

        session_id = event.unified_msg_origin
        user_input = event.message_str.strip()

        # 检查是否有待处理的任务
        if session_id not in self._pending_tasks:
            return  # 不是待处理消息，继续传播

        pending = self._pending_tasks[session_id]

        # 超时检查（使用 perf_counter 避免 Windows datetime.now() 精度问题）
        # 兼容旧版 pending_at（datetime 对象）到新版（perf_counter float）
        pending_at = pending.get("pending_at")
        if pending_at:
            if isinstance(pending_at, datetime):
                elapsed = (datetime.now() - pending_at).total_seconds()
            else:
                elapsed = time.perf_counter() - pending_at
            if elapsed > self._PENDING_TIMEOUT_SECONDS:
                del self._pending_tasks[session_id]
                yield event.plain_result(
                    f"⏰ 抱歉，上次的问题已超时（超过{self._format_timeout_text(self._PENDING_TIMEOUT_SECONDS)}），已自动取消。\n"
                    "如需继续，请重新发送任务指令。"
                )
                event.stop_event()
                return

        step = pending.get("step", "")

        # 处理不同步骤
        if step == "awaiting_time":
            # 用户在回答时间问题
            task_time = TimeParser.parse_datetime(user_input)

            # 无法解析为时间 → 检查是否是时长回复
            if not task_time:
                duration_reply = TimeParser.parse_duration(user_input)
                if duration_reply and duration_reply > 0:
                    # 用户回答了时长 → 记录时长，继续问时间
                    pending["duration"] = duration_reply
                    pending["pending_at"] = time.perf_counter()
                    yield event.plain_result(
                        f"⏱️ 时长：{TimeParser.format_duration(duration_reply)}\n\n"
                        f"请告诉我安排在什么时间？\n"
                        f"例如：今天下午3点、明天上午9点、下周三"
                    )
                    return
                else:
                    yield event.plain_result(
                        "没理解这个时间 😅\n"
                        "请回复具体时间，如：明天下午3点、明天9点、下周三"
                    )
                    return

            duration = pending.get("duration")

            # 如果没有时长，继续问时长
            if not duration:
                pending["task_time"] = task_time
                pending["step"] = "awaiting_duration"
                pending["pending_at"] = time.perf_counter()

                yield event.plain_result(
                    f"⏰ 时间：{task_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"预计需要多长时间？\n"
                    f"例如：1小时、30分钟"
                )
                return

            # 两者都有了 → 创建任务（先检查冲突）
            task_name = pending["name"]
            repeat = pending.get("repeat")
            prep = await self._prepare_task_creation(
                event, task_name, task_time, duration, repeat
            )
            if not prep["ok"]:
                yield event.plain_result(prep["message"])
                return
            task = prep["task"]
            await self._finalize_task_creation(task)
            del self._pending_tasks[session_id]

            yield event.plain_result(
                f"✅ 任务已创建\n━━━━━━━━━━━━━━━\n"
                f"📌 {task.name}\n"
                f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"⏱️ {TimeParser.format_duration(task.duration_minutes)}\n"
                f"\n💡 {task.remind_before}分钟后提醒你"
            )

        elif step == "awaiting_duration":
            # 用户在回答时长问题
            duration = TimeParser.parse_duration(user_input)
            if not duration:
                yield event.plain_result(
                    "没理解这个时长 😅\n请回复具体时长，如：1小时、30分钟、2小时"
                )
                return

            # 模糊时长（"大概左右"等）+ 有具体数字，检查原始输入是否包含模糊词
            fuzzy_keywords = {"大概", "左右", "估计", "差不多", "些许"}
            has_fuzzy = any(kw in user_input for kw in fuzzy_keywords)

            if has_fuzzy:
                # 提取估算值并询问确认
                m = re.search(
                    r"([+-]?\d+\.?\d*)\s*(?:小时|分钟|秒钟)", user_input.lower()
                )
                if m:
                    value = float(m.group(1))
                    kw = m.group(0)
                    fuzzy_val = int(value * 60) if "小时" in kw else int(value)
                    pending["fuzzy_duration"] = fuzzy_val
                    pending["pending_at"] = time.perf_counter()
                    yield event.plain_result(
                        f"你说的大概是 {TimeParser.format_duration(fuzzy_val)}，具体是多少呢？\n"
                        f"例如：45分钟、1小时"
                    )
                    return
                # 有模糊词但没匹配到数字
                yield event.plain_result(
                    "没理解这个时长 😅\n请回复具体时长，如：1小时、30分钟、2小时"
                )
                return

            task_time = pending.get("task_time")

            # 如果没有时间，继续问时间
            if not task_time:
                pending["duration"] = duration
                pending["step"] = "awaiting_time"
                pending["pending_at"] = time.perf_counter()

                yield event.plain_result(
                    f"⏱️ 时长：{TimeParser.format_duration(duration)}\n\n"
                    f"请告诉我安排在什么时间？\n"
                    f"例如：今天下午3点、明天上午9点、下周三"
                )
                return

            # 两者都有了 → 创建任务（先检查冲突）
            task_name = pending["name"]
            repeat = pending.get("repeat")
            prep = await self._prepare_task_creation(
                event, task_name, task_time, duration, repeat
            )
            if not prep["ok"]:
                yield event.plain_result(prep["message"])
                return
            task = prep["task"]
            await self._finalize_task_creation(task)
            del self._pending_tasks[session_id]

            yield event.plain_result(
                f"✅ 任务已创建\n━━━━━━━━━━━━━━━\n"
                f"📌 {task.name}\n"
                f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"⏱️ {TimeParser.format_duration(task.duration_minutes)}\n"
                f"\n💡 {task.remind_before}分钟后提醒你"
            )

        elif step == "awaiting_conflict_choice":
            # 等待用户处理冲突：自动顺延/候选时间/仍然创建/取消
            normalized = user_input.strip().lower()
            if normalized in {"自动顺延", "顺延", "下一个空档", "下个空档", "1"}:
                start_time = pending.get("candidate_time")
            elif normalized in {"候选时间", "改到候选时间", "2"}:
                start_time = pending.get("candidate_time")
            elif normalized in {"仍然创建", "继续创建", "强制创建", "3"}:
                start_time = pending.get("task_time")
            else:
                del self._pending_tasks[session_id]
                yield event.plain_result("已取消创建任务")
                event.stop_event()
                return

            task_name = pending["name"]
            duration = pending["duration"]
            repeat = pending.get("repeat")
            task = Task(
                id=str(uuid.uuid4()),
                name=task_name,
                start_time=start_time,
                duration_minutes=duration,
                status="pending",
                remind_before=await self.learning_service.get_remind_preference(
                    task_name, fallback_minutes=self._default_remind_before
                ),
                repeat=repeat,
                created_at=datetime.now(),
                session_origin=session_id,
            )
            await self._finalize_task_creation(task)
            del self._pending_tasks[session_id]

            yield event.plain_result(
                f"✅ 任务已创建\n━━━━━━━━━━━━━━━\n"
                f"📌 {task.name}\n"
                f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M') if task.start_time else '待定'}\n"
                f"⏱️ {TimeParser.format_duration(task.duration_minutes)}\n"
                f"\n💡 {task.remind_before}分钟后提醒你"
            )

        elif step == "awaiting_confirm":
            # 等待用户确认冲突
            if user_input in ["是", "确认", "好的", "添加"]:
                task = pending["task"]
                await self.task_service.create_task(task)
                if task.start_time:
                    await self.reminder_service.schedule_reminder(task)

                del self._pending_tasks[session_id]

                response = f"✅ 任务已创建\n━━━━━━━━━━━━━━━\n📌 {task.name}\n"
                if task.start_time:
                    response += f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}"
                else:
                    response += "⏰ 待定"
                yield event.plain_result(response)
            else:
                del self._pending_tasks[session_id]
                yield event.plain_result("已取消创建任务")

        elif step == "awaiting_learning_reset_confirm":
            if user_input.strip() == "确认重置":
                result = await self.learning_service.reset_learning_data(scope="all")
                del self._pending_tasks[session_id]
                yield event.plain_result(
                    "✅ 已重置全部学习数据。\n"
                    f"{self._format_learning_change(result['before'], result['after'])}"
                )
            else:
                del self._pending_tasks[session_id]
                yield event.plain_result("已取消重置学习数据。")

        # 停止事件传播
        event.stop_event()
