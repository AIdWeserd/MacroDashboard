import time
import requests
import pandas as pd
from config import BEA_API_KEY

BEA_BASE = "https://apps.bea.gov/api/data/"
START_YEAR = "2024"


def _get(params: dict, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(BEA_BASE, params=params, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"BEA не ответил: {last_err}")


def _parse_time_period(tp: str) -> pd.Timestamp:
    year, q = tp.split("Q")
    month = (int(q) - 1) * 3 + 1
    return pd.Timestamp(year=int(year), month=month, day=1)


def fetch_us_gdp() -> pd.DataFrame:
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": "T10105",
        "Frequency": "Q",
        "Year": f"{START_YEAR},2025,2026",
        "ResultFormat": "JSON",
    }
    data = _get(params)
    rows = data["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)
    # Оставляем только строку GDP (SeriesCode=A191RC)
    df = df[df["SeriesCode"] == "A191RC"].copy()
    df["date"] = df["TimePeriod"].apply(_parse_time_period)
    df["gdp_usd_mn"] = pd.to_numeric(
        df["DataValue"].str.replace(",", ""), errors="coerce"
    )
    df = df[["date", "gdp_usd_mn"]].dropna().sort_values("date")
    return df.reset_index(drop=True)


def fetch_us_current_account() -> pd.DataFrame:
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "ITA",
        "Indicator": "BalCurrAcct",
        "AreaOrCountry": "AllCountries",
        "Frequency": "QSA",
        "Year": f"{START_YEAR},2025,2026",
        "ResultFormat": "JSON",
    }
    data = _get(params)
    rows = data["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)
    df["date"] = df["TimePeriod"].apply(_parse_time_period)
    df["trade_usd_mn"] = pd.to_numeric(df["DataValue"], errors="coerce")
    df = df[["date", "trade_usd_mn"]].dropna().sort_values("date")
    df = df.drop_duplicates(subset="date", keep="last")
    return df.reset_index(drop=True)


def fetch_us_bea() -> pd.DataFrame:
    gdp = fetch_us_gdp()
    ca = fetch_us_current_account()

    if gdp.empty and ca.empty:
        return pd.DataFrame()

    result = gdp.merge(ca, on="date", how="outer")
    result["country"] = "US"
    result = result.sort_values("date").reset_index(drop=True)
    return result
