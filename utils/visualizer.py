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

    def _render_daily_timeline_items(
        self, tasks: List[Task], min_items: int = 6
    ) -> str:
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
                    <div class="time-start">{start_str}</div>
                    <div class="timeline-time-end">{end_str}</div>
                </div>
                <div class="timeline-dot" style="border-color: {color}; background: {bg_color};"></div>
                <div class="timeline-card{done_class}" style="background: {bg_color};">
                    <div class="task-content">
                        <span class="task-emoji">{emoji}</span>
                        <span class="task-name">{task.name}</span>
                        <span class="task-duration">{self._safe_int(task.duration_minutes)}分钟</span>
                        <span class="task-status">{status_icon}</span>
                    </div>
                </div>
            </div>
            """)

        # 填充空白占位，保持最小数量
        empty_count = max(0, min_items - len(tasks))
        for i in range(empty_count):
            rows.append(f"""
            <div class="timeline-item placeholder">
                <div class="timeline-time">
                    <div class="time-start">--:--</div>
                    <div class="timeline-time-end">--:--</div>
                </div>
                <div class="timeline-dot placeholder-dot"></div>
                <div class="timeline-card placeholder-card"></div>
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

        # 任务数量（用于动态样式和填充判断）
        task_count = len(sorted_tasks)

        if sorted_tasks:
            if resolved_style == "card":
                task_rows_html = self._render_daily_card_items(sorted_tasks)
            elif resolved_style == "compact":
                task_rows_html = self._render_daily_compact_items(sorted_tasks)
            else:
                # 时间轴样式：至少显示6个槽位，不足的用空白占位
                task_rows_html = self._render_daily_timeline_items(
                    sorted_tasks, min_items=6
                )
        else:
            task_rows_html = '<div class="no-tasks">暂无任务安排</div>'

        # 周几
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekdays[target_date.weekday()]

        # 根据任务数量动态调整样式 - 1:2手机比例 720x1440
        task_count = len(sorted_tasks)
        if task_count <= 3:
            # 大尺寸：1-3个任务
            header_pad = 36
            title_size = 60
            badge_size = 28
            item_gap = 20
            time_width = 140
            time_size = 52
            time_end_size = 32
            emoji_size = 64
            name_size = 44
            dur_size = 28
            stat_size = 48
            dot_size = 18
            card_pad = "24px 20px"
            stats_pad = 28
            stats_label = 28
            stats_value = 40
            free_size = 32
        elif task_count <= 6:
            # 中等尺寸：4-6个任务
            header_pad = 28
            title_size = 48
            badge_size = 24
            item_gap = 16
            time_width = 120
            time_size = 44
            time_end_size = 28
            emoji_size = 52
            name_size = 36
            dur_size = 24
            stat_size = 40
            dot_size = 16
            card_pad = "20px 16px"
            stats_pad = 24
            stats_label = 24
            stats_value = 34
            free_size = 28
        elif task_count <= 10:
            # 紧凑尺寸：7-10个任务
            header_pad = 22
            title_size = 40
            badge_size = 20
            item_gap = 12
            time_width = 100
            time_size = 36
            time_end_size = 24
            emoji_size = 42
            name_size = 30
            dur_size = 20
            stat_size = 34
            dot_size = 14
            card_pad = "16px 12px"
            stats_pad = 20
            stats_label = 20
            stats_value = 28
            free_size = 24
        else:
            # 超紧凑尺寸：超过10个任务
            header_pad = 18
            title_size = 34
            badge_size = 18
            item_gap = 8
            time_width = 85
            time_size = 28
            time_end_size = 20
            emoji_size = 34
            name_size = 24
            dur_size = 16
            stat_size = 28
            dot_size = 12
            card_pad = "12px 10px"
            stats_pad = 16
            stats_label = 16
            stats_value = 22
            free_size = 20

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{
            width: 720px;
            height: 1440px;
            overflow: hidden;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            padding: 0;
            margin: 0;
            display: flex;
            align-items: flex-start;
            justify-content: center;
        }}
        .container {{
            background: #ffffff;
            width: 720px;
            height: 1440px;
            color: #1e293b;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            overflow: hidden;
        }}
        .header {{
            padding: {header_pad}px {header_pad * 1.5}px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .titlewrapper {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .title {{
            font-size: {title_size}px;
            font-weight: 800;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 12px;
            letter-spacing: -1px;
        }}
        .date-badge {{
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
            color: #ffffff;
            padding: {badge_size * 0.4}px {badge_size}px;
            border-radius: 20px;
            font-size: {badge_size}px;
            font-weight: 700;
        }}
        .tasks-container {{
            flex: 1;
            padding: {header_pad}px {header_pad}px;
            display: flex;
            flex-direction: column;
            gap: {item_gap}px;
            background: #f8fafc;
            overflow: hidden;
        }}
        .timeline-item {{
            display: flex;
            align-items: center;
            gap: {item_gap}px;
            flex: 1;
            position: relative;
            min-height: 0;
        }}
        .timeline-time {{
            width: {time_width}px;
            min-width: {time_width}px;
            max-width: {time_width}px;
            text-align: center;
            color: #1e293b;
            font-weight: 800;
            background: #ffffff;
            border-radius: 16px;
            padding: 10px 6px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            box-shadow: 0 2px 12px rgba(102, 126, 234, 0.15);
        }}
        .time-start {{
            font-size: {time_size}px;
            line-height: 1.1;
            font-weight: 800;
            color: #1e293b;
        }}
        .time-end {{
            margin-top: 2px;
            font-size: {time_end_size}px;
            color: #94a3b8;
            font-weight: 600;
        }}
        .timeline-dot {{
            width: {dot_size}px;
            min-width: {dot_size}px;
            border-radius: 50%;
            border: 3px solid #667eea;
            position: relative;
            height: {dot_size}px;
            background: #667eea;
            box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.25);
        }}
        .timeline-dot::after {{
            content: "";
            position: absolute;
            top: {dot_size}px;
            left: 50%;
            transform: translateX(-50%);
            width: 2px;
            height: calc(100% + {item_gap}px);
            background: linear-gradient(180deg, #667eea 0%, #e2e8f0 100%);
        }}
        .timeline-item:last-child .timeline-dot::after {{
            display: none;
        }}
        .timeline-card {{
            flex: 1;
            height: 100%;
            padding: {card_pad};
            border-radius: 16px;
            background: #ffffff;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
            display: flex;
            align-items: center;
            overflow: hidden;
        }}
        .task-content {{
            display: flex;
            align-items: center;
            gap: 12px;
            width: 100%;
        }}
        .task-emoji {{
            font-size: {emoji_size}px;
            flex-shrink: 0;
        }}
        .task-name {{
            font-size: {name_size}px;
            color: #1e293b;
            font-weight: 700;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .task-duration {{
            font-size: {dur_size}px;
            color: #64748b;
            background: rgba(102, 126, 234, 0.1);
            padding: 6px 12px;
            border-radius: 8px;
            font-weight: 700;
            white-space: nowrap;
            flex-shrink: 0;
        }}
        .task-status {{
            font-size: {stat_size}px;
            flex-shrink: 0;
        }}
        /* 已完成样式 */
        .timeline-item.done .timeline-time {{
            background: #f1f5f9;
        }}
        .timeline-item.done .time-start {{
            text-decoration: line-through;
            color: #94a3b8;
        }}
        .timeline-item.done .timeline-dot {{
            background: #94a3b8;
            border-color: #94a3b8;
            box-shadow: none;
        }}
        .timeline-item.done .timeline-card {{
            background: #f8fafc;
            opacity: 0.7;
        }}
        .timeline-item.done .task-name {{
            text-decoration: line-through;
            color: #94a3b8;
        }}
        .timeline-item.done .task-emoji, .timeline-item.done .task-duration {{
            opacity: 0.5;
        }}
        /* 空白占位 */
        .timeline-item.placeholder .timeline-time {{
            background: #f1f5f9;
        }}
        .timeline-item.placeholder .time-start {{
            color: #cbd5e1;
        }}
        .timeline-item.placeholder .timeline-dot {{
            background: transparent;
            border-color: #e2e8f0;
            box-shadow: none;
        }}
        .timeline-item.placeholder .timeline-dot::after {{
            background: #e2e8f0;
        }}
        .timeline-item.placeholder .timeline-card {{
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 2px dashed #e2e8f0;
        }}
        .stats {{
            padding: {stats_pad}px {header_pad}px;
            background: #ffffff;
            border-top: 1px solid #e2e8f0;
        }}
        .progress-bar {{
            height: 12px;
            background: rgba(102, 126, 234, 0.1);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 12px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            border-radius: 10px;
        }}
        .stats-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .stats-label {{
            font-size: {stats_label}px;
            color: #64748b;
            font-weight: 600;
        }}
        .stats-value {{
            font-size: {stats_value}px;
            font-weight: 800;
            color: #667eea;
        }}
        .free-hint {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 10px 18px;
            border-radius: 16px;
            font-size: {free_size}px;
            font-weight: 700;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35);
        }}
        .footer {{
            display: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="titlewrapper">
                <div class="title">
                    📅 {target_date.strftime("%Y年%m月%d日")}
                </div>
                <div class="date-badge">{weekday}</div>
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
