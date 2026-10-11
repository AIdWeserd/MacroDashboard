import requests
import pandas as pd
from io import StringIO

# Eurostat SDMX 2.1 endpoint
EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"

# Датасет HICP (ECOICOP ver.2), месячный, с января 2026 — свежий
DATASET = "PRC_HICP_MINR"

FREQ = "M"

# Измерение "unit": RCH_A — annual rate (YoY), RCH_M — monthly rate (MoM)
UNIT_YOY = "RCH_A"
UNIT_MOM = "RCH_M"

# Измерение "coicop": TOTAL — all items (headline), TOT_X_NRG_FOOD — core
COICOP_HEADLINE = "TOTAL"
COICOP_CORE = "TOT_X_NRG_FOOD"

# Наши коды -> коды Eurostat
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

GEO_TO_COUNTRY = {v: k for k, v in COUNTRY_TO_GEO.items()}


def _fetch_slice(unit: str, coicop: str) -> pd.DataFrame:
    """
    Тянет один срез из PRC_HICP_MINR: фиксированные unit и coicop, все наши geo.
    Возвращает DataFrame с колонками: date, country, value.
    """
    geo_list = "+".join(COUNTRY_TO_GEO.values())
    key = f"{FREQ}.{unit}.{coicop}.{geo_list}"
    url = f"{EUROSTAT_BASE}/{DATASET}/{key}"

    r = requests.get(url, params={"format": "SDMX-CSV"}, timeout=60)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text), low_memory=False)
    if df.empty:
        return pd.DataFrame(columns=["date", "country", "value"])

    df = df.rename(columns={
        "TIME_PERIOD": "date",
        "geo": "country",
        "OBS_VALUE": "value",
    })
    df = df[["date", "country", "value"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    df["country"] = df["country"].map(GEO_TO_COUNTRY).fillna(df["country"])
    return df


def fetch_eurostat_hicp() -> pd.DataFrame:
    """
    Тянет HICP из Eurostat:
        value — YoY headline (RCH_A, TOTAL)
        mom   — MoM headline (RCH_M, TOTAL)
        core  — YoY core    (RCH_A, TOT_X_NRG_FOOD)
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    try:
        yoy = _fetch_slice(UNIT_YOY, COICOP_HEADLINE)
        mom = _fetch_slice(UNIT_MOM, COICOP_HEADLINE)
        core = _fetch_slice(UNIT_YOY, COICOP_CORE)
    except Exception as e:
        print(f"[ERROR] Eurostat: {e}")
        return pd.DataFrame()

    if yoy.empty:
        print("[WARN] Eurostat HICP: пусто (YoY headline)")
        return pd.DataFrame()

    yoy = yoy.rename(columns={"value": "value"})
    mom = mom.rename(columns={"value": "mom"}) if not mom.empty else pd.DataFrame(columns=["date", "country", "mom"])
    core = core.rename(columns={"value": "core"}) if not core.empty else pd.DataFrame(columns=["date", "country", "core"])

    df = yoy.merge(mom, on=["date", "country"], how="left")
    df = df.merge(core, on=["date", "country"], how="left")

    # Оставляем последние 10 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=10)
    df = df[df["date"] >= cutoff]

    return df.sort_values(["country", "date"]).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_eurostat_hicp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Стран: {df['country'].nunique()}")
        print(f"Колонки: {list(df.columns)}")
        print("\nПоследние значения по каждой стране:")
        latest = df.sort_values("date").groupby("country").tail(1)
        print(latest.sort_values("country").to_string(index=False))
