
"""Presentation helpers for Macro Dashboard.

No calculations of macro indicators.
No network requests or SQLite writes.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    frequency: str


METRICS = (
    Metric(
        "policy_rate",
        "Ставка ЦБ, % (уровень)",
        "Уровень ставки на дату",
    ),
    Metric(
        "inflation",
        "CPI/HICP YoY, %",
        "Годовое изменение цен; HICP для Еврозоны",
    ),
    Metric(
        "inflation_mom",
        "CPI/HICP MoM, %",
        "Месячное изменение цен, если опубликовано",
    ),
    Metric(
        "inflation_core",
        "Core CPI/HICP YoY, %",
        "Годовое изменение базового индекса",
    ),
    Metric(
        "inflation_core_mom",
        "Core HICP MoM, %",
        "Месячный опубликованный базовый HICP, Eurostat; остальные страны — пока нет ряда",
    ),
    Metric(
        "ppi_yoy",
        "PPI YoY, %",
        "Европа: промышленный PPI, NSA; США: Final Demand, NSA; Япония: CGPI, NSA",
    ),
    Metric(
        "ppi_mom",
        "PPI MoM, %",
        "Европа: промышленный PPI, NSA; США: Final Demand, SA; Япония: CGPI, NSA",
    ),
    Metric(
        "gdp_growth",
        "Реальный ВВП YoY, %",
        "Годовое изменение объёма ВВП или годовой IMF WEO при fallback; период указан у значения",
    ),
    Metric(
        "gdp_qoq",
        "Реальный ВВП QoQ, % (Eurostat)",
        "Опубликованный рост к предыдущему кварталу, SCA",
    ),
    Metric(
        "unemployment",
        "Безработица, % (уровень)",
        "Доля рабочей силы; SA/NSA по источнику",
    ),
    Metric(
        "debt_gdp",
        "Госдолг / ВВП, % (доля)",
        "Доля ВВП, не YoY; сектор госуправления указан у значения",
    ),
    Metric(
        "budget_gdp",
        "Бюджет / ВВП, % (доля)",
        "Доля ВВП, не YoY; методика и период указаны у значения",
    ),
    Metric(
        "trade_gdp",
        "Внешний баланс / ВВП, % (доля)",
        "Часто текущий счёт / ВВП; точное определение в источнике",
    ),
)


LABEL_BY_KEY = {
    m.key: m.label for m in METRICS
}

KEY_BY_LABEL = {
    m.label: m.key for m in METRICS
}

FREQUENCY_BY_LABEL = {
    m.label: m.frequency for m in METRICS
}


def _valid_imf(
    imf: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "country", "year", "metric", "value"
    }

    if (
        not isinstance(imf, pd.DataFrame)
        or imf.empty
        or not required.issubset(imf.columns)
    ):
        return pd.DataFrame(
            columns=[
                "country", "year",
                "metric", "value",
            ]
        )

    out = imf.loc[
        :,
        ["country", "year", "metric", "value"],
    ].copy()

    out["year"] = pd.to_numeric(
        out["year"], errors="coerce"
    )

    out["value"] = pd.to_numeric(
        out["value"], errors="coerce"
    )

    return out.dropna(
        subset=[
            "country", "year",
            "metric", "value",
        ]
    )


def sort_summary(
    summary: pd.DataFrame,
    imf: pd.DataFrame,
    mode: str,
    selected_year: int,
    current_year: int,
) -> tuple[pd.DataFrame, str]:

    if mode == "Исходный порядок":
        return summary.copy(), ""

    if mode == "Страна А–Я":
        return (
            summary.sort_values(
                "country_name",
                kind="stable",
            ).reset_index(drop=True),
            "",
        )

    if mode not in ("ВВП ↓", "ВВП ↑"):
        return summary.copy(), ""

    base_year = min(
        int(selected_year),
        int(current_year) - 1,
    )

    data = _valid_imf(imf)

    data = data.loc[
        (data.metric == "GDP_USD_BN")
        & (data.year == base_year)
    ]

    if data.empty:
        return (
            summary.copy(),
            f"В базе пока нет номинального ВВП IMF WEO за {base_year} год. "
            "Для сортировки запусти `python scheduler.py imf`. "
            "Порядок стран не изменён.",
        )

    values = (
        data.drop_duplicates(
            subset=["country"],
            keep="last",
        )
        .set_index("country")["value"]
    )

    result = summary.copy()

    result["_nominal_gdp_sort"] = (
        result.country.map(values)
    )

    result = result.sort_values(
        "_nominal_gdp_sort",
        ascending=(mode == "ВВП ↑"),
        na_position="last",
        kind="stable",
    )

    missing = int(
        result["_nominal_gdp_sort"].isna().sum()
    )

    result = (
        result.drop(
            columns=["_nominal_gdp_sort"]
        )
        .reset_index(drop=True)
    )

    note = (
        f"Ранжирование по номинальному ВВП "
        f"за {base_year} год, IMF WEO, млрд USD. "
        "Еврозона пересекается со странами-членами."
    )

    if missing:
        note += (
            f" Без значения ВВП: {missing} "
            "экономик — в конце списка."
        )

    return result, note


def make_forecast_table(
    imf: pd.DataFrame,
    names: dict,
    forecast_year: int,
) -> pd.DataFrame:

    metric_labels = {
        "GDP_GROWTH": "Реальный ВВП YoY, %",
        "INFLATION": "CPI, YoY, % (годовой)",
        "DEBT_GDP": "Госдолг / ВВП, %",
        "BUDGET_GDP": "Бюджет / ВВП, %",
    }

    x = _valid_imf(imf)

    x = x.loc[
        x.year.eq(forecast_year)
        & x.metric.isin(metric_labels)
    ]

    if x.empty:
        return pd.DataFrame()

    x = x[
        x.country.isin(names)
    ]

    x = x.drop_duplicates(
        ["country", "metric"],
        keep="last",
    )

    wide = x.pivot(
        index="country",
        columns="metric",
        values="value",
    )

    wide = (
        wide.rename(columns=metric_labels)
        .reindex(
            columns=list(metric_labels.values())
        )
    )

    wide.insert(
        0,
        "Страна",
        [names[c] for c in wide.index],
    )

    wide.insert(
        1,
        "Год / статус",
        f"{forecast_year} · прогноз IMF WEO (годовой)",
    )

    return wide.reset_index(
        drop=True
    ).round(2)


def compare_snapshot(
    summary: pd.DataFrame,
    previous: pd.DataFrame,
    countries: dict,
    selected_metrics: list[str],
) -> pd.DataFrame:
    """Weekly snapshot is NOT previous publication."""

    if (
        previous is None
        or previous.empty
        or summary.empty
    ):
        return pd.DataFrame()

    old = previous.set_index(
        ["country", "metric"]
    )

    rows = []

    for _, row in summary.iterrows():
        for metric in selected_metrics:
            key = (
                row["country"],
                metric,
            )

            if key not in old.index:
                continue

            past = old.loc[key]

            if isinstance(
                past, pd.DataFrame
            ):
                past = past.iloc[-1]

            before = past.get("value")
            after = row.get(metric)

            if (
                pd.isna(before)
                and pd.isna(after)
            ):
                continue

            rows.append(
                {
                    "Страна": countries.get(
                        row["country"],
                        row["country"],
                    ),
                    "Показатель": LABEL_BY_KEY[metric],
                    "Прошлый недельный снимок": (
                        None
                        if pd.isna(before)
                        else float(before)
                    ),
                    "Сейчас": (
                        None
                        if pd.isna(after)
                        else float(after)
                    ),
                    "Период сейчас": row.get(
                        metric + "_date"
                    ),
                }
            )

    return pd.DataFrame(rows)
