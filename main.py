"""
计划助手插件 - AstrBot插件
智能计划助手，基于 Schedule App 后端 API
"""

import asyncio
import re
import os
import tempfile
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any

from playwright.async_api import async_playwright

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
from astrbot.api import logger

from .services.api_client import init_api_client, get_api_client


def _strip_cmd(text: str, *aliases: str) -> str:
    """移除消息开头的指令词，返回剩余部分。"""
    if not text:
        return text
    for alias in aliases:
        stripped = re.sub(rf"^(?:/)?{re.escape(alias)}(?:\s+|$)", "", text.strip())
        if stripped != text.strip():
            return stripped.strip()
    return text.strip()


@register(
    "astrbot_plugin_planner",
    "eternitylarva1",
    """智能计划助手

基于 Schedule App 后端，支持自然语言创建日程、AI 任务拆解、目标规划。

📌 核心指令：
  /计划 - 创建日程
  /日程 - 查看日程（今天/明天/本周）
  /完成 - 完成任务
  /取消 - 取消日程
  /待办 - 查看待办列表

📌 AI 功能：
  /ai规划 - AI 模糊目标规划
  /拆解 - 任务拆解
""",
    "1.0.0",
    "https://github.com/eternitylarva1/astrbot_plugin_planner",
)
class PlannerPlugin(Star):
    """计划助手插件 - 基于 Schedule App API"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self.config = config
        self._context = context

        api_base = config.get("schedule_api_base", "http://localhost:8080")
        init_api_client(api_base)
        self.api = get_api_client()

        self._frontend_url = config.get("frontend_url", "http://localhost:8080")
        self._screenshot_enabled = config.get("enable_screenshot", True)
        self._browser_context = None

        logger.info(f"计划助手插件已加载，API: {api_base}")

    async def _get_browser_context(self):
        """获取或创建 Playwright browser context"""
        if self._browser_context is None:
            pw = await async_playwright().start()
            self._browser_context = await pw.chromium.launch(headless=True)
        return self._browser_context

    async def _render_schedule_screenshot(self, view: str = "day") -> Optional[str]:
        """使用 Playwright 渲染日程截图。

        Args:
            view: 支持多种视图组合
                - 日历: day, week, month
                - 待办: todo_all, todo_today, todo_week, todo_month
                - 目标: goals
                - 记事本: notepad

        Returns:
            图片 URL 或 None
        """
        if not self._screenshot_enabled:
            return None

        url = self._frontend_url
        try:
            browser = await self._get_browser_context()
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(500)

            if view != "day":
                main_view = view
                subview = None

                if view.startswith("todo_"):
                    main_view = "todo"
                    subview = view.replace("todo_", "")

                js_code = f"""
                    if (window.ScheduleAppCore && window.ScheduleAppCore.state) {{
                        window.ScheduleAppCore.state.currentView = '{main_view}';
                        window.ScheduleAppCore.state.calendarSubview = '{main_view}';
                """
                if subview:
                    js_code += f"""
                        window.ScheduleAppCore.state.todoSubview = '{subview}';
                    """
                js_code += (
                    """
                    }
                    if (window.switchView) {
                        window.switchView('"""
                    + main_view
                    + """');
                    }
                """
                )
                await page.evaluate(js_code)
                await page.wait_for_timeout(1500)

            screenshot_bytes = await page.screenshot(full_page=False)
            await page.close()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(screenshot_bytes)
                temp_path = os.path.abspath(f.name)

            return temp_path
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    @staticmethod
    def _parse_date_filter(text: str) -> str:
        """解析日期文本为 filter 字符串。"""
        text = text.strip().lower()
        if "本周" in text:
            return "week"
        elif "下周" in text:
            return "week"
        elif "明天" in text:
            return "today"
        elif "后天" in text:
            return "today"
        elif "本月" in text:
            return "month"
        elif any(
            w in text for w in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        ):
            return "week"
        else:
            return "today"

    @filter.command("计划", alias={"创建日程", "新建日程", "添加日程", "安排"})
    async def create_schedule(self, event: AstrMessageEvent) -> MessageEventResult:
        """创建日程

        用法：
        /计划 明天下午3点开会
        /计划 明天上午9点写代码2小时
        /计划 现在做作业
        """
        user_input = _strip_cmd(
            event.message_str, "计划", "创建日程", "新建日程", "添加日程", "安排"
        )

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/计划 <日程描述>\n"
                "示例：\n"
                "• /计划 明天下午3点开会\n"
                "• /计划 明天上午9点写代码2小时\n"
                "• /计划 今天晚上复习1小时"
            )
            return

        yield event.plain_result("🔄 正在创建日程...")

        result = await self.api.llm_create(user_input)
        if not result:
            yield event.plain_result("❌ 创建失败，请稍后重试或检查后端服务")
            return

        events = result if isinstance(result, list) else [result]
        lines = [f"✅ 已创建 {len(events)} 个日程"]
        for e in events:
            start = e.get("start_time", "待定")
            if start and isinstance(start, str):
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start = dt.strftime("%m-%d %H:%M")
                except:
                    pass
            lines.append(f"• {e.get('title', '未知')} [{start}]")

        yield event.plain_result("\n".join(lines))

    @filter.command("日程", alias={"查看日程", "任务", "日", "周程"})
    async def view_schedule(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看日程

        用法：
        /日程 今日
        /日程 明天
        /日程 本周
        """
        user_input = _strip_cmd(
            event.message_str, "日程", "查看日程", "任务", "日", "周程"
        )
        date_filter = self._parse_date_filter(user_input) if user_input else "today"

        yield event.plain_result("🔄 加载中...")

        events = await self.api.get_events(date_filter)
        if events is None:
            yield event.plain_result("❌ 获取日程失败，请检查后端服务")
            return

        if not events:
            yield event.plain_result("📋 暂无日程")
            return

        lines = [f"📅 日程列表（{date_filter}）"]
        for e in events:
            start = e.get("start_time")
            if start:
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start_str = dt.strftime("%m-%d %H:%M")
                except:
                    start_str = str(start)[:16]
            else:
                start_str = "待定"

            status = "✓" if e.get("status") == "done" else "○"
            title = e.get("title", "未知")
            lines.append(f"{status} {title} [{start_str}]")

        yield event.plain_result("\n".join(lines))

    @filter.command("图表", alias={"可视化", "截图"})
    async def view_chart(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看可视化图表

        用法：
        /图表 今天/本周/本月
        /图表 日历/待办/目标
        /图表 日历本周/待办本周
        """
        user_input = _strip_cmd(event.message_str, "图表", "可视化", "截图")

        view = "day"
        text = user_input.strip().lower()

        if "待办" in text:
            if "本周" in text:
                view = "todo_week"
            elif "今天" in text or "今日" in text:
                view = "todo_today"
            elif "本月" in text:
                view = "todo_month"
            else:
                view = "todo_all"
        elif "目标" in text or "goals" in text:
            view = "goals"
        elif "记事" in text or "notepad" in text:
            view = "notepad"
        elif "本周" in text or "周" in text:
            view = "week"
        elif "本月" in text or "月" in text:
            view = "month"
        elif "今天" in text or "今日" in text:
            view = "day"

        yield event.plain_result("🔄 生成图表...")

        image_url = await self._render_schedule_screenshot(view)
        if image_url:
            yield event.image_result(image_url)
        else:
            yield event.plain_result("❌ 截图失败，请检查前端服务")

    @filter.command("完成", alias={"done", "已完成"})
    async def complete_schedule(self, event: AstrMessageEvent) -> MessageEventResult:
        """完成任务

        用法：
        /完成 1
        /完成 开会
        """
        user_input = _strip_cmd(event.message_str, "完成", "done", "已完成")

        if not user_input:
            yield event.plain_result("❗请指定要完成的任务编号或名称")
            return

        events = await self.api.get_events("today")
        if not events:
            yield event.plain_result("📋 今天没有待办任务")
            return

        pending = [e for e in events if e.get("status") != "done"]

        event_id = None
        try:
            idx = int(user_input) - 1
            if 0 <= idx < len(pending):
                event_id = pending[idx].get("id")
            else:
                yield event.plain_result(f"编号 {user_input} 不存在")
                return
        except ValueError:
            matched = [e for e in pending if user_input in e.get("title", "")]
            if not matched:
                yield event.plain_result(f"没有找到包含「{user_input}」的任务")
                return
            event_id = matched[0].get("id")

        if not event_id:
            yield event.plain_result("❌ 任务ID无效")
            return

        result = await self.api.complete_event(event_id)
        if result:
            yield event.plain_result(f"✅ 已完成：{result.get('title', '')}")
        else:
            yield event.plain_result("❌ 操作失败")

    @filter.command("取消", alias={"删除日程", "删除任务", "remove"})
    async def cancel_schedule(self, event: AstrMessageEvent) -> MessageEventResult:
        """取消/删除日程

        用法：
        /取消 1
        /取消 开会
        /取消 -1（删除今天全部）
        """
        user_input = _strip_cmd(
            event.message_str, "取消", "删除日程", "删除任务", "remove"
        )

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/取消 <编号|名称|-1>\n"
                "示例：\n"
                "• /取消 1\n"
                "• /取消 开会\n"
                "• /取消 -1（删除今天全部）"
            )
            return

        if user_input == "-1":
            events = await self.api.get_events("today")
            if events:
                count = 0
                for e in events:
                    if e.get("id"):
                        await self.api.delete_event(e["id"])
                        count += 1
                yield event.plain_result(f"❌ 已删除 {count} 个日程")
            else:
                yield event.plain_result("📋 今天没有日程")
            return

        events = await self.api.get_events("today")
        if not events:
            yield event.plain_result("📋 没有日程")
            return

        event_id = None
        try:
            idx = int(user_input) - 1
            if 0 <= idx < len(events):
                event_id = events[idx].get("id")
            else:
                yield event.plain_result(f"编号 {user_input} 不存在")
                return
        except ValueError:
            matched = [e for e in events if user_input in e.get("title", "")]
            if not matched:
                yield event.plain_result(f"没有找到包含「{user_input}」的日程")
                return
            event_id = matched[0].get("id")

        if not event_id:
            yield event.plain_result("❌ 日程ID无效")
            return

        if await self.api.delete_event(event_id):
            yield event.plain_result("❌ 已取消")
        else:
            yield event.plain_result("❌ 操作失败")

    @filter.command("待办", alias={"todo", "待办列表", "任务列表"})
    async def list_todo(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看待办列表"""
        events = await self.api.get_events("month")
        if events is None:
            yield event.plain_result("❌ 获取失败，请检查后端服务")
            return

        pending = [e for e in events if e.get("status") != "done"]
        if not pending:
            yield event.plain_result("📋 没有待办")
            return

        lines = [f"📋 待办列表（共 {len(pending)} 项）"]
        for i, e in enumerate(pending[:20], 1):
            start = e.get("start_time", "")
            if start:
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start_str = dt.strftime("%m-%d %H:%M")
                except:
                    start_str = str(start)[:16]
            else:
                start_str = "待定"
            lines.append(f"{i}. {e.get('title', '未知')} [{start_str}]")

        yield event.plain_result("\n".join(lines))

    @filter.command("ai规划", alias={"智能规划", "规划一下", "auto_plan"})
    async def ai_plan(self, event: AstrMessageEvent) -> MessageEventResult:
        """AI 模糊目标规划

        用法：
        /ai规划 这周把作品集和算法复习安排一下
        """
        user_input = _strip_cmd(
            event.message_str, "ai规划", "智能规划", "规划一下", "auto_plan"
        )

        if not user_input:
            yield event.plain_result(
                "请告诉我想做什么，我来帮你规划：\n"
                "示例：/ai规划 这周把作品集和算法复习安排一下"
            )
            return

        yield event.plain_result("🔄 AI 规划中...")

        result = await self.api.llm_breakdown(user_input, horizon="short")
        if not result:
            yield event.plain_result("❌ AI 处理失败，请稍后重试")
            return

        subtasks = result.get("subtasks", [])
        if not subtasks:
            message = result.get("message", "无法生成规划")
            yield event.plain_result(f"💬 {message}")
            return

        lines = ["🤖 AI 规划建议", "━━━━━━━━━━━━━━━"]
        for i, st in enumerate(subtasks[:10], 1):
            title = st.get("title", "未知")
            date_str = st.get("date", "")
            time_str = st.get("start_time", "")
            duration = st.get("duration_minutes", 30)
            lines.append(f"{i}. {title}")
            if date_str or time_str:
                lines.append(f"   {date_str} {time_str} ({duration}分钟)")

        lines.append("")
        lines.append("💡 如需导入日程，请说「导入」或「创建」")

        yield event.plain_result("\n".join(lines))

    @filter.command("拆解", alias={"分解", "任务拆解"})
    async def breakdown_task(self, event: AstrMessageEvent) -> MessageEventResult:
        """任务拆解

        用法：
        /拆解 完成毕业论文
        /拆解 准备技术面试
        """
        user_input = _strip_cmd(event.message_str, "拆解", "分解", "任务拆解")

        if not user_input:
            yield event.plain_result(
                "❗参数缺失\n"
                "用法：/拆解 <任务名称>\n"
                "示例：\n"
                "• /拆解 完成毕业论文\n"
                "• /拆解 准备技术面试"
            )
            return

        yield event.plain_result("🔄 正在拆解...")

        result = await self.api.llm_breakdown(user_input.strip(), horizon="short")
        if not result:
            yield event.plain_result("❌ 拆解失败，请稍后重试")
            return

        subtasks = result.get("subtasks", [])
        if not subtasks:
            message = result.get("message", "无法拆解")
            yield event.plain_result(f"💬 {message}")
            return

        lines = [f"📋 任务拆解：{user_input}", "", "序号 | 任务 | 时长"]
        lines.append("-" * 40)
        total = 0
        for i, st in enumerate(subtasks[:10], 1):
            title = st.get("title", "未知")
            duration = st.get("duration_minutes", 30)
            total += duration
            lines.append(f"{i} | {title} | {duration}分钟")
        lines.append("-" * 40)
        lines.append(f"共 {len(subtasks)} 项，约 {total} 分钟")

        yield event.plain_result("\n".join(lines))

    @filter.command("统计", alias={"stats", "完成率"})
    async def view_stats(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看完成率统计

        用法：
        /统计 今天
        /统计 本周
        """
        user_input = _strip_cmd(event.message_str, "统计", "stats", "完成率")
        date_filter = self._parse_date_filter(user_input) if user_input else "today"

        stats = await self.api.get_stats(date_filter)
        if not stats:
            yield event.plain_result("❌ 获取统计失败")
            return

        total = stats.get("total", 0)
        completed = stats.get("completed", 0)
        pending = stats.get("pending", 0)
        rate = stats.get("completion_rate", 0)

        by_cat = stats.get("by_category", {})
        cat_names = {"work": "工作", "life": "生活", "study": "学习", "health": "健康"}

        lines = [
            f"📊 {date_filter} 统计",
            "━━━━━━━━━━━━━━━",
            f"总日程：{total}",
            f"已完成：{completed}",
            f"待完成：{pending}",
            f"完成率：{rate}%",
        ]

        if by_cat:
            lines.append("")
            lines.append("按分类：")
            for cat_id, count in by_cat.items():
                name = cat_names.get(cat_id, cat_id)
                lines.append(f"  • {name}: {count}")

        yield event.plain_result("\n".join(lines))

    @filter.command("帮助", alias={"help", "使用说明"})
    async def show_help(self, event: AstrMessageEvent) -> MessageEventResult:
        """显示帮助信息"""
        yield event.plain_result(
            "📋 计划助手 - 帮助\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 创建日程\n"
            "/计划 明天下午3点开会\n"
            "/计划 明天上午9点写代码2小时\n\n"
            "📅 查看日程\n"
            "/日程 今日 /日程 明天 /日程 本周\n\n"
            "📊 统计\n"
            "/统计 今天 /统计 本周\n\n"
            "✅ 完成任务\n"
            "/完成 1\n\n"
            "❌ 取消日程\n"
            "/取消 1 /取消 -1（删除今天全部）\n\n"
            "📋 待办列表\n"
            "/待办\n\n"
            "🤖 AI 规划\n"
            "/ai规划 这周把作品集和算法复习安排一下\n\n"
            "📋 任务拆解\n"
            "/拆解 完成毕业论文\n\n"
            "📷 可视化图表\n"
            "/图表 今天 /图表 本周\n"
        )

    @filter.command("设置", alias={"config"})
    async def show_settings(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看/修改设置"""
        user_input = _strip_cmd(event.message_str, "设置", "config")

        settings = await self.api.get_settings()
        if not settings:
            yield event.plain_result("❌ 获取设置失败")
            return

        lines = ["⚙️ 当前设置", "━━━━━━━━━━━━━━━"]
        for key, value in settings.items():
            if key in ["schedule_api_base", "frontend_url"]:
                continue
            lines.append(f"{key}: {value}")

        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(name="planner_create")
    async def planner_create(self, event: AstrMessageEvent, description: str) -> str:
        """创建日程

        当用户想创建日程时使用，如"帮我安排明天开会"、"创建日程"。

        Args:
            description(str): 自然语言日程描述，如"明天下午3点开会2小时"
        """
        if not description or not description.strip():
            return "请提供日程描述，如：明天下午3点开会"
        result = await self.api.llm_create(description)
        if not result:
            return "❌ 创建失败，请稍后重试"
        events = result if isinstance(result, list) else [result]
        lines = [f"✅ 已创建 {len(events)} 个日程"]
        for e in events:
            start = e.get("start_time", "待定")
            if start and isinstance(start, str):
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start = dt.strftime("%m-%d %H:%M")
                except:
                    pass
            lines.append(f"• {e.get('title', '未知')} [{start}]")
        return "\n".join(lines)

    @filter.llm_tool(name="planner_query")
    async def planner_query(
        self,
        event: AstrMessageEvent,
        type: str,
        date_filter: Optional[str] = None,
        horizon: Optional[str] = None,
    ) -> str:
        """查看日程/待办/统计/目标

        Args:
            type(str): 查询类型 - todos/stats/events/goals
            date_filter(str): 日期过滤，如 today/week/month（用于 todos/stats/events）
            horizon(str): 规划范围，如 short/semester/long（用于 goals）
        """
        if type == "todos":
            events = await self.api.get_events("month")
            if events is None:
                return "❌ 获取失败，请检查后端服务"
            pending = [e for e in events if e.get("status") != "done"]
            if not pending:
                return "📋 没有待办"
            lines = [f"📋 待办列表（共 {len(pending)} 项）"]
            for i, e in enumerate(pending[:20], 1):
                start = e.get("start_time", "")
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start_str = dt.strftime("%m-%d %H:%M")
                    except:
                        start_str = str(start)[:16]
                else:
                    start_str = "待定"
                lines.append(f"{i}. {e.get('title', '未知')} [{start_str}]")
            return "\n".join(lines)

        elif type == "stats":
            filter_str = date_filter or "today"
            stats = await self.api.get_stats(filter_str)
            if not stats:
                return "❌ 获取统计失败"
            total = stats.get("total", 0)
            completed = stats.get("completed", 0)
            rate = stats.get("completion_rate", 0)
            return f"📊 {filter_str} 统计\n总日程：{total}\n已完成：{completed}\n完成率：{rate}%"

        elif type == "events":
            filter_str = date_filter or "today"
            events = await self.api.get_events(filter_str)
            if events is None:
                return "❌ 获取日程失败"
            if not events:
                return f"📋 {filter_str} 暂无日程"
            lines = [f"📅 日程列表（{filter_str}）"]
            for e in events:
                start = e.get("start_time", "")
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start_str = dt.strftime("%m-%d %H:%M")
                    except:
                        start_str = str(start)[:16]
                else:
                    start_str = "待定"
                status = "✓" if e.get("status") == "done" else "○"
                lines.append(f"{status} {e.get('title', '未知')} [{start_str}]")
            return "\n".join(lines)

        elif type == "goals":
            horizon_str = horizon or "short"
            goals = await self.api.get_goals(horizon_str)
            if goals is None:
                return "❌ 获取目标失败"
            if not goals:
                return f"📋 暂无 {horizon_str} 目标"
            lines = [f"🎯 目标列表（{horizon_str}）"]
            for g in goals[:10]:
                status = "✓" if g.get("status") == "done" else "○"
                lines.append(f"{status} {g.get('title', '未知')}")
            return "\n".join(lines)

        else:
            return f"❌ 不支持的查询类型：{type}，可选：todos/stats/events/goals"

    @filter.llm_tool(name="planner_manage")
    async def planner_manage(
        self,
        event: AstrMessageEvent,
        action: str,
        event_id: Optional[int] = None,
        keyword: Optional[str] = None,
    ) -> str:
        """完成或取消日程

        Args:
            action(str): 操作类型 - complete/cancel
            event_id(int): 日程 ID（可选）
            keyword(str): 日程名称关键字（用于模糊匹配）
        """
        if action not in ("complete", "cancel"):
            return "❌ action 必须为 complete 或 cancel"

        events = await self.api.get_events("today")
        if not events:
            return "📋 今天没有日程"

        target_id = event_id
        if not target_id and keyword:
            matched = [e for e in events if keyword in e.get("title", "")]
            if not matched:
                return f"❌ 没有找到包含「{keyword}」的日程"
            target_id = matched[0].get("id")

        if not target_id:
            return "❌ 请提供 event_id 或 keyword"

        if action == "complete":
            result = await self.api.complete_event(target_id)
            if result:
                return f"✅ 已完成：{result.get('title', '')}"
            return "❌ 操作失败"

        else:
            if await self.api.delete_event(target_id):
                return "❌ 已取消"
            return "❌ 操作失败"

    @filter.llm_tool(name="planner_ai_plan")
    async def planner_ai_plan(
        self,
        event: AstrMessageEvent,
        intention: str,
        horizon: str = "short",
    ) -> str:
        """AI 模糊目标规划

        当用户说"帮我安排一下"、"规划一下"等模糊意图时使用。

        Args:
            intention(str): 用户目标描述，如"这周把作品集和算法复习安排一下"
            horizon(str): 规划范围 - short/semester/long
        """
        if not intention or not intention.strip():
            return "请提供目标描述，如：帮我安排这周的学习计划"
        result = await self.api.llm_breakdown(intention, horizon)
        if not result:
            return "❌ AI 处理失败，请稍后重试"
        subtasks = result.get("subtasks", [])
        if not subtasks:
            return f"💬 {result.get('message', '无法生成规划')}"
        lines = ["🤖 AI 规划建议", "━━━━━━━━━━━━━━━"]
        for i, st in enumerate(subtasks[:10], 1):
            title = st.get("title", "未知")
            date_str = st.get("date", "")
            time_str = st.get("start_time", "")
            duration = st.get("duration_minutes", 30)
            lines.append(f"{i}. {title}")
            if date_str or time_str:
                lines.append(f"   {date_str} {time_str} ({duration}分钟)")
        return "\n".join(lines)

    @filter.llm_tool(name="planner_breakdown")
    async def planner_breakdown(
        self,
        event: AstrMessageEvent,
        task_name: str,
        horizon: str = "short",
    ) -> str:
        """任务拆解

        将大任务拆解为可执行的小任务。

        Args:
            task_name(str): 要拆解的任务名称
            horizon(str): 规划范围 - short/semester/long
        """
        if not task_name or not task_name.strip():
            return "请提供要拆解的任务名称"
        result = await self.api.llm_breakdown(task_name.strip(), horizon)
        if not result:
            return "❌ 拆解失败，请稍后重试"
        subtasks = result.get("subtasks", [])
        if not subtasks:
            return f"💬 {result.get('message', '无法拆解')}"
        lines = [f"📋 任务拆解：{task_name}", "", "序号 | 任务 | 时长"]
        lines.append("-" * 40)
        total = 0
        for i, st in enumerate(subtasks[:10], 1):
            title = st.get("title", "未知")
            duration = st.get("duration_minutes", 30)
            total += duration
            lines.append(f"{i} | {title} | {duration}分钟")
        lines.append("-" * 40)
        lines.append(f"共 {len(subtasks)} 项，约 {total} 分钟")
        return "\n".join(lines)

    async def terminate(self):
        """插件卸载时关闭浏览器"""
        if self._browser_context:
            await self._browser_context.close()
            self._browser_context = None
        logger.info("计划助手插件已卸载")
