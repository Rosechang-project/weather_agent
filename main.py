# =====================================================================
# Weather Agent main.py
# 設定檔驅動版：抓取指定行政區的鄉鎮預報與 AQI，輸出乾淨 JSON
# =====================================================================
import json
import logging
import sys
from pathlib import Path

from cwa_scraper import CwaWeatherScraper
from moenv_scraper import MoenvAirScraper


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "weather_agent.log"


def configure_console_encoding():
    """確保 Windows 終端機列印 Emoji 與繁體中文時不會噴 cp950 錯誤"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def configure_logging():
    """建立 UTF-8 日誌，保留主控台與檔案紀錄。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


def load_target_locations(config_path: Path = CONFIG_PATH) -> list:
    """從設定檔載入監控行政區，避免把地區名稱硬編碼在主流程。"""
    if not config_path.exists():
        raise FileNotFoundError(f"找不到設定檔：{config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    target_locations = config.get("target_locations", [])
    if not isinstance(target_locations, list) or not target_locations:
        raise ValueError("config.json 必須提供非空的 target_locations 陣列")

    required_fields = {"city", "district", "aqi_station"}
    for index, item in enumerate(target_locations, start=1):
        missing_fields = required_fields - set(item)
        if missing_fields:
            raise ValueError(
                f"target_locations 第 {index} 筆缺少欄位：{', '.join(sorted(missing_fields))}"
            )

    return target_locations


def extract_air_records(response: dict) -> list:
    """防禦環境部 API 回傳資料型態：相容 Dict 與 List 結構。"""
    data = response.get("data", [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("records", [])
    return []


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_temperature_range(min_temp, max_temp):
    if min_temp is None or max_temp is None:
        return "未取得"
    return f"{min_temp}-{max_temp}"


def normalize_district_name(name: str) -> str:
    return name.replace("區", "").replace("市", "").replace("鄉", "").replace("鎮", "").strip()


def empty_weather(error_msg: str) -> dict:
    return {
        "temperature_range": "未取得",
        "min_temperature": "未取得",
        "max_temperature": "未取得",
        "pop": "0",
        "error": error_msg,
    }


def parse_location_weather(location: dict) -> dict:
    """解析單一行政區的最高/最低溫與降雨機率。"""
    min_temp = None
    max_temp = None
    pop = 0

    for element in location.get("WeatherElement", []):
        element_name = element.get("ElementName", "")
        time_slots = element.get("Time", [])
        if not time_slots:
            continue

        first_value = time_slots[0].get("ElementValue", [{}])[0]

        if element_name == "最低溫度":
            min_temp = safe_int(first_value.get("MinTemperature"))
        elif element_name == "最高溫度":
            max_temp = safe_int(first_value.get("MaxTemperature"))
        elif "降雨機率" in element_name:
            pop = safe_int(first_value.get("ProbabilityOfPrecipitation")) or 0

    return {
        "temperature_range": build_temperature_range(min_temp, max_temp),
        "min_temperature": min_temp if min_temp is not None else "未取得",
        "max_temperature": max_temp if max_temp is not None else "未取得",
        "pop": str(pop),
    }


def find_district_weather(weather_raw: dict, district_name: str) -> dict:
    """從縣市鄉鎮預報中挑出指定行政區。"""
    try:
        if weather_raw.get("status") == "error":
            return empty_weather(weather_raw.get("msg", "天氣資料抓取失敗"))

        records = weather_raw.get("records", {})
        locations = records.get("Locations", [{}])[0]
        location_list = locations.get("Location", [])
        if not location_list:
            return empty_weather("天氣資料缺少 Location 清單")

        target_normalized = normalize_district_name(district_name)
        for location in location_list:
            location_name = str(location.get("LocationName", "")).strip()
            location_normalized = normalize_district_name(location_name)
            if district_name == location_name or target_normalized == location_normalized:
                return parse_location_weather(location)

        return empty_weather(f"找不到行政區預報：{district_name}")
    except (KeyError, IndexError, TypeError) as exc:
        return empty_weather(f"天氣資料解析失敗：{str(exc)}")


def find_air_record(records: list, station: str) -> dict:
    """用設定檔指定的 AQI 測站名稱，從全台 AQI 清單中找最接近的資料。"""
    target_site = station.strip()
    for record in records:
        db_site = str(record.get("sitename", "")).strip()
        if target_site in db_site or db_site in target_site:
            return record
    return {}


def build_air_snapshot(record: dict) -> dict:
    """只輸出乾淨 AQI 數值；若資料不可用，提供保守 fallback。"""
    if not record:
        return {
            "aqi": "50",
            "source": "fallback",
        }

    return {
        "aqi": record.get("aqi", "50"),
        "source": record.get("sitename", "環境部 AQI"),
    }


def build_final_ai_package():
    configure_console_encoding()
    configure_logging()

    target_locations = load_target_locations()
    logging.info("啟動 9 個黃金指標點資料清洗作業，共 %s 個監控點", len(target_locations))

    cwa = CwaWeatherScraper()
    moenv = MoenvAirScraper()

    logging.info("正在向環境部索取全台即時 AQI 資料，後續以本地記憶體比對")
    global_air_response = moenv.fetch_all_taiwan_aqi()
    all_air_records = []

    if global_air_response.get("status") == "success":
        all_air_records = extract_air_records(global_air_response)
        logging.info("成功取得全台 %s 個 AQI 測站資料", len(all_air_records))
    else:
        logging.warning("AQI 資料抓取失敗：%s", global_air_response.get("msg"))

    weather_cache = {}
    final_locations = []

    for item in target_locations:
        city = item["city"]
        district = item["district"]
        aqi_station = item["aqi_station"]
        key = item.get("key") or f"{city}{district}"

        if city not in weather_cache:
            logging.info("抓取中央氣象署鄉鎮預報：%s", city)
            weather_cache[city] = cwa.fetch_city_weather(city)

        weather = find_district_weather(weather_cache[city], district)
        air_quality = build_air_snapshot(find_air_record(all_air_records, aqi_station))

        if weather.get("error"):
            logging.warning("%s%s 天氣資料異常：%s", city, district, weather["error"])

        final_locations.append(
            {
                "key": key,
                "city": city,
                "district": district,
                "weather": weather,
                "air_quality": air_quality,
            }
        )

        logging.info(
            "%s 完成：%s°C，降雨機率 %s%%，AQI %s",
            key,
            weather["temperature_range"],
            weather["pop"],
            air_quality["aqi"],
        )

    return {
        "reporting_mode": "configured_golden_indicators",
        "location_count": len(final_locations),
        "locations": final_locations,
    }


if __name__ == "__main__":
    package_result = build_final_ai_package()
    print(json.dumps(package_result, ensure_ascii=False, indent=2))
