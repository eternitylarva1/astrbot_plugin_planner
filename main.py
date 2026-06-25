"""
计划助手插件 - AstrBot插件
智能计划助手，基于 Schedule App 后端 API
"""

import asyncio
import re
import os
import subprocess
import sys
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
  /计划   - 创建日程
  /日程   - 查看日程（今天/明天/本周）
  /完成   - 完成任务
  /取消   - 取消日程
  /待办   - 查看待办列表

📌 智能管理（AI 对话即可操作）：
  支出记录、预算管理、笔记管理

📌 AI 功能：
  /ai规划 - AI 模糊目标规划
  /拆解   - 任务拆解
""",
    "2.1.0",
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
        self._screenshot_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "screenshots"
        )
        os.makedirs(self._screenshot_dir, exist_ok=True)

        logger.info(f"计划助手插件已加载，API: {api_base}")

    async def _get_browser_context(self):
        """获取或创建 Playwright browser context，浏览器缺失时自动安装"""
        if self._browser_context is None:
            pw = await async_playwright().start()
            try:
                self._browser_context = await pw.chromium.launch(headless=True)
            except Exception:
                logger.warning("Playwright 浏览器未安装，正在自动安装 chromium...")
                await self._install_playwright_browser()
                self._browser_context = await pw.chromium.launch(headless=True)
        return self._browser_context

    async def _install_playwright_browser(self):
        """尝试安装 Playwright chromium 浏览器，依次尝试多种命令"""
        commands = [
            ["playwright", "install", "chromium"],
            [sys.executable, "-m", "playwright", "install", "chromium"],
        ]
        last_error = None
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    logger.info(f"Playwright chromium 安装成功: {' '.join(cmd)}")
                    return
                logger.warning(f"命令 {' '.join(cmd)} 失败: {result.stderr.strip() or result.stdout.strip()}")
                last_error = result.stderr or result.stdout or "未知错误"
            except FileNotFoundError:
                logger.warning(f"命令 {' '.join(cmd)} 不存在，尝试下一种...")
                last_error = f"命令 {' '.join(cmd)} 不存在"
            except Exception as e:
                logger.warning(f"命令 {' '.join(cmd)} 异常: {e}")
                last_error = str(e)
        logger.error(f"Playwright 自动安装失败，请手动运行: playwright install chromium")
        raise RuntimeError(f"Playwright 浏览器安装失败: {last_error}")

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
                note_data = None

                if view.startswith("todo_"):
                    main_view = "todo"
                    subview = view.replace("todo_", "")

                is_note_detail = view.startswith("note_")
                if view == "budget" or view == "notes":
                    main_view = "notepad"

                js_code = f"""
                    if (window.ScheduleAppCore && window.ScheduleAppCore.state) {{
                        window.ScheduleAppCore.state.currentView = '{main_view}';
                        window.ScheduleAppCore.state.calendarSubview = '{main_view}';
                """
                if subview:
                    js_code += f"""
                        window.ScheduleAppCore.state.todoSubview = '{subview}';
                    """

                if view == "budget":
                    js_code += """
                        window.ScheduleAppCore.state.notepadSubview = 'expense';
                    """
                elif view == "notes":
                    js_code += """
                        window.ScheduleAppCore.state.notepadSubview = 'notes';
                    """
                elif is_note_detail:
                    note_id_str = view.replace("note_", "")
                    try:
                        note_id = int(note_id_str)
                    except ValueError:
                        note_id = 0
                    if note_id > 0:
                        note_data = await self.api.get_note(note_id)
                    js_code += """
                        window.ScheduleAppCore.state.notepadSubview = 'notes';
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

                # If opening a specific note detail, open it after view renders
                if is_note_detail and note_data:
                    import json
                    note_json = json.dumps(note_data, ensure_ascii=False)
                    detail_js = f"""
                        setTimeout(function() {{
                            if (window.ScheduleAppNoteEditor && window.ScheduleAppNoteEditor.showNoteDetail) {{
                                window.ScheduleAppNoteEditor.showNoteDetail({note_json});
                            }}
                        }}, 800);
                    """
                    await page.evaluate(detail_js)
                    await page.wait_for_timeout(1000)

            screenshot_bytes = await page.screenshot(full_page=False)
            await page.close()

            import uuid

            filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(self._screenshot_dir, filename)
            with open(filepath, "wb") as f:
                f.write(screenshot_bytes)

            return filepath
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

        logger.info(f"create_schedule 调用，user_input={user_input}")

        try:
            result = await self.api.llm_create(user_input)
            logger.info(f"llm_create 返回: {result}")

            if not result:
                yield event.plain_result("❌ 创建失败，请稍后重试或检查后端服务")
                return

            events = result if isinstance(result, list) else [result]
            lines = [f"✅ 已创建 {len(events)} 个日程"]
            for e in events:
                start = e.get("start_time", "待定")
                end = e.get("end_time")
                if start and isinstance(start, str):
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start = dt.strftime("%m-%d %H:%M")
                    except:
                        pass
                if end and isinstance(end, str):
                    try:
                        dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                        end = dt.strftime("%H:%M")
                    except:
                        pass
                    time_str = f"{start}-{end}"
                else:
                    time_str = start
                lines.append(f"• {e.get('title', '未知')} [{time_str}]")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"create_schedule 异常: {e}")
            yield event.plain_result(f"❌ 创建失败: {e}")

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

        if "预算" in text or "支出" in text:
            view = "budget"
        elif "笔记" in text:
            import re as re_mod
            note_match = re_mod.search(r'笔记\s*[:：]?\s*(\d+)', text)
            if note_match:
                view = f"note_{note_match.group(1)}"
            else:
                view = "notes"
        elif "待办" in text:
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

    @filter.command("帮助", alias={"help", "使用说明"})
    async def show_help(self, event: AstrMessageEvent) -> MessageEventResult:
        """显示帮助信息"""
        yield event.plain_result(
            "📋 计划助手 - 帮助\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 创建日程\n"
            "/计划 明天下午3点开会\n\n"
            "📅 查看日程\n"
            "/日程 今日 /日程 明天 /日程 本周\n\n"
            "✅ 完成任务\n"
            "/完成 1\n\n"
            "❌ 取消日程\n"
            "/取消 1 /取消 -1（删除今天全部）\n\n"
            "📋 待办列表\n"
            "/待办\n\n"
            "🤖 AI 规划\n"
            "/ai规划 这周把作品集和算法复习安排一下\n\n"
            "🔨 任务拆解\n"
            "/拆解 完成毕业论文\n\n"
            "📷 可视化图表\n"
            "/图表 今天 /图表 本周\n"
            "/图表 预算 /图表 笔记\n"
            "/图表 笔记:5（指定笔记详情）\n\n"
            "💰 支出管理（AI 可通过对话操作）\n"
            "\"记一笔中午吃饭30元\"\n"
            "\"查一下本月支出\"\n\n"
            "📊 预算管理（AI 可通过对话操作）\n"
            "\"创建预算：餐饮2000元\"\n"
            "\"查看我的预算\"\n\n"
            "📝 笔记管理（AI 可通过对话操作）\n"
            "\"记个笔记：购物清单...\"\n"
            "\"帮我查笔记\"\n"
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

    @filter.command("现状", alias={"我的现状", "个人现状"})
    async def manage_context(self, event: AstrMessageEvent) -> MessageEventResult:
        """管理个人现状

        用法：
        /现状 - 查看所有现状
        /现状 添加 我目前在学Python - 添加现状
        /现状 编辑 1 我目前在学Go - 修改现状
        /现状 删除 1 - 删除现状
        """
        user_input = _strip_cmd(event.message_str, "现状", "我的现状", "个人现状")

        if not user_input:
            # 列出所有现状
            contexts = await self.api.get_user_contexts()
            if contexts is None:
                yield event.plain_result("❌ 获取现状失败")
                return
            if not contexts:
                yield event.plain_result("📋 暂无现状记录\n用法：/现状 添加 <内容>")
                return
            lines = ["📋 我的现状", "━━━━━━━━━━━━━━━"]
            for i, ctx in enumerate(contexts, 1):
                content = ctx.get("content", "")
                lines.append(f"{i}. {content}")
            yield event.plain_result("\n".join(lines))
            return

        parts = user_input.split(maxsplit=1)
        action = parts[0].strip().lower()

        if action == "添加":
            if len(parts) < 2:
                yield event.plain_result("❗请提供现状内容\n用法：/现状 添加 <内容>")
                return
            content = parts[1].strip()
            result = await self.api.create_user_context({"content": content})
            if result:
                yield event.plain_result(f"✅ 已添加现状：{content}")
            else:
                yield event.plain_result("❌ 添加失败")

        elif action == "编辑":
            if len(parts) < 2:
                yield event.plain_result("❗用法：/现状 编辑 <编号> <新内容>")
                return
            edit_parts = parts[1].split(maxsplit=1)
            if len(edit_parts) < 2:
                yield event.plain_result("❗用法：/现状 编辑 <编号> <新内容>")
                return
            try:
                idx = int(edit_parts[0]) - 1
            except ValueError:
                yield event.plain_result("❗编号必须是数字")
                return
            contexts = await self.api.get_user_contexts()
            if not contexts or idx < 0 or idx >= len(contexts):
                yield event.plain_result("❗编号无效")
                return
            ctx_id = contexts[idx].get("id")
            if not ctx_id:
                yield event.plain_result("❌ 编辑失败")
                return
            new_content = edit_parts[1].strip()
            result = await self.api.update_user_context(int(ctx_id), {"content": new_content})
            if result:
                yield event.plain_result(f"✅ 已更新")
            else:
                yield event.plain_result("❌ 编辑失败")

        elif action == "删除":
            if len(parts) < 2:
                yield event.plain_result("❗用法：/现状 删除 <编号>")
                return
            try:
                idx = int(parts[1].strip()) - 1
            except ValueError:
                yield event.plain_result("❗编号必须是数字")
                return
            contexts = await self.api.get_user_contexts()
            if not contexts or idx < 0 or idx >= len(contexts):
                yield event.plain_result("❗编号无效")
                return
            ctx_id = contexts[idx].get("id")
            if not ctx_id:
                yield event.plain_result("❌ 删除失败")
                return
            if await self.api.delete_user_context(int(ctx_id)):
                yield event.plain_result("✅ 已删除")
            else:
                yield event.plain_result("❌ 删除失败")

        else:
            yield event.plain_result(
                "❗操作方式\n\n"
                "/现状 - 查看\n"
                "/现状 添加 <内容>\n"
                "/现状 编辑 <编号> <新内容>\n"
                "/现状 删除 <编号>"
            )

    @filter.llm_tool(name="planner_create")
    async def planner_create(self, event: AstrMessageEvent, description: str) -> str:
        """创建日程

        当用户想创建日程时使用，如"帮我安排明天开会"、"创建日程"。

        Args:
            description(str): 自然语言日程描述，如"明天下午3点开会2小时"
        """
        if not description or not description.strip():
            return "请提供日程描述，如：明天下午3点开会"

        logger.info(f"planner_create 调用，description={description}")

        try:
            result = await self.api.llm_create(description)
            logger.info(f"llm_create 返回: {result}")

            if not result:
                return "❌ 创建失败，请稍后重试或检查后端服务"

            events = result if isinstance(result, list) else [result]
            lines = [f"✅ 已创建 {len(events)} 个日程"]
            for e in events:
                start = e.get("start_time", "待定")
                end = e.get("end_time")
                if start and isinstance(start, str):
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start = dt.strftime("%m-%d %H:%M")
                    except:
                        pass
                if end and isinstance(end, str):
                    try:
                        dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                        end = dt.strftime("%H:%M")
                    except:
                        pass
                    time_str = f"{start}-{end}"
                else:
                    time_str = start
                lines.append(f"• {e.get('title', '未知')} [{time_str}]")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"planner_create 异常: {e}")
            return f"❌ 创建失败: {e}"

    @filter.llm_tool(name="planner_query")
    async def planner_query(
        self,
        event: AstrMessageEvent,
        type: str,
        date_filter: Optional[str] = None,
        horizon: Optional[str] = None,
    ) -> str:
        """查看日程/待办/目标

        Args:
            type(str): 查询类型 - todos/events/goals
            date_filter(str): 日期过滤，如 today/week/month（用于 todos/events）
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

        elif type == "expenses":
            filter_str = date_filter or "month"
            expenses = await self.api.get_expenses(filter_str)
            if expenses is None:
                return "❌ 获取支出记录失败"
            if not expenses:
                return f"💰 {filter_str} 暂无支出记录"
            stats = await self.api.get_expense_stats(filter_str)
            total = stats.get("total", 0) if stats else 0
            lines = [f"💰 支出记录（{filter_str}），总计：{total}元"]
            for e in expenses[:20]:
                cat = e.get("category", "其他") or "其他"
                amt = e.get("amount", 0)
                note = e.get("note", "")
                date = e.get("date", "")[:10] if e.get("date") else ""
                note_str = f" - {note}" if note else ""
                lines.append(f"{date} {cat} {amt}元{note_str}")
            return "\n".join(lines)

        elif type == "budgets":
            budgets = await self.api.get_budgets()
            if budgets is None:
                return "❌ 获取预算失败"
            if not budgets:
                return "📋 暂无预算"
            lines = [f"📊 预算列表（共 {len(budgets)} 项）"]
            for b in budgets:
                name = b.get("name", "未知")
                amount = b.get("amount", 0)
                spent = b.get("spent", 0)
                lines.append(f"{name}: {spent}/{amount}元")
            return "\n".join(lines)

        else:
            return f"❌ 不支持的查询类型：{type}，可选：todos/events/goals/expenses/budgets"

    @filter.llm_tool(name="planner_manage")
    async def planner_manage(
        self,
        event: AstrMessageEvent,
        action: str,
        event_id: Optional[int] = None,
        keyword: Optional[str] = None,
        date_filter: Optional[str] = None,
        expense_id: Optional[int] = None,
        budget_id: Optional[int] = None,
    ) -> str:
        """完成或取消日程/支出/预算

        Args:
            action(str): 操作类型 - complete/cancel/delete_expense/delete_budget
            event_id(int): 日程 ID（complete/cancel时需要）
            keyword(str): 日程名称关键字（用于模糊匹配）
            date_filter(str): 查询日期，支持：
                - today/tomorrow/week/month/all
                - 特定日期如 2026-04-26
                - 自然语言如 明天/下周/本周
            expense_id(int): 支出记录 ID（delete_expense时需要）
            budget_id(int): 预算 ID（delete_budget时需要）
        """
        if action == "delete_expense":
            if not expense_id:
                return "❌ 删除支出需要提供 expense_id"
            if await self.api.delete_expense(expense_id):
                return "✅ 已删除支出记录"
            return "❌ 删除失败"

        if action == "delete_budget":
            if not budget_id:
                return "❌ 删除预算需要提供 budget_id"
            if await self.api.delete_budget(budget_id):
                return "✅ 已删除预算"
            return "❌ 删除失败"

        if action not in ("complete", "cancel"):
            return "❌ action 必须为 complete/cancel/delete_expense/delete_budget"

        filter_str = date_filter or "today"
        events = await self.api.get_events(filter_str)
        if not events:
            return f"📋 {filter_str} 没有日程"

        target_id = event_id
        if not target_id and keyword:
            matched = [e for e in events if keyword in e.get("title", "")]
            if not matched and filter_str == "today":
                events_all = await self.api.get_events("month")
                if events_all:
                    matched = [e for e in events_all if keyword in e.get("title", "")]
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

    @filter.llm_tool(name="planner_expenses")
    async def planner_expenses(
        self,
        event: AstrMessageEvent,
        action: str,
        amount: Optional[float] = None,
        category: Optional[str] = None,
        note: Optional[str] = None,
        expense_id: Optional[int] = None,
        date_filter: Optional[str] = None,
    ) -> str:
        """支出记录管理

        Args:
            action(str): 操作类型
                - list: 列出支出记录（需要 date_filter: today/week/month）
                - create: 记录支出（需要 amount, 可选 category/note）
                - delete: 删除支出（需要 expense_id）
            amount(float): 支出金额（create时需要）
            category(str): 支出分类，如"餐饮/交通/购物/娱乐/其他"
            note(str): 支出备注
            expense_id(int): 支出记录ID（delete时需要）
            date_filter(str): 日期过滤（list时使用：today/week/month）
        """
        if action == "list":
            filter_str = date_filter or "month"
            expenses = await self.api.get_expenses(filter_str)
            if expenses is None:
                return "❌ 获取支出记录失败"
            if not expenses:
                return f"💰 {filter_str} 暂无支出记录"
            stats = await self.api.get_expense_stats(filter_str)
            total = stats.get("total", 0) if stats else 0
            # 分类ID → 中文名映射（显示用）
            _cat_display = {
                "food": "餐饮", "transport": "交通", "shopping": "购物",
                "entertainment": "娱乐", "other": "其他",
            }
            lines = [f"💰 支出记录（{filter_str}），总计：{total}元（共 {len(expenses)} 笔）"]
            for e in expenses[:20]:
                cat_id = e.get("category", "other") or "other"
                cat = _cat_display.get(cat_id, cat_id)
                amt = e.get("amount", 0)
                exp_note = e.get("note", "")
                date = e.get("date", "")[:10] if e.get("date") else ""
                note_str = f" - {exp_note}" if exp_note else ""
                lines.append(f"{date} {cat} {amt}元{note_str}")
            return "\n".join(lines)

        elif action == "create":
            if amount is None:
                return "❌ 记录支出需要提供金额（amount）"
            expense_data = {"amount": amount}
            if category:
                # 将中文分类名映射为英文ID（前端/后端按ID匹配）
                _cat_map = {
                    "餐饮": "food", "交通": "transport", "购物": "shopping",
                    "娱乐": "entertainment", "其他": "other",
                }
                expense_data["category"] = _cat_map.get(category, category)
            if note:
                expense_data["note"] = note
            result = await self.api.create_expense(expense_data)
            if result:
                cat_str = category or "未分类"
                return f"✅ 已记录支出：{amount}元（{cat_str}）"
            return "❌ 记录失败"

        elif action == "delete":
            if not expense_id:
                return "❌ 删除支出需要提供 expense_id"
            if await self.api.delete_expense(expense_id):
                return "✅ 已删除支出记录"
            return "❌ 删除失败"

        else:
            return "❌ action 必须为 list/create/delete"

    @filter.llm_tool(name="planner_budgets")
    async def planner_budgets(
        self,
        event: AstrMessageEvent,
        action: str,
        name: Optional[str] = None,
        amount: Optional[float] = None,
        budget_id: Optional[int] = None,
    ) -> str:
        """预算管理

        Args:
            action(str): 操作类型
                - list: 列出所有预算
                - create: 创建预算（需要 name, amount）
                - view: 查看单个预算详情（需要 budget_id）
                - delete: 删除预算（需要 budget_id）
            name(str): 预算名称（create时需要）
            amount(float): 预算金额（create时需要）
            budget_id(int): 预算ID（view/delete时需要）
        """
        if action == "list":
            budgets = await self.api.get_budgets()
            if budgets is None:
                return "❌ 获取预算失败"
            if not budgets:
                return "📋 暂无预算"
            lines = [f"📊 预算列表（共 {len(budgets)} 项）"]
            for b in budgets:
                b_name = b.get("name", "未知")
                b_amount = b.get("amount", 0)
                b_spent = b.get("spent", 0)
                b_id = b.get("id")
                pct = int(b_spent / b_amount * 100) if b_amount > 0 else 0
                lines.append(f"{b_name}: {b_spent}/{b_amount}元 ({pct}%) [ID:{b_id}]")
            return "\n".join(lines)

        elif action == "create":
            if not name:
                return "❌ 创建预算需要提供名称（name）"
            if amount is None:
                return "❌ 创建预算需要提供金额（amount）"
            budget_data = {"name": name, "amount": amount}
            result = await self.api.create_budget(budget_data)
            if result:
                return f"✅ 已创建预算：{name}（{amount}元）"
            return "❌ 创建失败"

        elif action == "view":
            if not budget_id:
                return "❌ 查看预算需要提供 budget_id"
            budget = await self.api.get_budget(budget_id)
            if not budget:
                return "❌ 预算不存在"
            b_name = budget.get("name", "未知")
            b_amount = budget.get("amount", 0)
            b_spent = budget.get("spent", 0)
            b_id = budget.get("id")
            pct = int(b_spent / b_amount * 100) if b_amount > 0 else 0
            lines = [
                f"📊 预算详情 [ID:{b_id}]",
                f"名称：{b_name}",
                f"预算：{b_amount}元",
                f"已用：{b_spent}元",
                f"进度：{pct}%",
            ]
            return "\n".join(lines)

        elif action == "delete":
            if not budget_id:
                return "❌ 删除预算需要提供 budget_id"
            if await self.api.delete_budget(budget_id):
                return "✅ 已删除预算"
            return "❌ 删除失败"

        else:
            return "❌ action 必须为 list/create/view/delete"

    @filter.llm_tool(name="planner_notes")
    async def planner_notes(
        self,
        event: AstrMessageEvent,
        action: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        note_id: Optional[int] = None,
        query: Optional[str] = None,
    ) -> str:
        """笔记管理

        Args:
            action(str): 操作类型
                - list: 列出所有笔记
                - create: 创建笔记（需要 title, 可选 content）
                - view: 查看笔记内容（需要 note_id）
                - update: 更新笔记（需要 note_id, 可选 title/content）
                - delete: 删除笔记（需要 note_id）
                - search: 搜索笔记（需要 query 关键字）
            title(str): 笔记标题（create时需要）
            content(str): 笔记内容（create/update时可选）
            note_id(int): 笔记ID（view/update/delete时需要）
            query(str): 搜索关键字（search时需要）
        """
        if action == "list":
            notes = await self.api.get_notes()
            if notes is None:
                return "❌ 获取笔记失败"
            if not notes:
                return "📝 暂无笔记"
            lines = [f"📝 笔记列表（共 {len(notes)} 篇）"]
            for n in notes[:20]:
                n_title = n.get("title", "无标题")
                n_id = n.get("id")
                n_updated = n.get("updated_at", "")[:10] if n.get("updated_at") else ""
                lines.append(f"{n_id}. {n_title} [{n_updated}]")
            return "\n".join(lines)

        elif action == "create":
            if not title:
                return "❌ 创建笔记需要提供标题（title）"
            note_data = {"title": title}
            if content:
                note_data["content"] = content
            result = await self.api.create_note(note_data)
            if result:
                return f"✅ 已创建笔记：{title}"
            return "❌ 创建失败"

        elif action == "view":
            if not note_id:
                return "❌ 查看笔记需要提供 note_id"
            note = await self.api.get_note(note_id)
            if not note:
                return "❌ 笔记不存在"
            n_title = note.get("title", "无标题")
            n_content = note.get("content", "")
            n_created = note.get("created_at", "")[:19] if note.get("created_at") else ""
            lines = [f"📝 {n_title}", f"创建于：{n_created}", ""]
            if n_content:
                lines.append(n_content)
            else:
                lines.append("（无内容）")
            return "\n".join(lines)

        elif action == "update":
            if not note_id:
                return "❌ 更新笔记需要提供 note_id"
            note_data = {}
            if title:
                note_data["title"] = title
            if content:
                note_data["content"] = content
            if not note_data:
                return "❌ 请提供要更新的内容（title 或 content）"
            result = await self.api.update_note(note_id, note_data)
            if result:
                return f"✅ 已更新笔记"
            return "❌ 更新失败"

        elif action == "delete":
            if not note_id:
                return "❌ 删除笔记需要提供 note_id"
            if await self.api.delete_note(note_id):
                return "✅ 已删除笔记"
            return "❌ 删除失败"

        elif action == "search":
            if not query:
                return "❌ 搜索笔记需要提供关键字（query）"
            notes = await self.api.get_notes()
            if notes is None:
                return "❌ 获取笔记失败"
            matched = [n for n in notes if query.lower() in (n.get("title", "") + n.get("content", "")).lower()]
            if not matched:
                return f"❌ 没有找到包含「{query}」的笔记"
            lines = [f"🔍 搜索结果（{len(matched)} 篇）"]
            for n in matched[:20]:
                n_title = n.get("title", "无标题")
                n_id = n.get("id")
                lines.append(f"{n_id}. {n_title}")
            return "\n".join(lines)

        else:
            return "❌ action 必须为 list/create/view/update/delete/search"

    @filter.llm_tool(name="planner_context")
    async def planner_context(
        self,
        event: AstrMessageEvent,
        action: str,
        content: Optional[str] = None,
        context_id: Optional[int] = None,
    ) -> str:
        """个人现状管理

        当用户想查看/添加/修改/删除个人现状时使用，如"我目前的状态"、"添加一个现状"。

        Args:
            action(str): 操作类型
                - list: 列出所有现状
                - add: 添加现状（需要 content）
                - update: 修改现状（需要 context_id, content）
                - delete: 删除现状（需要 context_id）
            content(str): 现状内容（add/update时需要）
            context_id(int): 现状ID（update/delete时需要）
        """
        if action == "list":
            contexts = await self.api.get_user_contexts()
            if contexts is None:
                return "❌ 获取现状失败"
            if not contexts:
                return "📋 暂无现状记录"
            lines = ["📋 我的现状", "━━━━━━━━━━━━━━━"]
            for i, ctx in enumerate(contexts, 1):
                lines.append(f"{i}. {ctx.get('content', '')}")
            return "\n".join(lines)

        elif action == "add":
            if not content or not content.strip():
                return "❌ 添加现状需要提供 content"
            result = await self.api.create_user_context({"content": content.strip()})
            if result:
                return f"✅ 已添加现状：{content}"
            return "❌ 添加失败"

        elif action == "update":
            if not context_id:
                return "❌ 修改现状需要提供 context_id"
            if not content or not content.strip():
                return "❌ 修改现状需要提供 content"
            result = await self.api.update_user_context(context_id, {"content": content.strip()})
            if result:
                return f"✅ 已更新现状"
            return "❌ 修改失败"

        elif action == "delete":
            if not context_id:
                return "❌ 删除现状需要提供 context_id"
            if await self.api.delete_user_context(context_id):
                return "✅ 已删除现状"
            return "❌ 删除失败"

        else:
            return "❌ action 必须为 list/add/update/delete"

    async def terminate(self):
        """插件卸载时关闭浏览器"""
        if self._browser_context:
            await self._browser_context.close()
            self._browser_context = None
        logger.info("计划助手插件已卸载")
