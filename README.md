# Weather Agent

一個自動整理天氣、空氣品質，並透過 Dify 生成文字後推送到 LINE 的天氣小精靈。

它的任務很單純：定時醒來，收集指定地點的天氣與 AQI，整理成結構化 JSON，交給 Dify Workflow 轉成可讀訊息，最後送到 LINE。早上提醒出門前的重點，晚上整理收尾與隔日參考。

## 功能概覽

- 讀取 `config.json` 中設定的 9 個目標地點。
- 透過中央氣象署開放資料 API 取得各縣市鄉鎮區天氣預報。
- 透過環境部 AQI API 取得全台空氣品質資料。
- 依地點合併天氣、降雨機率與 AQI。
- 將資料包裝為 Dify Workflow 可使用的 JSON payload。
- 呼叫 Dify Workflow 產生 LINE 推播文案。
- 使用 LINE Messaging API Push Message 發送訊息。
- 支援 `morning` 與 `evening` 兩種推播模式。
- 使用 GitHub Actions 每天自動執行，也可手動觸發。
- 使用 rotating log 保存執行紀錄，避免 log 無限制膨脹。

## 系統流程

```text
GitHub Actions / local run
        |
        v
Load config.json target locations
        |
        v
Fetch CWA weather data + MOENV AQI data
        |
        v
Build structured weather JSON
        |
        v
Send JSON to Dify Workflow
        |
        v
Push final wording to LINE
```

## 專案結構

```text
weather_agent/
|-- .github/workflows/weather-agent.yml  # GitHub Actions 排程與驗證流程
|-- config.json                          # 目標地點、行政區與 AQI 測站設定
|-- cwa_scraper.py                       # 中央氣象署天氣 API client
|-- moenv_scraper.py                     # 環境部 AQI API client
|-- main.py                              # 天氣與空氣品質資料整合主程式
|-- test_dify.py                         # Dify Workflow 與 LINE 推播流程
|-- DEVELOPMENT_GUIDELINES.md            # 開發與維護準則
`-- README.md                            # 專案說明文件
```

## 推播模式

`WEATHER_AGENT_MODE` 控制 Dify 文案生成時使用的情境。

| 模式 | 用途 |
| --- | --- |
| `morning` | 早晨提醒，聚焦出門前的溫度、降雨機率、空氣品質與注意事項 |
| `evening` | 晚間整理，聚焦夜間狀況、隔日準備與簡短生活提醒 |

若未設定或設定值不合法，程式會回到 `morning`。

## GitHub Actions 排程

Workflow 檔案：

```text
.github/workflows/weather-agent.yml
```

目前排程使用 UTC cron，對應台灣時間如下：

| UTC cron | 台灣時間 | 模式 |
| --- | --- | --- |
| `57 22 * * *` | 每天 06:57 | `morning` |
| `57 12 * * *` | 每天 20:57 | `evening` |

GitHub Actions 執行時會先做基本檢查：

- 安裝 Python 3.11 與必要套件。
- 執行 `python -m py_compile` 檢查 Python 語法。
- 執行 `python -m json.tool config.json` 驗證 JSON 格式。
- 依排程或手動輸入決定 `WEATHER_AGENT_MODE`。
- 執行 `python test_dify.py` 完成 Dify 與 LINE 推播流程。

也可以在 GitHub Actions 頁面使用 `workflow_dispatch` 手動執行，並選擇 `morning` 或 `evening`。

## 環境變數

本機開發可放在 `.env`，GitHub Actions 請設定為 Repository Secrets。

```text
CWA_API_KEY=
MOENV_API_KEY=
DIFY_API_KEY=
DIFY_API_URL=https://api.dify.ai/v1/workflows/run
DIFY_INPUT_KEY=weather_data
LINE_CHANNEL_ACCESS_TOKEN=
LINE_USER_ID=
WEATHER_AGENT_MODE=morning
```

| 變數 | 說明 |
| --- | --- |
| `CWA_API_KEY` | 中央氣象署開放資料 API key |
| `MOENV_API_KEY` | 環境部資料開放平台 API key |
| `DIFY_API_KEY` | Dify App API key |
| `DIFY_API_URL` | Dify Workflow API endpoint，預設為 `https://api.dify.ai/v1/workflows/run` |
| `DIFY_INPUT_KEY` | Dify Workflow 接收天氣 JSON 的 input key，預設為 `weather_data` |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API Channel access token |
| `LINE_USER_ID` | 接收推播的 LINE user ID |
| `WEATHER_AGENT_MODE` | 推播模式，可為 `morning` 或 `evening` |

## `config.json` 設定

目前 `config.json` 使用 `target_locations` 管理 9 個推播地點。每個地點需要下列欄位：

```json
{
  "key": "顯示用地點名稱",
  "city": "縣市名稱",
  "district": "行政區名稱",
  "aqi_station": "AQI 測站名稱"
}
```

欄位用途：

- `key`：最後輸出給 Dify 的地點識別名稱。
- `city`：用來選擇中央氣象署 API 的縣市資料集。
- `district`：用來在天氣資料中找到對應行政區。
- `aqi_station`：用來從環境部 AQI 資料中比對最近或指定測站。

提醒：這個檔案請維持 UTF-8 編碼。如果地名出現亂碼，API 比對可能失準，天氣小精靈就會開始迷路。

## 本機執行

安裝套件：

```bash
pip install requests python-dotenv
```

只產生整合後的天氣 JSON：

```bash
python main.py
```

執行完整流程，包含 Dify 生成與 LINE 推播：

```bash
python test_dify.py
```

切換推播模式：

```bash
$env:WEATHER_AGENT_MODE="evening"
python test_dify.py
```

## 輸出資料格式

`main.py` 會建立一份給 Dify 使用的資料包，主要結構如下：

```json
{
  "reporting_mode": "morning",
  "location_count": 9,
  "locations": [
    {
      "key": "地點名稱",
      "city": "縣市",
      "district": "行政區",
      "weather": {
        "temperature_range": "20-25",
        "min_temperature": 20,
        "max_temperature": 25,
        "pop": "30"
      },
      "air_quality": {
        "aqi": "42",
        "source": "AQI 測站"
      }
    }
  ],
  "delivery_context": {
    "label": "morning_7am",
    "title": "推播標題",
    "focus": [],
    "writing_instruction": "Dify 文案指示"
  }
}
```

實際內容會依 API 回傳與 `WEATHER_AGENT_MODE` 而變動。

## Log

執行紀錄會寫入：

```text
weather_agent.log
```

目前設定：

- 單一 log 檔最大約 1 MB。
- 最多保留 3 份備份。
- log 檔已列入 `.gitignore`，不會被提交到 GitHub。

## 維護重點

- API key、LINE token、Dify key 一律放在 `.env` 或 GitHub Secrets，不要寫進程式碼。
- 調整推播時間時，同步更新 workflow 的 cron、註解與 `MORNING_CRON` / `EVENING_CRON` 判斷值。
- 新增地點時，請同時確認 CWA 縣市資料集、行政區名稱與 AQI 測站名稱可以正確比對。
- Dify Workflow 的 input key 若更名，請同步更新 `DIFY_INPUT_KEY`。
- 若 LINE 推播失敗，優先檢查 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID` 與 LINE Messaging API 權限。

## 快速檢查

```bash
python -m py_compile main.py cwa_scraper.py moenv_scraper.py test_dify.py
python -m json.tool config.json
```

兩個指令都通過後，再執行完整推播流程。這樣比較不會讓天氣小精靈在半路打結。
