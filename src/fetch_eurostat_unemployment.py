import requests
import pandas as pd
from io import StringIO

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"

# Датасет: безработица, месячная, сезонно сглаженная, %
DATASET = "UNE_RT_M"
FREQ = "M"          # Monthly
S_ADJ = "SA"        # Seasonally adjusted
AGE = "TOTAL"       # Total age
UNIT = "PC_ACT"     # % of active population
SEX = "T"           # Total sex

COUNTRY_TO_GEO = {
    "EU": "EU27_2020",
    "DE": "DE",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
    "NL": "NL",
    "BE": "BE",
    "PL": "PL",
    "SE": "SE",
    "AT": "AT",
    "IE": "IE",
    "PT": "PT",
    "GR": "EL",
    "FI": "FI",
    "DK": "DK",
    "CZ": "CZ",
    "RO": "RO",
    "HU": "HU",
}


def fetch_eurostat_unemployment() -> pd.DataFrame:
    """
    Тянет уровень безработицы из Eurostat.
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    geo_list = "+".join(COUNTRY_TO_GEO.values())
    # Порядок измерений: freq . s_adj . age . unit . sex . geo
    url = f"{EUROSTAT_BASE}/{DATASET}/{FREQ}.{S_ADJ}.{AGE}.{UNIT}.{SEX}.{geo_list}"

    params = {"format": "SDMX-CSV"}

    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Eurostat unemployment: {e}")
        return pd.DataFrame()

    df = pd.read_csv(StringIO(r.text))
    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "TIME_PERIOD": "date",
        "geo": "country",
        "OBS_VALUE": "value",
    })
    df = df[["date", "country", "value"]].copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    geo_to_country = {v: k for k, v in COUNTRY_TO_GEO.items()}
    df["country"] = df["country"].map(geo_to_country).fillna(df["country"])

    df["indicator"] = "UNEMPLOYMENT"
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    return df.sort_values(["country", "date"]).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_eurostat_unemployment()
    print(f"Всего строк: {len(df)}")
    print(f"Стран: {df['country'].nunique()}")
    print("\nПоследние значения по каждой стране:")
    latest = df.sort_values("date").groupby("country").tail(1)
    print(latest.sort_values("country").to_string())