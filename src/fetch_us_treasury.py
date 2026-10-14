import time
import requests
import pandas as pd

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8, "September": 9,
    "October": 10, "November": 11, "December": 12,
}

START_DATE = "2024-01-01"


def _get(url: str, params: dict, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Не удалось получить {url}: {last_err}")


def fetch_us_debt() -> pd.DataFrame:
    url = f"{BASE}/v2/accounting/od/debt_to_penny"
    params = {
        "fields": "record_date,tot_pub_debt_out_amt",
        "filter": f"record_date:gte:{START_DATE}",
        "sort": "record_date",
        "page[size]": 10000,
    }
    data = _get(url, params)
    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["record_date"])
    df["debt_usd"] = pd.to_numeric(df["tot_pub_debt_out_amt"], errors="coerce")
    df = df[["date", "debt_usd"]].dropna().sort_values("date")
    return df.reset_index(drop=True)


def fetch_us_budget() -> pd.DataFrame:
    url = f"{BASE}/v1/accounting/mts/mts_table_1"
    params = {
        "filter": f"record_date:gte:{START_DATE}",
        "sort": "record_date",
        "page[size]": 10000,
    }
    data = _get(url, params)
    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    df = df[df["record_type_cd"] == "MTH"].copy()
    df["cls_month"] = df["classification_desc"].map(MONTHS)
    df = df[df["cls_month"].notna()].copy()

    df["rec_month"] = pd.to_numeric(df["record_calendar_month"], errors="coerce")
    df["rec_year"] = pd.to_numeric(df["record_calendar_year"], errors="coerce")
    df = df[df["cls_month"] == df["rec_month"]].copy()

    # Берём строки из секции "Total" (sequence_number_cd начинается с "2.")
    df = df[df["sequence_number_cd"].astype(str).str.startswith("2.")].copy()

    df["deficit_usd"] = pd.to_numeric(df["current_month_dfct_sur_amt"], errors="coerce")
    df["date"] = pd.to_datetime(dict(
        year=df["rec_year"].astype(int),
        month=df["rec_month"].astype(int),
        day=1,
    ))
    df["record_date"] = pd.to_datetime(df["record_date"])

    df = df.sort_values("record_date").drop_duplicates(subset="date", keep="last")

    df = df[["date", "deficit_usd"]].dropna().sort_values("date")
    return df.reset_index(drop=True)


def fetch_us_treasury() -> pd.DataFrame:
    debt = fetch_us_debt()
    budget = fetch_us_budget()

    if debt.empty and budget.empty:
        return pd.DataFrame()

    frames = []

    if not debt.empty:
        debt = debt.copy()
        debt["quarter"] = debt["date"].dt.to_period("Q")
        debt_q = debt.groupby("quarter").last().reset_index()
        debt_q["date"] = debt_q["quarter"].dt.start_time
        debt_q = debt_q[["date", "debt_usd"]]
        frames.append(debt_q)

    if not budget.empty:
        budget = budget.copy()
        budget["quarter"] = budget["date"].dt.to_period("Q")
        budget_q = budget.groupby("quarter", as_index=False)["deficit_usd"].sum()
        budget_q["date"] = budget_q["quarter"].dt.start_time
        budget_q = budget_q[["date", "deficit_usd"]]
        frames.append(budget_q)

    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="date", how="outer")

    result["country"] = "US"
    result = result.sort_values("date").reset_index(drop=True)
    return result
