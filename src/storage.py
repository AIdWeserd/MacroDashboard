import sqlite3
import re
from datetime import date, datetime

import pandas as pd
from config import DB_PATH


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback on context exit and always release the SQLite file."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


# Каждая запись определяется бизнес-ключом, а не своим положением в файле.
# Для остальных страновых таблиц — (country, date); исключения перечислены явно.
SPECIAL_KEYS = {
    "fred": ("country", "indicator", "date"),
    "imf": ("country", "year", "metric"),
    "bloomberg": ("country", "metric", "date"),
    "forexfactory": ("datetime", "currency", "event"),
    "rss": ("link",),
    "russia_cbr_reference": ("country", "metric", "date"),
}
DATE_COLUMNS = {"date", "datetime", "published"}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


def _identifier(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Некорректное имя таблицы/колонки: {name!r}")
    return f'"{name}"'


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        timeout=20,
        factory=_ClosingConnection,
    )
    connection.execute("PRAGMA busy_timeout = 20000")
    return connection


def _keys_for(table: str) -> tuple[str, ...]:
    if table in SPECIAL_KEYS:
        return SPECIAL_KEYS[table]
    if table in STANDARD_TABLES or table in {
        "china_core_cpi", "china_fiscal", "india_cpi", "russia_cpi", "russia_quarterly"
    }:
        return ("country", "date")
    raise ValueError(f"Для таблицы {table!r} не определён ключ: запись запрещена")


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in DATE_COLUMNS.intersection(out.columns):
        # Сохраняем время (например, календарь ForexFactory),
        # а не приводим всё к одной календарной дате.
        parsed = pd.to_datetime(out[col], errors="coerce", utc=True, format="mixed")
        if parsed.isna().any():
            raise ValueError(f"Некорректная дата в колонке {col}")
        out[col] = parsed.dt.strftime("%Y-%m-%d %H:%M:%S")
    return out


def _validate_frame(df: pd.DataFrame, table: str, keys: tuple[str, ...]) -> None:
    missing = set(keys) - set(df.columns)
    if missing:
        raise ValueError(f"{table}: нет колонок ключа {sorted(missing)}")
    if df[list(keys)].isna().any().any():
        raise ValueError(f"{table}: пустые значения ключа {keys}")
    for col in keys:
        if df[col].dtype == "object" and df[col].astype(str).str.strip().eq("").any():
            raise ValueError(f"{table}: пустые строки ключа {col}")
    duplicates = df.duplicated(subset=list(keys), keep=False)
    if duplicates.any():
        example = df.loc[duplicates, list(keys)].head(3).to_dict("records")
        raise ValueError(f"{table}: повторяющиеся бизнес-ключи: {example}")
    if "country" in df.columns and table.startswith("russia_"):
        if not df["country"].eq("RU").all():
            raise ValueError(f"{table}: встречена страна, отличная от RU")


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _column_type(series: pd.Series) -> str:
    from pandas.api.types import is_integer_dtype, is_float_dtype, is_bool_dtype
    if is_bool_dtype(series) or is_integer_dtype(series):
        return "INTEGER"
    if is_float_dtype(series):
        return "REAL"
    if not series.notna().any():
        return "NUMERIC"  # NULL-only column: keep type flexible for later numeric values
    return "TEXT"


def _sqlite_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _validate_policy_rate_months(df: pd.DataFrame) -> None:
    """Не допускаем будущих месяцев в истории ставок.

    Текущий месяц допустим, даже если дата нормализована на последнее
    календарное число месяца. Граница вычисляется при каждой записи.
    """
    if df.empty:
        return
    required = {"country", "date", "rate"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"policy_rates: отсутствуют колонки {sorted(missing)}")
    dates = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    if dates.isna().any():
        raise ValueError("policy_rates: некорректные даты")
    future = dates.dt.to_period("M") > pd.Timestamp.now().to_period("M")
    if future.any():
        examples = df.loc[future, ["country", "date"]].head(3).to_dict("records")
        raise ValueError(f"policy_rates: будущий месяц: {examples}")


def _save_df(df: pd.DataFrame, table: str):
    """Безопасное объединение, затем атомарная запись с rollback при ошибке.

    Неполный ответ источника никогда не удаляет старые даты/страны/метрики.
    Неопубликованные (NULL) значения не затирают уже сохранённые значения.
    """
    if df is None or df.empty:
        print(f"[SKIP] {table}: пустой DataFrame")
        return

    _identifier(table)
    keys = _keys_for(table)
    incoming = _normalize_dates(df)
    _validate_frame(incoming, table, keys)
    if table == "policy_rates":
        _validate_policy_rate_months(incoming)

    with _connect() as con:
        # BEGIN IMMEDIATE не позволяет конкурентному writer изменить таблицу
        # между чтением старых данных и завершением нашего обновления.
        con.execute("BEGIN IMMEDIATE")
        exists = _table_exists(con, table)
        if exists:
            old = pd.read_sql_query(
                f"SELECT * FROM {_identifier(table)}", con
            )
            old = _normalize_dates(old) if not old.empty else old
            if not old.empty:
                _validate_frame(old, table, keys)
            else:
                # Даже у пустой существующей таблицы должна быть корректная схема.
                absent = set(keys) - set(old.columns)
                if absent:
                    raise ValueError(f"{table}: неверная схема, нет {sorted(absent)}")
        else:
            old = pd.DataFrame(columns=incoming.columns)

        if old.empty:
            combined = incoming.copy()
        else:
            # Новая ненулевая информация приоритетна, прежние значения остаются.
            # Имеет значение полный состав ключа: дата + страна + метрика.
            combined = (
                incoming.set_index(list(keys))
                .combine_first(old.set_index(list(keys)))
                .reset_index()
            )
        combined = combined.reset_index(drop=True)
        _validate_frame(combined, table, keys)
        if table == "policy_rates":
            _validate_policy_rate_months(combined)

        # Защита от потери ключей даже при неожиданном изменении pandas.
        if not old.empty:
            old_keys = set(map(tuple, old[list(keys)].itertuples(index=False, name=None)))
            current_keys = set(map(tuple, combined[list(keys)].itertuples(index=False, name=None)))
            if not old_keys.issubset(current_keys):
                raise AssertionError(f"{table}: обновление теряет старые записи")

        if not exists:
            definitions = ", ".join(
                f"{_identifier(col)} {_column_type(combined[col])}"
                for col in combined.columns
            )
            con.execute(f"CREATE TABLE {_identifier(table)} ({definitions})")
        else:
            schema = {
                row[1] for row in con.execute(f"PRAGMA table_info({_identifier(table)})")
            }
            for col in combined.columns:
                if col not in schema:
                    con.execute(
                        f"ALTER TABLE {_identifier(table)} ADD COLUMN "
                        f"{_identifier(col)} {_column_type(combined[col])}"
                    )

        columns = list(combined.columns)
        names = ", ".join(_identifier(col) for col in columns)
        params = ", ".join("?" for _ in columns)
        values = [
            tuple(_sqlite_value(v) for v in row)
            for row in combined[columns].itertuples(index=False, name=None)
        ]

        # DELETE + INSERT составляют ОДНУ транзакцию: при ошибке весь
        # предыдущий снимок таблицы восстанавливается автоматически.
        con.execute(f"DELETE FROM {_identifier(table)}")
        con.executemany(
            f"INSERT INTO {_identifier(table)} ({names}) VALUES ({params})", values
        )
        saved = con.execute(
            f"SELECT COUNT(*) FROM {_identifier(table)}"
        ).fetchone()[0]
        if saved != len(combined):
            raise RuntimeError(f"{table}: записано {saved} из {len(combined)} строк")
        # COMMIT вызывается __exit__ соединения только при отсутствии ошибок.

    print(f"[SAVE] {table}: {len(combined)} строк (в новой загрузке {len(incoming)})")


def _load_df(table: str, parse_dates: list[str] | None = None) -> pd.DataFrame:
    _identifier(table)
    with _connect() as con:
        if not _table_exists(con, table):
            return pd.DataFrame()
        # Повреждение базы, неправильная схема и прочие ошибки не маскируются.
        return pd.read_sql_query(
            f"SELECT * FROM {_identifier(table)}",
            con,
            parse_dates=parse_dates,
        )


def clear_table(name: str):
    _identifier(name)
    with _connect() as con:
        con.execute(f"DROP TABLE IF EXISTS {_identifier(name)}")


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
            "russia_cpi", "russia_quarterly", "russia_rates", "russia_credit", "russia_mortgage", "russia_money",
            "russia_trade", "russia_trade_estimates", "russia_investors",
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
    "russia_mortgage": "date",
    "russia_money": "date",
    "russia_trade": "date",
    "russia_trade_estimates": "date",
    "russia_investors": "date",
    "russia_cbr_reference": "date",
    "russia_ruonia": "date",
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


def _save_merged_rows(df: pd.DataFrame, table: str, columns: list[str]):
    """Обратная совместимость: стандартный атомарный merge по (country, date)."""
    if df is None or df.empty:
        print(f"[SKIP] {table}: пустой DataFrame")
        return
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"{table}: отсутствуют колонки {sorted(missing)}")
    _save_df(df, table)


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


# Shared official-series facade. The physical table remains
# official_eurostat_extra for backward compatibility; no migration.
def load_official_extra() -> pd.DataFrame:
    """Read all published supplemental observations, including national PPI."""
    from src.eurostat_extra import load_eurostat_extra
    return load_eurostat_extra()


def save_official_extra(data: pd.DataFrame) -> None:
    """Upsert extra official observations by (country, date, metric)."""
    from src.eurostat_extra import save_eurostat_extra
    save_eurostat_extra(data)
