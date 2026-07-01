import os
import requests
from dotenv import load_dotenv

load_dotenv()


class MoenvAirScraper:
    """負責管理環境部 API 的連線，確保單次高效率撈取全台資料"""

    def __init__(self):
        self.base_url = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
        self.token = os.getenv("MOENV_API_KEY")

    def fetch_all_taiwan_aqi(self) -> dict:
        """
        全宇宙只呼叫一次，直接拉回全台最新空污大禮包，完美避開流量鎖定
        """
        if not self.token:
            return {"status": "error", "msg": "缺少 MOENV_API_KEY，請確認 .env 設定"}

        payload = {
            "api_key": self.token,
            "limit": 100,
            "format": "json"
        }
        try:
            response = requests.get(self.base_url, params=payload, timeout=10)
            response.raise_for_status()
            return {"status": "success", "data": response.json()}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "msg": f"環境部連線失敗：{str(e)}"}
