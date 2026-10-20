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
        "imf", "eurostat", "eurostat_unemployment",
        "eurostat_quarterly", "eurostat_annual",
        "forexfactory", "rss",
        "singapore_unemployment", "singapore_cpi",
        "singapore_gdp", "singapore_quarterly",
        "brazil_unemployment", "brazil_cpi",
        "brazil_gdp", "brazil_quarterly",
        "uk_quarterly",
        "china_unemployment", "china_cpi", "china_debt",
        "china_debt_fred", "china_fiscal", "china_gdp",
        "china_core_cpi",
        "india_unemployment", "india_cpi", "india_gdp",
        "uk_cpi", "canada_cpi", "canada_quarterly",
        "australia_cpi", "australia_quarterly",
        "turkey_cpi",
        "switzerland_cpi", "switzerland_unemployment",
        "switzerland_gdp", "switzerland_quarterly",
        "japan_cpi", "korea_cpi", "korea_quarterly",
        "us_quarterly", "us_annual_bea",
        "japan_quarterly",
        "russia_cpi", "russia_quarterly", "russia_rates", "russia_credit",
        "policy_rates", "bloomberg",
    ):
        clear_table(t)


# ============================================================
# Стандартные операции хранения
# ============================================================

# В каждом имени: (имя таблицы, поле даты).
# Для таблиц без даты указано None.
STANDARD_TABLES = {
    "fred": "date",
    "forexfactory": "datetime",
    "rss": "published",
    "imf": None,
    "eurostat": "date",
    "eurostat_unemployment": "date",
    "eurostat_quarterly": "date",
    "eurostat_annual": "date",
    "fred_unemployment": "date",
    "fred_cpi": "date",
    "fred_gdp": "date",
    "singapore_unemployment": "date",
    "singapore_cpi": "date",
    "singapore_gdp": "date",
    "singapore_quarterly": "date",
    "brazil_unemployment": "date",
    "brazil_cpi": "date",
    "brazil_gdp": "date",
    "brazil_quarterly": "date",
    "uk_quarterly": "date",
    "china_unemployment": "date",
    "china_cpi": "date",
    "china_debt": "date",
    "china_debt_fred": "date",
    "china_gdp": "date",
    "india_unemployment": "date",
    "india_gdp": "date",
    "uk_cpi": "date",
    "canada_cpi": "date",
    "canada_quarterly": "date",
    "australia_cpi": "date",
    "australia_quarterly": "date",
    "turkey_cpi": "date",
    "switzerland_cpi": "date",
    "switzerland_unemployment": "date",
    "switzerland_gdp": "date",
    "switzerland_quarterly": "date",
    "japan_cpi": "date",
    "korea_cpi": "date",
    "korea_quarterly": "date",
    "us_quarterly": "date",
    "us_annual_bea": "date",
    "japan_quarterly": "date",
    "russia_rates": "date",
    "russia_credit": "date",
    "policy_rates": "date",
    "bloomberg": "date",
}


def _register_standard_functions():
    """
    Создаёт привычные save_* / load_* функции
    для стандартных таблиц проекта.
    """

    for table, date_col in STANDARD_TABLES.items():

        def make_save(table_name):
            def save(df: pd.DataFrame):
                _save_df(df, table_name)
            save.__name__ = f"save_{table_name}"
            return save

        def make_load(table_name, date_column):
            def load() -> pd.DataFrame:
                df = _load_df(
                    table_name,
                    parse_dates=[date_column] if date_column else None,
                )

                if table_name == "rss" and not df.empty:
                    df = df.sort_values(
                        "published",
                        ascending=False,
                    )

                return df

            load.__name__ = f"load_{table_name}"
            return load

        globals()[f"save_{table}"] = make_save(table)
        globals()[f"load_{table}"] = make_load(
            table, date_col
        )


_register_standard_functions()


# ============================================================
# Китай — Core CPI
# ============================================================

def _last_notna(series):
    series = series.dropna()
    return series.iloc[-1] if not series.empty else None


def _save_merged_rows(
    df: pd.DataFrame,
    table: str,
    columns: list[str],
):
    if df is None or df.empty:
        print(f"[SKIP] {table}: пустой DataFrame")
        return

    new = df.copy()
    new["date"] = pd.to_datetime(new["date"])

    with _connect() as con:
        try:
            old = pd.read_sql(
                f"SELECT * FROM {table}",
                con,
                parse_dates=["date"],
            )
        except Exception:
            old = pd.DataFrame()

        if not old.empty:
            combined = pd.concat(
                [old, new],
                ignore_index=True,
            )

            aggregations = {
                "country": "first",
            }

            for column in columns:
                aggregations[column] = _last_notna

            combined = (
                combined.groupby(
                    "date",
                    as_index=False,
                ).agg(aggregations)
            )
        else:
            combined = new

        combined = (
            combined.sort_values("date")
            .reset_index(drop=True)
        )

        combined.to_sql(
            table,
            con,
            if_exists="replace",
            index=False,
        )

    print(
        f"[SAVE] {table}: {len(combined)} строк "
        f"(обновлено {len(df)})"
    )


def save_china_core_cpi(df: pd.DataFrame):
    _save_merged_rows(
        df,
        "china_core_cpi",
        ["inflation_core"],
    )


def load_china_core_cpi() -> pd.DataFrame:
    return _load_df(
        "china_core_cpi",
        parse_dates=["date"],
    )


# ============================================================
# Китай — квартальные бюджет и текущий счёт
# ============================================================

def save_china_fiscal(df: pd.DataFrame):
    _save_merged_rows(
        df,
        "china_fiscal",
        ["budget_gdp", "trade_gdp"],
    )


def load_china_fiscal() -> pd.DataFrame:
    return _load_df(
        "china_fiscal",
        parse_dates=["date"],
    )


# ============================================================
# Индия — CPI
# ============================================================

def save_india_cpi(df: pd.DataFrame):
    _save_merged_rows(
        df,
        "india_cpi",
        ["value", "mom", "core"],
    )


def load_india_cpi() -> pd.DataFrame:
    return _load_df(
        "india_cpi",
        parse_dates=["date"],
    )


# ============================================================
# Россия — CPI
# ============================================================

def save_russia_cpi(df: pd.DataFrame):
    if df is None or df.empty:
        print("[SKIP] russia_cpi: пустой DataFrame")
        return

    new = df.copy()
    new["date"] = pd.to_datetime(new["date"])

    if (
        new["date"].isna().any()
        or new["date"].duplicated().any()
    ):
        raise ValueError(
            "russia_cpi: некорректные или "
            "повторяющиеся даты"
        )

    if not new["country"].eq("RU").all():
        raise ValueError(
            "russia_cpi: обнаружена страна, "
            "отличная от RU"
        )

    old = _load_df(
        "russia_cpi",
        parse_dates=["date"],
    )

    if not old.empty:
        # Месячные данные нормализуются на конец месяца.
        # Это исключает дубли при переходе со старого
        # источника на бюллетень ЦБ.
        old["date"] = (
            pd.to_datetime(old["date"])
            + pd.offsets.MonthEnd(0)
        )

        old = old.drop_duplicates(
            subset=["date"],
            keep="last",
        )

        old = old.set_index("date")
        new = new.set_index("date")

        combined = (
            new.combine_first(old)
            .reset_index()
        )
    else:
        combined = new

    combined = (
        combined.sort_values("date")
        .reset_index(drop=True)
    )

    _save_df(combined, "russia_cpi")


def load_russia_cpi() -> pd.DataFrame:
    return _load_df(
        "russia_cpi",
        parse_dates=["date"],
    )


# ============================================================
# Россия — квартальные финансовые показатели
# ============================================================

def save_russia_quarterly(df: pd.DataFrame):
    if df is None or df.empty:
        print("[SKIP] russia_quarterly: пусто")
        return

    required = {
        "date",
        "country",
        "debt_gdp",
        "budget_gdp",
        "trade_gdp",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"russia_quarterly: нет колонок {missing}"
        )

    new = df.copy()

    new["date"] = pd.to_datetime(new["date"])

    if (
        new["date"].isna().any()
        or new["date"].duplicated().any()
    ):
        raise ValueError(
            "russia_quarterly: даты некорректны "
            "или повторяются"
        )

    if not new["country"].eq("RU").all():
        raise ValueError(
            "russia_quarterly: неверная страна"
        )

    old = _load_df(
        "russia_quarterly",
        parse_dates=["date"],
    )

    if not old.empty:
        combined = (
            new.set_index("date")
            .combine_first(
                old.set_index("date")
            )
            .reset_index()
        )
    else:
        combined = new

    combined = combined.sort_values("date")

    _save_df(
        combined,
        "russia_quarterly",
    )


def load_russia_quarterly() -> pd.DataFrame:
    return _load_df(
        "russia_quarterly",
        parse_dates=["date"],
    )
