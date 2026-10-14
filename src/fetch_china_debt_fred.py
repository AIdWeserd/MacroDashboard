"""
General Government Gross Debt для Китая из FRED (IMF WEO).

Источник: IMF World Economic Outlook (WEO)
Series: GGGDTACNA188N — General government gross debt, % of GDP
"""

import time
import requests
import pandas as pd
from config import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = "GGGDTACNA188N"


def fetch_china_debt_fred() -> pd.DataFrame:
    """
    Тянет General Gov Gross Debt Китая (annual, % GDP) из FRED.
    Возвращает DataFrame с колонками: date, country, debt_gdp.
    """
    if not FRED_API_KEY:
        print("[WARN] FRED_API_KEY не задан")
        return pd.DataFrame()

    params = {
        "series_id": SERIES_ID,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }

    for attempt in range(1, 4):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=60)
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            break
        except Exception as e:
            if attempt == 3:
                print(f"[WARN] FRED {SERIES_ID}: {e}")
                return pd.DataFrame()
            time.sleep(2 * attempt)

    if not obs:
        return pd.DataFrame()

    rows = []
    for item in obs:
        try:
            date = pd.to_datetime(item["date"])
            value = float(item["value"])
        except (ValueError, TypeError, KeyError):
            continue
        rows.append({
            "date": date,
            "country": "CN",
            "debt_gdp": round(value, 2),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = fetch_china_debt_fred()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(10).to_string(index=False))
