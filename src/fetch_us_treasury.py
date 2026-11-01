
import time

import pandas as pd
import requests


BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

START_DATE = "2020-01-01"
PAGE_SIZE = 10000

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


def _get(url: str, params: dict, retries: int = 3) -> dict:
    last_error = None

    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=90,
            )
            response.raise_for_status()

            data = response.json()

            if (
                not isinstance(data, dict)
                or not isinstance(data.get("data"), list)
            ):
                raise ValueError(
                    "Treasury API: unexpected response format"
                )

            return data

        except (requests.RequestException, ValueError) as exc:
            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        "Treasury API request failed "
        f"({type(last_error).__name__})"
    ) from None


def _get_all(url: str, params: dict) -> list:
    """
    Загружает все страницы Treasury API.
    Проверяет полноту полученного результата.
    """
    rows = []
    requested_page_size = int(
        params.get("page[size]", PAGE_SIZE)
    )

    for page in range(1, 1001):
        page_params = dict(params)
        page_params["page[number]"] = page

        response = _get(url, page_params)

        page_rows = response["data"]
        meta = response.get("meta", {})

        if (
            not isinstance(meta, dict)
            or "total-pages" not in meta
        ):
            raise RuntimeError(
                "Treasury API: pagination metadata unavailable"
            )

        total_pages = int(meta["total-pages"])

        total_count = (
            int(meta["total-count"])
            if "total-count" in meta
            else None
        )

        if total_pages < 0 or page > max(1, total_pages):
            raise RuntimeError(
                "Treasury API: inconsistent pagination metadata"
            )

        if not page_rows and page < total_pages:
            raise RuntimeError(
                "Treasury API: empty page before end of dataset"
            )

        rows.extend(page_rows)

        if page >= total_pages:
            if (
                total_count is not None
                and len(rows) != total_count
            ):
                raise RuntimeError(
                    "Treasury API: incomplete response "
                    f"({len(rows)} of {total_count} rows)"
                )

            return rows

        if len(page_rows) > requested_page_size:
            raise RuntimeError(
                "Treasury API: response exceeds page size"
            )

    raise RuntimeError(
        "Treasury API: exceeded 1000 pages"
    )


def fetch_us_debt() -> pd.DataFrame:
    """
    Daily Debt to the Penny:
    Total Public Debt Outstanding, USD.
    """
    url = f"{BASE}/v2/accounting/od/debt_to_penny"

    params = {
        "fields": "record_date,tot_pub_debt_out_amt",
        "filter": f"record_date:gte:{START_DATE}",
        "sort": "record_date",
        "page[size]": PAGE_SIZE,
    }

    rows = _get_all(url, params)

    if not rows:
        return pd.DataFrame(
            columns=["date", "debt_usd"]
        )

    df = pd.DataFrame(rows)

    df["date"] = pd.to_datetime(
        df["record_date"],
        errors="coerce",
    )

    df["debt_usd"] = pd.to_numeric(
        df["tot_pub_debt_out_amt"],
        errors="coerce",
    )

    return (
        df[["date", "debt_usd"]]
        .dropna()
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_us_budget() -> pd.DataFrame:
    """
    Monthly Treasury Statement, Table 1.

    Сохраняем исходный выбор строк:
    - record_type_cd = MTH
    - classification_desc соответствует месяцу
    - sequence_number_cd начинается с 2.
    """
    url = f"{BASE}/v1/accounting/mts/mts_table_1"

    params = {
        "filter": f"record_date:gte:{START_DATE}",
        "sort": "record_date",
        "page[size]": PAGE_SIZE,
    }

    rows = _get_all(url, params)

    if not rows:
        return pd.DataFrame(
            columns=["date", "deficit_usd"]
        )

    df = pd.DataFrame(rows)

    df = df[
        df["record_type_cd"] == "MTH"
    ].copy()

    df["cls_month"] = (
        df["classification_desc"].map(MONTHS)
    )

    df = df[
        df["cls_month"].notna()
    ].copy()

    df["rec_month"] = pd.to_numeric(
        df["record_calendar_month"],
        errors="coerce",
    )

    df["rec_year"] = pd.to_numeric(
        df["record_calendar_year"],
        errors="coerce",
    )

    df = df[
        df["cls_month"] == df["rec_month"]
    ].copy()

    # Сохраняем ранее проверенный фильтр MTS.
    df = df[
        df["sequence_number_cd"]
        .astype(str)
        .str.startswith("2.")
    ].copy()

    df["deficit_usd"] = pd.to_numeric(
        df["current_month_dfct_sur_amt"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["rec_year", "rec_month"]
    )

    df["date"] = pd.to_datetime(
        dict(
            year=df["rec_year"].astype(int),
            month=df["rec_month"].astype(int),
            day=1,
        ),
        errors="coerce",
    )

    df["record_date"] = pd.to_datetime(
        df["record_date"],
        errors="coerce",
    )

    df = (
        df.sort_values("record_date")
        .drop_duplicates(
            subset="date",
            keep="last",
        )
    )

    return (
        df[["date", "deficit_usd"]]
        .dropna()
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_us_treasury() -> pd.DataFrame:
    """
    Квартальные компоненты Treasury.

    debt_usd:
        Последнее опубликованное значение
        в каждом квартале.

    deficit_usd:
        Сумма месячных значений за квартал.

    Расчёты отношения к ВВП выполняются
    в src.fetch_us и здесь не меняются.
    """
    debt = fetch_us_debt()
    budget = fetch_us_budget()

    if debt.empty or budget.empty:
        print(
            "[WARN] US Treasury: debt or budget is empty"
        )
        return pd.DataFrame()

    # Debt: последнее значение квартала.
    debt = debt.copy()
    debt["quarter"] = (
        debt["date"].dt.to_period("Q")
    )

    debt_q = (
        debt.groupby("quarter")
        .last()
        .reset_index()
    )

    debt_q["date"] = (
        debt_q["quarter"].dt.start_time
    )

    debt_q = debt_q[
        ["date", "debt_usd"]
    ]

    # Budget: сумма месячных значений.
    budget = budget.copy()
    budget["quarter"] = (
        budget["date"].dt.to_period("Q")
    )

    budget_q = (
        budget.groupby(
            "quarter",
            as_index=False,
        )["deficit_usd"]
        .sum()
    )

    budget_q["date"] = (
        budget_q["quarter"].dt.start_time
    )

    budget_q = budget_q[
        ["date", "deficit_usd"]
    ]

    # Оба компонента должны относиться
    # к одному кварталу.
    result = debt_q.merge(
        budget_q,
        on="date",
        how="inner",
    )

    # Незавершённый квартал не используем.
    current_quarter = (
        pd.Timestamp.now().to_period("Q")
    )

    result = result[
        result["date"].dt.to_period("Q")
        < current_quarter
    ].copy()

    result["country"] = "US"

    return (
        result.sort_values("date")
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    result = fetch_us_treasury()

    print("ROWS:", len(result))

    if not result.empty:
        print("FIRST:", result["date"].min())
        print("LAST:", result["date"].max())
        print(result.tail(5).to_string(index=False))
