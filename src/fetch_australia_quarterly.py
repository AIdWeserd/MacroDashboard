import time
import requests
import pandas as pd
import io

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/vnd.sdmx.data+csv; labels=name",
}

BASE = "https://data.api.abs.gov.au/rest/data"

START_DATE = pd.Timestamp("2024-01-01")


def _get(dataflow: str, key: str, start_period: str = "2024-Q1",
         end_period: str | None = None, retries: int = 3) -> str:
    """Скачивает CSV из ABS Data API."""
    url = f"{BASE}/ABS,{dataflow},1.0.0/{key}"
    params = {
        "startPeriod": start_period,
        "endPeriod": end_period or f"{pd.Timestamp.now().year}-Q{pd.Timestamp.now().quarter}",
        "format": "csvfilewithlabels",
    }
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"ABS не ответил по {dataflow}/{key}: {last_err}")


def _parse_csv(csv_text: str) -> pd.DataFrame:
    """Парсит CSV от ABS Data API. Возвращает [date, value]."""
    # Первая строка — заголовок, значения в кавычках
    df = pd.read_csv(io.StringIO(csv_text))
    # Ищем колонку с периодом и значением
    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        return pd.DataFrame()

    df = df[["TIME_PERIOD", "OBS_VALUE"]].dropna()

    # TIME_PERIOD: "2026-Q2" -> Timestamp(2026-04-01)
    def _parse_period(p):
        try:
            year, q = p.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return pd.Timestamp(year=int(year), month=month, day=1)
        except Exception:
            return None

    df["date"] = df["TIME_PERIOD"].apply(_parse_period)
    df["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    return df[["date", "value"]].sort_values("date").reset_index(drop=True)


def fetch_australia_trade() -> pd.DataFrame:
    """Current Account Balance (SA), млн AUD."""
    csv_text = _get("BOP", "1.100.20..")
    df = _parse_csv(csv_text)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"value": "ca_aud_mn"})
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    return df


def fetch_australia_gdp() -> pd.DataFrame:
    """GDP, Current prices (SA), млн AUD."""
    csv_text = _get("ANA_AGG", "M3.GPM.20..")
    df = _parse_csv(csv_text)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"value": "gdp_aud_mn"})
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    return df


def fetch_australia_quarterly() -> pd.DataFrame:
    """Квартальный Трейд/ВВП для Австралии.

    Возвращает DataFrame [date, country, trade_gdp].
    """
    trade = fetch_australia_trade()
    gdp = fetch_australia_gdp()

    if trade.empty or gdp.empty:
        return pd.DataFrame()

    df = trade.merge(gdp, on="date", how="inner")
    df["trade_gdp"] = df["ca_aud_mn"] / df["gdp_aud_mn"] * 100
    df["country"] = "AU"

    return df[["date", "country", "trade_gdp"]].sort_values("date").reset_index(drop=True)
