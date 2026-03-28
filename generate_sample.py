"""
生成图表样本HTML文件 - 现代UI设计风格
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
                    <div class="time-start">{task['time']}</div>
                    <div class="time-end">{task['end']}</div>
                </div>
                <div class="timeline-card">
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
        item_gap = 24
        card_padding = "28px 24px"
        time_font_size = 56
        time_end_font_size = 36
        emoji_font_size = 36
        name_font_size = 40
        duration_font_size = 24
        status_font_size = 32
    elif task_count <= 10:
        item_gap = 18
        card_padding = "24px 20px"
        time_font_size = 48
        time_end_font_size = 32
        emoji_font_size = 32
        name_font_size = 36
        duration_font_size = 22
        status_font_size = 28
    else:
        item_gap = 14
        card_padding = "20px 18px"
        time_font_size = 40
        time_end_font_size = 28
        emoji_font_size = 28
        name_font_size = 32
        duration_font_size = 20
        status_font_size = 24
    
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
            border-radius: 28px;
            padding: 32px 28px 24px;
            box-shadow: 
                0 10px 40px -10px rgba(0, 0, 0, 0.1),
                0 6px 20px -6px rgba(0, 0, 0, 0.08);
            width: min(96vw, 900px);
            min-height: min(96vh, 1680px);
            aspect-ratio: 1 / 2;
            margin: 0 auto;
            color: #1e293b;
            display: flex;
            flex-direction: column;
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
            color: #64748b;
            font-weight: 600;
            background: #f1f5f9;
            border-radius: 16px;
            padding: 16px 12px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            box-shadow: 0 2px 8px rgba(99, 102, 241, 0.06);
        }}
        .time-start {{
            font-size: {time_font_size}px;
            font-weight: 700;
            color: #1e293b;
            line-height: 1.2;
        }}
        .time-end {{
            font-size: {time_end_font_size}px;
            color: #94a3b8;
            font-weight: 500;
            margin-top: 4px;
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
                gap: 12px;
            }}
            .title {{
                font-size: 32px;
            }}
            .task-name {{
                font-size: 24px;
            }}
            .stats-row {{
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
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
