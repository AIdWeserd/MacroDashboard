"""
Годовые метрики Eurostat для EU, DE, FR, IT, ES (General Government).

Источник: Eurostat
    - gov_10dd_edpt1 (annual): debt_gdp, budget_gdp
    - bop_gdp6_q (annual): trade_gdp (Current Account % GDP)
      * Страны: partner=WRL_REST; Еврозона: partner=EXT_EAxx
      * Еврозона: EA19/EA20/EA21 в зависимости от периода

Date = 31 декабря каждого года.
"""

import requests
import pandas as pd
from src.euro_area_geo import all_requested_geos, keep_period_geo, EURO_AREA_GEOS

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

COUNTRY_TO_GEO = {
    "EU": "EA21",
    "DE": "DE",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
}
GEO_TO_COUNTRY = {v: k for k, v in COUNTRY_TO_GEO.items()}
GEO_TO_COUNTRY.update({geo: "EU" for geo in EURO_AREA_GEOS})
GEO_LIST = all_requested_geos(COUNTRY_TO_GEO)

LAST_PERIODS = 5


def _parse_jsonstat(data: dict) -> pd.DataFrame:
    """Парсит JSON-stat 2.0 в плоский DataFrame."""
    if not isinstance(data, dict) or "value" not in data or "dimension" not in data:
        return pd.DataFrame()

    dim_ids = data.get("id", [])
    dim_sizes = data.get("size", [])
    dims = data.get("dimension", {})

    positions = {}
    for dim_id in dim_ids:
        category = dims.get(dim_id, {}).get("category", {})
        positions[dim_id] = category.get("index", {})

    by_pos = {dim_id: {v: k for k, v in pos.items()} for dim_id, pos in positions.items()}

    strides = [1] * len(dim_sizes)
    for i in range(len(dim_sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * dim_sizes[i + 1]

    rows = []
    for key, value in data["value"].items():
        if value is None:
            continue
        idx = int(key)
        row = {}
        for i, dim_id in enumerate(dim_ids):
            pos = (idx // strides[i]) % dim_sizes[i]
            row[dim_id] = by_pos[dim_id].get(pos)
        row["value"] = float(value)
        rows.append(row)

    return pd.DataFrame(rows)


def _fetch_dataset(dataset: str, extra_params: dict) -> pd.DataFrame:
    """Тянет один датасет Eurostat."""
    params = {
        "format": "JSON",
        "lang": "EN",
        "geo": GEO_LIST,
        "lastTimePeriod": LAST_PERIODS,
    }
    params.update(extra_params)

    url = f"{EUROSTAT_BASE}/{dataset}"
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return _parse_jsonstat(r.json())


def _fetch_bop_annual_slice(geos: list[str], partner: str) -> pd.DataFrame:
    """
    Тянет annual Current Account % GDP из bop_gdp6_q для заданных geo и partner.
    lastTimePeriod не работает для annual — задаём годы явно.
    """
    current_year = pd.Timestamp.now().year
    years = list(range(current_year - 5, current_year + 1))

    params = [
        ("format", "JSON"),
        ("lang", "EN"),
        ("freq", "A"),
        ("unit", "PC_GDP"),
        ("s_adj", "NSA"),
        ("bop_item", "CA"),
        ("stk_flow", "BAL"),
        ("partner", partner),
    ]
    for g in geos:
        params.append(("geo", g))
    for y in years:
        params.append(("time", str(y)))

    url = f"{EUROSTAT_BASE}/bop_gdp6_q"
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return _parse_jsonstat(r.json())


def _fetch_euro_area_bop_annual() -> pd.DataFrame:
    """Read official annual euro-area current account ratios (extra-EA)."""
    frames = []
    for geo in EURO_AREA_GEOS:
        try:
            frame = _fetch_bop_annual_slice([geo], f"EXT_{geo}")
            if not frame.empty:
                frames.append(frame[frame["geo"] == geo])
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"[WARN] Eurostat annual trade: {geo}, {type(exc).__name__}")
    if not frames:
        return pd.DataFrame(columns=["geo", "time", "value"])
    return pd.concat(frames, ignore_index=True)


def _time_to_year_end(time_code: str) -> pd.Timestamp | None:
    """'2025' → 2025-12-31"""
    try:
        year = int(time_code)
        return pd.Timestamp(year=year, month=12, day=31)
    except (ValueError, AttributeError):
        return None


def fetch_eurostat_annual() -> pd.DataFrame:
    """
    Тянет годовые General Gov метрики Eurostat для EU, DE, FR, IT, ES.
    Возвращает DataFrame: date, country, debt_gdp, budget_gdp, trade_gdp.
    """
    # 1. gov_10dd_edpt1 — debt_gdp и budget_gdp
    try:
        df_gov = _fetch_dataset("gov_10dd_edpt1", {
            "unit": "PC_GDP",
            "sector": "S13",
        })
    except Exception as e:
        print(f"[WARN] Eurostat annual gov_10dd_edpt1: {e}")
        df_gov = pd.DataFrame()

    debt_df = pd.DataFrame(columns=["geo", "time", "debt_gdp"])
    budget_df = pd.DataFrame(columns=["geo", "time", "budget_gdp"])

    if not df_gov.empty and "na_item" in df_gov.columns:
        gd = df_gov[df_gov["na_item"] == "GD"][["geo", "time", "value"]].rename(
            columns={"value": "debt_gdp"}
        )
        b9 = df_gov[df_gov["na_item"] == "B9"][["geo", "time", "value"]].rename(
            columns={"value": "budget_gdp"}
        )
        debt_df = gd
        budget_df = b9

    # 2. Annual current account % GDP, partner Rest of the world,
    # including a period-appropriate euro-area aggregate.
    try:
        national = _fetch_bop_annual_slice(["DE", "FR", "IT", "ES"], "WRL_REST")
        euro_area = _fetch_euro_area_bop_annual()
        df_bop = pd.concat([national, euro_area], ignore_index=True)
        trade_df = (
            df_bop[["geo", "time", "value"]].rename(columns={"value": "trade_gdp"})
            if not df_bop.empty
            else pd.DataFrame(columns=["geo", "time", "trade_gdp"])
        )
    except Exception as e:
        print(f"[WARN] Eurostat annual bop (WRL_REST): {e}")
        trade_df = pd.DataFrame(columns=["geo", "time", "trade_gdp"])

    # 3. Мерж
    frames = [f for f in (debt_df, budget_df, trade_df) if not f.empty]
    if not frames:
        print("[ERROR] Eurostat annual: все датасеты пусты")
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on=["geo", "time"], how="outer")

    result["date"] = result["time"].apply(_time_to_year_end)
    result = result.dropna(subset=["date"])
    result = keep_period_geo(result, "geo", "date")
    result["country"] = result["geo"].map(GEO_TO_COUNTRY)
    result = result.dropna(subset=["country"])

    cols = ["date", "country", "debt_gdp", "budget_gdp", "trade_gdp"]
    for c in cols:
        if c not in result.columns:
            result[c] = None

    result = result[cols].sort_values(["country", "date"]).reset_index(drop=True)
    return result


if __name__ == "__main__":
    df = fetch_eurostat_annual()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.to_string(index=False))
