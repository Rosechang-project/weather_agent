# =====================================================================
# 1. 外部套件引入區 (依據 PEP 8 規範，一律置於檔案最上方)
# =====================================================================
import json
import os
import sys
from datetime import datetime
import requests
from dotenv import load_dotenv

from main import TAIPEI_TIMEZONE, build_final_ai_package
from api_utils import request_error_summary

# =====================================================================
# 2. 專案初始化配置 (全域配置，檔案開啟時先載入一次即可)
# =====================================================================
load_dotenv()


def configure_console_encoding():
    """確保 Windows 終端機列印 Emoji 與繁體中文時不會噴 cp950 錯誤"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def get_secret(name):
    """讀取環境變數並清掉常見複製貼上造成的空白/換行/外層引號。"""
    value = os.getenv(name, "")
    return value.strip().strip('"').strip("'")


BROADCAST_STYLE_INSTRUCTION = (
    "播報請使用自然、簡短的台灣日常口吻，像熟悉的氣象主播輕鬆提醒家人。"
    "保留重要氣溫、降雨與空氣品質資訊，避免逐項照讀數據；天氣相近的地區可合併說明。"
    "降雨以自然語句說明，不逐區把百分比改寫成幾成重念，必要時最多保留一個代表數字。"
    "降雨機率不能代表雨量或雨勢強弱，沒有雨量資料時，不描述雨勢較大、較明顯或豪雨。"
    "每次最多自然帶入一句貼合天氣的生活提醒，沒有適合的內容就省略，不必每段都說『記得帶雨傘』。"
    "開場與結尾不必套用固定句型，不要為了變化刻意開玩笑、加入長篇閒聊或增加篇幅。"
    "節日話題不用主動加入，只有輸入提供日期背景且與提醒直接相關時才簡短提及。"
    "所有天氣敘述都須有輸入資料支持；沒有歷史資料，不說『比上週冷』或『最近一直下雨』；"
    "沒有明確預報時段，不把數值指定為今晚、明早、明天或節日當天的天氣。"
    "weather.forecast_start 與 forecast_end 是該筆資料的適用時段；next_period 若存在，代表另一個獨立時段。"
    "以 generated_at 的台灣日期為基準，分別依起訖時間判斷今晚、明早或明天，不把兩個時段的數值混在一起。"
    "標示 error、未取得或 source 為 fallback 的資料不能當成有效觀測或預報來播報。"
)


REPORT_CONTEXTS = {
    "morning": {
        "label": "morning_7am",
        "title": "早安出門提醒",
        "focus": [
            "今日氣溫高低與體感",
            "降雨機率與降雨熱區",
            "穿衣建議",
            "雨具與防曬準備",
        ],
        "writing_instruction": (
            "請用早上出門前的口吻，先簡短說明天氣重點，再視需要帶入穿衣或隨身物品的小提醒。"
            "不需要把每種建議都講一遍。"
            + BROADCAST_STYLE_INSTRUCTION
        ),
    },
    "evening": {
        "label": "evening_9pm",
        "title": "晚安生活準備提醒",
        "focus": [
            "今晚到明晨是否適合室外曬衣",
            "資料涵蓋時段的降雨風險",
            "資料有提供時才說明隔天整體天氣趨勢",
            "明早出門前可先準備的雨具或衣物",
        ],
        "writing_instruction": (
            "請用晚上收尾、準備休息的口吻，簡短說明資料支持的天氣重點。"
            "若有適用時段的資料，可自然帶入曬衣或出門準備的小提醒；資料不足時省略，不必硬湊。"
            + BROADCAST_STYLE_INSTRUCTION
        ),
    },
}


def get_report_mode():
    mode = os.getenv("WEATHER_AGENT_MODE", "morning").strip().lower()
    if mode not in REPORT_CONTEXTS:
        print(f"⚠️ 未知推播模式 {mode}，自動改用 morning")
        return "morning"
    return mode


def attach_delivery_context(weather_package, report_mode, now=None):
    now = now or datetime.now(TAIPEI_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TAIPEI_TIMEZONE)
    weather_package["generated_at"] = now.astimezone(TAIPEI_TIMEZONE).isoformat()
    weather_package["reporting_mode"] = report_mode
    weather_package["delivery_context"] = REPORT_CONTEXTS[report_mode]
    return weather_package

# =====================================================================
# 3. 核心業務邏輯區 (函式定義)
# =====================================================================
def extract_dify_wording(response_data):
    """只接受成功完成的 Workflow 在指定輸出欄位提供的非空白文字。"""
    if not isinstance(response_data, dict):
        return ""
    data = response_data.get("data")
    if not isinstance(data, dict) or data.get("status") != "succeeded" or data.get("error"):
        return ""
    outputs = data.get("outputs")
    if isinstance(outputs, dict):
        for key in ("text", "answer", "result", "output", "final_wording"):
            value = outputs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def has_usable_weather(weather_package):
    """資料全數失效時阻止生成與推播；部分缺測仍交給既有播報規則處理。"""
    if not isinstance(weather_package, dict):
        return False
    locations = weather_package.get("locations")
    if not isinstance(locations, list):
        return False
    for location in locations:
        weather = location.get("weather") if isinstance(location, dict) else None
        if not isinstance(weather, dict) or weather.get("error"):
            continue
        min_temp = weather.get("min_temperature")
        max_temp = weather.get("max_temperature")
        if type(min_temp) is int and type(max_temp) is int and min_temp <= max_temp:
            return True
        pop = weather.get("pop")
        if isinstance(pop, str) and pop.isascii() and pop.isdigit() and 0 <= int(pop) <= 100:
            return True
    return False


def json_runner_to_dify(weather_json_data):
    """
    將天氣 JSON 送進 Dify Workflow，取得 Dify 生成的家族提醒文案。

    .env 可設定：
    - DIFY_API_KEY：必要，Dify App API key
    - DIFY_API_URL：選填，預設 https://api.dify.ai/v1/workflows/run
    - DIFY_INPUT_KEY：選填，預設 weather_data，需對應 Dify Workflow 的輸入變數名稱
    """
    dify_api_key = get_secret("DIFY_API_KEY")
    if not dify_api_key:
        print("🚨 錯誤：未能在環境變數中讀取到 DIFY_API_KEY")
        return ""

    url = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1/workflows/run")
    input_key = os.getenv("DIFY_INPUT_KEY", "weather_data")
    headers = {
        "Authorization": f"Bearer {dify_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {
            input_key: weather_json_data,
        },
        "response_mode": "blocking",
        "user": "weather-agent-test",
    }

    try:
        print("🧠 正在把天氣 JSON 送進 Dify 雲端大腦...")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        wording = extract_dify_wording(response.json())
        if not wording:
            print("🚨 Dify 有回應，但沒有找到可用的文案欄位。")
            return ""

        print("✨ 【Dify 文案生成成功】")
        return wording

    except ValueError:
        print("🚨 Dify 回傳內容不是有效 JSON。")
    except requests.exceptions.RequestException as req_err:
        print(f"🚨 {request_error_summary('Dify', req_err)}")

    return ""


def send_line_message(wording_text):
    """
    【2026 現代化架構】將大腦文案透過 LINE Messaging API 主動推播（Push Message）至執行長手機
    """
    if not isinstance(wording_text, str) or not wording_text.strip():
        print("🚨 LINE 文案必須是非空白文字。")
        return False

    # 1. 嚴格落實防硬編碼，從環境變數讀取新燃料
    access_token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = get_secret("LINE_USER_ID")
    
    if not access_token or not user_id:
        print("🚨 錯誤：未能在環境變數中讀取到 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID")
        return False

    # 2. 2026 官方標準 Push Message 大門網址
    url = "https://api.line.me/v2/bot/message/push"
    
    # 根據官方規格，必須採用 Bearer 認證機制，且宣告為 JSON 格式
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # 3. 組裝官方標準結構：指定目的地(to) 與 訊息陣列(messages)
    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": wording_text
            }
        ]
    }

    try:
        print("📲 正在透過 2026 Messaging API 渠道進行主動推播...")
        # 加上 15 秒防禦性超時設定，避免網路阻塞掛起
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        # 檢查 HTTP 狀態碼（例如：Token 貼錯會噴 401，ID 錯會噴 400）
        response.raise_for_status()
        
        print("✨ LINE 已接受推播請求。")
        return True

    except requests.exceptions.RequestException as exc:
        print(f"🚨 {request_error_summary('LINE', exc)}")
        
    return False

# =====================================================================
# 4. 測試點火控制區
# =====================================================================
def run_weather_agent():
    configure_console_encoding()
    print("=== 🌟 天氣特工 2.0 現代化渠道全線通車大典 🌟 ===")

    report_mode = get_report_mode()
    print(f"🕒 本次推播模式：{REPORT_CONTEXTS[report_mode]['title']} ({report_mode})")

    print("🌦️ 正在抓取 9 個黃金指標點的即時天氣與 AQI 資料...")
    try:
        weather_package = build_final_ai_package()
    except (OSError, ValueError, TypeError) as exc:
        print(f"❌ 無法建立天氣資料（{type(exc).__name__}），停止推播。")
        return 1
    if not has_usable_weather(weather_package):
        print("❌ 所有地點皆缺少有效天氣資料，停止生成文案與 LINE 推播。")
        return 1
    weather_package = attach_delivery_context(weather_package, report_mode)
    weather_json_data = json.dumps(weather_package, ensure_ascii=False)

    # 第一棒：Python 把即時數據餵給 Dify 雲端大腦
    final_wording = json_runner_to_dify(weather_json_data)

    # 第二棒：大腦順利吐出精美文案後，直接交給第三棒 LINE 新引擎推播
    if final_wording:
        push_status = send_line_message(final_wording)
        if push_status:
            print("\n🏆 【大獲全勝】2026 全新自動化閉環完美通車！請查看手機！")
        else:
            print("\n❌ LINE 推播失敗，請查看上方 LINE API 錯誤訊息。")
            return 1
    else:
        print("\n❌ 通車中斷，大腦未能正確產出文案。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_weather_agent())
