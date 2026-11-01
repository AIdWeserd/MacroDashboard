import time
import requests
import pandas as pd

BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
HEADERS = {"User-Agent": "Mozilla/5.0"}

START_DATE = pd.Timestamp("2024-01-01")


def _get(series: str, start: str = "01/01/2024", retries: int = 3) -> list:
    last_err = None
    for attempt in range(retries):
        try:
            url = BASE.format(codigo=series)
            params = {"formato": "json", "dataInicial": start}
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"BCB не ответил по {series}: {last_err}")


def _parse_date(d: str) -> pd.Timestamp:
    return pd.to_datetime(d, format="%d/%m/%Y")


def fetch_brazil_debt() -> pd.DataFrame:
    """SGS 13762 — DBGG (% PIB), месячный."""
    data = _get("13762")
    rows = [{"date": _parse_date(r["data"]), "debt_gdp": float(r["valor"])} for r in data]
    df = pd.DataFrame(rows)
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_brazil_budget_12m() -> pd.DataFrame:
    """SGS 5785 — NFSP primário (% PIB), 12-месячный накопленный, месячный."""
    data = _get("5785")
    rows = [{"date": _parse_date(r["data"]), "budget_gdp_12m": float(r["valor"])} for r in data]
    df = pd.DataFrame(rows)
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_brazil_current_account() -> pd.DataFrame:
    """SGS 23081 — Transações correntes, trimestral, saldo, US$ milhões."""
    data = _get("23081")
    rows = []
    for r in data:
        try:
            ts = pd.to_datetime(r["data"], format="%d/%m/%Y")
        except Exception:
            continue
        rows.append({"date": ts, "ca_usd_mn": float(r["valor"])})
    df = pd.DataFrame(rows)
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_brazil_gdp_usd() -> pd.DataFrame:
    """SGS 4385 — PIB mensal em US$ milhões."""
    data = _get("4385")
    rows = [{"date": _parse_date(r["data"]), "gdp_usd_mn": float(r["valor"])} for r in data]
    df = pd.DataFrame(rows)
    df = df[df["date"] >= START_DATE].sort_values("date").reset_index(drop=True)
    return df


def fetch_brazil_quarterly() -> pd.DataFrame:
    debt = fetch_brazil_debt()
    budget_12m = fetch_brazil_budget_12m()
    ca = fetch_brazil_current_account()
    gdp = fetch_brazil_gdp_usd()

    if debt.empty and budget_12m.empty and ca.empty and gdp.empty:
        return pd.DataFrame()

    # 1. Долг/ВВП — значение на последний месяц квартала
    debt_q = pd.DataFrame()
    if not debt.empty:
        debt = debt.copy()
        debt["quarter"] = debt["date"].dt.to_period("Q")
        debt_q = debt.groupby("quarter").last().reset_index()
        debt_q["date"] = debt_q["quarter"].dt.start_time
        debt_q = debt_q[["date", "debt_gdp"]]

    # 2. Бюджет/ВВП (12м) — значение на последний месяц квартала
    budget_q = pd.DataFrame()
    if not budget_12m.empty:
        budget_12m = budget_12m.copy()
        budget_12m["quarter"] = budget_12m["date"].dt.to_period("Q")
        budget_q = budget_12m.groupby("quarter").last().reset_index()
        budget_q["date"] = budget_q["quarter"].dt.start_time
        budget_q["budget_gdp_date_label"] = budget_q["quarter"].apply(
            lambda q: f"{MONTHS_RU[q.end_time.month]} {q.end_time.year} (12м)"
        )
        budget_q = budget_q[["date", "budget_gdp_12m", "budget_gdp_date_label"]]

    # 3. Трейд/ВВП — сумма за квартал / сумма GDP за квартал
    trade_q = pd.DataFrame()
    if not ca.empty and not gdp.empty:
        ca = ca.copy()
        ca["quarter"] = ca["date"].dt.to_period("Q")
        ca_q = ca.groupby("quarter", as_index=False)["ca_usd_mn"].sum()
        ca_q["date"] = ca_q["quarter"].dt.start_time

        gdp = gdp.copy()
        gdp["quarter"] = gdp["date"].dt.to_period("Q")
        gdp_q = gdp.groupby("quarter", as_index=False)["gdp_usd_mn"].sum()
        gdp_q["date"] = gdp_q["quarter"].dt.start_time

        trade_q = ca_q.merge(gdp_q, on="date", how="inner")
        trade_q["trade_gdp"] = trade_q["ca_usd_mn"] / trade_q["gdp_usd_mn"] * 100
        trade_q = trade_q[["date", "trade_gdp"]]

    # Объединяем
    frames = [f for f in [debt_q, budget_q, trade_q] if not f.empty]
    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="date", how="outer")

    result["country"] = "BR"
    result = result.sort_values("date").reset_index(drop=True)
    return result


MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр",
    5: "май", 6: "июн", 7: "июл", 8: "авг",
    9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}
