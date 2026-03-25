"""
可视化渲染器 - 生成日程图片HTML
"""

from typing import List, Dict, Tuple, Any
from datetime import datetime, date, timedelta
from ..models.task import Task


class Visualizer:
    """可视化渲染器"""

    # 任务颜色映射
    TASK_COLORS = {
        "开会": ("#4A90D9", "#E8F4FD"),
        "报告": ("#9B59B6", "#F5E6F5"),
        "代码": ("#27AE60", "#E8F8EE"),
        "写代码": ("#27AE60", "#E8F8EE"),
        "学习": ("#E67E22", "#FDF2E6"),
        "运动": ("#E74C3C", "#FDEDEC"),
        "吃饭": ("#F39C12", "#FEF9E7"),
        "休息": ("#95A5A6", "#F4F6F6"),
        "睡觉": ("#34495E", "#ECF0F1"),
        "阅读": ("#1ABC9C", "#E8F8F5"),
        "写作": ("#D35400", "#FDEBD0"),
        "复习": ("#8E44AD", "#F4ECF7"),
        "考试": ("#C0392B", "#FDEDEC"),
        "面试": ("#2980B9", "#EBF5FB"),
        "项目": ("#E74C3C", "#FADBD8"),
        "default": ("#667EEA", "#EEF2FF"),
    }

    def _get_task_color(self, task_name: str) -> Tuple[str, str]:
        """获取任务对应的颜色"""
        for keyword, colors in self.TASK_COLORS.items():
            if keyword in task_name:
                return colors
        return self.TASK_COLORS["default"]

    def _get_task_emoji(self, task_name: str) -> str:
        """获取任务emoji"""
        emojis = {
            "开会": "💼",
            "报告": "📝",
            "代码": "👨‍💻",
            "写代码": "👨‍💻",
            "学习": "📚",
            "运动": "🏃",
            "吃饭": "🍽️",
            "睡觉": "🛌",
            "休息": "☕",
            "阅读": "📖",
            "写作": "✍️",
            "复习": "📖",
            "考试": "📋",
            "面试": "🎯",
            "电话": "📞",
            "项目": "📁",
        }
        for keyword, emoji in emojis.items():
            if keyword in task_name:
                return emoji
        return "📌"

    def _safe_int(self, value: Any, default: int = 0) -> int:
        """安全转换为整数"""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def render_daily_schedule(self, tasks: List[Task], target_date: date) -> str:
        """渲染今日/指定日期的日程HTML"""

        # 排序任务
        sorted_tasks = sorted(
            [t for t in tasks if t.status != "cancelled"],
            key=lambda x: x.start_time or datetime.max,
        )

        # 统计数据 - 确保类型正确
        total_minutes = self._safe_int(
            sum(self._safe_int(t.duration_minutes) for t in sorted_tasks)
        )
        completed_minutes = self._safe_int(
            sum(
                self._safe_int(t.duration_minutes)
                for t in sorted_tasks
                if t.status == "done"
            )
        )
        total_count = len(sorted_tasks)
        completed_count = len([t for t in sorted_tasks if t.status == "done"])

        # 计算进度
        if total_minutes > 0:
            progress = self._safe_int(
                (self._safe_float(completed_minutes) / self._safe_float(total_minutes))
                * 100
            )
        else:
            progress = 0

        # 可用时间（9:00-22:00 = 13小时 = 780分钟）
        available_minutes = 780
        free_minutes = available_minutes - total_minutes
        free_hours = self._safe_float(free_minutes) / 60 if free_minutes > 0 else 0

        # 生成任务条HTML
        task_rows = []
        for task in sorted_tasks:
            color, bg_color = self._get_task_color(task.name)
            emoji = self._get_task_emoji(task.name)

            start_str = (
                task.start_time.strftime("%H:%M") if task.start_time else "--:--"
            )
            end_dt = (
                task.start_time
                + timedelta(minutes=self._safe_int(task.duration_minutes))
                if task.start_time
                else None
            )
            end_str = end_dt.strftime("%H:%M") if end_dt else "--:--"

            status_icon = "✅" if task.status == "done" else "🔲"

            task_rows.append(f"""
            <div class="task-row" style="margin-bottom: 12px;">
                <div class="task-time">{start_str}</div>
                <div class="task-bar-container">
                    <div class="task-bar" style="background: {bg_color}; border-left: 4px solid {color};">
                        <div class="task-content">
                            <span class="task-emoji">{emoji}</span>
                            <span class="task-name">{task.name}</span>
                            <span class="task-duration">{self._safe_int(task.duration_minutes)}分钟</span>
                            <span class="task-status">{status_icon}</span>
                        </div>
                    </div>
                </div>
                <div class="task-end-time">{end_str}</div>
            </div>
            """)

        task_rows_html = (
            "\n".join(task_rows)
            if task_rows
            else '<div class="no-tasks">暂无任务安排</div>'
        )

        # 周几
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekdays[target_date.weekday()]

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .title {{
            font-size: 24px;
            font-weight: 700;
            color: #333;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .date-badge {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
        }}
        .tasks-container {{
            min-height: 200px;
        }}
        .task-row {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .task-time {{
            font-size: 13px;
            color: #666;
            width: 45px;
            text-align: right;
            font-weight: 500;
        }}
        .task-bar-container {{
            flex: 1;
        }}
        .task-bar {{
            padding: 12px 16px;
            border-radius: 12px;
            transition: transform 0.2s;
        }}
        .task-bar:hover {{
            transform: translateX(4px);
        }}
        .task-content {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .task-emoji {{
            font-size: 18px;
        }}
        .task-name {{
            font-size: 15px;
            color: #333;
            font-weight: 500;
            flex: 1;
        }}
        .task-duration {{
            font-size: 12px;
            color: #666;
            background: rgba(0,0,0,0.05);
            padding: 2px 8px;
            border-radius: 10px;
        }}
        .task-status {{
            font-size: 14px;
        }}
        .task-end-time {{
            font-size: 13px;
            color: #999;
            width: 45px;
        }}
        .no-tasks {{
            text-align: center;
            color: #999;
            padding: 40px;
            font-size: 15px;
        }}
        .stats {{
            margin-top: 24px;
            padding-top: 20px;
            border-top: 2px solid #f0f0f0;
        }}
        .progress-bar {{
            height: 8px;
            background: #f0f0f0;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 12px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 4px;
            transition: width 0.5s ease;
        }}
        .stats-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .stats-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .stats-label {{
            font-size: 13px;
            color: #666;
        }}
        .stats-value {{
            font-size: 15px;
            font-weight: 600;
            color: #333;
        }}
        .free-hint {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        .footer {{
            margin-top: 16px;
            text-align: center;
            font-size: 12px;
            color: #ccc;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                📅 {target_date.strftime("%Y年%m月%d日")}
                <span class="date-badge">{weekday}</span>
            </div>
        </div>
        <div class="tasks-container">
            {task_rows_html}
        </div>
        <div class="stats">
            <div class="progress-bar">
                <div class="progress-fill" style="width: {progress}%;"></div>
            </div>
            <div class="stats-row">
                <div class="stats-item">
                    <span class="stats-label">✅ 已完成</span>
                    <span class="stats-value">{completed_count}/{total_count}</span>
                </div>
                <div class="free-hint">💡 还有 {free_hours:.1f}h 空闲</div>
            </div>
        </div>
        <div class="footer">计划助手</div>
    </div>
</body>
</html>"""

    def render_weekly_schedule(self, tasks_by_date: Dict[date, List[Task]]) -> str:
        """渲染周视图HTML"""

        # 日期范围
        dates = sorted(tasks_by_date.keys())
        if not dates:
            start_date = date.today()
            dates = [start_date + timedelta(days=i) for i in range(7)]

        weekdays = ["一", "二", "三", "四", "五", "六", "日"]

        # 生成每天的任务
        day_columns = []
        for d in dates:
            tasks = tasks_by_date.get(d, [])
            weekday = weekdays[d.weekday()]

            task_items = []
            for task in sorted(tasks, key=lambda x: x.start_time or datetime.max)[:5]:
                color, bg_color = self._get_task_color(task.name)
                emoji = self._get_task_emoji(task.name)
                time_str = (
                    task.start_time.strftime("%H:%M") if task.start_time else "--"
                )
                status = "✅" if task.status == "done" else "🔲"
                task_items.append(f"""
                <div class="week-task" style="background: {bg_color}; border-left: 3px solid {color};">
                    <span>{emoji}</span>
                    <span class="week-task-name">{task.name}</span>
                    <span class="week-task-time">{time_str}</span>
                    {status}
                </div>
                """)

            if not task_items:
                task_items = ['<div class="week-task-empty">休息日</div>']

            date_str = d.strftime("%m/%d")
            is_today = d == date.today()

            day_columns.append(f"""
            <div class="day-column {"today" if is_today else ""}">
                <div class="day-header">
                    <div class="day-date">{date_str}</div>
                    <div class="day-weekday">周{weekday}</div>
                </div>
                <div class="day-tasks">
                    {"".join(task_items)}
                </div>
            </div>
            """)

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .title {{
            font-size: 24px;
            font-weight: 700;
            color: #333;
        }}
        .subtitle {{
            font-size: 14px;
            color: #999;
            margin-top: 4px;
        }}
        .week-grid {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 8px;
        }}
        .day-column {{
            background: #f8f9fa;
            border-radius: 12px;
            padding: 12px;
            min-height: 200px;
        }}
        .day-column.today {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }}
        .day-header {{
            text-align: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(0,0,0,0.1);
        }}
        .day-date {{
            font-size: 16px;
            font-weight: 600;
        }}
        .day-weekday {{
            font-size: 12px;
            opacity: 0.8;
        }}
        .day-tasks {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .week-task {{
            padding: 6px 8px;
            border-radius: 6px;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .week-task-name {{
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .week-task-time {{
            font-size: 10px;
            opacity: 0.7;
        }}
        .week-task-empty {{
            text-align: center;
            color: #999;
            padding: 20px 0;
            font-size: 12px;
        }}
        .footer {{
            margin-top: 20px;
            text-align: center;
            font-size: 12px;
            color: #ccc;
        }}
        @media (max-width: 768px) {{
            .week-grid {{
                grid-template-columns: repeat(4, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">📆 本周日程</div>
            <div class="subtitle">{dates[0].strftime("%Y年%m月%d日")} - {dates[-1].strftime("%Y年%m月%d日")}</div>
        </div>
        <div class="week-grid">
            {"".join(day_columns)}
        </div>
        <div class="footer">计划助手</div>
    </div>
</body>
</html>"""
