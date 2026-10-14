"""
Годовые данные General Government для США из FRED (IMF WEO).
Используются только для завершённых лет.

- USAGGXCNLGDP  — General Government Net Lending/Borrowing, % GDP, Annual
- USAGGXWDGGDP  — General Government Gross Debt, % GDP, Annual
"""
import time
import requests
import pandas as pd
from config import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "USAGGXCNLGDP": "budget_gdp",
    "USAGGXWDGGDP": "debt_gdp",
}


def _fetch_series(series_id: str, retries: int = 3) -> pd.DataFrame:
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY не задан")

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=60)
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            break
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)

    if not obs:
        return pd.DataFrame()

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().sort_values("date").reset_index(drop=True)


def fetch_us_general_gov_annual() -> pd.DataFrame:
    """
    Годовые General Gov данные США из FRED (IMF).
    Возвращает date, country, budget_gdp, debt_gdp.
    """
    frames = []
    for series_id, col_name in SERIES.items():
        try:
            df = _fetch_series(series_id)
            if df.empty:
                print(f"[WARN] FRED {series_id}: пусто")
                continue
            df = df.rename(columns={"value": col_name})
            frames.append(df)
        except Exception as e:
            print(f"[WARN] FRED {series_id}: {e}")

    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="date", how="outer")

    result["country"] = "US"
    return result.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_us_general_gov_annual()
    print(df.tail(10).to_string(index=False))
