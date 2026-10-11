import json
import re
import requests
import pandas as pd

MCP_URL = "https://mcp.mospi.gov.in/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# Сколько лет запрашивать (для расчёта YoY нужно минимум 2, берём 5 лет)
YEARS = "2026-27,2025-26,2024-25,2023-24,2022-23"


def _call_mcp(name: str, arguments: dict) -> dict | None:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    try:
        r = requests.post(MCP_URL, json=payload, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] India GDP MCP: {e}")
        return None

    for line in r.text.splitlines():
        if line.startswith("data: "):
            try:
                return json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                return None
    return None


def _fy_quarter_to_date(fy: str, quarter: str) -> pd.Timestamp | None:
    """
    FY 2026-27 Q1 → апрель–июнь 2026 → 2026-06-30
    FY 2026-27 Q2 → июль–сентябрь 2026 → 2026-09-30
    FY 2026-27 Q3 → октябрь–декабрь 2026 → 2026-12-31
    FY 2026-27 Q4 → январь–март 2027 → 2027-03-31
    """
    m = re.match(r"(\d{4})-(\d{2})", fy.strip())
    if not m:
        return None
    start_year = int(m.group(1))

    m2 = re.match(r"Q(\d)", quarter.strip())
    if not m2:
        return None
    q = int(m2.group(1))

    # Q1→июнь, Q2→сентябрь, Q3→декабрь, Q4→март следующего года
    if q == 1:
        return pd.Timestamp(year=start_year, month=6, day=30)
    elif q == 2:
        return pd.Timestamp(year=start_year, month=9, day=30)
    elif q == 3:
        return pd.Timestamp(year=start_year, month=12, day=31)
    elif q == 4:
        return pd.Timestamp(year=start_year + 1, month=3, day=31)
    return None


def fetch_india_gdp() -> pd.DataFrame:
    """
    Тянет квартальный рост ВВП Индии (YoY, %) из MoSPI MCP (NAS, indicator_code=5).
    Считает YoY из constant_price (реальный ВВП).
    Возвращает DataFrame: date, country, gdp_growth.
    """
    result = _call_mcp("get_data", {
        "dataset": "NAS",
        "filters": {
            "base_year": "2022-23",
            "series": "Current",
            "frequency_code": "2",  # Quarterly
            "indicator_code": 5,  # Gross Domestic Product
            "year": YEARS,
            "limit": 100,
            "Format": "JSON",
        },
    })

    if result is None:
        print("[ERROR] India GDP: нет ответа от MCP")
        return pd.DataFrame()

    content = result.get("result", {}).get("content", [{}])[0].get("text", "")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print("[ERROR] India GDP: не удалось распарсить JSON")
        return pd.DataFrame()

    records = data.get("data", [])
    if not records:
        print("[ERROR] India GDP: нет данных")
        return pd.DataFrame()

    rows = []
    for rec in records:
        if rec.get("indicator") != "Gross Domestic Product":
            continue
        date = _fy_quarter_to_date(rec.get("year", ""), rec.get("quarter", ""))
        if date is None:
            continue
        try:
            constant = float(rec.get("constant_price"))
        except (ValueError, TypeError):
            continue
        rows.append({"date": date, "constant": constant})

    if not rows:
        print("[ERROR] India GDP: нет распарсенных строк")
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # YoY: pct_change(periods=4)
    df["gdp_growth"] = df["constant"].pct_change(periods=4) * 100
    df = df.dropna(subset=["gdp_growth"])

    df["country"] = "IN"
    df = df[["date", "country", "gdp_growth"]]

    # Оставляем последние 5 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_india_gdp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(10).to_string(index=False))
