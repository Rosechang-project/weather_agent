import os
import requests
from dotenv import load_dotenv

load_dotenv()


class CwaWeatherScraper:
    """負責管理中央氣象署各縣市 API 的連線與資料抓取"""

    def __init__(self):
        # 🗺️ 建立執行長指定的縣市代碼對照表（符合準則 2：永續擴充性）
        self.city_codes = {
            "基隆市": "F-D0047-051",
            "臺北市": "F-D0047-063",
            "新北市": "F-D0047-071",
            "桃園市": "F-D0047-007",
            "花蓮縣": "F-D0047-043"
        }
        self.token = os.getenv("CWA_API_KEY")

    def fetch_city_weather(self, city_name: str) -> dict:
        """
        傳入縣市名稱（例如：'臺北市'、'花蓮縣'），自動動態撈取對應的氣象編號
        """
        if not self.token:
            return {"status": "error", "msg": "缺少 CWA_API_KEY，請確認 .env 設定"}

        code = self.city_codes.get(city_name)
        if not code:
            return {"status": "error", "msg": f"未支援的縣市：{city_name}"}
            
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{code}"

        try:
            response = requests.get(url, params={"Authorization": self.token}, timeout=10)
            response.raise_for_status()  # 確保 HTTP 回應狀態碼是 200
            return response.json()  # 回傳 JSON 格式的資料
        except requests.exceptions.RequestException as e:
            return {"status": "error", "msg": f"中央氣象署連線失敗，無法抓取 {city_name} 氣象資料：{str(e)}"}
