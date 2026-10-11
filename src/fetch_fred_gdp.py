import requests
import pandas as pd
from config import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Квартальный Real GDP из FRED
FRED_GDP_SERIES = {
    "US": "GDPC1",  # Real GDP
    "JP": "JPNRGDPEXP",  # Real GDP
    "GB": "NGDPRSAXDCGBQ",  # Real GDP, SA
    "CA": "NGDPRSAXDCCAQ",  # Real GDP, SA
    "AU": "NGDPRSAXDCAUQ",  # Real GDP, SA
    "KR": "NGDPRSAXDCKRQ",  # Real GDP, SA
    "TR": "NGDPRSAXDCTRQ",  # Real GDP, SA
}


def _fetch_series(series_id: str, retries: int = 3, timeout: int = 60) -> pd.DataFrame:
    """Тянет одну серию FRED с retry."""
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
            r = requests.get(FRED_BASE, params=params, timeout=timeout)
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            break
        except Exception as e:
            if attempt == retries:
                raise
            import time
            time.sleep(2 * attempt)

    if not obs:
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df


def fetch_fred_gdp() -> pd.DataFrame:
    """
    Тянет квартальный Real GDP из FRED для US, JP, GB, CA, AU, KR, TR.
    Считает YoY, %.
    Возвращает DataFrame с колонками: date, country, gdp_growth.
    """
    frames = []
    for country, series_id in FRED_GDP_SERIES.items():
        try:
            df = _fetch_series(series_id)
            if df.empty:
                print(f"[SKIP] FRED GDP {country} ({series_id}): пусто")
                continue

            df["yoy"] = df["value"].pct_change(periods=4) * 100  # квартал к кварталу год назад
            df = df.dropna(subset=["yoy"])

            df["country"] = country
            df = df.rename(columns={"yoy": "gdp_growth"})
            df = df[["date", "country", "gdp_growth"]]

            frames.append(df)
            last = df.iloc[-1]
            print(f"[OK] FRED GDP {country} ({series_id}): {len(df)} строк, "
                  f"последняя — {last['date'].date()}, YoY={last['gdp_growth']:.2f}")

        except Exception as e:
            print(f"[WARN] FRED GDP {country}: {e}")

    if not frames:
        return pd.DataFrame()

    full = pd.concat(frames, ignore_index=True)
    return full.sort_values(["country", "date"]).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_fred_gdp()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print(df.tail(15).to_string(index=False))
