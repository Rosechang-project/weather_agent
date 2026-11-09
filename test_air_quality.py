"""驗證 AQI 測站比對與缺測處理，不呼叫外部 API 或發送訊息。"""
import unittest

from main import build_air_snapshot, find_air_record, load_target_locations


class AirQualityTests(unittest.TestCase):
    def test_exact_match_skips_empty_and_partial_station_names(self):
        records = [
            {"sitename": "", "aqi": "10"},
            {"sitename": None, "aqi": "20"},
            {"sitename": "松山機場", "aqi": "40"},
            {"sitename": " 松山 ", "aqi": "30"},
        ]
        self.assertEqual(find_air_record(records, " 松山 "), records[-1])
        self.assertEqual(find_air_record(records, "松"), {})
        self.assertEqual(find_air_record(records, ""), {})

    def test_missing_station_does_not_fabricate_aqi(self):
        record = find_air_record([{"sitename": "松山", "aqi": "30"}], "信義")
        self.assertEqual(
            build_air_snapshot(record), {"aqi": "未取得", "source": "未取得"}
        )

    def test_invalid_aqi_keeps_known_source(self):
        for value in (None, "", " ", "-", "ND", "-1", "31.5", 31.5, True):
            with self.subTest(value=value):
                self.assertEqual(
                    build_air_snapshot({"sitename": "松山", "aqi": value}),
                    {"aqi": "未取得", "source": "松山"},
                )
        self.assertEqual(build_air_snapshot({"sitename": "松山"})["aqi"], "未取得")

    def test_valid_zero_and_measured_fifty_are_preserved(self):
        for value in (0, "0", " 30 ", "50"):
            with self.subTest(value=value):
                self.assertEqual(
                    build_air_snapshot({"sitename": " 松山 ", "aqi": value}),
                    {"aqi": str(int(value)), "source": "松山"},
                )

    def test_numeric_aqi_without_station_is_unavailable(self):
        self.assertEqual(
            build_air_snapshot({"aqi": "30"}),
            {"aqi": "未取得", "source": "未取得"},
        )

    def test_xinyi_uses_songshan_reference(self):
        location = next(
            item for item in load_target_locations() if item["key"] == "臺北市信義區"
        )
        self.assertEqual(location["aqi_station"], "松山")


if __name__ == "__main__":
    unittest.main()
