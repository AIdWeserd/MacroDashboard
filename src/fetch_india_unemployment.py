import json
import requests
import pandas as pd

MCP_URL = "https://mcp.mospi.gov.in/mcp"

MONTH_TO_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def fetch_india_unemployment() -> pd.DataFrame:
    """
    Тянет месячную безработицу Индии из MoSPI MCP-сервера.
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_data",
            "arguments": {
                "dataset": "PLFS",
                "filters": {
                    "indicator_code": 3,  # UR
                    "frequency_code": 3,  # Monthly
                    "year": "2025,2026",
                    "month_code": "1,2,4,5,6,7,8,9,10,11,12",
                    "state_code": 99,  # All India
                    "gender_code": 3,  # person
                    "age_code": 1,  # 15+
                    "sector_code": 3,  # rural + urban
                    "limit": 100,
                    "Format": "JSON",
                },
            },
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        r = requests.post(MCP_URL, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] India MCP: {e}")
        return pd.DataFrame()

    # Парсим SSE: ищем строку, начинающуюся с "data: "
    raw_text = r.text
    json_line = None
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            json_line = line[len("data: "):]
            break

    if json_line is None:
        print("[ERROR] India MCP: не найден data-блок в ответе")
        return pd.DataFrame()

    try:
        outer = json.loads(json_line)
        # Внутри: result.content[0].text -> строка JSON
        inner_text = outer["result"]["content"][0]["text"]
        inner = json.loads(inner_text)
        records = inner.get("data", [])
    except Exception as e:
        print(f"[ERROR] India MCP parse: {e}")
        return pd.DataFrame()

    rows = []
    for rec in records:
        try:
            year = int(rec["year"])
            month = MONTH_TO_NUM.get(rec["month"])
            if month is None:
                continue
            date = pd.Timestamp(year=year, month=month, day=1)
            value = float(rec["value"])
        except (ValueError, TypeError, KeyError):
            continue

        rows.append({
            "date": date,
            "country": "IN",
            "indicator": "UNEMPLOYMENT",
            "value": value,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_india_unemployment()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(8).to_string())
