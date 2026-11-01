"""Monthly harmonised unemployment rates, official Eurostat/ECB series.

National data and the latest euro-area composition come from Eurostat
`une_rt_m`.  The historic euro-area changing-composition aggregate is supplied
by the ECB Data Portal (`LFSI`, source: Eurostat), because Eurostat's current
`une_rt_m` API rejects retired EA19/EA20 GEO positions.

All rates: seasonally adjusted, ages 15-74, both sexes, percent of labour force.
Never calculate the aggregate from national values.
"""
from io import StringIO

import pandas as pd
import requests

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
DATASET = "UNE_RT_M"
EURO_AREA_KEY = "M.U2.S.UNEHRT.TOTAL0.15_74.T"

COUNTRY_TO_GEO = {
    "DE": "DE", "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL",
    "BE": "BE", "PL": "PL", "SE": "SE", "AT": "AT", "IE": "IE",
    "PT": "PT", "GR": "EL", "FI": "FI", "DK": "DK", "CZ": "CZ",
    "RO": "RO", "HU": "HU",
}
GEO_TO_COUNTRY = {geo: country for country, geo in COUNTRY_TO_GEO.items()}


def _get_geo_slice(geos: list[str]) -> pd.DataFrame:
    """Load a group of countries (or the current Eurostat EA21 series)."""
    key = "+".join(geos)
    url = f"{EUROSTAT_BASE}/{DATASET}/M.SA.TOTAL.PC_ACT.T.{key}"
    response = requests.get(url, params={"format": "SDMX-CSV"}, timeout=60)
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text), low_memory=False)
    if frame.empty:
        return pd.DataFrame(columns=["date", "geo", "value"])
    geo_col = "geo" if "geo" in frame else "GEO"
    required = {geo_col, "TIME_PERIOD", "OBS_VALUE"}
    if not required.issubset(frame.columns):
        raise ValueError("Eurostat une_rt_m: изменилась схема колонок")
    frame = frame.rename(columns={
        geo_col: "geo", "TIME_PERIOD": "date", "OBS_VALUE": "value",
    })[["date", "geo", "value"]]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna(subset=["date", "geo", "value"])


def _get_national_series(geos: list[str]) -> list[pd.DataFrame]:
    try:
        return [_get_geo_slice(geos)]
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) != 400 or len(geos) <= 1:
            print(f"[WARN] Eurostat unemployment: national HTTP {getattr(exc.response, 'status_code', '?')}")
            return []
        print("[WARN] Eurostat unemployment: изолирую коды стран после HTTP 400")
        parts = []
        for geo in geos:
            try:
                parts.append(_get_geo_slice([geo]))
            except requests.RequestException as individual:
                print(f"[WARN] Eurostat unemployment: geo={geo}, {type(individual).__name__}")
        return parts
    except requests.RequestException as exc:
        print(f"[WARN] Eurostat unemployment: countries {type(exc).__name__}")
        return []


def _fetch_ecb_euro_area_unemployment() -> pd.DataFrame:
    """Official changing-composition euro-area series, including 2023-25.

    ECB LFSI, source EUROSTAT: rate for both sexes age 15-74, SA.
    No conversion, interpolation, or self-computation.
    """
    url = f"{ECB_BASE}/LFSI/{EURO_AREA_KEY}"
    response = requests.get(
        url,
        params={"format": "csvdata", "startPeriod": "2000-01"},
        headers={"Accept": "text/csv"},
        timeout=60,
    )
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text), low_memory=False)
    needed = {"TIME_PERIOD", "OBS_VALUE"}
    if not needed.issubset(frame.columns):
        raise ValueError("ECB LFSI: отсутствуют TIME_PERIOD/OBS_VALUE")
    frame = frame.rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "value"})
    if "KEY" in frame.columns:
        frame = frame[frame["KEY"].astype(str).str.endswith(EURO_AREA_KEY)]
    frame = frame[["date", "value"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"])
    frame["country"] = "EU"
    return frame[["date", "country", "value"]]


def fetch_eurostat_unemployment() -> pd.DataFrame:
    """Return `date, country, value, indicator` without duplicate periods."""
    parts = []
    for frame in _get_national_series(list(COUNTRY_TO_GEO.values())):
        if frame.empty:
            continue
        frame = frame.copy()
        frame["country"] = frame["geo"].map(GEO_TO_COUNTRY)
        parts.append(frame[["date", "country", "value"]].dropna(subset=["country"]))

    # ECB reports the changing-composition aggregate directly; essential for
    # historical years when Eurostat no longer accepts GEO=EA19/EA20.
    try:
        historic = _fetch_ecb_euro_area_unemployment()
        if not historic.empty:
            parts.append(historic)
    except (requests.RequestException, ValueError, pd.errors.ParserError) as exc:
        print(f"[WARN] ECB Euro area unemployment: {type(exc).__name__}")

    # More recent Eurostat EA21 observations take priority for 2026 onward.
    # Before 2026, EA21 MUST NOT be substituted for the official EA19/EA20
    # changing-composition historic series.
    try:
        latest = _get_geo_slice(["EA21"])
        if not latest.empty:
            latest = latest[latest["date"].dt.year >= 2026].copy()
            latest["country"] = "EU"
            parts.append(latest[["date", "country", "value"]])
    except (requests.RequestException, ValueError, pd.errors.ParserError) as exc:
        print(f"[WARN] Eurostat unemployment: EA21 {type(exc).__name__}")

    if not parts:
        print("[ERROR] Eurostat unemployment: не получен ни один ряд")
        return pd.DataFrame(columns=["date", "country", "value", "indicator"])

    result = pd.concat(parts, ignore_index=True)
    result = result.dropna(subset=["date", "country", "value"])
    result = result.drop_duplicates(subset=["date", "country"], keep="last")
    result["indicator"] = "UNEMPLOYMENT"
    return result[["date", "country", "value", "indicator"]].sort_values(
        ["country", "date"]
    ).reset_index(drop=True)


if __name__ == "__main__":
    data = fetch_eurostat_unemployment()
    print(f"Всего строк: {len(data)}")
    if not data.empty:
        print(data.sort_values("date").groupby("country").tail(1).to_string(index=False))
