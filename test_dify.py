# =====================================================================
# 1. 外部套件引入區 (依據 PEP 8 規範，一律置於檔案最上方)
# =====================================================================
import json
import os
import sys
import requests
from dotenv import load_dotenv

# =====================================================================
# 2. 專案初始化配置 (全域配置，檔案開啟時先載入一次即可)
# =====================================================================
load_dotenv()


def configure_console_encoding():
    """確保 Windows 終端機列印 Emoji 與繁體中文時不會噴 cp950 錯誤"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

# =====================================================================
# 3. 核心業務邏輯區 (函式定義)
# =====================================================================
def extract_dify_wording(response_data):
    """
    從 Dify blocking response 中取出最終文案。
    相容常見欄位：answer、data.outputs.text、data.outputs.answer 等。
    """
    if response_data.get("answer"):
        return response_data["answer"]

    data = response_data.get("data", {})
    if isinstance(data, dict) and data.get("answer"):
        return data["answer"]

    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    if isinstance(outputs, dict):
        for key in ("text", "answer", "result", "output", "message", "final_wording"):
            if outputs.get(key):
                return str(outputs[key])

        if outputs:
            return json.dumps(outputs, ensure_ascii=False, indent=2)

    return ""


def json_runner_to_dify(weather_json_data):
    """
    將天氣 JSON 送進 Dify Workflow，取得 Dify 生成的家族提醒文案。

    .env 可設定：
    - DIFY_API_KEY：必要，Dify App API key
    - DIFY_API_URL：選填，預設 https://api.dify.ai/v1/workflows/run
    - DIFY_INPUT_KEY：選填，預設 weather_data，需對應 Dify Workflow 的輸入變數名稱
    """
    dify_api_key = os.getenv("DIFY_API_KEY")
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

    except requests.exceptions.HTTPError as http_err:
        detail = ""
        if http_err.response is not None:
            detail = http_err.response.text[:500]
        print(f"🚨 Dify 呼叫失敗，HTTP 錯誤：{http_err}\n{detail}")
    except requests.exceptions.RequestException as req_err:
        print(f"🚨 Dify 連線異常：{req_err}")
    except ValueError as json_err:
        print(f"🚨 Dify 回傳內容不是合法 JSON：{json_err}")

    return ""


def send_line_message(wording_text):
    """
    【2026 現代化架構】將大腦文案透過 LINE Messaging API 主動推播（Push Message）至執行長手機
    """
    # 1. 嚴格落實防硬編碼，從環境變數讀取新燃料
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")
    
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
        
        print("✨ 【LINE 特工推播成功】文案已成功彈出至手機！")
        return True

    except requests.exceptions.HTTPError as http_err:
        print(f"🚨 LINE 發送失敗！HTTP 錯誤碼：{http_err}")
        print("💡 QA 偵錯提醒：請檢查 .env 中的 Access Token 是否複製完整，或 User ID 是否有複製到空格。")
    except Exception as e:
        print(f"🚨 LINE 渠道連線突發異常：{e}")
        
    return False

# =====================================================================
# 4. 測試點火控制區
# =====================================================================
if __name__ == "__main__":
    configure_console_encoding()
    print("=== 🌟 天氣特工 2.0 現代化渠道全線通車大典 🌟 ===")
    
    # 模擬測試數據
    mock_json_data = '{"reporting_mode": "morning", "location_count": 1, "locations": [{"key": "臺北市中山區", "city": "臺北市", "district": "中山區", "weather": {"temperature_range": "27-35", "min_temperature": 27, "max_temperature": 35, "pop": "10"}, "air_quality": {"aqi": "40", "source": "中山"}}]}'
    
    # 第一棒：Python 把即時數據餵給 Dify 雲端大腦
    final_wording = json_runner_to_dify(mock_json_data)
    
    # 第二棒：大腦順利吐出精美文案後，直接交給第三棒 LINE 新引擎推播
    if final_wording:
        push_status = send_line_message(final_wording)
        if push_status:
            print("\n🏆 【大獲全勝】2026 全新自動化閉環完美通車！請查看手機！")
    else:
        print("\n❌ 通車中斷，大腦未能正確產出文案。")
