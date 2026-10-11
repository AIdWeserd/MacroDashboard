import re
import requests
import pandas as pd

SINGSTAT_BASE = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"
TABLE_ID = "M015631"
ROW_TEXT = "gdp at current market prices"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _parse_period(key: str) -> pd.Timestamp | None:
    """
    '2026 2Q' → 2026-06-30
    '2025 4Q' → 2025-12-31
    """
    m = re.match(r"(\d{4})\s+(\d)Q", key.strip())
    if not m:
        return None
    year = int(m.group(1))
    quarter = int(m.group(2))
    month = quarter * 3
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def fetch_singapore_gdp() -> pd.DataFrame:
    """
    Тянет квартальный GDP Сингапура (YoY, %) из SingStat Table Builder.
    Таблица M015631 — Gross Domestic Product, YoY Growth Rate, Quarterly.
    Возвращает DataFrame: date, country, gdp_growth.
    """
    url = f"{SINGSTAT_BASE}/{TABLE_ID}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] Singapore GDP: {e}")
        return pd.DataFrame()

    rows = data.get("Data", {}).get("row", [])
    if not rows:
        print("[ERROR] Singapore GDP: нет строк")
        return pd.DataFrame()

    target = None
    for row in rows:
        if row.get("rowText", "").strip().lower() == ROW_TEXT:
            target = row
            break

    if target is None:
        print(f"[ERROR] Singapore GDP: не найдена строка «{ROW_TEXT}»")
        return pd.DataFrame()

    columns = target.get("columns", [])
    records = []
    for col in columns:
        key = col.get("key", "")
        value = col.get("value")
        if not key or value is None:
            continue

        date = _parse_period(key)
        if date is None:
            continue

        try:
            gdp_growth = float(value)
        except (ValueError, TypeError):
            continue

        records.append({
            "date": date,
            "country": "SG",
            "gdp_growth": gdp_growth,
        })

    if not records:
        print("[ERROR] Singapore GDP: не удалось распарсить колонки")
        return pd.DataFrame()

    df = pd.DataFrame(records).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 5 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
    df = df[df["date"] >= cutoff]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_singapore_gdp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(8).to_string(index=False))
