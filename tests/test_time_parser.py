import unittest
from datetime import date, datetime

from utils.time_parser import TimeParser


class TestTimeParserNoon(unittest.TestCase):
    def setUp(self):
        self.reference_date = date(2026, 3, 26)

    def test_noon_one_oclock(self):
        self.assertEqual(
            TimeParser.parse_datetime("中午1点", self.reference_date),
            datetime(2026, 3, 26, 13, 0),
        )

    def test_noon_twelve_oclock(self):
        self.assertEqual(
            TimeParser.parse_datetime("中午12点", self.reference_date),
            datetime(2026, 3, 26, 12, 0),
        )

    def test_noon_one_thirty(self):
        self.assertEqual(
            TimeParser.parse_datetime("中午1:30", self.reference_date),
            datetime(2026, 3, 26, 13, 30),
        )

    def test_today_noon(self):
        self.assertEqual(
            TimeParser.parse_datetime("今天中午", self.reference_date),
            datetime(2026, 3, 26, 12, 0),
        )

    def test_tomorrow_noon_two_oclock(self):
        self.assertEqual(
            TimeParser.parse_datetime("明天中午2点", self.reference_date),
            datetime(2026, 3, 27, 14, 0),
        )


class TestTimeParserRegression(unittest.TestCase):
    def test_month_day_evening_with_range_duration(self):
        reference_date = date(2026, 3, 27)
        text = "3月28号晚上5点。有一个。志愿服务需要去做。请你帮我计划一下，预计持续2-3小时。"
        parsed = TimeParser.parse_task_info(text)

        self.assertEqual(parsed["datetime"], datetime(2026, 3, 28, 17, 0))
        # 区间时长按上限处理，避免低估占用时段
        self.assertEqual(parsed["duration"], 180)
        self.assertIn("志愿服务", parsed["task_name"])

    def test_month_day_keep_current_year_when_past(self):
        reference_date = date(2026, 12, 31)
        self.assertEqual(
            TimeParser.parse_datetime("3月28日晚上5点", reference_date),
            datetime(2026, 3, 28, 17, 0),
        )

    def test_extract_core_task_name_from_verbose_description(self):
        text = "3月27日晚上6点，参加宣讲会。请提前到达，注意着装得体，准备好相关问题。"
        parsed = TimeParser.parse_task_info(text)
        self.assertEqual(parsed["task_name"], "参加宣讲会")
        self.assertEqual(parsed["datetime"], datetime(2026, 3, 27, 18, 0))

    def test_natural_planning_phrase_contains_duration(self):
        text = "今天帮我安排一个小时做视频"
        parsed = TimeParser.parse_task_info(text)
        # 口语化“帮我安排”语句至少应识别出时长与核心任务
        self.assertEqual(parsed["duration"], 60)
        self.assertIn("做视频", parsed["task_name"])


if __name__ == "__main__":
    unittest.main()
