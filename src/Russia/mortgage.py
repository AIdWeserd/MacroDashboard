"""Автоматическая загрузка шести ипотечных показателей Банка России."""

from io import BytesIO

import pandas as pd
import requests



SOURCE_URL = (
    "https://www.cbr.ru/vfs/statistics/BankSector/Mortgage/"
    "02_02_Mortgage.xlsx"
)

# Номера строк Excel (0-based). Подписи проверяются при каждом обновлении.
METRICS = {
    "issued_count": (2, "Количество предоставленных кредитов за месяц", 1.0),
    "issued_bln": (3, "Объем предоставленных кредитов за месяц", 1000.0),
    "debt_bln": (4, "Задолженность по предоставленным кредитам", 1000.0),
    "overdue_bln": (5, "просроченная задолженность по предоставленным кредитам", 1000.0),
    "term_months": (8, "Средневзвешенный срок кредитования", 1.0),
    "rate_pct": (9, "Средневзвешенная ставка по кредитам", 1.0),
}


def fetch_russia_mortgage() -> pd.DataFrame:
    """Рублёвая ипотека, отчётные даты ЦБ с 2020 года, без интерполяции."""
    print("[RU MORTGAGE] Загружаем ипотечную статистику ЦБ РФ...")

    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=120,
        verify=True,
    )
    response.raise_for_status()

    if not response.content.startswith(b"PK"):
        raise ValueError("[RU MORTGAGE] Источник не вернул XLSX")

    frame = pd.read_excel(
        BytesIO(response.content),
        sheet_name="в рублях",
        header=None,
    )

    if frame.shape[0] < 10 or frame.shape[1] < 2:
        raise ValueError("[RU MORTGAGE] Неожиданная структура Excel")

    title = str(frame.iat[0, 0]).lower()
    if "ипотечные жилищные кредиты" not in title:
        raise ValueError("[RU MORTGAGE] Неожиданный заголовок файла")

    if "отчетная дата" not in str(frame.iat[1, 0]).lower().replace("ё", "е"):
        raise ValueError("[RU MORTGAGE] Не найдена строка отчётных дат")

    dates = pd.to_datetime(
        frame.iloc[1, 1:],
        format="%d.%m.%Y",
        errors="coerce",
    )

    result = pd.DataFrame({"date": dates.to_numpy()})

    for name, (row_index, expected_label, divisor) in METRICS.items():
        actual_label = str(frame.iat[row_index, 0]).strip().lower().replace("ё", "е")
        normalized_expected = expected_label.lower().replace("ё", "е")
        if normalized_expected not in actual_label:
            raise ValueError(
                f"[RU MORTGAGE] Изменилась строка {name}: {actual_label}"
            )

        # ЦБ публикует объём и задолженность в млн руб.; единицы
        # преобразуем в млрд руб., не вычисляя новых макропоказателей.
        if divisor == 1000.0 and "млн руб" not in actual_label:
            raise ValueError(f"[RU MORTGAGE] Не подтверждены единицы {name}")

        values = pd.to_numeric(
            frame.iloc[row_index, 1:],
            errors="coerce",
        )
        result[name] = values.to_numpy() / divisor

    result = result.loc[
        result["date"].notna()
        & (result["date"] >= pd.Timestamp("2020-01-01"))
    ].copy()

    # Полностью пустая колонка — не опубликованная дата.
    metric_columns = list(METRICS)
    result = result.dropna(subset=metric_columns, how="all")
    result = result.sort_values("date").reset_index(drop=True)

    if result.empty or result["date"].duplicated().any():
        raise ValueError("[RU MORTGAGE] Нет наблюдений или дублируются даты")

    if result[metric_columns].isna().any().any():
        missing = result.loc[
            result[metric_columns].isna().any(axis=1), "date"
        ].dt.strftime("%Y-%m-%d").tolist()
        raise ValueError(f"[RU MORTGAGE] Неполные данные: {missing}")

    if (result[metric_columns] < 0).any().any():
        raise ValueError("[RU MORTGAGE] Обнаружено отрицательное значение")

    result.insert(1, "country", "RU")
    print(
        f"[RU MORTGAGE] Готово: {len(result)} дат, "
        f"с {result['date'].min():%Y-%m-%d} "
        f"по {result['date'].max():%Y-%m-%d}"
    )
    return result
