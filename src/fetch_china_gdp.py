import re
import requests
from bs4 import BeautifulSoup
import pandas as pd

URL = "https://data.10jqka.com.cn/macro/gdp/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Паттерн для разбора периода: "2026年第1季度", "2026年第1-2季度", "2026年第1-4季度"
QUARTER_PATTERN = re.compile(r"(\d{4})年第1(?:-(\d))?季度")


def _parse_period(period_str: str) -> tuple[pd.Timestamp, int] | None:
    """
    '2026年第1季度'    → (2026-03-31, 1)
    '2026年第1-2季度'  → (2026-06-30, 2)
    '2026年第1-3季度'  → (2026-09-30, 3)
    '2026年第1-4季度'  → (2026-12-31, 4)
    Возвращает (дата_конца_периода, номер_конечного_квартала).
    """
    m = QUARTER_PATTERN.match(period_str.strip())
    if not m:
        return None
    year = int(m.group(1))
    end_quarter = int(m.group(2)) if m.group(2) else 1
    month = end_quarter * 3
    date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return date, end_quarter


def fetch_china_gdp() -> pd.DataFrame:
    """
    Тянет квартальный ВВП Китая из Tonghuashun:
        gdp_growth — YoY, %
        gdp_abs    — поквартальный абсолютный ВВП в 亿元 (вычислен из накопленного)
    Возвращает DataFrame с колонками: date, country, gdp_growth, gdp_abs.
    """
    try:
        r = requests.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] China GDP: {e}")
        return pd.DataFrame()

    html = r.content.decode("gbk", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        print("[ERROR] China GDP: таблица не найдена")
        return pd.DataFrame()

    rows = tables[0].find_all("tr")

    # Собираем накопленные значения: [(year, end_quarter, gdp_abs, yoy)]
    records = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        period_str = cells[0].get_text().strip()
        parsed = _parse_period(period_str)
        if parsed is None:
            continue

        date, end_quarter = parsed

        # Столбец 1 — абсолютный ВВП (累计值, 亿元)
        try:
            gdp_abs = float(cells[1].get_text().strip().replace(",", ""))
        except (ValueError, IndexError):
            continue

        # Столбец 2 — YoY
        try:
            yoy = float(cells[2].get_text().strip().replace("%", "").replace(",", "."))
        except (ValueError, IndexError):
            continue

        records.append({
            "year": date.year,
            "end_quarter": end_quarter,
            "date": date,
            "gdp_abs_cum": gdp_abs,  # накопленный
            "gdp_growth": yoy,
        })

    if not records:
        print("[ERROR] China GDP: не удалось распарсить данные")
        return pd.DataFrame()

    df = pd.DataFrame(records).sort_values(["year", "end_quarter"]).reset_index(drop=True)

    # Вычисляем поквартальный ВВП из накопленного
    # {year: {end_quarter: gdp_abs_cum}}
    cum_by_year = {}
    for _, row in df.iterrows():
        cum_by_year.setdefault(row["year"], {})[row["end_quarter"]] = row["gdp_abs_cum"]

    rows_out = []
    for _, row in df.iterrows():
        year = row["year"]
        end_q = row["end_quarter"]
        cum = row["gdp_abs_cum"]

        # Предыдущий накопленный квартал
        prev_q = end_q - 1
        prev_cum = cum_by_year.get(year, {}).get(prev_q, 0.0)

        gdp_abs = round(cum - prev_cum, 2)

        rows_out.append({
            "date": row["date"],
            "country": "CN",
            "gdp_growth": row["gdp_growth"],
            "gdp_abs": gdp_abs,
        })

    result = pd.DataFrame(rows_out).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 5 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
    result = result[result["date"] >= cutoff]

    return result.reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_china_gdp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.to_string(index=False))
