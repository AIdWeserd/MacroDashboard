
from io import BytesIO

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

BASE = "https://www.cbr.ru/vfs/statistics/BankSector/"

SOURCES = {
    "Физлица": (
        BASE + "Mortgage/02_05_Debt_ind.xlsx",
        3,
    ),
    "Компании и ИП": (
        BASE
        + "Loans_to_corporations/01_05_D_Debt_subj.xlsx",
        2,
    ),
    "МСП": (
        BASE
        + "Loans_to_corporations/01_11_Debt_sme.xlsx",
        2,
    ),
}

for name, (url, data_row) in SOURCES.items():
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=120,
        verify=False,
    )
    response.raise_for_status()

    df = pd.read_excel(
        BytesIO(response.content),
        sheet_name="итого",
        header=None,
    )

    print("\n" + "=" * 60)
    print(name)

    print(
        "Название и единицы:",
        str(df.iat[0, 0])[:300],
        "|",
        str(df.iat[1, 0])[:300],
    )

    # Физлица: дата в строке 3, данные в строке 4.
    # Компании и МСП: дата в строке 2,
    # данные в строке 3.
    date_row = data_row - 1

    dates = pd.to_datetime(
        df.iloc[date_row, 1:],
        errors="coerce",
    )

    values = pd.to_numeric(
        df.iloc[data_row, 1:],
        errors="coerce",
    )

    result = pd.DataFrame({
        "date": dates.to_numpy(),
        "value": values.to_numpy(),
    }).dropna()

    result = result.loc[
        result["date"] >= "2024-01-01"
    ].sort_values("date")

    print("Количество:", len(result))
    print("Первая дата:", result["date"].min())
    print("Последняя дата:", result["date"].max())
    print("\nПоследние три значения:")
    print(result.tail(3).to_string(index=False))

print("\nSQLite не изменялась.")
