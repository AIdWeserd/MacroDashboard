import time
import requests
import pandas as pd

SINGSTAT_BASE = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"

TABLE_HEADLINE = "M213751"
TABLE_CORE = "M213891"

ROW_HEADLINE = "all items"
ROW_CORE = "mas core inflation measure"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

MONTH_TO_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _fetch_json(url: str, retries: int = 3, timeout: int = 60) -> dict | None:
    """Тянет JSON с SingStat с retry (502/503/504 и таймауты)."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            # 502/503/504 — ретраим
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] SingStat {url}: {e}")
                return None
            wait = 3 * attempt
            print(f"[RETRY] SingStat: попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return None


def _fetch_row(table_id: str, row_text: str) -> pd.DataFrame:
    """Тянет одну строку из таблицы SingStat. Возвращает date, index."""
    url = f"{SINGSTAT_BASE}/{table_id}"
    data = _fetch_json(url)
    if data is None:
        return pd.DataFrame(columns=["date", "index"])

    rows = data.get("Data", {}).get("row", [])
    if not rows:
        return pd.DataFrame(columns=["date", "index"])

    target = None
    for row in rows:
        if row.get("rowText", "").strip().lower() == row_text:
            target = row
            break

    if target is None:
        return pd.DataFrame(columns=["date", "index"])

    columns = target.get("columns", [])
    points = []
    for col in columns:
        key = col.get("key", "")
        value = col.get("value")
        if not key or value is None:
            continue

        parts = key.split()
        if len(parts) != 2:
            continue
        try:
            year = int(parts[0])
            month = MONTH_TO_NUM.get(parts[1])
            if month is None:
                continue
            date = pd.Timestamp(year=year, month=month, day=1)
            index = float(value)
        except (ValueError, TypeError):
            continue

        points.append({"date": date, "index": index})

    if not points:
        return pd.DataFrame(columns=["date", "index"])

    df = pd.DataFrame(points).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def fetch_singapore_cpi() -> pd.DataFrame:
    """
    Тянет CPI Сингапура из SingStat:
        value — YoY headline, % (CPI All Items)
        mom   — MoM headline, %
        core  — MAS Core Inflation Measure, YoY %
    Возвращает DataFrame: date, country, value, mom, core.
    """
    headline = _fetch_row(TABLE_HEADLINE, ROW_HEADLINE)
    core = _fetch_row(TABLE_CORE, ROW_CORE)

    if headline.empty:
        print("[WARN] Singapore CPI: пусто (headline)")
        return pd.DataFrame()

    raw = headline["index"]
    headline["mom"] = raw.pct_change(periods=1) * 100
    headline["value"] = raw.pct_change(periods=12) * 100

    if not core.empty:
        core["core"] = core["index"].pct_change(periods=12) * 100
        core = core[["date", "core"]]
    else:
        core = pd.DataFrame(columns=["date", "core"])

    df = headline.merge(core, on="date", how="left")
    df["country"] = "SG"
    df = df[["date", "country", "value", "mom", "core"]]
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_singapore_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
