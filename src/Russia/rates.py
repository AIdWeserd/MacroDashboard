"""Официальные средневзвешенные процентные ставки Банка России, с 2020 года.

Автокредиты: до 2026 года срок свыше 1 года; с февраля 2026 года
другая серия — все сроки. Две методологии не объединяются.
"""
from io import BytesIO
import re

import pandas as pd
import requests


BASE_URL = "https://www.cbr.ru/vfs/statistics/pdko/int_rat/"
MONTHS = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}


def _download_table(filename: str) -> pd.DataFrame:
    response = requests.get(
        BASE_URL + filename,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=120,
        verify=True,
    )
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError(f"[RU RATES] Получен не XLSX: {filename}")
    return pd.read_excel(
        BytesIO(response.content), sheet_name="ставки_руб", header=None
    )


def _extract_series(frame: pd.DataFrame, column: int) -> pd.Series:
    values = {}
    for _, row in frame.iterrows():
        period = str(row.iloc[0]).strip().lower()
        match = re.fullmatch(r"([а-яё]+)\s+(20\d{2})", period)
        if match is None:
            continue
        month = MONTHS.get(match.group(1))
        year = int(match.group(2))
        if month is None or year < 2020:
            continue
        date = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
        value = pd.to_numeric(row.iloc[column], errors="coerce")
        if pd.notna(value):
            values[date] = float(value)
    return pd.Series(values, dtype="float64").sort_index()


def fetch_russia_rates() -> pd.DataFrame:
    """Загрузить помесячные опубликованные ставки ЦБ, % годовых."""
    print("[RU RATES] Загружаем официальные ставки ЦБ РФ...")
    company = _download_table("loans_nonfin.xlsx")
    personal = _download_table("loans_ind_new.xlsx")
    deposits = _download_table("deposits.xlsx")
    auto_archive = _download_table("loans_ind.xlsx")

    # Официальная ставка МСП: лист «ставки_руб», колонка N (0-based 13).
    # Важно проверять двустрочный заголовок, чтобы не подменить
    # МСП общей ставкой нефинансовым организациям (колонка F).
    sme_header = str(company.iat[3, 9]).lower().replace("ё", "е")
    sme_term = str(company.iat[4, 13]).lower().replace("ё", "е")
    if not ("малого" in sme_header and "среднего" in sme_header):
        raise ValueError("[RU RATES] Не найден заголовок ставки МСП")
    if not ("до 1 года" in sme_term and "востребова" in sme_term):
        raise ValueError("[RU RATES] Не подтверждён срок кредитов МСП")

    series = {
        "sme_loans_1y": _extract_series(company, 13),
        "company_loans_1y": _extract_series(company, 5),
        "personal_loans_all": _extract_series(personal, 9),
        "personal_deposits_1y": _extract_series(deposits, 7),
        "company_deposits_1y": _extract_series(deposits, 16),
        "auto_loans_old_1y_plus": _extract_series(auto_archive, 16),
        "auto_loans_new_all": _extract_series(personal, 10),
    }
    series["auto_loans_old_1y_plus"] = series["auto_loans_old_1y_plus"].loc[
        lambda s: s.index.year <= 2025
    ]
    series["auto_loans_new_all"] = series["auto_loans_new_all"].loc[
        lambda s: s.index >= pd.Timestamp("2026-02-01")
    ]
    for name, values in series.items():
        if values.empty:
            raise ValueError(f"[RU RATES] Пустой ряд: {name}")
        print(f"[RU RATES] {name}: {len(values)} месяцев")

    result = pd.DataFrame(series)
    result.index.name = "date"
    result = result.reset_index().sort_values("date").reset_index(drop=True)
    result.insert(1, "country", "RU")
    if result["date"].duplicated().any():
        raise ValueError("[RU RATES] Дублирующиеся даты")
    if (
        result["auto_loans_old_1y_plus"].notna()
        & result["auto_loans_new_all"].notna()
    ).any():
        raise ValueError("[RU RATES] Пересечение методологий автокредитования")
    print(f"[RU RATES] Готово: {len(result)} месячных строк")
    return result
