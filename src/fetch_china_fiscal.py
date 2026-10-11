import re
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd

from src.fetch_china_trade import fetch_china_trade
from src.fetch_china_gdp import fetch_china_gdp

MOF_LIST_URL = "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_html(url: str, retries: int = 5, timeout: int = 90) -> str | None:
    """Скачивает HTML с retry (502/503/504 и таймауты)."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code in (502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] MOF {url}: {e}")
                return None
            wait = 3 * attempt
            print(f"[RETRY] MOF: попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return None


def _find_mof_reports() -> dict[str, str]:
    """
    Парсит список отчётов Минфина. Возвращает {period: url}.
    period = "YYYY-Q1" | "YYYY-H1" | "YYYY-Q3" | "YYYY-Y"
    """
    html = _fetch_html(MOF_LIST_URL)
    if html is None:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    reports = {}

    for a in soup.find_all("a", href=True):
        text = a.get_text().strip()
        href = a["href"]

        if "财政收支情况" not in text:
            continue

        year_match = re.search(r"(\d{4})年", text)
        if not year_match:
            continue
        year = year_match.group(1)

        # Определяем период
        if "一季度" in text and "1-2" not in text:
            period = f"{year}-Q1"
        elif "上半年" in text:
            period = f"{year}-H1"
        elif "前三季度" in text:
            period = f"{year}-Q3"
        elif re.match(rf"{year}年财政收支情况", text) or f"{year}年度" in text:
            period = f"{year}-Y"
        else:
            continue

        reports[period] = href

    return reports


def _extract_revenue_expenditure(html: str) -> tuple[float | None, float | None]:
    """Извлекает revenue и expenditure из HTML Минфина (в 亿元)."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    rev = None
    exp = None

    m = re.search(r"全国一般公共预算收入\s*([\d,]+)\s*亿元", text)
    if m:
        try:
            rev = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    m = re.search(r"全国一般公共预算支出\s*([\d,]+)\s*亿元", text)
    if m:
        try:
            exp = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return rev, exp


def _parse_budget_from_mof() -> dict[str, float]:
    """
    Парсит бюджет из Минфина.
    Возвращает {cumulative_key: deficit}:
        "YYYY-Q1" → deficit Q1
        "YYYY-H1" → deficit H1 (накопленный)
        "YYYY-Q3" → deficit Q1-Q3 (накопленный)
        "YYYY-Y"  → deficit за год
    """
    reports = _find_mof_reports()
    if not reports:
        print("[WARN] MOF: список отчётов пуст")
        return {}

    result = {}
    for period, url in sorted(reports.items()):
        html = _fetch_html(url)
        if not html:
            continue
        rev, exp = _extract_revenue_expenditure(html)
        if rev is not None and exp is not None:
            result[period] = rev - exp
            print(f"[OK] MOF {period}: revenue={rev:.0f}, expenditure={exp:.0f}, "
                  f"deficit={rev - exp:.0f}")

    return result


def _budget_to_quarters(cumulative: dict[str, float]) -> dict[str, float]:
    """
    Преобразует накопительные дефициты Минфина в поквартальные.
        Q1 = cumulative Q1
        Q2 = H1 − Q1
        Q3 = Q1-Q3 − H1
        Q4 = Year − Q1-Q3
    """
    result = {}
    years = sorted({k.split("-")[0] for k in cumulative.keys()})

    for year in years:
        q1 = cumulative.get(f"{year}-Q1")
        h1 = cumulative.get(f"{year}-H1")
        q3 = cumulative.get(f"{year}-Q3")
        y = cumulative.get(f"{year}-Y")

        if q1 is not None:
            result[f"{year}-Q1"] = q1
        if q1 is not None and h1 is not None:
            result[f"{year}-Q2"] = round(h1 - q1, 2)
        if h1 is not None and q3 is not None:
            result[f"{year}-Q3"] = round(q3 - h1, 2)
        if q3 is not None and y is not None:
            result[f"{year}-Q4"] = round(y - q3, 2)

    return result


def fetch_china_fiscal() -> pd.DataFrame:
    """
    Агрегатор для Китая:
        budget  — поквартальный дефицит (Минфин), 亿元
        trade   — поквартальный текущий счёт (SAFE), RMB billions → 亿元
        gdp     — поквартальный абсолютный ВВП (Tonghuashun), 亿元
    Возвращает DataFrame: date, country, budget_gdp, trade_gdp.
    """
    # 1. Бюджет из Минфина
    cumulative_budget = {}
    try:
        cumulative_budget = _parse_budget_from_mof()
    except Exception as e:
        print(f"[WARN] China fiscal MOF parse: {e}")

    budget_by_quarter = _budget_to_quarters(cumulative_budget)

    # 2. Трейд из SAFE (RMB billions)
    trade_by_quarter = {}  # {"YYYY-QN": value_rub_bln}
    try:
        trade_df = fetch_china_trade()
        for _, row in trade_df.iterrows():
            q = (row["date"].month - 1) // 3 + 1
            trade_by_quarter[f"{row['date'].year}-Q{q}"] = row["trade"]
    except Exception as e:
        print(f"[WARN] China fiscal SAFE parse: {e}")

    # 3. ВВП из Tonghuashun (gdp_abs в 亿元)
    gdp_by_quarter = {}
    try:
        gdp_df = fetch_china_gdp()
        for _, row in gdp_df.iterrows():
            q = (row["date"].month - 1) // 3 + 1
            gdp_by_quarter[f"{row['date'].year}-Q{q}"] = row["gdp_abs"]
    except Exception as e:
        print(f"[WARN] China fiscal GDP parse: {e}")

    # 4. Объединяем все кварталы, где есть ВВП
    all_quarters = sorted(gdp_by_quarter.keys())

    rows = []
    for q_key in all_quarters:
        year_str, q_str = q_key.split("-Q")
        year = int(year_str)
        q = int(q_str)
        month = q * 3
        date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)

        gdp = gdp_by_quarter[q_key]

        budget = budget_by_quarter.get(q_key)
        trade_bln = trade_by_quarter.get(q_key)
        trade_yi = trade_bln * 10 if trade_bln is not None else None

        budget_gdp = round(budget / gdp * 100, 2) if (budget is not None and gdp) else None
        trade_gdp = round(trade_yi / gdp * 100, 2) if (trade_yi is not None and gdp) else None

        rows.append({
            "date": date,
            "country": "CN",
            "budget_gdp": budget_gdp,
            "trade_gdp": trade_gdp,
        })

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_china_fiscal()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print(df.to_string(index=False))
