import requests
import pandas as pd

CHINA_URL = "https://chinadata.live/api/v2/data/china-unemployment"


def fetch_china_unemployment() -> pd.DataFrame:
    """
    Тянет месячную безработицу Китая из chinadata.live (источник NBS).
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    try:
        r = requests.get(CHINA_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] China unemployment: {e}")
        return pd.DataFrame()

    d = r.json()
    data = d.get("data", {}).get("data", [])

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        try:
            date = pd.to_datetime(item["date"] + "-01")  # "2018-01" -> "2018-01-01"
            value = float(item["value"])
        except (ValueError, TypeError, KeyError):
            continue

        rows.append({
            "date": date,
            "country": "CN",
            "indicator": "UNEMPLOYMENT",
            "value": value,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_china_unemployment()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(5).to_string())
