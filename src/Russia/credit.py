"""Задолженность по кредитам по официальным XLSX Банка России.

Три месячных показателя на 1-е число месяца, единица в БД: млрд руб.
Не путать остатки задолженности с новыми выдачами кредитов.
"""
from io import BytesIO
import warnings

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

_BASE = "https://www.cbr.ru/vfs/statistics/BankSector/"
SOURCES = {
    "personal_debt": {
        "url": _BASE + "Mortgage/02_05_Debt_ind.xlsx",
        "date_row": 2,
        "value_row": 3,
        "label": "РОССИЙСКАЯ ФЕДЕРАЦИЯ",
    },
    "company_debt": {
        "url": _BASE + "Loans_to_corporations/01_05_D_Debt_subj.xlsx",
        "date_row": 1,
        "value_row": 2,
        "label": "РОССИЙСКАЯ ФЕДЕРАЦИЯ",
    },
    "sme_debt": {
        "url": _BASE + "Loans_to_corporations/01_11_Debt_sme.xlsx",
        "date_row": 1,
        "value_row": 2,
        "label": "Субъектам малого и среднего",
    },
}


def _load_credit_series(name: str, source: dict) -> pd.DataFrame:
    response = requests.get(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=120,
        verify=False,
    )
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError(f"[RU CREDIT] Получен не XLSX: {name}")

    frame = pd.read_excel(
        BytesIO(response.content), sheet_name="итого", header=None,
    )
    date_row = source["date_row"]
    value_row = source["value_row"]
    label = str(frame.iat[value_row, 0]).strip()
    if source["label"].lower() not in label.lower():
        raise ValueError(f"[RU CREDIT] Неверная строка {name}: {label}")

    heading = " ".join(
        str(frame.iat[i, 0])
        for i in range(min(2, len(frame)))
    ).lower()
    if "задолженность" not in heading or "млн руб" not in heading:
        raise ValueError(
            f"[RU CREDIT] Не подтверждены показатель/единицы {name}: {heading}"
        )

    dates = pd.to_datetime(frame.iloc[date_row, 1:], errors="coerce")
    values = pd.to_numeric(frame.iloc[value_row, 1:], errors="coerce")
    result = pd.DataFrame({
        "date": dates.to_numpy(),
        name: values.to_numpy(),
    }).dropna(subset=["date", name])

    result = result.loc[result["date"] >= "2020-01-01"].copy()
    result[name] = result[name] / 1000.0  # млн руб. -> млрд руб.
    result = result.sort_values("date").reset_index(drop=True)
    if result.empty or result["date"].duplicated().any():
        raise ValueError(f"[RU CREDIT] Нет данных или повтор дат: {name}")
    print(
        f"[RU CREDIT] {name}: {len(result)} наблюдений, "
        f"последняя дата {result['date'].max():%Y-%m-%d}"
    )
    return result


def fetch_russia_credit() -> pd.DataFrame:
    """Загрузить задолженность физлиц, компаний/ИП и МСП (млрд руб.)."""
    print("[RU CREDIT] Загружаем задолженность по кредитам...")
    result = None
    for name, source in SOURCES.items():
        series = _load_credit_series(name, source)
        result = series if result is None else result.merge(
            series, on="date", how="outer", validate="one_to_one"
        )

    result = result.sort_values("date").reset_index(drop=True)
    result.insert(1, "country", "RU")
    if result["date"].duplicated().any():
        raise ValueError("[RU CREDIT] Дублирующиеся даты")
    print(f"[RU CREDIT] Готово: {len(result)} строк")
    return result
