import requests
import pandas as pd
from config import FRED_API_KEY, COUNTRIES, INDICATORS

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Соответствие (страна, метрика) -> код серии FRED
FRED_SERIES = {
    # США
    ("US", "CPI"): "CPIAUCSL",
    ("US", "PPI"): "PPIACO",
    ("US", "RATE"): "FEDFUNDS",
    ("US", "GDP"): "A191RL1Q225SBEA",

    # Еврозона
    ("EU", "CPI"): "CPHPTT01EZM659N",
    ("EU", "RATE"): "ECBDFR",

    # Великобритания
    ("GB", "CPI"): "GBRCPIALLMINMEI",
    ("GB", "RATE"): "BOERUKM",

    # Япония
    ("JP", "CPI"): "JPNCPIALLMINMEI",
    ("JP", "RATE"): "IRSTCB01JPM156N",

    # Китай
    ("CN", "CPI"): "CHNCPIALLMINMEI",
}


def fetch_fred(country: str, indicator: str) -> pd.DataFrame | None:
    """Скачивает одну серию из FRED."""
    series_id = FRED_SERIES.get((country, indicator))
    if not series_id:
        return None
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY не задан. Проверь .env")

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }
    r = requests.get(FRED_BASE, params=params, timeout=60)
    r.raise_for_status()
    obs = r.json().get("observations", [])

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["country"] = country
    df["indicator"] = indicator
    return df.dropna()


def fetch_all_macro() -> pd.DataFrame:
    """Проходит по всем странам и метрикам, собирает один DataFrame."""
    frames = []
    for country in COUNTRIES:
        for indicator in INDICATORS:
            try:
                df = fetch_fred(country, indicator)
                if df is not None and not df.empty:
                    frames.append(df)
                    print(f"[OK] {country}/{indicator}: {len(df)} строк")
                else:
                    print(f"[SKIP] {country}/{indicator}: нет серии в FRED")
            except Exception as e:
                print(f"[WARN] {country}/{indicator}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    df = fetch_all_macro()
    print(df.tail(10))
    print(f"Всего строк: {len(df)}")
