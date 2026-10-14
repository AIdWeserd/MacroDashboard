import requests
import pandas as pd

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

COUNTRY_TO_GEO = {
    "EU": "EU27_2020",
    "DE": "DE",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
}
GEO_TO_COUNTRY = {v: k for k, v in COUNTRY_TO_GEO.items()}

GEO_LIST = list(COUNTRY_TO_GEO.values())
LAST_PERIODS = 20

# Приоритет s_adj: сначала SCA, если нет — NSA
S_ADJ_PRIORITY = ["SCA", "SA", "NSA"]


def _parse_jsonstat(data: dict) -> pd.DataFrame:
    """Парсит JSON-stat 2.0 в плоский DataFrame со всеми измерениями."""
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
    """Тянет один датасет. Возвращает DataFrame geo, time, s_adj, value."""
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


def _pick_s_adj(df: pd.DataFrame) -> pd.DataFrame:
    """
    Для каждой (geo, time) выбирает одно значение s_adj по приоритету SCA > SA > NSA.
    Если колонки s_adj нет — возвращает df как есть.
    """
    if df.empty or "s_adj" not in df.columns:
        return df

    df = df.copy()
    df["_priority"] = df["s_adj"].apply(
        lambda x: S_ADJ_PRIORITY.index(x) if x in S_ADJ_PRIORITY else 999
    )
    df = df.sort_values(["geo", "time", "_priority"])
    df = df.drop_duplicates(subset=["geo", "time"], keep="first")
    df = df.drop(columns=["_priority"])
    return df


def _time_to_quarter_end(time_code: str) -> pd.Timestamp | None:
    try:
        year_str, q_str = time_code.split("-Q")
        year = int(year_str)
        q = int(q_str)
        month = q * 3
        return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    except (ValueError, AttributeError):
        return None


def fetch_eurostat_quarterly() -> pd.DataFrame:
    """
    Тянет квартальные метрики из Eurostat для EU, DE, FR, IT, ES:
        gdp_growth  — Рост ВВП, YoY % (namq_10_gdp)
        debt_gdp    — Долг/ВВП, % (gov_10q_ggdebt)
        budget_gdp  — Бюджет/ВВП, % от GDP (gov_10q_ggnfa)
        trade_gdp   — Трейд/ВВП, % от GDP (bop_gdp6_q)
    Для каждой метрики выбирается s_adj по приоритету SCA > SA > NSA.
    Возвращает DataFrame: date, country, gdp_growth, debt_gdp, budget_gdp, trade_gdp.
    """
    datasets = [
        ("gdp_growth", "namq_10_gdp", {
            "na_item": "B1GQ",
            "unit": "CLV_PCH_SM",
        }),
        ("debt_gdp", "gov_10q_ggdebt", {
            "na_item": "GD",
            "sector": "S13",
            "unit": "PC_GDP",
        }),
        ("budget_gdp", "gov_10q_ggnfa", {
            "na_item": "B9",
            "sector": "S13",
            "unit": "PC_GDP",
        }),
        ("trade_gdp", "bop_gdp6_q", {
            "bop_item": "CA",
            "stk_flow": "BAL",
            "unit": "PC_GDP",
        }),
    ]

    results = {}
    for metric, dataset, params in datasets:
        try:
            df = _fetch_dataset(dataset, params)
            if df.empty:
                print(f"[WARN] Eurostat quarterly {metric}: пусто")
                results[metric] = pd.DataFrame(columns=["geo", "time", metric])
                continue

            df = _pick_s_adj(df)
            df = df[["geo", "time", "value"]].rename(columns={"value": metric})
            results[metric] = df
        except Exception as e:
            print(f"[WARN] Eurostat quarterly {metric}: {e}")
            results[metric] = pd.DataFrame(columns=["geo", "time", metric])

    # Мерж всех метрик по (geo, time)
    dfs = [df for df in results.values() if not df.empty]
    if not dfs:
        print("[ERROR] Eurostat quarterly: все датасеты пусты")
        return pd.DataFrame()

    result = dfs[0]
    for other in dfs[1:]:
        result = result.merge(other, on=["geo", "time"], how="outer")

    result["country"] = result["geo"].map(GEO_TO_COUNTRY)
    result["date"] = result["time"].apply(_time_to_quarter_end)
    result = result.dropna(subset=["date", "country"])

    cols = ["date", "country", "gdp_growth", "debt_gdp", "budget_gdp", "trade_gdp"]
    for c in cols:
        if c not in result.columns:
            result[c] = None

    result = result[cols].sort_values(["country", "date"]).reset_index(drop=True)
    return result


if __name__ == "__main__":
    df = fetch_eurostat_quarterly()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(f"Стран: {df['country'].nunique()}")
        print("\nПоследние значения по каждой стране:")
        latest = df.sort_values("date").groupby("country").tail(1)
        print(latest.sort_values("country").to_string(index=False))
