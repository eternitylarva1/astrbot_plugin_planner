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


if __name__ == "__main__":
    unittest.main()
