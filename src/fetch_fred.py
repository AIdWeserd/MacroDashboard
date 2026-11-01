import requests
import pandas as pd
from config import FRED_API_KEY, COUNTRIES, INDICATORS
from src.fred_safety import safe_source_error

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
    """Собирает настроенные FRED-серии и сообщает о частичных сбоях.

    Ненастроенные сочетания страны и показателя не являются ошибками.
    Коды рядов, значения и методологии не меняются.
    """
    frames = []
    issues = []
    for country in COUNTRIES:
        for indicator in INDICATORS:
            series_id = FRED_SERIES.get((country, indicator))
            if series_id is None:
                continue
            label = f"{country}/{indicator} ({series_id})"
            try:
                df = fetch_fred(country, indicator)
                if df is None or df.empty:
                    print(f"[WARN] FRED {label}: нет наблюдений")
                    issues.append(label)
                    continue
                frames.append(df)
                print(f"[OK] {label}: {len(df)} строк")
            except Exception as exc:
                print(f"[WARN] FRED {label}: {safe_source_error(exc)}")
                issues.append(label)
    result = (pd.concat(frames, ignore_index=True) if frames else
              pd.DataFrame(columns=["date", "value", "country", "indicator"]))
    result.attrs["source_issues"] = tuple(issues)
    return result


if __name__ == "__main__":
    df = fetch_all_macro()
    print(df.tail(10))
    print(f"Всего строк: {len(df)}")
