"""
Web UI HTTP 服务器
"""

import asyncio
import logging
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from aiohttp import web

from astrbot.api import logger


@web.middleware
async def cors_middleware(request, handler):
    """CORS 中间件 - 支持跨域请求（移动端访问）"""
    if request.method == "OPTIONS":
        # 处理 preflight 请求
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Max-Age": "86400",
            }
        )
    
    response = await handler(request)
    
    # 添加 CORS 头到所有响应
    if hasattr(response, "headers"):
        response.headers["Access-Control-Allow-Origin"] = "*"
    
    return response


class WebUIServer:
    """Web UI HTTP 服务器"""

    def __init__(
        self,
        task_service,
        storage_service,
        learning_service,
        visualizer,
        port: int = 8099,
        host: str = "0.0.0.0",
        context=None,
        plugin=None,
    ):
        self.task_service = task_service
        self.storage = storage_service
        self.learning_service = learning_service
        self.visualizer = visualizer
        self.port = port
        self.host = host
        self.context = context
        self.plugin = plugin
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running = False

        # 获取静态文件目录
        self.static_dir = Path(__file__).parent / "static"
        self.template_dir = Path(__file__).parent / "templates"

    async def start(self):
        """启动 HTTP 服务器"""
        if self._running:
            logger.warning("WebUI server already running")
            return

        self.app = web.Application(middlewares=[cors_middleware])

        # 注册路由
        self._setup_routes()

        # 添加静态文件支持
        if self.static_dir.exists():
            self.app.router.add_static("/static", self.static_dir, follow_symlinks=True)
            logger.info(f"Serving static files from {self.static_dir}")

        # 启动服务器
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self._site = web.TCPSite(self.runner, self.host, self.port)
        await self._site.start()

        self._running = True
        logger.info(f"WebUI server started at http://{self.host}:{self.port}")

    async def stop(self):
        """停止 HTTP 服务器"""
        if not self._running:
            return

        if self._site:
            await self._site.stop()
        if self.runner:
            await self.runner.cleanup()

        self._running = False
        logger.info("WebUI server stopped")

    def _setup_routes(self):
        """设置路由"""
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/api/tasks", self.handle_get_tasks)
        self.app.router.add_post("/api/tasks", self.handle_create_task)
        self.app.router.add_put("/api/tasks/{task_id}/complete", self.handle_complete_task)
        self.app.router.add_delete("/api/tasks/{task_id}", self.handle_cancel_task)
        self.app.router.add_get("/api/chart", self.handle_chart)
        self.app.router.add_get("/api/stats", self.handle_stats)
        self.app.router.add_post("/api/breakdown", self.handle_breakdown)
        self.app.router.add_post("/api/breakdown/import", self.handle_breakdown_import)

    async def handle_index(self, request: web.Request) -> web.Response:
        """主页"""
        index_file = self.static_dir / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file)
        return web.Response(text="index.html not found", status=404)

    async def handle_get_tasks(self, request: web.Request) -> web.Response:
        """获取任务列表"""
        try:
            from datetime import date, timedelta

            date_text = request.query.get("date", "today")
            today = date.today()

            if date_text == "today":
                days = [today]
            elif date_text == "tomorrow":
                days = [today + timedelta(days=1)]
            elif date_text == "week":
                days = [today + timedelta(days=i) for i in range(7)]
            elif date_text == "next_week":
                days = [today + timedelta(days=i) for i in range(7, 14)]
            else:
                days = [today]

            all_tasks = []
            for d in days:
                daily_tasks = await self.task_service.get_tasks_by_date(d)
                for t in daily_tasks:
                    task_dict = t.to_dict()
                    task_dict["date"] = d.isoformat()
                    all_tasks.append(task_dict)

            # 按日期和时间排序
            all_tasks.sort(key=lambda x: (x.get("date", ""), x.get("start_time", "")))

            return web.json_response({"code": 0, "data": all_tasks})
        except Exception as e:
            logger.error(f"Error getting tasks: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_create_task(self, request: web.Request) -> web.Response:
        """创建任务"""
        try:
            from ..utils.time_parser import TimeParser
            import uuid
            from datetime import datetime

            data = await request.json()
            description = data.get("description", "")

            if not description:
                return web.json_response({"code": 1, "message": "任务描述不能为空"}, status=400)

            # 解析任务信息
            parsed = TimeParser.parse_task_info(description)

            task_name = parsed.get("task_name", "").strip()
            task_time = parsed.get("datetime")
            duration = parsed.get("duration") or 60  # 默认60分钟

            # 如果 task_name 为空或过短，使用原始描述
            if not task_name or len(task_name) < 2:
                task_name = description.strip()

            # 如果没有指定时间，使用当前时间
            if not task_time:
                task_time = datetime.now()

            # 创建任务
            from ..models.task import Task

            task = Task(
                id=str(uuid.uuid4()),
                name=task_name,
                start_time=task_time,
                duration_minutes=duration,
                status="pending",
                remind_before=10,
                created_at=datetime.now(),
                session_origin="webui",
            )

            await self.task_service.create_task(task)

            # 从任务对象中提取日期
            task_date = task.start_time.date().isoformat() if task.start_time else date.today().isoformat()

            return web.json_response({
                "code": 0,
                "message": "任务创建成功",
                "data": {**task.to_dict(), "date": task_date}
            })
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_complete_task(self, request: web.Request) -> web.Response:
        """完成任务"""
        try:
            task_id = request.match_info["task_id"]
            result = await self.task_service.complete_task(task_id)

            if result:
                return web.json_response({"code": 0, "message": "任务已完成"})
            return web.json_response({"code": 1, "message": "任务不存在"}, status=404)
        except Exception as e:
            logger.error(f"Error completing task: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_cancel_task(self, request: web.Request) -> web.Response:
        """取消任务"""
        try:
            task_id = request.match_info["task_id"]
            result = await self.task_service.cancel_task(task_id)

            if result:
                return web.json_response({"code": 0, "message": "任务已取消"})
            return web.json_response({"code": 1, "message": "任务不存在"}, status=404)
        except Exception as e:
            logger.error(f"Error cancelling task: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_chart(self, request: web.Request) -> web.Response:
        """获取日程图表"""
        try:
            from datetime import date, timedelta

            date_text = request.query.get("date", "today")
            style = request.query.get("style", "timeline")
            today = date.today()

            if date_text == "today":
                target_date = today
            elif date_text == "tomorrow":
                target_date = today + timedelta(days=1)
            elif date_text == "week":
                tasks_by_date = {}
                for i in range(7):
                    d = today + timedelta(days=i)
                    tasks_by_date[d] = await self.task_service.get_tasks_by_date(d)
                html = self.visualizer.render_weekly_schedule(tasks_by_date)
                return web.Response(text=html, content_type="text/html", charset="utf-8")
            elif date_text == "next_week":
                tasks_by_date = {}
                for i in range(7, 14):
                    d = today + timedelta(days=i)
                    tasks_by_date[d] = await self.task_service.get_tasks_by_date(d)
                html = self.visualizer.render_weekly_schedule(tasks_by_date)
                return web.Response(text=html, content_type="text/html", charset="utf-8")
            else:
                target_date = today

            tasks = await self.task_service.get_tasks_by_date(target_date)
            html = self.visualizer.render_daily_schedule(tasks, target_date, style=style)

            return web.Response(text=html, content_type="text/html", charset="utf-8")
        except Exception as e:
            logger.error(f"Error rendering chart: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def handle_stats(self, request: web.Request) -> web.Response:
        """获取统计数据"""
        try:
            from datetime import date

            today = date.today()
            tasks = await self.task_service.get_tasks_by_date(today)

            total = len([t for t in tasks if t.status != "cancelled"])
            completed = len([t for t in tasks if t.status == "done"])
            pending = len([t for t in tasks if t.status == "pending"])

            total_minutes = sum(t.duration_minutes or 0 for t in tasks if t.status != "cancelled")
            completed_minutes = sum(t.duration_minutes or 0 for t in tasks if t.status == "done")

            return web.json_response({
                "code": 0,
                "data": {
                    "total": total,
                    "completed": completed,
                    "pending": pending,
                    "completion_rate": int(completed / total * 100) if total > 0 else 0,
                    "total_minutes": total_minutes,
                    "completed_minutes": completed_minutes,
                }
            })
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_breakdown(self, request: web.Request) -> web.Response:
        """拆解任务"""
        try:
            data = await request.json()
            task_name = data.get("task_name", "").strip()
            
            if not task_name:
                return web.json_response({"code": 1, "message": "任务名称不能为空"}, status=400)
            
            # 调用 LLM 进行拆解
            logger.info(f"Breakdown request: plugin={self.plugin}, has_method={hasattr(self.plugin, '_call_llm_breakdown') if self.plugin else 'N/A'}")
            
            if self.plugin and hasattr(self.plugin, '_call_llm_breakdown'):
                # 使用插件的 LLM 方法
                tasks = await self.plugin._call_llm_breakdown(task_name)
                logger.info(f"Breakdown result: {len(tasks)} tasks")
                return web.json_response({
                    "code": 0,
                    "message": "拆解成功",
                    "data": {
                        "task_name": task_name,
                        "tasks": tasks
                    }
                })
            else:
                # 如果没有 LLM 接口，返回手动输入模式
                logger.warning("Plugin or method not available, returning manual mode")
                return web.json_response({
                    "code": 0,
                    "message": "请手动添加子任务",
                    "data": {
                        "task_name": task_name,
                        "tasks": []
                    }
                })
        except Exception as e:
            logger.error(f"Error in breakdown: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    async def handle_breakdown_import(self, request: web.Request) -> web.Response:
        """导入拆解结果到任务"""
        try:
            data = await request.json()
            tasks = data.get("tasks", [])
            
            if not tasks:
                return web.json_response({"code": 1, "message": "没有可导入的任务"}, status=400)
            
            from datetime import datetime, timedelta
            from ..models.task import Task
            imported = []
            
            # 计算默认开始时间：今天下午 6 点
            today = date.today()
            default_start = datetime.combine(today, datetime.min.time()) + timedelta(hours=18)
            
            for i, t in enumerate(tasks):
                task_name = t.get("name", "").strip()
                if not task_name:
                    continue
                # 每个任务间隔 30 分钟
                task_start = default_start + timedelta(minutes=i * 30)
                task = Task(
                    id=str(uuid.uuid4()),
                    name=task_name,
                    start_time=task_start,
                    duration_minutes=t.get("duration", 30),
                    status="pending",
                    remind_before=10,
                    created_at=datetime.now(),
                    session_origin="webui",
                )
                await self.task_service.create_task(task)
                imported.append(task_name)
            
            return web.json_response({
                "code": 0,
                "message": f"已导入 {len(imported)} 个任务",
                "data": {"imported": imported}
            })
        except Exception as e:
            logger.error(f"Error importing breakdown: {e}")
            return web.json_response({"code": 1, "message": str(e)}, status=500)

    def _build_breakdown_prompt(self, task_name: str) -> str:
        """构建任务拆解的 LLM 提示"""
        return f"""请将以下任务拆解成具体可执行的子任务：

任务：{task_name}

拆解要求：
1. 每个子任务控制在 15-30 分钟内
2. 按逻辑顺序排列
3. 用「- 任务名 (时长)」格式

输出格式：
- 任务1 (30分钟)
- 任务2 (20分钟)
- 任务3 (25分钟)

只需要输出任务列表，每行一个任务，格式为「- 任务名 (时长)」，不要输出其他内容。"""
