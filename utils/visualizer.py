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

    def _render_daily_timeline_items(self, tasks: List[Task]) -> str:
        """渲染日视图：时间轴样式（默认）"""
        rows = []
        for task in tasks:
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
            is_done = task.status == "done"
            done_class = " done" if is_done else ""
            rows.append(f"""
            <div class="timeline-item{done_class}">
                <div class="timeline-time">
                    <div>{start_str}</div>
                    <div class="timeline-time-end">{end_str}</div>
                </div>
                <div class="timeline-dot" style="border-color: {color}; background: {bg_color};"></div>
                <div class="timeline-card{done_class}" style="background: {bg_color}; border-left: 4px solid {color};">
                    <div class="task-content">
                        <span class="task-emoji">{emoji}</span>
                        <span class="task-name">{task.name}</span>
                        <span class="task-duration">{self._safe_int(task.duration_minutes)}分钟</span>
                        <span class="task-status">{status_icon}</span>
                    </div>
                </div>
            </div>
            """)
        return "\n".join(rows)

    def _render_daily_card_items(self, tasks: List[Task]) -> str:
        """渲染日视图：卡片样式"""
        cards = []
        for task in tasks:
            color, bg_color = self._get_task_color(task.name)
            emoji = self._get_task_emoji(task.name)
            time_str = task.start_time.strftime("%H:%M") if task.start_time else "--:--"
            status_icon = "✅" if task.status == "done" else "🔲"
            cards.append(f"""
            <div class="daily-card" style="background:{bg_color}; border-top:4px solid {color};">
                <div class="daily-card-head">
                    <span>{emoji} {task.name}</span>
                    <span>{status_icon}</span>
                </div>
                <div class="daily-card-meta">
                    <span>⏰ {time_str}</span>
                    <span>⏱️ {self._safe_int(task.duration_minutes)}分钟</span>
                </div>
            </div>
            """)
        return "\n".join(cards)

    def _render_daily_compact_items(self, tasks: List[Task]) -> str:
        """渲染日视图：紧凑样式"""
        items = []
        for task in tasks:
            color, _ = self._get_task_color(task.name)
            emoji = self._get_task_emoji(task.name)
            time_str = task.start_time.strftime("%H:%M") if task.start_time else "--:--"
            status_icon = "✅" if task.status == "done" else "🔲"
            items.append(f"""
            <div class="compact-item">
                <span class="compact-color" style="background:{color};"></span>
                <span>{emoji} {task.name}</span>
                <span class="compact-meta">{time_str} · {self._safe_int(task.duration_minutes)}分钟 · {status_icon}</span>
            </div>
            """)
        return "\n".join(items)

    def render_daily_schedule(
        self, tasks: List[Task], target_date: date, style: str = "timeline"
    ) -> str:
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

        style_alias = {
            "timeline": "timeline",
            "vertical": "timeline",
            "card": "card",
            "compact": "compact",
        }
        resolved_style = style_alias.get((style or "").lower(), "timeline")

        if sorted_tasks:
            if resolved_style == "card":
                task_rows_html = self._render_daily_card_items(sorted_tasks)
            elif resolved_style == "compact":
                task_rows_html = self._render_daily_compact_items(sorted_tasks)
            else:
                task_rows_html = self._render_daily_timeline_items(sorted_tasks)
        else:
            task_rows_html = '<div class="no-tasks">暂无任务安排</div>'

        # 周几
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekdays[target_date.weekday()]

        # 根据任务数量动态调整样式
        task_count = len(sorted_tasks)
        if task_count <= 6:
            # 大尺寸：5-6个任务填满页面
            item_gap = 20
            card_padding = "24px 20px"
            time_font_size = 68
            time_end_font_size = 42
            emoji_font_size = 34
            name_font_size = 38
            duration_font_size = 22
            status_font_size = 30
            dot_size = 16
            dot_border = 3
        elif task_count <= 10:
            # 中等尺寸：7-10个任务
            item_gap = 16
            card_padding = "20px 18px"
            time_font_size = 51
            time_end_font_size = 34
            emoji_font_size = 32
            name_font_size = 34
            duration_font_size = 20
            status_font_size = 28
            dot_size = 15
            dot_border = 3
        else:
            # 紧凑尺寸：超过10个任务
            item_gap = 12
            card_padding = "16px 16px"
            time_font_size = 38
            time_end_font_size = 25
            emoji_font_size = 30
            name_font_size = 30
            duration_font_size = 18
            status_font_size = 26
            dot_size = 14
            dot_border = 3

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{
            width: 100%;
            height: 100%;
            overflow: hidden;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            background: transparent;
            padding: 0;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: #ffffff;
            border-radius: 28px;
            padding: 32px 28px 24px;
            box-shadow:
                0 10px 40px -10px rgba(0, 0, 0, 0.1),
                0 6px 20px -6px rgba(0, 0, 0, 0.08);
            width: 100vw;
            height: 100vh;
            aspect-ratio: 1 / 2;
            margin: 0;
            color: #1e293b;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid rgba(99, 102, 241, 0.08);
        }}
        .title {{
            font-size: 48px;
            font-weight: 700;
            color: #1e293b;
            display: flex;
            align-items: center;
            gap: 12px;
            letter-spacing: -0.5px;
        }}
        .date-badge {{
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            color: #ffffff;
            padding: 10px 24px;
            border-radius: 20px;
            font-size: 24px;
            font-weight: 600;
            box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
        }}
        .tasks-container {{
            min-height: 0;
            flex: 1;
            padding-top: 8px;
            display: flex;
            flex-direction: column;
            gap: {item_gap}px;
        }}
        .timeline-item {{
            display: flex;
            align-items: stretch;
            gap: 20px;
            flex: 1;
            position: relative;
        }}
        .timeline-time {{
            width: 20%;
            text-align: center;
            color: #1e293b;
            font-weight: 700;
            background: #e2e8f0;
            border-radius: 16px;
            padding: 16px 12px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            box-shadow: 0 2px 8px rgba(99, 102, 241, 0.06);
        }}
        .timeline-time-end {{
            margin-top: 4px;
            font-size: {time_end_font_size}px;
            color: #475569;
            font-weight: 600;
        }}
        .timeline-dot {{
            width: {dot_size}px;
            min-width: {dot_size}px;
            border-radius: 50%;
            border: {dot_border}px solid #667eea;
            position: relative;
            margin-top: 12px;
            height: {dot_size}px;
            box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.3);
        }}
        .timeline-dot::after {{
            content: "";
            position: absolute;
            top: {dot_size}px;
            left: 50%;
            transform: translateX(-50%);
            width: 2px;
            height: calc(100% + {item_gap}px);
            background: #e5e7eb;
        }}
        .timeline-item:last-child .timeline-dot::after {{
            display: none;
        }}
        .timeline-card {{
            flex: 1;
            height: 100%;
            padding: {card_padding};
            border-radius: 20px;
            border: 1px solid rgba(99, 102, 241, 0.08);
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            box-shadow:
                0 4px 12px rgba(0, 0, 0, 0.08),
                0 2px 6px rgba(0, 0, 0, 0.04);
            display: flex;
            align-items: center;
            transition: all 0.3s ease;
        }}
        .timeline-card:hover {{
            transform: translateY(-2px);
            box-shadow:
                0 8px 20px rgba(0, 0, 0, 0.12),
                0 4px 8px rgba(0, 0, 0, 0.06);
        }}
        .task-content {{
            display: flex;
            align-items: center;
            gap: 16px;
            width: 100%;
        }}
        .task-emoji {{
            font-size: {emoji_font_size}px;
            filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.1));
        }}
        .task-name {{
            font-size: {name_font_size}px;
            color: #1e293b;
            font-weight: 600;
            flex: 1;
            letter-spacing: -0.3px;
        }}
        .task-duration {{
            font-size: {duration_font_size}px;
            color: #64748b;
            background: rgba(99, 102, 241, 0.08);
            padding: 8px 16px;
            border-radius: 12px;
            font-weight: 600;
            white-space: nowrap;
        }}
        .task-status {{
            font-size: {status_font_size}px;
            filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.1));
        }}
        /* 已完成任务样式：变暗、缩小 */
        .timeline-item.done {{
            flex: 0.6;
        }}
        .timeline-item.done .timeline-time {{
            opacity: 0.5;
            filter: grayscale(0.3);
        }}
        .timeline-item.done .timeline-time > div {{
            font-size: 0.7em;
        }}
        .timeline-item.done .timeline-dot {{
            opacity: 0.4;
            filter: grayscale(0.5);
        }}
        .timeline-card.done {{
            opacity: 0.5;
            filter: grayscale(0.3);
            transform: scale(0.95);
        }}
        .timeline-item.done .task-emoji {{
            opacity: 0.6;
            filter: grayscale(0.3);
        }}
        .timeline-item.done .task-name {{
            opacity: 0.6;
            font-size: 0.85em;
            text-decoration: line-through;
        }}
        .timeline-item.done .task-duration {{
            opacity: 0.5;
            font-size: 0.8em;
        }}
        .timeline-item.done .task-status {{
            opacity: 0.7;
            font-size: 0.85em;
        }}
        .daily-card {{
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 12px;
        }}
        .daily-card-head {{
            display: flex;
            justify-content: space-between;
            font-size: 22px;
            font-weight: 600;
            color: #111827;
        }}
        .daily-card-meta {{
            margin-top: 10px;
            display: flex;
            justify-content: space-between;
            color: #374151;
            font-size: 17px;
            font-weight: 700;
        }}
        .compact-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px 14px;
            margin-bottom: 10px;
            background: #f8f9fa;
            border-radius: 10px;
            font-size: 20px;
            color: #111827;
            font-weight: 700;
        }}
        .compact-color {{
            width: 8px;
            height: 24px;
            border-radius: 4px;
            display: inline-block;
        }}
        .compact-meta {{
            margin-left: auto;
            color: #374151;
            font-size: 15px;
            font-weight: 700;
        }}
        .no-tasks {{
            text-align: center;
            color: #999;
            padding: 80px 40px;
            font-size: 30px;
        }}
        .stats {{
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid rgba(99, 102, 241, 0.08);
        }}
        .progress-bar {{
            height: 12px;
            background: rgba(99, 102, 241, 0.08);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 16px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
            border-radius: 10px;
            transition: width 0.6s ease;
            box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
        }}
        .stats-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .stats-item {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .stats-label {{
            font-size: 22px;
            color: #64748b;
            font-weight: 600;
        }}
        .stats-value {{
            font-size: 32px;
            font-weight: 700;
            color: #1e293b;
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            padding: 4px 16px;
            border-radius: 12px;
        }}
        .free-hint {{
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            color: white;
            padding: 12px 24px;
            border-radius: 16px;
            font-size: 22px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
        }}
        .footer {{
            margin-top: 16px;
            text-align: center;
            font-size: 16px;
            color: #94a3b8;
            font-weight: 500;
        }}
        @media (max-width: 768px) {{
            body {{
                align-items: flex-start;
                padding: 0;
            }}
            .container {{
                width: 100vw;
                min-height: 100vh;
                aspect-ratio: auto;
                border-radius: 0;
                padding: 20px 16px;
            }}
            .header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 8px;
            }}
            .title {{
                font-size: 30px;
            }}
            .task-name {{
                font-size: 20px;
            }}
            .stats-row {{
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }}
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
            <div class="date-badge">样式：{"时间轴" if resolved_style == "timeline" else "卡片" if resolved_style == "card" else "紧凑"}</div>
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
            padding: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: #ffffff;
            border-radius: 24px;
            padding: 28px;
            box-shadow: 0 16px 46px rgba(15, 23, 42, 0.28);
            width: 96vw;
            max-width: 760px;
            min-height: 92vh;
            margin: 0 auto;
            color: #1f2937;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .title {{
            font-size: 30px;
            font-weight: 700;
            color: #111827;
        }}
        .subtitle {{
            font-size: 16px;
            color: #6b7280;
            margin-top: 4px;
            font-weight: 700;
        }}
        .week-grid {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 8px;
        }}
        .day-column {{
            background: #f8f9fa;
            border-radius: 14px;
            padding: 14px;
            min-height: 280px;
            color: #1f2937;
        }}
        .day-column.today {{
            background: #eef2ff;
            color: #1f2937;
            border: 2px solid #667eea;
        }}
        .day-header {{
            text-align: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(31, 41, 55, 0.12);
        }}
        .day-date {{
            font-size: 18px;
            font-weight: 700;
        }}
        .day-weekday {{
            font-size: 14px;
            opacity: 0.9;
            font-weight: 700;
        }}
        .day-tasks {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .week-task {{
            padding: 10px 10px;
            border-radius: 8px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 4px;
            color: #1f2937;
            font-weight: 700;
        }}
        .week-task-name {{
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .week-task-time {{
            font-size: 12px;
            opacity: 0.9;
            color: #4b5563;
            font-weight: 700;
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
                grid-template-columns: 1fr;
            }}
            body {{
                align-items: flex-start;
            }}
            .container {{
                width: 100vw;
                min-height: 100vh;
                border-radius: 0;
                padding: 16px;
            }}
            .title {{
                font-size: 24px;
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
