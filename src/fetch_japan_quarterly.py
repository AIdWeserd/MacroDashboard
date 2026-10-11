import os
import re
import time
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

ESTAT_APP_ID = os.getenv("ESTAT_APP_ID", "")
ESTAT_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

GDP_STATS_DATA_ID = "0003109785"

MOF_BASE = "https://www.mof.go.jp/english/policy/jgbs/reference/gbb/e{code}.html"

START_DATE = pd.Timestamp("2024-01-01")


def _get(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params or {}, headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Не удалось получить {url}: {last_err}")


def _parse_debt_html(html: str) -> float | None:
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    for table in tables:
        text = re.sub(r'<[^>]+>', ' ', table)
        text = re.sub(r'\s+', ' ', text)
        m = re.search(r'Total\s+([\d,]+)', text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def fetch_japan_debt() -> pd.DataFrame:
    now = datetime.now()
    quarters_to_try = []
    year, month = now.year, now.month
    for _ in range(6):
        q_month = ((month - 1) // 3) * 3 + 3
        quarters_to_try.append(f"{year}{q_month:02d}")
        if q_month == 3:
            year -= 1
            month = 12
        else:
            month = q_month - 3
    seen = set()
    quarters_to_try = [q for q in quarters_to_try if not (q in seen or seen.add(q))]

    rows = []
    for code in quarters_to_try:
        url = MOF_BASE.format(code=code)
        try:
            r = _get(url)
            total = _parse_debt_html(r.text)
            if total is None:
                continue
            year_int = int(code[:4])
            month_int = int(code[4:6])
            q = (month_int - 1) // 3 + 1
            date = pd.Timestamp(year=year_int, month=(q - 1) * 3 + 1, day=1)
            # MOF в 100 млн ¥ (= 10億 × 10), ВВП в 10億. Делим на 10.
            debt_bn_jpy = total / 10.0
            rows.append({"date": date, "debt_bn_jpy": debt_bn_jpy})
        except Exception:
            # Молча пропускаем 404 (ещё не опубликовано)
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset="date").sort_values("date")
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    return df


def fetch_japan_gdp() -> pd.DataFrame:
    if not ESTAT_APP_ID:
        raise RuntimeError("ESTAT_APP_ID не задан в .env")

    params = {
        "appId": ESTAT_APP_ID,
        "statsDataId": GDP_STATS_DATA_ID,
        "lang": "J",
        "limit": 100000,
    }
    r = _get(ESTAT_BASE, params)
    data = r.json()
    result = data.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
    values = result.get("DATA_INF", {}).get("VALUE", [])
    if isinstance(values, dict):
        values = [values]

    rows = []
    for v in values:
        if str(v.get("@tab")) != "11" or str(v.get("@cat01")) != "11":
            continue
        time_code = str(v.get("@time"))
        if len(time_code) != 10:
            continue
        year = int(time_code[:4])
        # Формат: YYYY0MM0MM — берём месяц начала из позиции 6:8
        try:
            month_start = int(time_code[6:8])
        except ValueError:
            continue
        if month_start not in (1, 4, 7, 10):
            continue
        try:
            gdp_bn = float(v.get("$"))
        except (ValueError, TypeError):
            continue
        date = pd.Timestamp(year=year, month=month_start, day=1)
        rows.append({"date": date, "gdp_bn_jpy": gdp_bn})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset="date").sort_values("date")
    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    return df


def fetch_japan_quarterly() -> pd.DataFrame:
    debt = fetch_japan_debt()
    gdp = fetch_japan_gdp()

    if debt.empty or gdp.empty:
        return pd.DataFrame()

    gdp = gdp.copy()
    gdp["gdp_saar"] = gdp["gdp_bn_jpy"] * 4

    result = gdp.merge(debt, on="date", how="left")
    result["debt_gdp"] = result["debt_bn_jpy"] / result["gdp_saar"] * 100
    result["country"] = "JP"

    return result[["date", "country", "debt_gdp"]].sort_values("date").reset_index(drop=True)
