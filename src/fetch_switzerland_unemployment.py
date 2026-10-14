import requests
import pandas as pd
from io import StringIO

SWISS_UNEMP_URL = (
    "https://api.dataseries.org/series.csv"
    "?dataset=ch_fso_unemp_rate&dims=origin=tot,sex=tot"
)


def fetch_switzerland_unemployment() -> pd.DataFrame:
    """
    Тянет месячную безработицу Швейцарии из dataseries.org (FSO).
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    try:
        r = requests.get(SWISS_UNEMP_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Switzerland unemployment: {e}")
        return pd.DataFrame()

    df = pd.read_csv(StringIO(r.text))

    if df.empty or "date" not in df.columns or "value" not in df.columns:
        print("[ERROR] Switzerland unemployment: неверный формат CSV")
        return pd.DataFrame()

    # Фильтруем только Total (origin=tot, sex=tot),
    # потому что API возвращает все комбинации гендеров
    if "origin" in df.columns:
        df = df[df["origin"] == "tot"]
    if "sex" in df.columns:
        df = df[df["sex"] == "tot"]

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)

    df["country"] = "CH"
    df["indicator"] = "UNEMPLOYMENT"

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df[["date", "country", "indicator", "value"]].reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_switzerland_unemployment()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(8).to_string())
