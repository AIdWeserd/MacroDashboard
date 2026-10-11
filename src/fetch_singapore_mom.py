import requests
import pandas as pd

SINGAPORE_URL = (
    "https://data.gov.sg/api/action/datastore_search"
    "?resource_id=d_ca32584c91ee07d091a4ce75fa868414"
    "&limit=200&sort=period%20desc"
)


def fetch_singapore_unemployment() -> pd.DataFrame:
    """
    Тянет квартальную безработицу Сингапура из data.gov.sg.
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    try:
        r = requests.get(SINGAPORE_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Singapore MOM: {e}")
        return pd.DataFrame()

    d = r.json()
    records = d.get("result", {}).get("records", [])

    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        # Оставляем только общую безработицу (overall)
        if rec.get("residential_status") != "overall":
            continue

        period = rec.get("period", "")  # "2026-06"
        if not period:
            continue

        # period -> дата (первое число квартала)
        try:
            year, month = period.split("-")
            date = pd.Timestamp(year=int(year), month=int(month), day=1)
        except Exception:
            continue

        value = rec.get("seasonally_adj_unemp_rate")
        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        rows.append({
            "date": date,
            "country": "SG",
            "indicator": "UNEMPLOYMENT",
            "value": value,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_singapore_unemployment()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print("\nПоследние 5 кварталов:")
        print(df.tail(5).to_string())
