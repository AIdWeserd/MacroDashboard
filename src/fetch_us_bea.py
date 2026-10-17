import time
import requests
import pandas as pd
from config import BEA_API_KEY, FRED_API_KEY

BEA_BASE = "https://apps.bea.gov/api/data/"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
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
    """Квартальный номинальный ВВП (SAAR, млн $) из BEA NIPA T10105."""
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
    df = df[df["SeriesCode"] == "A191RC"].copy()
    df["date"] = df["TimePeriod"].apply(_parse_time_period)
    df["gdp_usd_mn"] = pd.to_numeric(
        df["DataValue"].str.replace(",", ""), errors="coerce"
    )
    df = df[["date", "gdp_usd_mn"]].dropna().sort_values("date")
    return df.reset_index(drop=True)


def fetch_us_current_account() -> pd.DataFrame:
    """Квартальный Current Account (SAAR, млн $) из BEA ITA BalCurrAcct."""
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
    """Сборка квартальных BEA-данных: GDP + Current Account."""
    gdp = fetch_us_gdp()
    ca = fetch_us_current_account()

    frames = [f for f in (gdp, ca) if not f.empty]
    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="date", how="outer")

    result["country"] = "US"
    return result.sort_values("date").reset_index(drop=True)


def _fetch_nipa_annual(table: str, year: str) -> pd.DataFrame:
    """Тянет annual NIPA table и извлекает Net lending or net borrowing."""
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": table,
        "Frequency": "A",
        "Year": year,
        "ResultFormat": "JSON",
    }
    data = _get(params)
    rows = data["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)

    mask = df["LineDescription"].str.contains(
        "Net lending or net borrowing", case=False, na=False
    )
    sub = df[mask].copy()
    if sub.empty:
        return pd.DataFrame()

    sub["date"] = sub["TimePeriod"].apply(
        lambda tp: pd.Timestamp(year=int(tp), month=1, day=1)
    )
    sub["value"] = pd.to_numeric(
        sub["DataValue"].str.replace(",", ""), errors="coerce"
    )
    return sub[["date", "value"]].dropna()


def fetch_us_general_gov_debt_annual() -> pd.DataFrame:
    """
    Годовой General Government Gross Debt (% GDP) из FRED (IMF).
    Серия: USAGGXWDGGDP.
    """
    if not FRED_API_KEY:
        print("[WARN] FRED_API_KEY не задан")
        return pd.DataFrame()

    params = {
        "series_id": "USAGGXWDGGDP",
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",
    }
    try:
        r = requests.get(FRED_BASE, params=params, timeout=60)
        r.raise_for_status()
        obs = r.json().get("observations", [])
    except Exception as e:
        print(f"[WARN] FRED USAGGXWDGGDP: {e}")
        return pd.DataFrame()

    if not obs:
        return pd.DataFrame()

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["debt_gdp"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[["date", "debt_gdp"]].dropna().sort_values("date").reset_index(drop=True)
    df["country"] = "US"
    return df


def fetch_us_general_gov_annual() -> pd.DataFrame:
    """
    Годовой General Government (annual):
    - budget_gdp = (T30100 + T30300) / GDP * 100
    - trade_gdp  = Current Account (annual) / GDP * 100
    - debt_gdp   = FRED USAGGXWDGGDP (IMF, General Gov Gross Debt % GDP)
    """
    years = "2023,2024,2025"

    fed = _fetch_nipa_annual("T30100", years)
    sl = _fetch_nipa_annual("T30300", years)

    if fed.empty or sl.empty:
        return pd.DataFrame()

    fed = fed.rename(columns={"value": "federal"})
    sl = sl.rename(columns={"value": "state_local"})

    df = fed.merge(sl, on="date", how="inner")
    df["general_gov"] = df["federal"] + df["state_local"]

    # Годовой GDP (среднее по 4 кварталам)
    gdp = fetch_us_gdp()
    if gdp.empty:
        return pd.DataFrame()
    gdp = gdp.copy()
    gdp["year"] = gdp["date"].dt.year
    gdp_annual = gdp.groupby("year", as_index=False)["gdp_usd_mn"].mean()
    gdp_annual["date"] = pd.to_datetime(gdp_annual["year"].astype(str) + "-01-01")

    df = df.merge(gdp_annual[["date", "gdp_usd_mn"]], on="date", how="inner")
    df["budget_gdp"] = df["general_gov"] / df["gdp_usd_mn"] * 100

    # Годовой Current Account
    ca = fetch_us_current_account()
    if not ca.empty:
        ca = ca.copy()
        ca["year"] = ca["date"].dt.year
        ca_annual = ca.groupby("year", as_index=False)["trade_usd_mn"].mean()
        ca_annual["date"] = pd.to_datetime(ca_annual["year"].astype(str) + "-01-01")
        df = df.merge(ca_annual[["date", "trade_usd_mn"]], on="date", how="left")
        df["trade_gdp"] = df["trade_usd_mn"] / df["gdp_usd_mn"] * 100

    # Годовой General Gov Debt (% GDP) из FRED
    debt = fetch_us_general_gov_debt_annual()
    if not debt.empty:
        debt = debt.copy()
        debt["year"] = debt["date"].dt.year
        debt = debt[["year", "debt_gdp"]]
        df["year"] = df["date"].dt.year
        df = df.merge(debt, on="year", how="left")
        df = df.drop(columns=["year"])

    df["country"] = "US"
    return df[[
        "date", "country", "budget_gdp", "trade_gdp", "debt_gdp", "gdp_usd_mn",
    ]].sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    print("=== General Gov Annual ===")
    print(fetch_us_general_gov_annual().to_string(index=False))
