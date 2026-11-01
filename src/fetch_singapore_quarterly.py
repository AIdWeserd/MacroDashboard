import time
import requests
import pandas as pd

BASE = "https://tablebuilder.singstat.gov.sg/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

MONTHS_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

START_DATE = pd.Timestamp("2024-01-01")


def _get(rid: str, params: dict | None = None, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/table/tabledata/{rid}",
                params=params or {},
                headers=HEADERS,
                timeout=60,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"SingStat не ответил по {rid}: {last_err}")


def _parse_quarter(key: str) -> pd.Timestamp | None:
    try:
        parts = key.split()
        year = int(parts[0])
        q = int(parts[1].replace("Q", ""))
        month = (q - 1) * 3 + 1
        return pd.Timestamp(year=year, month=month, day=1)
    except Exception:
        return None


def _parse_month(key: str) -> pd.Timestamp | None:
    try:
        parts = key.split()
        year = int(parts[0])
        month = [k for k, v in MONTHS_ABBR.items() if v == parts[1]][0]
        return pd.Timestamp(year=year, month=month, day=1)
    except Exception:
        return None


def _extract_series(rows: list, series_no: str, parser) -> dict:
    for row in rows:
        if str(row.get("seriesNo")) == series_no:
            out = {}
            for col in row.get("columns", []):
                ts = parser(col["key"])
                if ts is None:
                    continue
                try:
                    out[ts] = float(col["value"])
                except (ValueError, TypeError):
                    continue
            return out
    return {}


def fetch_singapore_debt() -> pd.DataFrame:
    data = _get("M130181")
    rows = data["Data"].get("row", [])
    series = _extract_series(rows, "1", _parse_quarter)
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"date": ts, "debt_sgd_mn": v} for ts, v in series.items()]
    )
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_singapore_gdp_nominal() -> pd.DataFrame:
    data = _get("M014871")
    rows = data["Data"].get("row", [])
    series = _extract_series(rows, "1", _parse_quarter)
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"date": ts, "gdp_sgd_mn": v} for ts, v in series.items()]
    )
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_singapore_budget() -> pd.DataFrame:
    data = _get("M130621")
    rows = data["Data"].get("row", [])
    series = _extract_series(rows, "1", _parse_month)
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"date": ts, "deficit_sgd_mn": v} for ts, v in series.items()]
    )
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_singapore_current_account() -> pd.DataFrame:
    data = _get("M060171")
    rows = data["Data"].get("row", [])
    series = _extract_series(rows, "1.1", _parse_quarter)
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"date": ts, "ca_sgd_mn": v} for ts, v in series.items()]
    )
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_singapore_quarterly() -> pd.DataFrame:
    debt = fetch_singapore_debt()
    gdp = fetch_singapore_gdp_nominal()
    budget = fetch_singapore_budget()
    ca = fetch_singapore_current_account()

    if gdp.empty:
        return pd.DataFrame()

    result = gdp.copy()
    result["gdp_saar"] = result["gdp_sgd_mn"] * 4

    if not debt.empty:
        result = result.merge(debt, on="date", how="left")
        result["debt_gdp"] = result["debt_sgd_mn"] / result["gdp_saar"] * 100

    if not budget.empty:
        budget = budget.copy()
        budget["quarter"] = budget["date"].dt.to_period("Q")
        budget_q = budget.groupby("quarter", as_index=False)["deficit_sgd_mn"].sum()
        budget_q["date"] = budget_q["quarter"].dt.start_time
        budget_q = budget_q[["date", "deficit_sgd_mn"]]
        result = result.merge(budget_q, on="date", how="left")
        result["budget_gdp"] = result["deficit_sgd_mn"] * 4 / result["gdp_saar"] * 100

    if not ca.empty:
        result = result.merge(ca, on="date", how="left")
        result["trade_gdp"] = result["ca_sgd_mn"] * 4 / result["gdp_saar"] * 100

    result["country"] = "SG"
    result = result.sort_values("date").reset_index(drop=True)
    return result
