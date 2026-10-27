import re
import pandas as pd

from src.storage import (
    load_imf, load_eurostat, load_eurostat_unemployment,
    load_eurostat_quarterly, load_eurostat_annual,
    load_fred_unemployment, load_fred_gdp,
    load_singapore_unemployment, load_singapore_gdp,
    load_singapore_quarterly,
    load_brazil_unemployment, load_brazil_gdp,
    load_brazil_quarterly, load_uk_quarterly,
    load_japan_quarterly, load_korea_quarterly,
    load_australia_quarterly, load_switzerland_quarterly,
    load_canada_quarterly, load_policy_rates,
    load_china_unemployment, load_china_debt,
    load_china_fiscal, load_china_gdp,
    load_india_unemployment, load_india_gdp,
    load_fred_cpi, load_china_cpi, load_brazil_cpi,
    load_india_cpi, load_uk_cpi, load_canada_cpi,
    load_australia_cpi, load_turkey_cpi,
    load_switzerland_cpi, load_switzerland_unemployment,
    load_japan_cpi, load_korea_cpi,
    load_singapore_cpi, load_switzerland_gdp,
    load_us_quarterly, load_us_annual_bea,
    load_bloomberg, load_china_core_cpi,
    load_china_debt_fred, load_russia_cpi,
    load_russia_quarterly,
)

COUNTRY_ORDER = [
    "US", "CN", "EU", "DE", "JP", "IN", "GB", "FR", "IT",
    "BR", "CA", "KR", "AU", "ES", "TR", "CH", "SG", "RU",
]

COUNTRY_NAMES = {
    "US": "США",
    "CN": "Китай",
    "EU": "Еврозона",
    "JP": "Япония",
    "DE": "Германия",
    "GB": "Великобритания",
    "FR": "Франция",
    "IT": "Италия",
    "ES": "Испания",
    "CA": "Канада",
    "AU": "Австралия",
    "KR": "Южная Корея",
    "SG": "Сингапур",
    "BR": "Бразилия",
    "IN": "Индия",
    "TR": "Турция",
    "CH": "Швейцария",
    "RU": "Россия",
}

REGION_MAP = {
    "US": "Америка",
    "CA": "Америка",
    "BR": "Америка",
    "CN": "Азия и Океания",
    "JP": "Азия и Океания",
    "KR": "Азия и Океания",
    "SG": "Азия и Океания",
    "IN": "Азия и Океания",
    "AU": "Азия и Океания",
    "EU": "Европа",
    "DE": "Европа",
    "GB": "Европа",
    "FR": "Европа",
    "IT": "Европа",
    "ES": "Европа",
    "TR": "Европа",
    "CH": "Европа",
    "RU": "Европа",
}

REGION_ORDER = [
    "Америка",
    "Европа",
    "Азия и Океания",
]

MONTH_NAMES = {
    1: "янв",
    2: "фев",
    3: "мар",
    4: "апр",
    5: "май",
    6: "июн",
    7: "июл",
    8: "авг",
    9: "сен",
    10: "окт",
    11: "ноя",
    12: "дек",
}

EUROSTAT_QUARTERLY_COUNTRIES = {
    "EU", "DE", "FR", "IT", "ES"
}

FRED_GDP_COUNTRIES = {
    "US", "JP", "GB", "CA", "AU", "KR", "TR"
}

EUROZONE_COUNTRIES = {
    "DE", "FR", "IT", "ES"
}

BBG_METRICS = (
    "debt_gdp",
    "budget_gdp",
    "trade_gdp",
    "gdp_growth",
)


def _run_time() -> pd.Timestamp:
    """Wall clock at invocation, isolated for deterministic offline tests."""
    return pd.Timestamp.now()


def _month_end(year: int, month: int) -> pd.Timestamp:
    return (
            pd.Timestamp(year=year, month=month, day=1)
            + pd.offsets.MonthEnd(0)
    )


def _last_inflation_row(
        df: pd.DataFrame,
        country: str,
        cutoff: pd.Timestamp,
):
    if df.empty:
        return None

    sub = df[
        (df["country"] == country)
        & (df["date"] <= cutoff)
        ].sort_values("date")

    if sub.empty:
        return None

    return sub.iloc[-1]


def _last_quarterly_value(
        df: pd.DataFrame,
        country: str,
        column: str,
        cutoff: pd.Timestamp,
):
    """Возвращает последнее значение ТОЛЬКО за завершённый квартал.

    Источники могут датировать квартал его первым днём (01.01)
    либо последним (31.03). День месяца сам по себе не указывает
    на завершение квартала: 31 января — ещё не конец Q1.
    """
    if df.empty or not {"country", "date", column}.issubset(df.columns):
        return None, None

    sub = df.loc[
        (df["country"] == country) & df[column].notna()
    ].copy()
    if sub.empty:
        return None, None

    sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
    sub = sub.dropna(subset=["date"])
    if sub.empty:
        return None, None

    # Применяется к датам начала и конца квартала одинаково.
    sub["quarter_end"] = sub["date"].dt.to_period("Q").dt.end_time.dt.normalize()
    sub = sub.loc[sub["quarter_end"] <= cutoff]
    if sub.empty:
        return None, None

    last = sub.sort_values(["quarter_end", "date"]).iloc[-1]
    return last[column], last["date"]


def _bbg_value(df, country, metric, cutoff):
    """Выбирает последний ДОПУСТИМЫЙ отчётный период Bloomberg."""
    if df.empty or not {"country", "metric", "date", "value"}.issubset(df.columns):
        return None, None, None, None

    sub = df.loc[
        (df["country"] == country)
        & (df["metric"] == metric)
        & df["value"].notna()
    ].copy()
    if sub.empty:
        return None, None, None, None

    sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
    sub = sub.dropna(subset=["date"])
    sub = sub.loc[sub["date"] <= cutoff].copy()
    if sub.empty:
        return None, None, None, None

    if "period" not in sub.columns:
        sub["period"] = ""

    # Проверяем период каждой строки ДО выбора последнего значения,
    # иначе запись о будущем квартале скрывает допустимый прежний.
    sub["period_end"] = sub["period"].apply(_bbg_period_end)
    # Bloomberg Excel is a quarterly source: export date alone does not
    # prove which economic quarter LAST_UPDATE belongs to.
    sub = sub.dropna(subset=["period_end"])
    min_period = (pd.Period(cutoff, freq="Q") - 2).end_time.normalize()
    sub = sub.loc[
        (sub["period_end"] <= cutoff) & (sub["period_end"] >= min_period)
    ]
    sub["effective_end"] = sub["period_end"]
    if sub.empty:
        return None, None, None, None

    last = sub.sort_values(["effective_end", "date"]).iloc[-1]
    return (
        float(last["value"]),
        last["date"],
        str(last.get("period", "") or ""),
        str(last.get("source", "BBG") or "BBG"),
    )


def _bbg_period_end(period):
    match = re.match(
        r"Q(\d)\s+(\d{4})",
        str(period).strip(),
    )

    if not match:
        return None

    q = int(match.group(1))
    year = int(match.group(2))

    if q not in (1, 2, 3, 4):
        return None

    return (
            pd.Timestamp(year, q * 3, 1)
            + pd.offsets.MonthEnd(0)
    )


def _date_label(ts):
    return f"{MONTH_NAMES[ts.month]} {ts.year}"


def _quarter_label(ts):
    quarter = (ts.month - 1) // 3 + 1
    return f"Q{quarter} {ts.year}"


def _metric_quarter_label(country, metric, ts):
    """Fiscal quarter labels only for confirmed April–March source series.

    The Indian MoSPI GDP source calls Apr–Jun Q1, Jul–Sep Q2,
    Oct–Dec Q3 and Jan–Mar Q4. Other countries' calendar-quarter data
    retain their calendar labels (including IMF Japan annual data).
    """
    if country == "IN" and metric == "gdp_growth":
        end = pd.Period(pd.Timestamp(ts), freq="Q").end_time.normalize()
        fy = end.year if end.month >= 4 else end.year - 1
        fy_quarter = ((end.month - 4) % 12) // 3 + 1
        return f"FY {fy}/{(fy + 1) % 100:02d} Q{fy_quarter}"
    return _quarter_label(ts)


def _quarterly_to_row(
        row,
        df,
        country,
        cutoff,
        metrics,
        labels=None,
):
    if labels is None:
        labels = {}

    for metric in metrics:
        # A future month selected in the UI must not expose a quarter
        # that has not elapsed as of the actual scheduler/dashboard run.
        eligible_cutoff = min(pd.Timestamp(cutoff), _run_time().normalize())
        value, date = _last_quarterly_value(
            df, country, metric, eligible_cutoff
        )

        if value is None:
            continue

        row[metric] = round(float(value), 2)

        label = labels.get(metric)
        period_label = _metric_quarter_label(country, metric, date)

        if label:
            row[f"{metric}_date"] = f"{period_label} ({label})"
        else:
            row[f"{metric}_date"] = period_label


def _imf_reference_year(country: str, year: int, month: int) -> int:
    """WEO India references its April–March fiscal year by START year.

    Most other WEO series in the dashboard are calendar-year series. Never
    shift Japan/UK national-accounts data merely because government fiscal
    budgets for those countries have different reporting calendars.
    """
    if country == "IN" and month <= 3:
        return year - 1
    return year


def _is_annual_close(country: str, year: int, month: int) -> bool:
    """Annual WEO preference: calendar December; India FY closes in March."""
    return month == (3 if country == "IN" else 12)


def _annual_period_closed(country: str, reference_year: int, today) -> bool:
    """Period complete (not necessarily the publication's latest actual)."""
    if country == "IN":
        ending = pd.Timestamp(reference_year + 1, 3, 31)
    else:
        ending = pd.Timestamp(reference_year, 12, 31)
    return pd.Timestamp(today).normalize() > ending


def _imf_metric(imf, country, year, metric):
    if imf.empty:
        return None

    sub = imf[
        (imf["country"] == country)
        & (imf["year"] == year)
        & (imf["metric"] == metric)
        ]

    if sub.empty:
        return None

    value = sub.iloc[0]["value"]

    return (
        float(value)
        if pd.notna(value)
        else None
    )


def _imf_fallback_label(year, detail=None, country=None):
    """IMF WEO: исторический годовой ряд или текущий/будущий прогноз.

    Прошедшие годы называем годовыми данными из официальной публикации
    IMF, не утверждая, что каждое наблюдение обязательно окончательное:
    некоторые исторические годы в WEO могут быть оценками IMF.
    Проверка статуса actual/estimate потребовала бы metadata latest actual.
    """
    descriptor = f", {detail}" if detail else ""
    period_label = f"FY {year}/{str((year + 1) % 100).zfill(2)}" if country == "IN" else str(year)
    # For India FY2026/27 remains incomplete through March 2027.
    completed = _annual_period_closed(country or "", year, _run_time())
    if completed:
        return f"{period_label} (IMF WEO{descriptor}, годовые данные)"
    return f"{period_label} (IMF WEO{descriptor}, прогноз; годовое)"


def _annual_from_imf(
        row,
        imf,
        country,
        year,
        label="IMF, Gen Gov",
):
    for metric, imf_key in (
            ("debt_gdp", "DEBT_GDP"),
            ("budget_gdp", "BUDGET_GDP"),
            ("trade_gdp", "TRADE_GDP"),
    ):
        value = _imf_metric(
            imf, country, year, imf_key
        )

        if value is not None:
            row[metric] = round(value, 2)
            # IMF здесь годовой резерв, а не опубликованный квартал.
            row[f"{metric}_date"] = _imf_fallback_label(
                year, label.replace("IMF, ", "")
            )


def _set_inflation(row, source, cutoff, country, max_age_days=None):
    """Заполняет отдельные CPI-метрики последними ненулевыми наблюдениями.

    Уже заполненные более приоритетным источником значения не затираются.
    Период фиксируется для КАЖДОГО показателя отдельно.
    """
    if source.empty or not {"country", "date"}.issubset(source.columns):
        return row.get("inflation") is not None

    sub = source.loc[source["country"] == country].copy()
    if sub.empty:
        return row.get("inflation") is not None
    sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
    sub = sub.dropna(subset=["date"])
    sub = sub.loc[sub["date"] <= cutoff].sort_values("date")
    if max_age_days is not None:
        sub = sub.loc[sub["date"] >= cutoff - pd.Timedelta(days=max_age_days)]
    if sub.empty:
        return row.get("inflation") is not None

    for source_col, target_col in (
        ("value", "inflation"),
        ("mom", "inflation_mom"),
        ("core", "inflation_core"),
        ("core_mom", "inflation_core_mom"),
    ):
        if row.get(target_col) is not None or source_col not in sub.columns:
            continue
        valid = sub.loc[sub[source_col].notna()]
        if valid.empty:
            continue
        last = valid.iloc[-1]
        row[target_col] = round(float(last[source_col]), 2)
        row[f"{target_col}_date"] = _date_label(last["date"])

    return row.get("inflation") is not None


def _set_unemployment(
        row,
        frame,
        country,
        cutoff,
        quarterly=False,
):
    if frame.empty:
        return False

    if "country" in frame.columns:
        frame = frame[
            frame["country"] == country
            ]

    frame = frame[
        frame["date"] <= cutoff
        ].sort_values("date")

    if frame.empty:
        return False

    last = frame.iloc[-1]

    if pd.isna(last.get("value")):
        return False

    row["unemployment"] = round(
        float(last["value"]), 2
    )

    if quarterly:
        row["unemployment_date"] = (
            _quarter_label(last["date"])
        )
    else:
        row["unemployment_date"] = (
            _date_label(last["date"])
        )

    return True


def build_summary(
        year: int | None = None,
        month: int | None = None,
) -> pd.DataFrame:
    imf = load_imf()
    eurostat = load_eurostat()
    eurostat_q = load_eurostat_quarterly()
    eurostat_a = load_eurostat_annual()
    fred_gdp = load_fred_gdp()
    china_debt = load_china_debt()
    china_debt_fred = load_china_debt_fred()
    china_fiscal = load_china_fiscal()
    china_gdp = load_china_gdp()
    us_quarterly = load_us_quarterly()
    us_annual_bea = load_us_annual_bea()
    singapore_quarterly = load_singapore_quarterly()
    brazil_quarterly = load_brazil_quarterly()
    uk_quarterly = load_uk_quarterly()
    japan_quarterly = load_japan_quarterly()
    korea_quarterly = load_korea_quarterly()
    australia_quarterly = load_australia_quarterly()
    switzerland_quarterly = load_switzerland_quarterly()
    canada_quarterly = load_canada_quarterly()
    policy_rates = load_policy_rates()
    unemp_eu = load_eurostat_unemployment()
    unemp_fred = load_fred_unemployment()
    unemp_sg = load_singapore_unemployment()
    sg_gdp = load_singapore_gdp()
    unemp_br = load_brazil_unemployment()
    br_gdp = load_brazil_gdp()
    unemp_cn = load_china_unemployment()
    india_gdp = load_india_gdp()
    unemp_in = load_india_unemployment()
    cpi_fred = load_fred_cpi()
    cpi_cn = load_china_cpi()
    cpi_cn_core = load_china_core_cpi()
    cpi_br = load_brazil_cpi()
    cpi_in = load_india_cpi()
    cpi_uk = load_uk_cpi()
    cpi_ca = load_canada_cpi()
    cpi_au = load_australia_cpi()
    cpi_tr = load_turkey_cpi()
    cpi_ch = load_switzerland_cpi()
    unemp_ch = load_switzerland_unemployment()
    cpi_jp = load_japan_cpi()
    cpi_kr = load_korea_cpi()
    cpi_sg = load_singapore_cpi()
    cpi_ru = load_russia_cpi()
    ru_quarterly = load_russia_quarterly()
    switzerland_gdp = load_switzerland_gdp()
    bbg = load_bloomberg()

    now = _run_time()

    if year is None:
        year = now.year

    if month is None:
        month = now.month

    cutoff = _month_end(year, month)
    is_finished_year = year < now.year

    rows = []

    for country in COUNTRY_ORDER:
        row = {
            "country": country,
            "country_name": COUNTRY_NAMES.get(
                country, country
            ),
            "region": REGION_MAP.get(
                country, "Прочее"
            ),
        }

        # ====================================================
        # IMF WEO: годовой РЕЗЕРВ для любого выбранного месяца.
        # Официальный квартальный / годовой источник заменяет этот
        # резерв ниже; подходящий Bloomberg тоже может заменить IMF.
        # Оставляем значение, если более точных данных нет — таковы
        # правила заполнения сводной таблицы Макродашборда.
        # Подпись явно указывает годовую частоту и прогнозный статус.
        # ====================================================
        imf_year = _imf_reference_year(country, year, month)
        for imf_key, metric in (
            ("DEBT_GDP", "debt_gdp"),
            ("BUDGET_GDP", "budget_gdp"),
            ("TRADE_GDP", "trade_gdp"),
            ("GDP_GROWTH", "gdp_growth"),
            ("INFLATION", "inflation_imf"),
        ):
            value = _imf_metric(imf, country, imf_year, imf_key)
            row[metric] = round(value, 2) if value is not None else None

        has_imf = any(
            row.get(metric) is not None
            for metric in (
                "debt_gdp", "budget_gdp", "trade_gdp",
                "gdp_growth", "inflation_imf",
            )
        )
        imf_date = _imf_fallback_label(imf_year, country=country) if has_imf else None
        row["imf_date"] = imf_date

        for metric in (
            "debt_gdp", "budget_gdp", "trade_gdp", "gdp_growth"
        ):
            row[f"{metric}_date"] = (
                imf_date if row.get(metric) is not None else None
            )

        for metric in ("debt_gdp", "budget_gdp"):
            if row.get(metric) is not None:
                row[f"{metric}_date"] = _imf_fallback_label(
                    imf_year, "Gen Gov", country=country
                )

        # ====================================================
        # США
        # ====================================================

        if country == "US":
            _quarterly_to_row(
                row,
                us_quarterly,
                "US",
                cutoff,
                ("debt_gdp", "budget_gdp", "trade_gdp"),
                {
                    "debt_gdp": "Fed Gov",
                    "budget_gdp": "Fed Gov",
                },
            )

            if month == 12 and is_finished_year and not us_annual_bea.empty:
                annual = us_annual_bea[
                    us_annual_bea["date"].dt.year == year
                    ]

                if not annual.empty:
                    last = annual.iloc[-1]

                    for metric, label in (
                            ("budget_gdp", "BEA, Gen Gov"),
                            (
                                    "trade_gdp",
                                    "BEA, Current Account",
                            ),
                            ("debt_gdp", "IMF, Gen Gov"),
                    ):
                        value = last.get(metric)

                        if pd.notna(value):
                            row[metric] = round(
                                float(value), 2
                            )

                            row[f"{metric}_date"] = (
                                _imf_fallback_label(year, "Gen Gov")
                                if metric == "debt_gdp"
                                else (f"{year} ({label})" if label else str(year))
                            )

        # ====================================================
        # Eurostat
        # ====================================================

        if country in EUROSTAT_QUARTERLY_COUNTRIES:
            _quarterly_to_row(
                row,
                eurostat_q,
                country,
                cutoff,
                (
                    "debt_gdp",
                    "budget_gdp",
                    "trade_gdp",
                    "gdp_growth",
                ),
            )

            if month == 12 and is_finished_year and not eurostat_a.empty:
                annual = eurostat_a[
                    (eurostat_a["country"] == country)
                    & (
                            eurostat_a["date"].dt.year
                            == year
                    )
                    ]

                if not annual.empty:
                    last = annual.iloc[-1]

                    for metric, label in (
                            ("debt_gdp", "Eurostat, Gen Gov"),
                            ("budget_gdp", "Eurostat, Gen Gov"),
                            (
                                    "trade_gdp",
                                    "Eurostat, Current Account",
                            ),
                    ):
                        value = last.get(metric)

                        if pd.notna(value):
                            row[metric] = round(
                                float(value), 2
                            )
                            row[f"{metric}_date"] = (
                                f"{year} ({label})" if label else str(year)
                            )

        # ====================================================
        # Квартальный рост ВВП из FRED
        # ====================================================

        if country in FRED_GDP_COUNTRIES:
            _quarterly_to_row(
                row,
                fred_gdp,
                country,
                cutoff,
                ("gdp_growth",),
            )

        # ====================================================
        # Великобритания
        # ====================================================

        if country == "GB":
            _quarterly_to_row(
                row,
                uk_quarterly,
                "GB",
                cutoff,
                (
                    "debt_gdp",
                    "budget_gdp",
                    "trade_gdp",
                ),
                {
                    "debt_gdp": "ONS, Gen Gov",
                    "budget_gdp": "ONS, Gen Gov",
                    "trade_gdp": "ONS, Current Account",
                },
            )

            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "GB", year
                )

        # ====================================================
        # Япония
        # ====================================================

        if country == "JP":
            _quarterly_to_row(
                row,
                japan_quarterly,
                "JP",
                cutoff,
                ("debt_gdp",),
                {"debt_gdp": "Central Gov"},
            )

            if month == 12 and is_finished_year:
                value = _imf_metric(
                    imf, "JP", year, "DEBT_GDP"
                )

                if value is not None:
                    row["debt_gdp"] = round(
                        value, 2
                    )
                    row["debt_gdp_date"] = _imf_fallback_label(
                        year, "Gen Gov"
                    )

        # ====================================================
        # Южная Корея
        # ====================================================

        if country == "KR":
            _quarterly_to_row(
                row,
                korea_quarterly,
                "KR",
                cutoff,
                ("debt_gdp",),
                {"debt_gdp": "Central Gov"},
            )

        # ====================================================
        # Австралия
        # ====================================================

        if country == "AU":
            _quarterly_to_row(
                row,
                australia_quarterly,
                "AU",
                cutoff,
                ("trade_gdp",),
                {
                    "trade_gdp": (
                        "ABS, Current Account"
                    ),
                },
            )

            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "AU", year
                )

        # ====================================================
        # Швейцария
        # ====================================================

        if country == "CH":
            _quarterly_to_row(
                row,
                switzerland_quarterly,
                "CH",
                cutoff,
                ("trade_gdp",),
                {
                    "trade_gdp": (
                        "SNB, Current Account"
                    ),
                },
            )

            _quarterly_to_row(
                row,
                switzerland_gdp,
                "CH",
                cutoff,
                ("gdp_growth",),
            )

            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "CH", year
                )

        # ====================================================
        # Канада
        # ====================================================

        if country == "CA":
            _quarterly_to_row(
                row,
                canada_quarterly,
                "CA",
                cutoff,
                (
                    "debt_gdp",
                    "budget_gdp",
                    "trade_gdp",
                ),
                {
                    "debt_gdp": "StatCan, Gen Gov",
                    "budget_gdp": (
                        "StatCan, Gen Gov, NSA"
                    ),
                    "trade_gdp": (
                        "StatCan, Current Account"
                    ),
                },
            )

            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "CA", year
                )

        # ====================================================
        # Сингапур
        # ====================================================

        if country == "SG":
            _quarterly_to_row(
                row,
                sg_gdp,
                "SG",
                cutoff,
                ("gdp_growth",),
            )

            _quarterly_to_row(
                row,
                singapore_quarterly,
                "SG",
                cutoff,
                ("debt_gdp", "trade_gdp"),
                {
                    "debt_gdp": "Central Gov",
                    "trade_gdp": "Current Account",
                },
            )

            # Годовой бюджет IMF уже доступен как резерв в любой месяц.
            # В декабре сохраняем существующую годовую методологию.
            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "SG", year
                )

        # ====================================================
        # Бразилия
        # ====================================================

        if country == "BR":
            _quarterly_to_row(
                row,
                br_gdp,
                "BR",
                cutoff,
                ("gdp_growth",),
            )

            _quarterly_to_row(
                row,
                brazil_quarterly,
                "BR",
                cutoff,
                ("debt_gdp", "trade_gdp"),
                {
                    "debt_gdp": "BCB, Gen Gov",
                    "trade_gdp": (
                        "BCB, Current Account"
                    ),
                },
            )

            if month == 12 and is_finished_year:
                _annual_from_imf(
                    row, imf, "BR", year
                )

        # ====================================================
        # Индия
        # ====================================================

        if country == "IN":
            _quarterly_to_row(
                row,
                india_gdp,
                "IN",
                cutoff,
                ("gdp_growth",),
            )

        # ====================================================
        # Китай
        # ====================================================

        if country == "CN":
            _quarterly_to_row(
                row,
                china_debt,
                "CN",
                cutoff,
                ("debt_gdp",),
                {"debt_gdp": "Central Gov"},
            )

            if month == 12 and is_finished_year:
                applied = False

                if not china_debt_fred.empty:
                    annual = china_debt_fred[
                        china_debt_fred["date"].dt.year
                        == year
                        ]

                    if not annual.empty:
                        value = annual.iloc[-1].get(
                            "debt_gdp"
                        )

                        if pd.notna(value):
                            row["debt_gdp"] = round(
                                float(value), 2
                            )
                            row["debt_gdp_date"] = _imf_fallback_label(
                                year, "Gen Gov"
                            )
                            applied = True

                if not applied:
                    value = _imf_metric(
                        imf,
                        "CN",
                        year,
                        "DEBT_GDP",
                    )

                    if value is not None:
                        row["debt_gdp"] = round(
                            value, 2
                        )
                        row["debt_gdp_date"] = _imf_fallback_label(
                            year, "Gen Gov"
                        )

            _quarterly_to_row(
                row,
                china_fiscal,
                "CN",
                cutoff,
                ("budget_gdp", "trade_gdp"),
                {
                    "budget_gdp": "Central Gov",
                    "trade_gdp": (
                        "SAFE, Current Account"
                    ),
                },
            )

            if month == 12 and is_finished_year:
                budget = _imf_metric(
                    imf,
                    "CN",
                    year,
                    "BUDGET_GDP",
                )

                if budget is not None:
                    row["budget_gdp"] = round(
                        budget, 2
                    )
                    row["budget_gdp_date"] = _imf_fallback_label(
                        year, "Gen Gov"
                    )

            _quarterly_to_row(
                row,
                china_gdp,
                "CN",
                cutoff,
                ("gdp_growth",),
            )

        # ====================================================
        # Инфляция
        # ====================================================

        for metric in (
                "inflation",
                "inflation_mom",
                "inflation_core",
                "inflation_core_mom",
        ):
            row[metric] = None
            row[f"{metric}_date"] = None

        source_map = {
            "CN": cpi_cn,
            "BR": cpi_br,
            "IN": cpi_in,
            "GB": cpi_uk,
            "CA": cpi_ca,
            "AU": cpi_au,
            "TR": cpi_tr,
            "CH": cpi_ch,
            "JP": cpi_jp,
            "KR": cpi_kr,
            "SG": cpi_sg,
        }

        # Для стран Еврозоны сохраняем HICP Eurostat как основной ряд.
        # Для остальных стран сначала используем национальную статистику,
        # затем FRED в качестве резервного источника для пустых компонентов.
        if country in EUROSTAT_QUARTERLY_COUNTRIES:
            _set_inflation(row, eurostat, cutoff, country)

        if country in source_map:
            _set_inflation(row, source_map[country], cutoff, country)

        # Если основной источник не содержит отдельного компонента,
        # FRED может заполнить только этот компонент, не затирая остальные.
        _set_inflation(row, cpi_fred, cutoff, country, max_age_days=200)

        if country == "CN" and row["inflation_core"] is None:
            if not cpi_cn_core.empty and {
                "date", "country", "inflation_core"
            }.issubset(cpi_cn_core.columns):
                core = cpi_cn_core.loc[
                    (cpi_cn_core["country"] == "CN")
                    & cpi_cn_core["inflation_core"].notna()
                ].copy()
                core["date"] = pd.to_datetime(core["date"], errors="coerce")
                core = core.loc[core["date"] <= cutoff].sort_values("date")
                if not core.empty:
                    record = core.iloc[-1]
                    row["inflation_core"] = round(float(record["inflation_core"]), 2)
                    row["inflation_core_date"] = _date_label(record["date"])

        # Если месячного CPI нет, годовая инфляция IMF заполняет
        # пробел, но подпись НЕ выдаёт её за месячный CPI YoY.
        if row["inflation"] is None:
            annual_inflation = row.get("inflation_imf")
            if annual_inflation is not None:
                row["inflation"] = annual_inflation
                row["inflation_date"] = _imf_fallback_label(
                    imf_year, "годовая инфляция, не месячный YoY", country=country
                )

        # ====================================================
        # Безработица
        # ====================================================

        row["unemployment"] = None
        row["unemployment_date"] = None

        unemployment_sources = [
            (unemp_eu, False),
            (unemp_fred, False),
        ]

        if country == "SG":
            unemployment_sources.append(
                (unemp_sg, True)
            )

        elif country == "BR":
            unemployment_sources.append(
                (unemp_br, True)
            )

        elif country == "CN":
            unemployment_sources.append(
                (unemp_cn, False)
            )

        elif country == "IN":
            unemployment_sources.append(
                (unemp_in, False)
            )

        elif country == "CH":
            unemployment_sources.append(
                (unemp_ch, False)
            )

        for source, quarterly in unemployment_sources:
            if row["unemployment"] is not None:
                break

            _set_unemployment(
                row,
                source,
                country,
                cutoff,
                quarterly=quarterly,
            )

        # ====================================================
        # Ключевая ставка
        # ====================================================

        row["policy_rate"] = None
        row["policy_rate_date"] = None

        if not policy_rates.empty:
            rate_country = (
                "EU"
                if country in EUROZONE_COUNTRIES
                else country
            )

            rates = policy_rates[
                (policy_rates["country"] == rate_country)
                & (policy_rates["date"] <= cutoff)
                ].sort_values("date")

            if not rates.empty:
                last = rates.iloc[-1]

                row["policy_rate"] = round(
                    float(last["rate"]), 2
                )

                date_label = _date_label(
                    last["date"]
                )

                if country in ("IN", "KR", "TR"):
                    date_label += (
                        " (FRED, OECD)"
                    )

                row["policy_rate_date"] = (
                    date_label
                )

        # ====================================================
        # Россия
        # ====================================================

        if country == "RU":
            # Рост ВВП и безработица ещё не интегрированы.
            # Безработица не входит в доступные прогнозы IMF WEO.
            # ВВП сохраняет IMF как резерв, пока нет данных Росстата.
            row["unemployment"] = None
            row["unemployment_date"] = None

            # Декабрь: IMF annual.
            # Остальные месяцы: последний полный квартал.

            # Два показателя Росстата:
            # последние завершённые кварталы.
            # В декабре не подменяем годовой ВВП Q4.
            if month != 12 or not is_finished_year:
                _quarterly_to_row(
                    row,
                    ru_quarterly,
                    "RU",
                    cutoff,
                    ("gdp_growth", "unemployment"),
                )

            if month != 12 or not is_finished_year:
                _quarterly_to_row(
                    row,
                    ru_quarterly,
                    "RU",
                    cutoff,
                    (
                        "debt_gdp",
                        "budget_gdp",
                        "trade_gdp",
                    ),
                    {
                        "debt_gdp": (
                            "Gen Gov, broad debt"
                        ),
                        "budget_gdp": (
                            "Gen Gov"
                        ),
                        "trade_gdp": (
                            ""
                        ),
                    },
                )

            # Инфляция из бюллетеня Банка России.
            for metric in (
                    "inflation",
                    "inflation_mom",
                    "inflation_core",
            ):
                row[metric] = None
                row[f"{metric}_date"] = None

            ru_row = _last_inflation_row(
                cpi_ru,
                "RU",
                cutoff,
            )

            if ru_row is not None:
                date_label = (
                    f"{_date_label(ru_row['date'])}"
                )

                for source_col, target_col in (
                        ("value", "inflation"),
                        ("mom", "inflation_mom"),
                        ("core", "inflation_core"),
                ):
                    value = ru_row.get(
                        source_col
                    )

                    if pd.notna(value):
                        row[target_col] = round(
                            float(value), 2
                        )

                        row[
                            f"{target_col}_date"
                        ] = date_label

            # Декабрь: годовые показатели России.
            # Q4 не используется вместо полного года.
            if month == 12 and is_finished_year and not ru_quarterly.empty:
                annual = ru_quarterly.loc[
                    (ru_quarterly["country"] == "RU")
                    & (
                            ru_quarterly["date"]
                            == pd.Timestamp(year, 12, 31)
                    )
                    ]

                if not annual.empty:
                    record = annual.iloc[-1]

                    labels = {
                        "debt_gdp": (
                            "Gen Gov, broad debt"
                        ),
                        "budget_gdp": (
                            "Gen Gov"
                        ),
                        "trade_gdp": (
                            ""
                        ),
                    }

                    for metric, label in labels.items():
                        column = "annual_" + metric

                        if column not in record.index:
                            continue

                        value = record[column]

                        if pd.notna(value):
                            row[metric] = round(
                                float(value), 2
                            )
                            row[f"{metric}_date"] = (
                                f"{year} ({label})" if label else str(year)
                            )


            # Годовые ВВП и безработица России.
            # В декабре квартальные значения не используем.
            if month == 12 and is_finished_year and not ru_quarterly.empty:
                annual = ru_quarterly.loc[
                    (ru_quarterly["country"] == "RU")
                    & (
                        ru_quarterly["date"]
                        == pd.Timestamp(year, 12, 31)
                    )
                ]

                if not annual.empty:
                    record = annual.iloc[-1]

                    for metric in (
                        "gdp_growth",
                        "unemployment",
                    ):
                        column = "annual_" + metric

                        if column not in record.index:
                            continue

                        value = record[column]

                        if pd.notna(value):
                            row[metric] = round(
                                float(value), 2
                            )
                            row[f"{metric}_date"] = str(year)


        # ====================================================
        # Historics: annual at the end of the appropriate reporting year.
        # Official annual records set by country blocks above win; if a
        # quarterly value remains, replace it with the WEO annual figure.
        # A fiscal year is *not* the same thing as calendar December in India.
        # ====================================================
        if _is_annual_close(country, year, month) and _annual_period_closed(
            country, imf_year, now
        ):
            for metric, imf_key in (
                ("debt_gdp", "DEBT_GDP"),
                ("budget_gdp", "BUDGET_GDP"),
                ("trade_gdp", "TRADE_GDP"),
                ("gdp_growth", "GDP_GROWTH"),
            ):
                previous = str(row.get(f"{metric}_date") or "")
                if previous and not previous.startswith("Q"):
                    # Official calendar / fiscal annual indicator already set.
                    continue
                annual_value = _imf_metric(imf, country, imf_year, imf_key)
                if annual_value is not None:
                    row[metric] = round(annual_value, 2)
                    detail = "Gen Gov" if metric in ("debt_gdp", "budget_gdp") else None
                    row[f"{metric}_date"] = _imf_fallback_label(
                        imf_year, detail, country=country
                    )

        # ====================================================
        # Bloomberg — только fallback ПОСЛЕ всех официальных источников.
        # Декабрь остаётся годовым; Россия использует только официальные ряды.
        # Bloomberg заменяет резерв IMF, но не официальную публикацию.
        # ====================================================
        if not is_finished_year and country != "RU":
            for metric in BBG_METRICS:
                value, date, period, source = _bbg_value(
                    bbg, country, metric,
                    min(cutoff, _run_time().normalize())
                )
                if value is None:
                    continue

                current_label = row.get(f"{metric}_date")
                uses_annual_imf = (
                    isinstance(current_label, str)
                    and "IMF WEO" in current_label
                )
                if row.get(metric) is not None and not uses_annual_imf:
                    continue

                row[metric] = round(value, 2)
                row[f"{metric}_date"] = (
                    f"{period} ({source})" if period
                    else f"{date.strftime('%m.%Y')} ({source})"
                )

        rows.append(row)

    return pd.DataFrame(rows)

