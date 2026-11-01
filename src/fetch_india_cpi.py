import json
import requests
import pandas as pd

MCP_URL = "https://mcp.mospi.gov.in/mcp"

MONTH_TO_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def fetch_india_cpi() -> pd.DataFrame:
    """
    Тянет CPI Индии (YoY + MoM + Core) из MoSPI MCP-сервера.
        value — YoY headline, %
        mom   — MoM headline, % (считается из index)
        core  — Core YoY, % — MoSPI не публикует официальный Core, всегда None
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_data",
            "arguments": {
                "dataset": "CPI",
                "filters": {
                    "base_year": "2024",
                    "series": "Current",
                    "division_code": 0,  # CPI (General)
                    "state_code": 1,  # All India
                    "sector_code": 3,  # Combined
                    "year": ",".join(str(y) for y in range(2025, pd.Timestamp.now().year + 1)),
                    "month_code": "1,2,3,4,5,6,7,8,9,10,11,12",
                    "limit": max(100, 15 * (pd.Timestamp.now().year - 2025 + 1)),
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
        print(f"[ERROR] India CPI: {e}")
        return pd.DataFrame()

    # Парсим SSE: ищем строку с "data: "
    json_line = None
    for line in r.text.splitlines():
        if line.startswith("data: "):
            json_line = line[len("data: "):]
            break

    if json_line is None:
        print("[ERROR] India CPI: не найден data-блок в ответе")
        return pd.DataFrame()

    try:
        outer = json.loads(json_line)
        inner_text = outer["result"]["content"][0]["text"]
        inner = json.loads(inner_text)
        records = inner.get("data", [])
    except Exception as e:
        print(f"[ERROR] India CPI parse: {e}")
        return pd.DataFrame()

    rows = []
    for rec in records:
        inflation = rec.get("inflation")
        index_val = rec.get("index")
        if inflation is None:
            continue

        try:
            year = int(rec["year"])
            month = MONTH_TO_NUM.get(rec["month"])
            if month is None:
                continue
            date = pd.Timestamp(year=year, month=month, day=1)
            yoy = float(inflation)
            idx = float(index_val) if index_val is not None else None
        except (ValueError, TypeError, KeyError):
            continue

        rows.append({"date": date, "value": yoy, "index": idx})

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if df.empty:
        return pd.DataFrame()

    # MoM из индекса
    df["mom"] = df["index"].pct_change(periods=1) * 100

    df["country"] = "IN"
    df["core"] = None  # MoSPI не публикует Core
    df = df[["date", "country", "value", "mom", "core"]]

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_india_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
