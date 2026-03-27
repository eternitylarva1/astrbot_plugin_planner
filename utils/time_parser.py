import re
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any


class TimeParser:
    """时间解析工具"""

    # 时间段到小时的映射
    TIME_PERIODS = {
        "早上": (6, 9),
        "上午": (9, 12),
        "中午": (11, 13),
        "下午": (13, 18),
        "傍晚": (17, 19),
        "晚上": (18, 22),
        "深夜": (22, 24),
        "凌晨": (0, 6),
    }

    # 星期映射
    WEEKDAYS = {
        "今天": 0,
        "明天": 1,
        "后天": 2,
        "大后天": 3,
        "周一": 0,
        "星期一": 0,
        "周二": 1,
        "星期二": 1,
        "周三": 2,
        "星期三": 2,
        "周四": 3,
        "星期四": 3,
        "周五": 4,
        "星期五": 4,
        "周六": 5,
        "星期六": 5,
        "周日": 6,
        "星期日": 6,
        "星期天": 6,
    }

    # 循环模式
    REPEAT_PATTERNS = {
        "每天": "daily",
        "每日": "daily",
        "每周": "weekly",
        "每周一": "weekly",
        "每个工作日": "workdays",
        "工作日": "workdays",
        "每月": "monthly",
        "每月1号": "monthly",
    }

    @classmethod
    def parse_duration(cls, text: str) -> Optional[int]:
        """解析时长（分钟数），无法解析时返回 None。"""
        text_lower = text.strip().lower()
        text_lower = (
            text_lower.replace("一个小时", "1小时")
            .replace("一小时", "1小时")
            .replace("一个钟头", "1小时")
            .replace("半小时", "30分钟")
        )

        # 先匹配范围时长（例如：2-3小时、2~3小时、2到3小时）
        range_match = re.search(
            r"(\d+\.?\d*)\s*(?:-|~|—|到|至)\s*(\d+\.?\d*)\s*(小时|分钟|秒钟|h|min|天|周)",
            text_lower,
        )
        if range_match:
            # 对范围时长取上限，避免低估任务占用时段
            value = max(float(range_match.group(1)), float(range_match.group(2)))
            unit = range_match.group(3)
            if unit in ("小时", "h"):
                return int(value * 60)
            if unit == "天":
                return int(value * 60 * 24)
            if unit == "周":
                return int(value * 60 * 24 * 7)
            return int(value)

        # 先尝试匹配时长（数字 + 单位）
        dur_match = re.search(r"(\d+\.?\d*)\s*(?:小时|分钟|秒钟|h|min|天|周)", text_lower)
        if dur_match:
            value = float(dur_match.group(1))
            kw = dur_match.group(0)
            if "小时" in kw or "h" in kw:
                return int(value * 60)
            elif "天" in kw:
                return int(value) * 60 * 24
            elif "周" in kw:
                return int(value) * 60 * 24 * 7
            else:
                return int(value)

        # 匹配 "X点半"
        half_match = re.search(r"(\d+)\s*(?:点半|点30)", text_lower)
        if half_match:
            return 30

        # 匹配 "X刻钟" 或 "一刻钟"
        quarter_match = re.search(r"(?:一刻钟|一刻|(\d+)\s*刻钟)", text_lower)
        if quarter_match:
            return 15

        return None

    @classmethod
    def parse_datetime(
        cls, text: str, reference_date: Optional[date] = None
    ) -> Optional[datetime]:
        """解析日期时间

        Args:
            text: 待解析的文本
            reference_date: 参考日期，默认为今天

        Returns:
            datetime对象，如果无法解析返回None
        """
        if reference_date is None:
            reference_date = date.today()

        text_lower = text.strip().lower()
        today = reference_date

        # ---- 立即时间词（优先检测，返回当前时刻）----
        immediate_kws = ["现在", "立刻", "马上", "立即", "此时", "此刻"]
        for kw in immediate_kws:
            if kw in text_lower:
                return datetime.combine(reference_date, datetime.now().time())

        # ---- 确定基准日期 ----
        base_date = today
        found_date = False

        # 显式月日：3月28日 / 3月28号
        md_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text_lower)
        if md_match:
            month = int(md_match.group(1))
            day = int(md_match.group(2))
            try:
                base_date = date(today.year, month, day)
                found_date = True
            except ValueError:
                pass

        abs_dates = {
            "今天": 0, "明天": 1, "后天": 2, "大后天": 3,
            "昨天": -1, "前天": -2,
        }
        if not found_date:
            for kw, delta in abs_dates.items():
                idx = text_lower.find(kw)
                if idx != -1:
                    base_date = today + timedelta(days=delta)
                    found_date = True
                    break

        weekday_kws = [
            "周一", "星期一", "周二", "星期二", "周三", "星期三",
            "周四", "星期四", "周五", "星期五", "周六", "星期六",
            "周日", "星期天", "星期日",
        ]
        if not found_date:
            weekday_prefixes = {"下", "这", "本", "上"}
            for kw in weekday_kws:
                idx = text_lower.find(kw)
                if idx != -1:
                    if idx == 0 or text_lower[idx - 1] in weekday_prefixes or not (
                        "\u4e00" <= text_lower[idx - 1] <= "\u9fff"
                    ):
                        weekday = cls.WEEKDAYS.get(kw, 0)
                        days_ahead = (weekday - today.weekday()) % 7
                        if days_ahead == 0:
                            days_ahead = 7
                        base_date = today + timedelta(days=days_ahead)
                        found_date = True
                        break

        # ---- 提取时间文本：从日期关键词位置开始 ----
        all_date_kws = [r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]?"] + list(abs_dates.keys()) + weekday_kws
        time_text = text_lower
        for kw in all_date_kws:
            m = re.search(kw, text_lower)
            if m:
                time_text = text_lower[m.start():].strip()
                break

        # ---- 解析时间（只在 time_text 中匹配）----
        hour: Optional[int] = None
        minute = 0

        # 中午 + X点/X:XX（优先于通用 HH:MM，避免被提前匹配为凌晨/上午时刻）
        if hour is None and "中午" in time_text:
            hour = 12
            minute = 0
            m = re.search(
                r"中午(?:\s*(\d{1,2})(?:\s*[点时](?:(\d{1,2})\s*分?)?|:(\d{2}))?)?",
                time_text,
            )
            if m and m.group(1):
                h = int(m.group(1))
                if 0 <= h <= 23:
                    if h == 12:
                        hour = 12
                    elif h < 12:
                        hour = h + 12
                    else:
                        hour = h

                if m.group(2):
                    mn = int(m.group(2))
                    if 0 <= mn <= 59:
                        minute = mn
                elif m.group(3):
                    mn = int(m.group(3))
                    if 0 <= mn <= 59:
                        minute = mn

        # HH:MM
        m = re.search(r"(\d{1,2}):(\d{2})", time_text)
        if hour is None and m:
            h = int(m.group(1))
            mn = int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                hour = h
                minute = mn

        # 上午/早上 + X点
        for prefix in ["上午", "早上"]:
            if hour is None:
                m = re.search(rf"{prefix}\s*(\d{{1,2}})(?::(\d{{2}}))?", time_text)
                if m:
                    h = int(m.group(1))
                    mn = int(m.group(2)) if m.group(2) else 0
                    if 0 <= h <= 23:
                        hour = 0 if h == 12 else h
                        minute = mn

        # 下午 + X点
        if hour is None:
            m = re.search(r"下午\s*(\d{1,2})点(?::(\d{2}))?", time_text)
            if m:
                h = int(m.group(1))
                mn = int(m.group(2)) if m.group(2) else 0
                if 0 <= h <= 23:
                    hour = h if h >= 12 else h + 12
                    minute = mn

        # 晚上 + X点（要求数字后紧跟"点"，避免误匹配）
        if hour is None:
            m = re.search(r"晚上\s*(\d{1,2})点(?::(\d{2}))?", time_text)
            if m:
                h = int(m.group(1))
                mn = int(m.group(2)) if m.group(2) else 0
                if 0 <= h <= 23:
                    hour = h if h >= 12 else h + 12
                    minute = mn

        # 凌晨 + X点
        if hour is None:
            m = re.search(r"凌晨\s*(\d{1,2})(?::(\d{2}))?", time_text)
            if m:
                h = int(m.group(1))
                mn = int(m.group(2)) if m.group(2) else 0
                if 0 <= h <= 23:
                    hour = h
                    minute = mn

        # X点Y分（无前缀）
        if hour is None:
            m = re.search(r"(\d{1,2})\s*[点时]\s*(\d{1,2})\s*分?", time_text)
            if m:
                h = int(m.group(1))
                mn = int(m.group(2))
                if 0 <= h <= 23 and 0 <= mn <= 59:
                    hour = h
                    minute = mn

        # X点（无前缀）
        if hour is None:
            m = re.search(r"(\d{1,2})\s*[点时](?:\s*分)?", time_text)
            if m:
                h = int(m.group(1))
                if 0 <= h <= 23:
                    hour = h
                    minute = 0

        # 有日期但无具体时间 → 默认上午9点
        if hour is None and found_date:
            hour, minute = 9, 0

        if hour is None:
            return None

        return datetime.combine(base_date, datetime.min.time().replace(hour=hour, minute=minute))

    @classmethod
    def parse_task_info(cls, text: str) -> Dict[str, Any]:
        """解析任务信息

        从文本中提取任务名称、时间和时长

        Returns:
            dict: {
                'task_name': str,
                'datetime': datetime or None,
                'duration': int or None,  # 分钟
                'repeat': str or None
            }
        """
        result = {"task_name": "", "datetime": None, "duration": None, "repeat": None}

        # 移除常见前缀（包括中文冒号和「任务」「日程」等）
        text = re.sub(r"^(?:安排|计划|添加|创建|任务|日程)\s*[:：]\s*", "", text)
        text = re.sub(r"^(?:安排|计划|添加|创建|任务|日程)\s*", "", text)

        # 解析重复模式
        for pattern_name, repeat_type in cls.REPEAT_PATTERNS.items():
            if pattern_name in text:
                result["repeat"] = repeat_type
                text = text.replace(pattern_name, "").strip()
                break

        # 解析时长
        duration = cls.parse_duration(text)
        if duration:
            result["duration"] = duration
            # 从文本中移除时长部分（支持区间和整数/小数）
            text = re.sub(
                r"[\d.]+\s*(?:-|~|—|到|至)\s*[\d.]+\s*(?:小时|h|个时|分钟|min|分|天|周)\s*",
                "",
                text,
            )
            text = re.sub(
                r"[\d.]+\s*(?:小时|h|个时|分钟|min|分|点半|点30|刻钟|一刻钟|天|周)\s*",
                "",
                text,
            ).strip()

        # 解析日期时间
        dt = cls.parse_datetime(text)
        if dt:
            result["datetime"] = dt
            # 尝试提取任务名
            result["task_name"] = cls._extract_task_name(text)
        else:
            # 没有日期时间，整个文本作为任务名
            result["task_name"] = text.strip()

        # 清理任务名
        result["task_name"] = result["task_name"].strip("_-、，。")

        return result

    @classmethod
    def _extract_task_name(cls, text: str) -> str:
        """从包含时间的文本中提取任务名"""
        # 移除日期时间部分
        name = text

        # 移除时间相关词汇
        time_keywords = [
            "今天",
            "明天",
            "后天",
            "周一",
            "周二",
            "周三",
            "周四",
            "周五",
            "周六",
            "周日",
            "早上",
            "上午",
            "中午",
            "下午",
            "傍晚",
            "晚上",
            "凌晨",
            r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]?",
            r"\d{1,2}:\d{2}",
            r"\d{1,2}\s*(?:点|时)",
        ]
        for kw in time_keywords:
            name = re.sub(kw, "", name)

        # 移除时长与常见上下文词
        name = re.sub(
            r"[\d.]+\s*(?:-|~|—|到|至)\s*[\d.]+\s*(?:小时|分钟|秒钟|h|min|天|周)",
            "",
            name,
        )
        name = re.sub(r"[\d.]+\s*(?:小时|分钟|秒钟|h|min|天|周)", "", name)
        name = re.sub(r"(预计持续|预计|持续|需要去做|有一个|请你帮我计划一下|请提前)", "", name)
        name = name.replace("一个", "")
        name = name.replace("月日", " ").replace("月号", " ")

        # 常见分隔符后优先选择首个“任务语义”片段，避免拿到提醒性句子
        segments = [
            seg.strip(" ，。；;、")
            for seg in re.split(r"[，。；;、]", name)
            if seg.strip(" ，。；;、")
        ]
        if segments:
            noise_pattern = r"(请提前|注意|准备|帮我计划|帮我安排|得体|相关问题)"
            preferred = [seg for seg in segments if not re.search(noise_pattern, seg) and len(seg) > 1]
            name = preferred[0] if preferred else segments[0]

        # 移除数字
        name = re.sub(r"\d+", "", name)

        return name.strip()

    @classmethod
    def format_duration(cls, minutes: int) -> str:
        """格式化时长显示"""
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            if mins == 0:
                return f"{hours}小时"
            return f"{hours}小时{mins}分钟"
        return f"{minutes}分钟"

    @classmethod
    def format_time_range(cls, start: datetime, duration_minutes: int) -> str:
        """格式化时间段"""
        end = start + timedelta(minutes=duration_minutes)
        return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

    @classmethod
    def suggest_time_slot(
        cls, duration_minutes: int, preference: Optional[str] = None
    ) -> datetime:
        """建议一个时间槽

        Args:
            duration_minutes: 任务时长
            preference: 时间偏好，如"上午"、"下午"

        Returns:
            建议的开始时间
        """
        now = datetime.now()

        # 如果当前时间在偏好时间段之后，往后推一天
        if preference:
            if preference in cls.TIME_PERIODS:
                start_hour, end_hour = cls.TIME_PERIODS[preference]
                preferred_time = now.replace(
                    hour=start_hour, minute=0, second=0, microsecond=0
                )

                if now > preferred_time or (now.hour >= end_hour):
                    # 明天
                    return preferred_time + timedelta(days=1)
                return preferred_time

        # 默认：从下一个整点开始，不硬推到9点
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_hour
