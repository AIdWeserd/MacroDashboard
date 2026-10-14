import sqlite3
import pandas as pd
from config import DB_PATH


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _save_df(df: pd.DataFrame, table: str):
    if df.empty:
        print(f"[SKIP] {table}: пустой DataFrame")
        return
    with _connect() as con:
        df.to_sql(table, con, if_exists="replace", index=False)
    print(f"[SAVE] {table}: {len(df)} строк")


def _load_df(table: str, parse_dates: list[str] | None = None) -> pd.DataFrame:
    try:
        with _connect() as con:
            return pd.read_sql(f"SELECT * FROM {table}", con, parse_dates=parse_dates)
    except Exception:
        return pd.DataFrame()


def clear_table(name: str):
    with _connect() as con:
        con.execute(f"DROP TABLE IF EXISTS {name}")


def clear_all():
    for t in (
            "fred", "fred_cpi", "fred_unemployment", "fred_gdp",
            "imf",
            "eurostat", "eurostat_unemployment", "eurostat_quarterly",
            "eurostat_annual",
            "forexfactory", "rss",
            "singapore_unemployment", "singapore_cpi", "singapore_gdp",
            "singapore_quarterly",
            "brazil_unemployment", "brazil_cpi", "brazil_gdp",
            "brazil_quarterly",
            "uk_quarterly",
            "china_unemployment", "china_cpi", "china_debt", "china_debt_fred",
            "china_fiscal", "china_gdp", "china_core_cpi",
            "india_unemployment", "india_cpi", "india_gdp",
            "uk_cpi",
            "canada_cpi", "canada_quarterly",
            "australia_cpi", "australia_quarterly",
            "turkey_cpi",
            "switzerland_cpi", "switzerland_unemployment", "switzerland_gdp",
            "switzerland_quarterly",
            "japan_cpi",
            "korea_cpi", "korea_quarterly",
            "us_quarterly", "us_annual_bea",
            "japan_quarterly",
            "policy_rates",
            "bloomberg",
    ):
        clear_table(t)


# ============================================================
# FRED — исторические макро-ряды
# ============================================================
def save_fred(df: pd.DataFrame):
    _save_df(df, "fred")


def load_fred() -> pd.DataFrame:
    return _load_df("fred", parse_dates=["date"])


# ============================================================
# ForexFactory
# ============================================================
def save_forexfactory(df: pd.DataFrame):
    _save_df(df, "forexfactory")


def load_forexfactory() -> pd.DataFrame:
    return _load_df("forexfactory", parse_dates=["datetime"])


# ============================================================
# RSS
# ============================================================
def save_rss(df: pd.DataFrame):
    _save_df(df, "rss")


def load_rss() -> pd.DataFrame:
    df = _load_df("rss", parse_dates=["published"])
    if not df.empty:
        df = df.sort_values("published", ascending=False)
    return df


# ============================================================
# IMF
# ============================================================
def save_imf(df: pd.DataFrame):
    _save_df(df, "imf")


def load_imf() -> pd.DataFrame:
    return _load_df("imf")


# ============================================================
# Eurostat — HICP
# ============================================================
def save_eurostat(df: pd.DataFrame):
    _save_df(df, "eurostat")


def load_eurostat() -> pd.DataFrame:
    return _load_df("eurostat", parse_dates=["date"])


# ============================================================
# Eurostat — безработица
# ============================================================
def save_eurostat_unemployment(df: pd.DataFrame):
    _save_df(df, "eurostat_unemployment")


def load_eurostat_unemployment() -> pd.DataFrame:
    return _load_df("eurostat_unemployment", parse_dates=["date"])


# ============================================================
# Eurostat — квартальные макро-метрики
# ============================================================
def save_eurostat_quarterly(df: pd.DataFrame):
    _save_df(df, "eurostat_quarterly")


def load_eurostat_quarterly() -> pd.DataFrame:
    return _load_df("eurostat_quarterly", parse_dates=["date"])


# ============================================================
# Eurostat — годовые General Gov метрики
# ============================================================
def save_eurostat_annual(df: pd.DataFrame):
    _save_df(df, "eurostat_annual")


def load_eurostat_annual() -> pd.DataFrame:
    return _load_df("eurostat_annual", parse_dates=["date"])


# ============================================================
# FRED — безработица (не-ЕС)
# ============================================================
def save_fred_unemployment(df: pd.DataFrame):
    _save_df(df, "fred_unemployment")


def load_fred_unemployment() -> pd.DataFrame:
    return _load_df("fred_unemployment", parse_dates=["date"])


# ============================================================
# FRED — CPI
# ============================================================
def save_fred_cpi(df: pd.DataFrame):
    _save_df(df, "fred_cpi")


def load_fred_cpi() -> pd.DataFrame:
    return _load_df("fred_cpi", parse_dates=["date"])


# ============================================================
# FRED — квартальный Real GDP
# ============================================================
def save_fred_gdp(df: pd.DataFrame):
    _save_df(df, "fred_gdp")


def load_fred_gdp() -> pd.DataFrame:
    return _load_df("fred_gdp", parse_dates=["date"])


# ============================================================
# Сингапур — безработица
# ============================================================
def save_singapore_unemployment(df: pd.DataFrame):
    _save_df(df, "singapore_unemployment")


def load_singapore_unemployment() -> pd.DataFrame:
    return _load_df("singapore_unemployment", parse_dates=["date"])


# ============================================================
# Сингапур — CPI
# ============================================================
def save_singapore_cpi(df: pd.DataFrame):
    _save_df(df, "singapore_cpi")


def load_singapore_cpi() -> pd.DataFrame:
    return _load_df("singapore_cpi", parse_dates=["date"])


# ============================================================
# Сингапур — квартальный рост ВВП
# ============================================================
def save_singapore_gdp(df: pd.DataFrame):
    _save_df(df, "singapore_gdp")


def load_singapore_gdp() -> pd.DataFrame:
    return _load_df("singapore_gdp", parse_dates=["date"])


# ============================================================
# Сингапур — квартальные метрики
# ============================================================
def save_singapore_quarterly(df: pd.DataFrame):
    _save_df(df, "singapore_quarterly")


def load_singapore_quarterly() -> pd.DataFrame:
    return _load_df("singapore_quarterly", parse_dates=["date"])


# ============================================================
# Бразилия — безработица
# ============================================================
def save_brazil_unemployment(df: pd.DataFrame):
    _save_df(df, "brazil_unemployment")


def load_brazil_unemployment() -> pd.DataFrame:
    return _load_df("brazil_unemployment", parse_dates=["date"])


# ============================================================
# Бразилия — CPI
# ============================================================
def save_brazil_cpi(df: pd.DataFrame):
    _save_df(df, "brazil_cpi")


def load_brazil_cpi() -> pd.DataFrame:
    return _load_df("brazil_cpi", parse_dates=["date"])


# ============================================================
# Бразилия — квартальный рост ВВП
# ============================================================
def save_brazil_gdp(df: pd.DataFrame):
    _save_df(df, "brazil_gdp")


def load_brazil_gdp() -> pd.DataFrame:
    return _load_df("brazil_gdp", parse_dates=["date"])


# ============================================================
# Бразилия — квартальные метрики
# ============================================================
def save_brazil_quarterly(df: pd.DataFrame):
    _save_df(df, "brazil_quarterly")


def load_brazil_quarterly() -> pd.DataFrame:
    return _load_df("brazil_quarterly", parse_dates=["date"])


# ============================================================
# Великобритания — квартальные метрики (ONS)
# ============================================================
def save_uk_quarterly(df: pd.DataFrame):
    _save_df(df, "uk_quarterly")


def load_uk_quarterly() -> pd.DataFrame:
    return _load_df("uk_quarterly", parse_dates=["date"])


# ============================================================
# Китай — безработица
# ============================================================
def save_china_unemployment(df: pd.DataFrame):
    _save_df(df, "china_unemployment")


def load_china_unemployment() -> pd.DataFrame:
    return _load_df("china_unemployment", parse_dates=["date"])


# ============================================================
# Китай — CPI
# ============================================================
def save_china_cpi(df: pd.DataFrame):
    _save_df(df, "china_cpi")


def load_china_cpi() -> pd.DataFrame:
    return _load_df("china_cpi", parse_dates=["date"])


# ============================================================
# Китай — Core CPI (NBS), с накоплением
# ============================================================
def save_china_core_cpi(df: pd.DataFrame):
    if df.empty:
        print("[SKIP] china_core_cpi: пустой DataFrame")
        return

    with _connect() as con:
        try:
            existing = pd.read_sql("SELECT * FROM china_core_cpi", con)
        except Exception:
            existing = pd.DataFrame()

        if not existing.empty:
            existing["date"] = pd.to_datetime(existing["date"])
            new = df.copy()
            new["date"] = pd.to_datetime(new["date"])

            combined = pd.concat([existing, new], ignore_index=True)

            def _last_notna(s):
                s = s.dropna()
                return s.iloc[-1] if not s.empty else None

            combined = combined.groupby("date", as_index=False).agg({
                "country": "first",
                "inflation_core": _last_notna,
            })
        else:
            combined = df.copy()

        combined = combined.sort_values("date").reset_index(drop=True)
        combined.to_sql("china_core_cpi", con, if_exists="replace", index=False)

    print(f"[SAVE] china_core_cpi: {len(combined)} строк (обновлено {len(df)})")


def load_china_core_cpi() -> pd.DataFrame:
    return _load_df("china_core_cpi", parse_dates=["date"])


# ============================================================
# Китай — квартальный долг (NIFD)
# ============================================================
def save_china_debt(df: pd.DataFrame):
    _save_df(df, "china_debt")


def load_china_debt() -> pd.DataFrame:
    return _load_df("china_debt", parse_dates=["date"])


# ============================================================
# Китай — годовой долг (FRED / IMF WEO)
# ============================================================
def save_china_debt_fred(df: pd.DataFrame):
    _save_df(df, "china_debt_fred")


def load_china_debt_fred() -> pd.DataFrame:
    return _load_df("china_debt_fred", parse_dates=["date"])


# ============================================================
# Китай — квартальный бюджет и трейд
# ============================================================
def save_china_fiscal(df: pd.DataFrame):
    if df.empty:
        print("[SKIP] china_fiscal: пустой DataFrame")
        return

    with _connect() as con:
        try:
            existing = pd.read_sql("SELECT * FROM china_fiscal", con)
        except Exception:
            existing = pd.DataFrame()

        if not existing.empty:
            existing["date"] = pd.to_datetime(existing["date"])
            new = df.copy()
            new["date"] = pd.to_datetime(new["date"])

            combined = pd.concat([existing, new], ignore_index=True)

            def _last_notna(s):
                s = s.dropna()
                return s.iloc[-1] if not s.empty else None

            combined = combined.groupby("date", as_index=False).agg({
                "country": "first",
                "budget_gdp": _last_notna,
                "trade_gdp": _last_notna,
            })
        else:
            combined = df.copy()

        combined = combined.sort_values("date").reset_index(drop=True)
        combined.to_sql("china_fiscal", con, if_exists="replace", index=False)

    print(f"[SAVE] china_fiscal: {len(combined)} строк (обновлено {len(df)})")


def load_china_fiscal() -> pd.DataFrame:
    return _load_df("china_fiscal", parse_dates=["date"])


# ============================================================
# Китай — квартальный рост ВВП
# ============================================================
def save_china_gdp(df: pd.DataFrame):
    _save_df(df, "china_gdp")


def load_china_gdp() -> pd.DataFrame:
    return _load_df("china_gdp", parse_dates=["date"])


# ============================================================
# Индия — безработица
# ============================================================
def save_india_unemployment(df: pd.DataFrame):
    _save_df(df, "india_unemployment")


def load_india_unemployment() -> pd.DataFrame:
    return _load_df("india_unemployment", parse_dates=["date"])


# ============================================================
# Индия — CPI
# ============================================================
def save_india_cpi(df: pd.DataFrame):
    _save_df(df, "india_cpi")


def load_india_cpi() -> pd.DataFrame:
    return _load_df("india_cpi", parse_dates=["date"])


# ============================================================
# Индия — квартальный рост ВВП (MoSPI MCP, NAS)
# ============================================================
def save_india_gdp(df: pd.DataFrame):
    _save_df(df, "india_gdp")


def load_india_gdp() -> pd.DataFrame:
    return _load_df("india_gdp", parse_dates=["date"])


# ============================================================
# Великобритания — CPI
# ============================================================
def save_uk_cpi(df: pd.DataFrame):
    _save_df(df, "uk_cpi")


def load_uk_cpi() -> pd.DataFrame:
    return _load_df("uk_cpi", parse_dates=["date"])


# ============================================================
# Канада — CPI
# ============================================================
def save_canada_cpi(df: pd.DataFrame):
    _save_df(df, "canada_cpi")


def load_canada_cpi() -> pd.DataFrame:
    return _load_df("canada_cpi", parse_dates=["date"])


# ============================================================
# Канада — квартальные метрики (StatCan WDS)
# ============================================================
def save_canada_quarterly(df: pd.DataFrame):
    _save_df(df, "canada_quarterly")


def load_canada_quarterly() -> pd.DataFrame:
    return _load_df("canada_quarterly", parse_dates=["date"])


# ============================================================
# Австралия — CPI
# ============================================================
def save_australia_cpi(df: pd.DataFrame):
    _save_df(df, "australia_cpi")


def load_australia_cpi() -> pd.DataFrame:
    return _load_df("australia_cpi", parse_dates=["date"])


# ============================================================
# Австралия — квартальные метрики
# ============================================================
def save_australia_quarterly(df: pd.DataFrame):
    _save_df(df, "australia_quarterly")


def load_australia_quarterly() -> pd.DataFrame:
    return _load_df("australia_quarterly", parse_dates=["date"])


# ============================================================
# Турция — CPI
# ============================================================
def save_turkey_cpi(df: pd.DataFrame):
    _save_df(df, "turkey_cpi")


def load_turkey_cpi() -> pd.DataFrame:
    return _load_df("turkey_cpi", parse_dates=["date"])


# ============================================================
# Швейцария — CPI
# ============================================================
def save_switzerland_cpi(df: pd.DataFrame):
    _save_df(df, "switzerland_cpi")


def load_switzerland_cpi() -> pd.DataFrame:
    return _load_df("switzerland_cpi", parse_dates=["date"])


# ============================================================
# Швейцария — безработица
# ============================================================
def save_switzerland_unemployment(df: pd.DataFrame):
    _save_df(df, "switzerland_unemployment")


def load_switzerland_unemployment() -> pd.DataFrame:
    return _load_df("switzerland_unemployment", parse_dates=["date"])


# ============================================================
# Швейцария — квартальный рост ВВП (SECO)
# ============================================================
def save_switzerland_gdp(df: pd.DataFrame):
    _save_df(df, "switzerland_gdp")


def load_switzerland_gdp() -> pd.DataFrame:
    return _load_df("switzerland_gdp", parse_dates=["date"])


# ============================================================
# Швейцария — квартальные метрики
# ============================================================
def save_switzerland_quarterly(df: pd.DataFrame):
    _save_df(df, "switzerland_quarterly")


def load_switzerland_quarterly() -> pd.DataFrame:
    return _load_df("switzerland_quarterly", parse_dates=["date"])


# ============================================================
# Япония — CPI
# ============================================================
def save_japan_cpi(df: pd.DataFrame):
    _save_df(df, "japan_cpi")


def load_japan_cpi() -> pd.DataFrame:
    return _load_df("japan_cpi", parse_dates=["date"])


# ============================================================
# Южная Корея — CPI
# ============================================================
def save_korea_cpi(df: pd.DataFrame):
    _save_df(df, "korea_cpi")


def load_korea_cpi() -> pd.DataFrame:
    return _load_df("korea_cpi", parse_dates=["date"])


# ============================================================
# Южная Корея — квартальные метрики (IMF DSBB)
# ============================================================
def save_korea_quarterly(df: pd.DataFrame):
    _save_df(df, "korea_quarterly")


def load_korea_quarterly() -> pd.DataFrame:
    return _load_df("korea_quarterly", parse_dates=["date"])


# ============================================================
# США — квартальные метрики (Treasury + BEA)
# ============================================================
def save_us_quarterly(df: pd.DataFrame):
    _save_df(df, "us_quarterly")


def load_us_quarterly() -> pd.DataFrame:
    return _load_df("us_quarterly", parse_dates=["date"])


# ============================================================
# США — годовые General Gov (BEA NIPA)
# ============================================================
def save_us_annual_bea(df: pd.DataFrame):
    _save_df(df, "us_annual_bea")


def load_us_annual_bea() -> pd.DataFrame:
    return _load_df("us_annual_bea", parse_dates=["date"])


# ============================================================
# Япония — квартальные метрики
# ============================================================
def save_japan_quarterly(df: pd.DataFrame):
    _save_df(df, "japan_quarterly")


def load_japan_quarterly() -> pd.DataFrame:
    return _load_df("japan_quarterly", parse_dates=["date"])


# ============================================================
# Ставки ЦБ (policy rates)
# ============================================================
def save_policy_rates(df: pd.DataFrame):
    _save_df(df, "policy_rates")


def load_policy_rates() -> pd.DataFrame:
    return _load_df("policy_rates", parse_dates=["date"])


# ============================================================
# Bloomberg (ручные выгрузки)
# ============================================================
def save_bloomberg(df: pd.DataFrame):
    _save_df(df, "bloomberg")


def load_bloomberg() -> pd.DataFrame:
    return _load_df("bloomberg", parse_dates=["date"])
