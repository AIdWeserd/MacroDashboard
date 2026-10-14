import requests
import pandas as pd
from io import StringIO

URL = "https://api.dataseries.org/series.csv"

# Swiss SECO GDP — многомерный датасет
DIMS = "type=real;structure=gdp;seas_adj=csa"


def fetch_switzerland_gdp() -> pd.DataFrame:
    """
    Тянет квартальный Real GDP Швейцарии из dataseries.org (SECO).
    Считает YoY, %.
    Возвращает DataFrame с колонками: date, country, gdp_growth.
    """
    params = {
        "dataset": "ch_seco_gdp",
        "dims": DIMS,
    }

    try:
        r = requests.get(URL, params=params, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Switzerland GDP: {e}")
        return pd.DataFrame()

    df = pd.read_csv(StringIO(r.text))
    if df.empty or "date" not in df.columns or "value" not in df.columns:
        print("[ERROR] Switzerland GDP: неверный формат CSV")
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)

    # YoY: pct_change(periods=4) — 4 квартала назад
    df["yoy"] = df["value"].pct_change(periods=4) * 100
    df = df.dropna(subset=["yoy"])

    df["country"] = "CH"
    df = df.rename(columns={"yoy": "gdp_growth"})
    df = df[["date", "country", "gdp_growth"]]

    # Оставляем последние 5 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_switzerland_gdp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(10).to_string(index=False))
