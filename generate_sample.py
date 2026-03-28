"""
生成图表样本HTML文件
"""
from datetime import datetime, date, timedelta


def generate_sample():
    """生成样本HTML文件"""
    # 创建示例任务数据（6个任务，填满页面）
    today = date.today()
    
    # 任务数据
    tasks_data = [
        {"name": "晨间会议", "time": "09:00", "end": "10:00", "duration": 60, "status": "pending"},
        {"name": "代码开发", "time": "10:30", "end": "12:30", "duration": 120, "status": "done"},
        {"name": "午餐休息", "time": "13:00", "end": "14:00", "duration": 60, "status": "pending"},
        {"name": "项目评审", "time": "14:30", "end": "16:00", "duration": 90, "status": "pending"},
        {"name": "文档编写", "time": "16:30", "end": "17:30", "duration": 60, "status": "pending"},
        {"name": "学习新技术", "time": "18:00", "end": "19:30", "duration": 90, "status": "pending"},
    ]
    
    # 生成任务HTML
    task_rows_html = ""
    for i, task in enumerate(tasks_data):
        status_icon = "✅" if task["status"] == "done" else "🔲"
        task_rows_html += f"""
            <div class="timeline-item">
                <div class="timeline-time">
                    <div>{task['time']}</div>
                    <div class="timeline-time-end">{task['end']}</div>
                </div>
                <div class="timeline-dot" style="border-color: #667eea; background: #EEF2FF;"></div>
                <div class="timeline-card" style="background: #EEF2FF; border-left: 4px solid #667eea;">
                    <div class="task-content">
                        <span class="task-emoji">📌</span>
                        <span class="task-name">{task['name']}</span>
                        <span class="task-duration">{task['duration']}分钟</span>
                        <span class="task-status">{status_icon}</span>
                    </div>
                </div>
            </div>
        """
    
    # 周几
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekdays[today.weekday()]
    
    # 任务数量
    task_count = len(tasks_data)
    if task_count <= 6:
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
    
    # 生成完整HTML
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            background: transparent;
            padding: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: #ffffff;
            border-radius: 24px;
            padding: 24px 24px 18px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.16);
            width: min(96vw, 900px);
            min-height: min(96vh, 1680px);
            aspect-ratio: 1 / 2;
            margin: 0 auto;
            color: #1f2937;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .title {{
            font-size: 46px;
            font-weight: 700;
            color: #111827;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .date-badge {{
            background: #eef2ff;
            color: #3730a3;
            padding: 8px 18px;
            border-radius: 24px;
            font-size: 22px;
            font-weight: 700;
        }}
        .tasks-container {{
            min-height: 0;
            flex: 1;
            padding-top: 4px;
            display: flex;
            flex-direction: column;
            gap: {item_gap}px;
        }}
        .timeline-item {{
            display: flex;
            align-items: stretch;
            gap: 14px;
            flex: 1;
            position: relative;
        }}
        .timeline-time {{
            width: 20%;
            text-align: center;
            font-size: {time_font_size}px;
            color: #374151;
            font-weight: 700;
            padding-top: 4px;
            border: 2px solid #e5e7eb;
            border-radius: 12px;
            background: #f9fafb;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }}
        .timeline-time-end {{
            margin-top: 4px;
            font-size: {time_end_font_size}px;
            color: #999;
        }}
        .timeline-dot {{
            width: {dot_size}px;
            min-width: {dot_size}px;
            border-radius: 50%;
            border: {dot_border}px solid #667eea;
            position: relative;
            margin-top: 12px;
            height: {dot_size}px;
        }}
        .timeline-dot::after {{
            content: "";
            position: absolute;
            top: {dot_size}px;
            left: 50%;
            transform: translateX(-50%);
            width: 2px;
            height: calc(100% + {item_gap}px);
            background: #eceff5;
        }}
        .timeline-item:last-child .timeline-dot::after {{
            display: none;
        }}
        .timeline-card {{
            flex: 1;
            height: 100%;
            padding: {card_padding};
            border-radius: 14px;
            display: flex;
            align-items: center;
        }}
        .task-content {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .task-emoji {{
            font-size: {emoji_font_size}px;
        }}
        .task-name {{
            font-size: {name_font_size}px;
            color: #111827;
            font-weight: 700;
            flex: 1;
        }}
        .task-duration {{
            font-size: {duration_font_size}px;
            color: #374151;
            background: rgba(0,0,0,0.05);
            padding: 7px 14px;
            border-radius: 12px;
            font-weight: 700;
        }}
        .task-status {{
            font-size: {status_font_size}px;
        }}
        .stats {{
            margin-top: 14px;
            padding-top: 14px;
            border-top: 2px solid #f0f0f0;
        }}
        .progress-bar {{
            height: 16px;
            background: #f0f0f0;
            border-radius: 8px;
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
            gap: 8px;
        }}
        .stats-label {{
            font-size: 24px;
            color: #4b5563;
            font-weight: 700;
        }}
        .stats-value {{
            font-size: 34px;
            font-weight: 600;
            color: #111827;
        }}
        .free-hint {{
            background: linear-gradient(135deg, #4f46e5, #9333ea);
            color: white;
            padding: 14px 22px;
            border-radius: 22px;
            font-size: 24px;
            font-weight: 700;
        }}
        .footer {{
            margin-top: 10px;
            text-align: center;
            font-size: 18px;
            color: #b5b8c2;
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
                padding: 22px 16px;
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
                📅 {today.strftime("%Y年%m月%d日")}
                <span class="date-badge">{weekday}</span>
            </div>
            <div class="date-badge">样式：时间轴</div>
        </div>
        <div class="tasks-container">
            {task_rows_html}
        </div>
        <div class="stats">
            <div class="progress-bar">
                <div class="progress-fill" style="width: 17%;"></div>
            </div>
            <div class="stats-row">
                <div class="stats-item">
                    <span class="stats-label">✅ 已完成</span>
                    <span class="stats-value">1/6</span>
                </div>
                <div class="free-hint">💡 还有 6.5h 空闲</div>
            </div>
        </div>
        <div class="footer">计划助手</div>
    </div>
</body>
</html>"""
    
    # 保存到文件
    output_path = "sample_schedule.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"样本HTML已生成到: {output_path}")
    print(f"包含 {len(tasks_data)} 个任务")
    print("请在浏览器中打开查看效果")


if __name__ == "__main__":
    generate_sample()
