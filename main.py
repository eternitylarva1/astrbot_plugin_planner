"""
计划助手插件 - AstrBot插件
智能计划助手，支持自然语言创建任务、定时提醒、可视化日程
"""

import asyncio
import re
import time
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any
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
  2. create_planner_task 工具：一次性提供完整信息，直接创建
  3. list/complete/cancel_planner_task：自然语言查看/完成/取消任务

📌 示例：
  • /计划 明天下午3点写代码2小时
  • /计划 现在做作业1小时
  • create_planner_task("明天上午9点开会1小时")
  • list_planner_tasks("本周")
""",
    "1.0.7",
    "https://github.com/eternitylarva1/astrbot_plugin_planner",
)
class PlannerPlugin(Star):
    """计划助手插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 初始化服务
        self.storage = StorageService("astrbot_plugin_planner")
        self.task_service = TaskService(self.storage)
        self.learning_service = LearningService(self.storage)
        self.scheduler_adapter = AstrBotSchedulerAdapter(context)
        self.reminder_service = ReminderService(
            self.storage, self.task_service, self.scheduler_adapter
        )
        self.visualizer = Visualizer()

        # 从配置读取（WebUI 可视化配置，持久化到 data/config/）
        self.config = config
        self._PENDING_TIMEOUT_SECONDS = config.get("timeout_seconds", 120)
        self._default_remind_before = config.get("remind_before", 10)

        # 状态管理
        self._pending_tasks: Dict[
            str, Dict
        ] = {}  # session_id -> 等待确认的任务（带 pending_at 时间戳）
        self._goal_states: Dict[str, GoalState] = {}  # session_id -> 目标状态

        logger.info("计划助手插件已加载")

    @staticmethod
    def _filter_tasks_by_session(tasks: List[Task], session_origin: str) -> List[Task]:
        """按会话过滤任务，避免跨会话误操作。"""
        if not session_origin:
            return tasks
        return [t for t in tasks if t.session_origin == session_origin]

    async def _get_session_pending_tasks(self, session_origin: str) -> List[Task]:
        """获取当前会话的待办任务。"""
        pending_tasks = await self.task_service.get_pending_tasks()
        return self._filter_tasks_by_session(pending_tasks, session_origin)

    async def _resolve_pending_task(
        self, session_origin: str, target: Optional[str]
    ) -> Optional[Task]:
        """按编号/名称解析当前会话待办任务。"""
        pending_tasks = await self._get_session_pending_tasks(session_origin)
        if not pending_tasks:
            return None

        if not target:
            today_tasks = [
                t for t in pending_tasks if t.start_time and t.start_time.date() == date.today()
            ]
            return today_tasks[0] if today_tasks else pending_tasks[0]

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

    async def _prepare_task_creation(
        self,
        event: AstrMessageEvent,
        task_name: str,
        task_time: datetime,
        duration: int,
        repeat: Optional[str] = None,
        interactive: bool = True,
    ) -> Dict[str, Any]:
        """统一处理创建任务前的冲突检测。

        返回:
        - ok=True 且 task 不为空: 可直接创建
        - ok=False: 已检测到冲突，message 为给用户的提示文案
        """
        conflicts = await self.task_service.check_conflict(task_time, duration)
        if not conflicts:
            task = Task(
                id=str(uuid.uuid4()),
                name=task_name,
                start_time=task_time,
                duration_minutes=duration,
                status="pending",
                remind_before=await self.learning_service.get_remind_preference(
                    task_name
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
                conflict_lines.append(
                    f"• {c.name}（{c.start_time.strftime('%H:%M')}-{c.get_end_time().strftime('%H:%M')}）"
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
        await self.learning_service.record_user_specified_duration(
            task.name, task.duration_minutes
        )

    async def terminate(self):
        """插件卸载时调用"""
        await self.reminder_service.stop()
        logger.info("计划助手插件已卸载")

    async def _render_schedule_by_text(
        self, query_text: str, event: AstrMessageEvent
    ) -> MessageEventResult:
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
        image_url = await self.html_render(html, {})
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
            "/学习 统计"
        )

    # ========== LLM 工具 - AI 智能调用 ==========

    @filter.llm_tool(name="create_planner_task")
    async def create_planner_task(
        self, event: AstrMessageEvent, description: str
    ) -> str:
        """创建计划任务。

        当用户想要安排一个任务时调用此工具，一次性完成创建。
        需要同时提供：任务名称、时间（如"明天下午3点"、"现在"）、时长（如"2小时"）。

        支持的时间表达：今天、明天、下周三、下午3点、15:30、现在、立刻 等。
        支持的时长表达：2小时、30分钟、1小时 等。

        注意：此工具只处理完整信息。如果用户只提供了部分信息，
        请告知用户需要补充哪些信息。也可以让用户使用 /计划 命令进行交互式创建。

        Args:
            description(string): 任务描述，必须包含任务名称、时间和时长。
                例如："明天下午3点写代码2小时"、"现在做毕业设计4小时"。
                如果信息不完整，请告知用户补充。
        """
        user_input = description.strip()
        if not user_input:
            return "请告诉我你要安排什么任务~"

        # 解析任务信息
        parsed = TimeParser.parse_task_info(user_input)
        task_name = parsed["task_name"]
        task_time = parsed["datetime"]
        duration = parsed["duration"]
        repeat = parsed["repeat"]

        # 没有解析出任务名 → 询问
        if not task_name:
            return "请告诉我任务名称是什么？"

        # 清理任务名中的模糊词
        task_name = re.sub(r"(大概|左右|估计|差不多|些许)\s*", "", task_name).strip()

        # 缺少时长 → 提示用户
        if not duration:
            fuzzy_duration = None
            # 尝试提取模糊时长 "大概1小时"
            m = re.search(r"([+-]?\d+\.?\d*)\s*(?:小时|分钟|秒钟)", user_input)
            if m:
                value = float(m.group(1))
                kw_text = user_input[m.start() : m.end()]
                fuzzy_duration = int(value * 60) if "小时" in kw_text else int(value)
            if fuzzy_duration:
                return (
                    f"📝 任务「{task_name}」\n\n"
                    f"你说的大概是 {TimeParser.format_duration(fuzzy_duration)}，具体是多少呢？\n"
                    f"例如：45分钟、1小时\n\n"
                    f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
                )
            return (
                f"📝 任务「{task_name}」\n\n"
                f"请告诉我预计需要多长时间？\n"
                f"例如：1小时、30分钟\n\n"
                f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
            )

        # 缺少时间 → 提示用户
        if not task_time:
            return (
                f"📝 任务「{task_name}」\n"
                f"⏱️ 时长：{TimeParser.format_duration(duration)}\n\n"
                f"请告诉我安排在什么时间？\n"
                f"例如：今天下午3点、明天上午9点、下周三\n\n"
                f"请补充完整后再次调用此工具，或使用 /计划 命令进行交互式创建。"
            )

        auto_shift = any(
            kw in user_input for kw in ["自动顺延", "下一个空档", "下个空档", "顺延"]
        )
        if auto_shift:
            conflicts = await self.task_service.check_conflict(task_time, duration)
            if conflicts:
                task_time = await self.task_service.get_next_available_slot(
                    task_time.date(), duration
                )

        prep = await self._prepare_task_creation(
            event, task_name, task_time, duration, repeat, interactive=False
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
    ) -> str:
        """设置计划助手的配置参数。

        Args:
            timeout_seconds(int): 超时时间，单位为秒。建议范围 60-600 秒（1-10分钟）。
            remind_before(int): 任务开始前多少分钟提醒。
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
            results.append(f"超时时间设置为 {timeout_seconds} 秒")

        if remind_before is not None:
            if remind_before < 0:
                return "提醒时间不能为负数"
            self._default_remind_before = remind_before
            self.config["remind_before"] = remind_before
            await self.config.save_config()
            results.append(f"提前 {remind_before} 分钟提醒")

        if not results:
            return "请提供要设置的参数"

        return "✅ " + " | ".join(results)

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
        self, event: AstrMessageEvent, target: Optional[str] = None
    ) -> str:
        """完成当前会话中的任务（支持编号或名称）。

        Args:
            target(string): 任务编号（如"1"）或任务名关键字；为空时默认完成最近一项。
        """
        task = await self._resolve_pending_task(event.unified_msg_origin, target)
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
    async def cancel_planner_task(self, event: AstrMessageEvent, target: str) -> str:
        """取消当前会话中的任务（支持编号、名称或 all）。

        Args:
            target(string): 任务编号、任务名关键字，或 all/-1（取消当前会话全部待办）。
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

        task = await self._resolve_pending_task(event.unified_msg_origin, target)
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

        yield event.plain_result(f"✅ 超时时间已设置为 {seconds} 秒")

    # ========== 事件监听器 - 处理多轮对话 ==========

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_pending_message(self, event: AstrMessageEvent):
        """处理待确认的消息"""
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
                    "⏰ 抱歉，上次的问题已超时（超过2分钟），已自动取消。\n"
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
                    task_name
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
                f"⏰ {task.start_time.strftime('%Y-%m-%d %H:%M')}\n"
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

        # 停止事件传播
        event.stop_event()
