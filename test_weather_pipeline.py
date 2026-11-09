"""離線驗證預報時段、異常資料、金鑰保護與推播前檢查。"""
import contextlib
import io
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import requests

import main
import test_dify as runner
from cwa_scraper import CwaWeatherScraper
from moenv_scraper import MoenvAirScraper


def forecast_location(pop="30"):
    periods = [
        ("2026-11-09T06:00:00+08:00", "2026-11-09T18:00:00+08:00", 20, 23, pop),
        ("2026-11-09T18:00:00+08:00", "2026-11-10T06:00:00+08:00", 17, 20, "20"),
        ("2026-11-10T06:00:00+08:00", "2026-11-10T18:00:00+08:00", 18, 24, "40"),
    ]
    elements = []
    for name, field, index in [
        ("最低溫度", "MinTemperature", 2),
        ("最高溫度", "MaxTemperature", 3),
        ("12小時降雨機率", "ProbabilityOfPrecipitation", 4),
    ]:
        elements.append({
            "ElementName": name,
            "Time": [{"StartTime": p[0], "EndTime": p[1],
                      "ElementValue": [{field: p[index]}]} for p in periods],
        })
    return {"LocationName": "中山區", "WeatherElement": elements}


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("離線測試禁止網路請求"))
        network.start()
        self.addCleanup(network.stop)


class ForecastTests(OfflineTestCase):
    def parse(self, location=None, time="2026-11-09T09:00:00+08:00"):
        return main.parse_location_weather(
            forecast_location() if location is None else location,
            now=datetime.fromisoformat(time),
        )

    def test_morning_uses_current_daytime(self):
        result = self.parse()
        self.assertEqual(result["temperature_range"], "20-23")
        self.assertEqual(result["pop"], "30")
        self.assertEqual(result["forecast_end"], "2026-11-09T18:00:00+08:00")

    def test_evening_uses_night_and_next_morning(self):
        result = self.parse(time="2026-11-09T20:57:00+08:00")
        self.assertEqual(result["temperature_range"], "17-20")
        self.assertEqual(result["pop"], "20")
        following = result["next_period"]
        self.assertEqual(following["temperature_range"], "18-24")
        self.assertEqual(following["forecast_start"], "2026-11-10T06:00:00+08:00")

    def test_boundary_excludes_ended_period(self):
        result = self.parse(time="2026-11-09T18:00:00+08:00")
        self.assertEqual(result["temperature_range"], "17-20")

    def test_utc_and_taipei_choose_same_period(self):
        utc = self.parse(time="2026-11-09T13:00:00+00:00")
        taipei = self.parse(time="2026-11-09T21:00:00+08:00")
        self.assertEqual(utc, taipei)

    def test_future_forecast_keeps_actual_start(self):
        result = self.parse(time="2026-11-09T05:00:00+08:00")
        self.assertEqual(result["forecast_start"], "2026-11-09T06:00:00+08:00")

    def test_expired_data_is_unavailable(self):
        result = self.parse(time="2026-11-11T09:00:00+08:00")
        self.assertIn("error", result)
        self.assertEqual(result["pop"], "未取得")

    def test_missing_or_invalid_pop_is_not_zero(self):
        for value in (None, "", "-", "ND", "-1", "101", True, "0.5"):
            with self.subTest(value=value):
                result = self.parse(forecast_location(value))
                self.assertEqual(result["pop"], "未取得")
                self.assertEqual(result["temperature_range"], "20-23")

    def test_actual_zero_pop_is_preserved(self):
        self.assertEqual(self.parse(forecast_location("0"))["pop"], "0")

    def test_no_rain_element_is_unavailable(self):
        location = forecast_location()
        location["WeatherElement"].pop()
        self.assertEqual(self.parse(location)["pop"], "未取得")

    def test_different_rain_period_is_not_mixed_into_temperature(self):
        location = forecast_location()
        location["WeatherElement"][-1]["Time"][0]["EndTime"] = "2026-11-09T12:00:00+08:00"
        self.assertEqual(self.parse(location)["pop"], "未取得")

    def test_unordered_slots_still_choose_current(self):
        location = forecast_location()
        for element in location["WeatherElement"]:
            element["Time"].reverse()
        self.assertEqual(self.parse(location)["temperature_range"], "20-23")

    def test_malformed_nested_elements_are_ignored(self):
        for elements in (None, {}, [None], [{"ElementName": []}],
                         [{"ElementName": "最低溫度", "Time": [None, {}]}]):
            with self.subTest(elements=elements):
                result = self.parse({"WeatherElement": elements})
                self.assertIn("error", result)

    def test_invalid_value_arrays_do_not_crash(self):
        for value in (None, [], {}, [None]):
            location = forecast_location()
            location["WeatherElement"][0]["Time"][0]["ElementValue"] = value
            with self.subTest(value=value):
                self.assertEqual(self.parse(location)["min_temperature"], "未取得")

    def test_reversed_temperature_range_is_unavailable(self):
        location = forecast_location()
        location["WeatherElement"][0]["Time"][0]["ElementValue"][0]["MinTemperature"] = "30"
        self.assertIn("error", self.parse(location))

    def test_missing_or_invalid_times_are_not_used(self):
        for start in (None, "not-a-time", "2026-11-09T19:00:00+08:00"):
            location = forecast_location()
            for element in location["WeatherElement"]:
                element["Time"] = element["Time"][:1]
                element["Time"][0]["StartTime"] = start
            with self.subTest(start=start):
                self.assertIn("error", self.parse(location))


class ResponseShapeTests(OfflineTestCase):
    def test_invalid_config_reports_value_error(self):
        for config in (None, [], {"target_locations": [None]},
                       {"target_locations": [{"city": None, "district": "中山區", "aqi_station": "中山"}]}):
            with self.subTest(config=config), patch("pathlib.Path.open", return_value=io.StringIO(json.dumps(config))):
                with self.assertRaises(ValueError):
                    main.load_target_locations()

    def test_malformed_weather_responses_return_unavailable(self):
        for payload in (None, [], {}, {"records": None}, {"records": []},
                        {"records": {"Locations": None}},
                        {"records": {"Locations": [None, {"Location": [None]}]}}):
            with self.subTest(payload=payload):
                result = main.find_district_weather(payload, "中山區")
                self.assertIn("error", result)

    def test_valid_district_after_null_group_is_found(self):
        data = {"records": {"Locations": [None, {"Location": [None, forecast_location()]}]}}
        result = main.find_district_weather(data, "中山區", now=datetime.fromisoformat("2026-11-09T09:00:00+08:00"))
        self.assertEqual(result["temperature_range"], "20-23")

    def test_invalid_air_records_are_ignored(self):
        for payload in (None, [], {"data": None}, {"data": {"records": None}}):
            self.assertEqual(main.extract_air_records(payload), [])
        record = {"sitename": "松山", "aqi": "30"}
        self.assertEqual(main.extract_air_records({"data": {"records": [None, record]}}), [record])
        self.assertEqual(main.find_air_record([None, record], "松山"), record)
        self.assertEqual(main.build_air_snapshot(None)["aqi"], "未取得")


class ApiSecurityTests(OfflineTestCase):
    secret = "AUDIT_DUMMY_NOT_A_REAL_SECRET"

    def test_scrapers_do_not_return_credentials_from_request_errors(self):
        for client, args in ((CwaWeatherScraper(), ("臺北市",)), (MoenvAirScraper(), ())):
            client.token = self.secret
            method = client.fetch_city_weather if args else client.fetch_all_taiwan_aqi
            response = requests.Response()
            response.status_code = 403
            response.url = "https://example.invalid/?api_key=" + self.secret
            for error in (requests.HTTPError("URL " + self.secret, response=response),
                          requests.ConnectionError("URL " + self.secret)):
                with self.subTest(client=type(client).__name__, error=type(error).__name__), patch("requests.get", side_effect=error):
                    result = method(*args)
                    self.assertEqual(result["status"], "error")
                    self.assertNotIn(self.secret, json.dumps(result))
                    self.assertNotIn("https://", result["msg"])

    def test_scrapers_handle_invalid_json_and_roots(self):
        for client, args in ((CwaWeatherScraper(), ("臺北市",)), (MoenvAirScraper(), ())):
            client.token = self.secret
            method = client.fetch_city_weather if args else client.fetch_all_taiwan_aqi
            for value in (None, "text", 5):
                with self.subTest(client=type(client).__name__, value=value), patch("requests.get", return_value=Mock(json=Mock(return_value=value))):
                    self.assertEqual(method(*args)["status"], "error")
            response = Mock(json=Mock(side_effect=ValueError(self.secret)))
            with patch("requests.get", return_value=response):
                result = method(*args)
                self.assertEqual(result["status"], "error")
                self.assertNotIn(self.secret, json.dumps(result))

    def test_dify_and_line_errors_do_not_print_response_or_secret(self):
        response = requests.Response()
        response.status_code = 401
        response.url = "https://example.invalid/?key=" + self.secret
        response._content = self.secret.encode()
        error = requests.HTTPError(self.secret, response=response)
        for action in (runner.json_runner_to_dify, runner.send_line_message):
            output = io.StringIO()
            with patch.dict("os.environ", {"DIFY_API_KEY": self.secret, "LINE_CHANNEL_ACCESS_TOKEN": self.secret, "LINE_USER_ID": "test-user"}), patch("requests.post", side_effect=error), contextlib.redirect_stdout(output):
                result = action("test wording")
            self.assertFalse(result)
            self.assertNotIn(self.secret, output.getvalue())
            self.assertIn("401", output.getvalue())


class DifyAndDeliveryTests(OfflineTestCase):
    def test_generation_time_uses_taipei_date_across_midnight(self):
        package = runner.attach_delivery_context({}, "evening", now=datetime.fromisoformat("2026-11-09T16:30:00+00:00"))
        self.assertEqual(package["generated_at"], "2026-11-10T00:30:00+08:00")

    def test_only_successful_text_output_is_accepted(self):
        for key in ("text", "answer", "result", "output", "final_wording"):
            data = {"data": {"status": "succeeded", "outputs": {key: " 播報內容 "}}}
            self.assertEqual(runner.extract_dify_wording(data), "播報內容")

    def test_failure_status_or_nontext_outputs_are_rejected(self):
        payloads = [None, [], {"data": None}, {"answer": "未驗證"}]
        for status in (None, "failed", "stopped", "running", "partial-succeeded"):
            payloads.append({"data": {"status": status, "outputs": {"result": "錯誤或部分輸出"}}})
        for outputs in (None, [], {"metadata": {"count": 9}}, {"message": "provider error"},
                        {"result": {"error": "failed"}}, {"result": ["text"]}, {"result": "  "}, {"result": 50}):
            payloads.append({"data": {"status": "succeeded", "outputs": outputs}})
        payloads.append({"data": {"status": "succeeded", "error": "failed", "outputs": {"result": "text"}}})
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(runner.extract_dify_wording(payload), "")

    def test_full_outage_stops_before_dify_and_line(self):
        unavailable = {"status": "error", "msg": "模擬資料服務失效"}
        with patch("main.configure_logging"), patch("main.configure_console_encoding"), patch("test_dify.configure_console_encoding"), patch("main.CwaWeatherScraper.fetch_city_weather", return_value=unavailable), patch("main.MoenvAirScraper.fetch_all_taiwan_aqi", return_value=unavailable), patch("test_dify.json_runner_to_dify") as dify, patch("test_dify.send_line_message") as line, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_weather_agent(), 1)
            dify.assert_not_called()
            line.assert_not_called()

    def test_partial_weather_can_still_be_delivered(self):
        weather = main.parse_location_weather(forecast_location(), now=datetime.fromisoformat("2026-11-09T09:00:00+08:00"))
        package = {"locations": [{"weather": main.empty_weather("缺測")}, {"weather": weather}]}
        with patch("test_dify.configure_console_encoding"), patch("test_dify.build_final_ai_package", return_value=package), patch("test_dify.json_runner_to_dify", return_value="播報內容") as dify, patch("test_dify.send_line_message", return_value=True) as line, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_weather_agent(), 0)
            sent = json.loads(dify.call_args.args[0])
            self.assertIn("forecast_start", sent["locations"][1]["weather"])
            line.assert_called_once_with("播報內容")

    def test_failed_dify_response_stops_before_line(self):
        package = {"locations": [{"weather": {"min_temperature": 20, "max_temperature": 23}}]}
        response = Mock(json=Mock(return_value={"data": {"status": "failed", "outputs": {"message": "provider error"}}}))
        with patch.dict("os.environ", {"DIFY_API_KEY": "audit-key"}), patch("test_dify.configure_console_encoding"), patch("test_dify.build_final_ai_package", return_value=package), patch("requests.post", return_value=response), patch("test_dify.send_line_message") as line, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_weather_agent(), 1)
            line.assert_not_called()

    def test_missing_weather_or_configuration_stops_delivery(self):
        for package in (None, {}, {"locations": None}, {"locations": [None]},
                        {"locations": [{"weather": {"pop": "未取得"}}]}):
            self.assertFalse(runner.has_usable_weather(package))
        self.assertTrue(runner.has_usable_weather({"locations": [{"weather": {"pop": "0"}}]}))
        with patch("test_dify.configure_console_encoding"), patch("test_dify.build_final_ai_package", side_effect=ValueError("設定異常")), patch("test_dify.json_runner_to_dify") as dify, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.run_weather_agent(), 1)
            dify.assert_not_called()

    def test_blank_or_nontext_line_payload_never_reaches_network(self):
        for value in (None, {}, "", " "):
            with self.subTest(value=value), patch("requests.post") as post, contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(runner.send_line_message(value))
                post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
