"""外部 API 錯誤摘要；不輸出可能含金鑰的網址、例外文字或回應內文。"""


def request_error_summary(service, error):
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return f"{service}請求失敗（HTTP {status}）"
    return f"{service}連線失敗（{type(error).__name__}）"
