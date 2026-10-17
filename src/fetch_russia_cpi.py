from datetime import date
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.cbr.ru/hd_base/infl/"


def fetch_russia_cpi() -> pd.DataFrame:
    """
    Russia CPI from official Bank of Russia data.

    value: officially published CPI YoY, percent
    mom:   unavailable until separate official source is connected
    core:  unavailable until separate official source is connected

    No macroeconomic indicators are calculated.
    """

    today = date.today()

    params = {
        "UniDbQuery.Posted": "True",
        "UniDbQuery.From": "01.01.2024",
        "UniDbQuery.To": today.strftime("%d.%m.%Y"),
    }

    response = requests.get(
        SOURCE_URL,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    selected_table = None

    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True).lower()

        if (
                "инфляция" in text
                and "ключевая ставка" in text
                and "дата" in text
        ):
            selected_table = table
            break

    if selected_table is None:
        raise ValueError(
            "Не найдена таблица инфляции на сайте Банка России"
        )

    tables = pd.read_html(
        StringIO(str(selected_table)),
        decimal=",",
        thousands=" ",
    )

    if not tables:
        raise ValueError("Таблица инфляции не прочитана")

    raw = tables[0].copy()

    raw.columns = [
        " ".join(map(str, col))
        if isinstance(col, tuple)
        else str(col)
        for col in raw.columns
    ]

    date_col = next(
        (
            col for col in raw.columns
            if "дата" in col.lower()
        ),
        None,
    )

    inflation_col = next(
        (
            col for col in raw.columns
            if "инфляция" in col.lower()
               and "г/г" in col.lower()
        ),
        None,
    )

    if date_col is None or inflation_col is None:
        raise ValueError(
            "Не найдены ожидаемые столбцы даты и CPI YoY. "
            f"Столбцы: {list(raw.columns)}"
        )

    result = pd.DataFrame()

    result["date"] = pd.to_datetime(
        raw[date_col].astype(str).str.strip(),
        format="%m.%Y",
        errors="coerce",
    )

    result["country"] = "RU"

    result["value"] = pd.to_numeric(
        raw[inflation_col]
        .astype(str)
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )

    result["mom"] = None
    result["core"] = None

    result = (
        result.dropna(subset=["date", "value"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    result = result[
        result["date"] >= pd.Timestamp("2024-01-01")
        ].copy()

    if result.empty:
        raise ValueError(
            "Банк России не вернул значений CPI YoY с января 2024 года"
        )

    if not result["value"].between(-100, 100).all():
        raise ValueError("Обнаружены некорректные значения CPI YoY")

    return result


if __name__ == "__main__":
    df = fetch_russia_cpi()

    print("Источник:", SOURCE_URL)
    print("Количество наблюдений:", len(df))
    print(df.tail(12).to_string(index=False))
