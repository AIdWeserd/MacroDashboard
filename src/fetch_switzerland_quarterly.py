import time
import requests
import pandas as pd
import io

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

BASE = "https://api.dataseries.org/series.csv"

START_DATE = pd.Timestamp("2024-01-01")


def _get(dataset: str, retries: int = 3) -> pd.DataFrame:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(
                BASE,
                params={"dataset": dataset},
                headers=HEADERS,
                timeout=120,
            )
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text))
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"dataseries.org не ответил по {dataset}: {last_err}")


def fetch_switzerland_gdp() -> pd.DataFrame:
    """Номинальный ВВП Швейцарии (SECO), квартально, млн CHF."""
    df = _get("ch_seco_gdp")
    sub = df[
        (df["type"] == "nom") &
        (df["structure"] == "gdp") &
        (df["seas_adj"] == "csa")
        ].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub["gdp_chf_mn"] = pd.to_numeric(sub["value"], errors="coerce")
    sub = sub[["date", "gdp_chf_mn"]].dropna()
    sub = sub[sub["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return sub


def fetch_switzerland_current_account() -> pd.DataFrame:
    """Current Account Швейцарии (SNB), квартально, млн CHF."""
    df = _get("ch_snb_bopcurrq")
    sub = df[
        (df["D0"] == "L0") &
        (df["D1"] == "S")
        ].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub["ca_chf_mn"] = pd.to_numeric(sub["value"], errors="coerce")
    sub = sub[["date", "ca_chf_mn"]].dropna()
    sub = sub[sub["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return sub


def fetch_switzerland_quarterly() -> pd.DataFrame:
    """Квартальный Трейд/ВВП для Швейцарии.

    Возвращает DataFrame [date, country, trade_gdp].
    """
    gdp = fetch_switzerland_gdp()
    ca = fetch_switzerland_current_account()

    if gdp.empty or ca.empty:
        return pd.DataFrame()

    df = gdp.merge(ca, on="date", how="inner")
    df["trade_gdp"] = df["ca_chf_mn"] / df["gdp_chf_mn"] * 100
    df["country"] = "CH"

    return df[["date", "country", "trade_gdp"]].sort_values("date").reset_index(drop=True)
