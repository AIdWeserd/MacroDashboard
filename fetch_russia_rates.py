import re
from io import BytesIO

import pandas as pd
import requests


BASE_URL = (
    "https://www.cbr.ru/vfs/statistics/"
    "pdko/int_rat/"
)

MONTHS_RU = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def _download_rates_table(filename):
    url = BASE_URL + filename

    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
        timeout=120,
        verify=True,
    )

    response.raise_for_status()

    if not response.content.startswith(b"PK"):
        raise ValueError(
            f"ЦБ РФ вернул не XLSX: {url}"
        )

    return pd.read_excel(
        BytesIO(response.content),
        sheet_name="ставки_руб",
        header=None,
    )


def _extract_rate_series(frame, column):
    values = {}

    for _, row in frame.iterrows():
        label = str(row.iloc[0]).strip().lower()

        match = re.fullmatch(
            r"([а-яё]+)\s+(20\d{2})",
            label,
        )

        if not match:
            continue

        month = MONTHS_RU.get(match.group(1))
        year = int(match.group(2))

        if month is None or year < 2024:
            continue

        date = pd.Timestamp(
            year=year,
            month=month,
            day=1,
        ) + pd.offsets.MonthEnd(0)

        value = pd.to_numeric(
            row.iloc[column],
            errors="coerce",
        )

        if pd.notna(value):
            values[date] = float(value)

    return pd.Series(
        values,
        dtype="float64",
    ).sort_index()


def fetch_russia_rates():
    """
    Средневзвешенные ставки Банка России.

    Все значения:
    - проценты годовых;
    - рублевые кредиты и депозиты;
    - месячная периодичность;
    - история с января 2024 года.

    Автокредиты представлены двумя отдельными
    рядами из-за изменения методологии.
    """

    print(
        "[RU RATES] Загружаем официальные "
        "процентные ставки ЦБ РФ..."
    )

    nonfin = _download_rates_table(
        "loans_nonfin.xlsx"
    )

    personal = _download_rates_table(
        "loans_ind_new.xlsx"
    )

    deposits = _download_rates_table(
        "deposits.xlsx"
    )

    auto_archive = _download_rates_table(
        "loans_ind.xlsx"
    )

    series = {
        "company_loans_1y": _extract_rate_series(
            nonfin, 5
        ),
        "personal_loans_all": _extract_rate_series(
            personal, 9
        ),
        "personal_deposits_1y": _extract_rate_series(
            deposits, 7
        ),
        "company_deposits_1y": _extract_rate_series(
            deposits, 16
        ),
        "auto_loans_old_1y_plus": (
            _extract_rate_series(
                auto_archive, 16
            ).loc[
                lambda s: s.index.year <= 2025
            ]
        ),
        "auto_loans_new_all": (
            _extract_rate_series(
                personal, 10
            ).loc[
                lambda s: (
                        s.index >= pd.Timestamp(
                    "2026-02-01"
                )
                )
            ]
        ),
    }

    for name, values in series.items():
        if values.empty:
            raise ValueError(
                f"[RU RATES] Пустой ряд: {name}"
            )

        print(
            f"[RU RATES] {name}: "
            f"{len(values)} месяцев; "
            f"последний — "
            f"{values.index.max():%Y-%m}"
        )

    # Объединение опубликованных рядов.
    # Значения не пересчитываются
    # и пропуски не заполняются.
    result = pd.DataFrame(series)

    result.index.name = "date"
    result = result.reset_index()

    result.insert(
        1,
        "country",
        "RU",
    )

    result = result.sort_values(
        "date"
    ).reset_index(drop=True)

    if result["date"].duplicated().any():
        raise ValueError(
            "[RU RATES] Дублирующиеся даты"
        )

    # Не допускаем смешивания методологий.
    old = result.loc[
        result["auto_loans_old_1y_plus"].notna(),
        "date",
    ]

    new = result.loc[
        result["auto_loans_new_all"].notna(),
        "date",
    ]

    if (
            (not old.empty and old.max().year > 2025)
            or (
            not new.empty
            and new.min() < pd.Timestamp(
        "2026-02-01"
    )
    )
    ):
        raise ValueError(
            "[RU RATES] Пересечение методологий "
            "автокредитования"
        )

    print(
        f"[RU RATES] Готово: "
        f"{len(result)} месячных строк"
    )

    return result
