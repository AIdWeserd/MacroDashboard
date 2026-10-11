import requests
import pandas as pd

# ONS — серии CPI
# Каждая: (URL, что содержит)
ONS_SERIES = {
    "yoy":  "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data",  # CPI YoY headline
    "mom":  "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7oe/mm23/data",  # CPI MoM headline
    "core": "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/dko8/mm23/data",  # Core CPI YoY
}

MONTH_TO_NUM = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _fetch_series(url: str) -> pd.DataFrame:
    """
    Тянет одну серию ONS. Возвращает DataFrame с колонками: date, value.
    """
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    months = data.get("months", [])
    if not months:
        return pd.DataFrame(columns=["date", "value"])

    rows = []
    for rec in months:
        date_str = rec.get("date", "")
        value = rec.get("value")
        if not date_str or value is None:
            continue
        try:
            year_str, month_str = date_str.split()
            year = int(year_str)
            month = MONTH_TO_NUM.get(month_str.upper())
            if month is None:
                continue
            rows.append({
                "date": pd.Timestamp(year=year, month=month, day=1),
                "value": float(value),
            })
        except (ValueError, TypeError, KeyError):
            continue

    if not rows:
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


def fetch_uk_cpi() -> pd.DataFrame:
    """
    Тянет CPI Великобритании с ONS: YoY, MoM, Core YoY.
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    try:
        yoy = _fetch_series(ONS_SERIES["yoy"]).rename(columns={"value": "value"})
        mom = _fetch_series(ONS_SERIES["mom"]).rename(columns={"value": "mom"})
        core = _fetch_series(ONS_SERIES["core"]).rename(columns={"value": "core"})
    except Exception as e:
        print(f"[ERROR] UK ONS: {e}")
        return pd.DataFrame()

    if yoy.empty:
        print("[WARN] UK ONS: пусто (YoY)")
        return pd.DataFrame()

    # Мержим три серии по дате
    df = yoy.merge(mom, on="date", how="left")
    df = df.merge(core, on="date", how="left")

    df["country"] = "GB"
    df = df[["date", "country", "value", "mom", "core"]]

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_uk_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))