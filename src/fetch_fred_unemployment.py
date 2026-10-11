import time
import requests
import pandas as pd
from config import FRED_API_KEY

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

FRED_UNEMPLOYMENT_SERIES = {
    "US": "UNRATE",
    "JP": "LRHUTTTTJPM156S",
    "GB": "LRHUTTTTGBM156S",
    "CA": "LRHUTTTTCAM156S",
    "AU": "LRUNTTTTAUM156S",
    "KR": "LRUNTTTTKRM156S",
    "TR": "LRHUTTTTTRM156S",
}


def _fetch_one(country: str, series_id: str, max_retries: int = 3) -> pd.DataFrame:
    """Тянет одну серию с retry на таймауты."""
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY не задан")

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2020-01-01",
    }

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=60)
            r.raise_for_status()
            obs = r.json().get("observations", [])

            df = pd.DataFrame(obs)[["date", "value"]]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df["country"] = country
            df["indicator"] = "UNEMPLOYMENT_FRED"
            return df.dropna()

        except Exception as e:
            print(f"[RETRY {attempt}/{max_retries}] FRED unemployment {country}: {e}")
            if attempt < max_retries:
                time.sleep(5)
            else:
                print(f"[ERROR] FRED unemployment {country}: не удалось после {max_retries} попыток")
                return pd.DataFrame()


def fetch_fred_unemployment() -> pd.DataFrame:
    """
    Тянет месячную безработицу из FRED по странам вне ЕС.
    С retry на таймауты.
    """
    frames = []
    for country, series_id in FRED_UNEMPLOYMENT_SERIES.items():
        df = _fetch_one(country, series_id)
        if not df.empty:
            frames.append(df)
            print(f"[OK] FRED unemployment {country} ({series_id}): {len(df)} строк")

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    df = fetch_fred_unemployment()
    print(f"\nВсего строк: {len(df)}")
    print(f"Страны: {df['country'].unique().tolist() if not df.empty else 'пусто'}")
    if not df.empty:
        latest = df.sort_values("date").groupby("country").tail(1)
        print(latest.sort_values("country").to_string())
