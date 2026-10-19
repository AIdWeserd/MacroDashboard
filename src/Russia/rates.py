from io import BytesIO
import re
import warnings

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning


warnings.filterwarnings(
    "ignore",
    category=InsecureRequestWarning,
)

BASE_URL = (
    "https://www.cbr.ru/vfs/statistics/"
    "pdko/int_rat/"
)

MONTHS = {
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


def _download_table(filename):
    url = BASE_URL + filename

    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=120,
        verify=False,
    )

    response.raise_for_status()

    if not response.content.startswith(b"PK"):
        raise ValueError(
            f"Ответ ЦБ РФ не является XLSX: {filename}"
        )

    return pd.read_excel(
        BytesIO(response.content),
        sheet_name="ставки_руб",
        header=None,
    )


def _extract_series(frame, column):
    values = {}

    for _, row in frame.iterrows():
        period = str(row.iloc[0]).strip().lower()

        match = re.fullmatch(
            r"([а-яё]+)\s+(20\d{2})",
            period,
        )

        if not match:
            continue

        month = MONTHS.get(match.group(1))
        year = int(match.group(2))

        if month is None or year < 2024:
            continue

        date = (
            pd.Timestamp(year, month, 1)
            + pd.offsets.MonthEnd(0)
        )

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
    Официальные средневзвешенные процентные
    ставки Банка России, % годовых.

    Период: с января 2024 года.
    Частота: месячная.

    Автокредиты сохраняются двумя рядами
    из-за изменения методологии в 2026 году.
    """

    print(
        "[RU RATES] Загрузка ставок ЦБ РФ..."
    )

    company = _download_table(
        "loans_nonfin.xlsx"
    )

    personal = _download_table(
        "loans_ind_new.xlsx"
    )

    deposits = _download_table(
        "deposits.xlsx"
    )

    auto_archive = _download_table(
        "loans_ind.xlsx"
    )

    series = {
        "company_loans_1y": _extract_series(
            company, 5
        ),
        "personal_loans_all": _extract_series(
            personal, 9
        ),
        "personal_deposits_1y": _extract_series(
            deposits, 7
        ),
        "company_deposits_1y": _extract_series(
            deposits, 16
        ),
        "auto_loans_old_1y_plus": _extract_series(
            auto_archive, 16
        ),
        "auto_loans_new_all": _extract_series(
            personal, 10
        ),
    }

    series["auto_loans_old_1y_plus"] = (
        series["auto_loans_old_1y_plus"].loc[
            lambda s: s.index.year <= 2025
        ]
    )

    series["auto_loans_new_all"] = (
        series["auto_loans_new_all"].loc[
            lambda s: (
                s.index >= pd.Timestamp("2026-02-01")
            )
        ]
    )

    for name, values in series.items():
        if values.empty:
            raise ValueError(
                f"[RU RATES] Пустой ряд: {name}"
            )

        print(
            f"[RU RATES] {name}: "
            f"{len(values)} месяцев, "
            f"последний {values.index.max():%Y-%m}"
        )

    result = pd.DataFrame(series)

    result.index.name = "date"
    result = result.reset_index()

    result.insert(1, "country", "RU")

    result = (
        result.sort_values("date")
        .reset_index(drop=True)
    )

    if result["date"].duplicated().any():
        raise ValueError(
            "[RU RATES] Дублирующиеся даты"
        )

    # Не допускаем пересечения методологий.
    old_dates = result.loc[
        result["auto_loans_old_1y_plus"].notna(),
        "date",
    ]

    new_dates = result.loc[
        result["auto_loans_new_all"].notna(),
        "date",
    ]

    if not old_dates.empty:
        if old_dates.max().year > 2025:
            raise ValueError(
                "Старая методология после 2025 года"
            )

    if not new_dates.empty:
        if new_dates.min() < pd.Timestamp("2026-02-01"):
            raise ValueError(
                "Новая методология до февраля 2026"
            )

    if (
        result["auto_loans_old_1y_plus"].notna()
        & result["auto_loans_new_all"].notna()
    ).any():
        raise ValueError(
            "Пересечение двух рядов автокредитов"
        )

    print(
        f"[RU RATES] Готово: {len(result)} месяцев"
    )

    return result
