import os
import requests
from dotenv import load_dotenv
from api_utils import request_error_summary

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
            data = response.json()
            records = data.get("records") if isinstance(data, dict) else data
            if not isinstance(records, list):
                return {"status": "error", "msg": "環境部回傳資料缺少測站清單"}
            return {"status": "success", "data": data}
        except ValueError:
            return {"status": "error", "msg": "環境部回傳內容不是有效 JSON"}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "msg": request_error_summary("環境部", e)}
