import requests
import pandas as pd
from io import StringIO

ABS_BASE = "https://data.api.abs.gov.au/rest/data"
ABS_DATAFLOW = "CPI"

# MEASURE: 3 = YoY, 2 = MoM
# INDEX: 10001 = All groups CPI
# TSEST: 10 = Original
# REGION: 50 = Weighted average of eight capital cities
# FREQ: M = Monthly
ABS_KEY_YOY = "3.10001.10.50.M"
ABS_KEY_MOM = "2.10001.10.50.M"


def _fetch_abs(data_key: str, start_period: str = "2024-01") -> pd.DataFrame:
    """
    Тянет один срез из ABS Data API.
    Возвращает DataFrame с колонками: date, value.
    """
    url = f"{ABS_BASE}/{ABS_DATAFLOW}/{data_key}"
    params = {
        "startPeriod": start_period,
        "format": "csvfile",
    }

    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text))
    if df.empty or "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        return pd.DataFrame(columns=["date", "value"])

    df = df[["TIME_PERIOD", "OBS_VALUE"]].rename(columns={
        "TIME_PERIOD": "date",
        "OBS_VALUE": "value",
    })
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return df


def fetch_australia_cpi() -> pd.DataFrame:
    """
    Тянет CPI Австралии из ABS Data API:
        value — YoY headline (%)
        mom   — MoM headline (%)
        core  — Trimmed mean YoY, % — недоступен через открытый ABS Data API,
                всегда None. Для получения нужен API-ключ ABS Indicator API.
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    try:
        yoy = _fetch_abs(ABS_KEY_YOY).rename(columns={"value": "value"})
        mom = _fetch_abs(ABS_KEY_MOM).rename(columns={"value": "mom"})
    except Exception as e:
        print(f"[ERROR] Australia CPI: {e}")
        return pd.DataFrame()

    if yoy.empty:
        print("[WARN] Australia CPI: пусто (YoY)")
        return pd.DataFrame()

    df = yoy.merge(mom, on="date", how="left")

    # Core (Trimmed mean) через открытый ABS Data API недоступен
    df["core"] = None

    df["country"] = "AU"
    df = df[["date", "country", "value", "mom", "core"]]

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_australia_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
