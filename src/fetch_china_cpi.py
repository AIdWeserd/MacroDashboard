import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

URL = "https://data.10jqka.com.cn/macro/cpi/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def fetch_china_cpi() -> pd.DataFrame:
    """
    Тянет CPI Китая (YoY + MoM) с Tonghuashun (10jqka.com.cn).
    Возвращает DataFrame с колонками: date, country, value, mom, core.
        value — YoY headline, %
        mom   — MoM headline, %
        core  — Core YoY, % — не публикуется в этой таблице, всегда None
    """
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] China CPI: {e}")
        return pd.DataFrame()

    # Tonghuashun отдаёт GBK, декодируем явно
    html = r.content.decode("gbk", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        print("[ERROR] China CPI: таблица не найдена")
        return pd.DataFrame()

    table = tables[0]
    rows = table.find_all("tr")

    records = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        # Первая колонка — дата "2026-08" или заголовок "月份"
        date_str = cells[0].get_text().strip()
        if not re.match(r"^\d{4}-\d{2}$", date_str):
            continue

        try:
            date = pd.to_datetime(date_str, format="%Y-%m")
        except ValueError:
            continue

        # Вторая колонка — индекс (全国 当月), пропускаем
        # Третья колонка — YoY (全国 同比增长)
        # Четвёртая колонка — MoM (全国 环比增长)
        yoy_str = cells[2].get_text().strip().replace("%", "")
        mom_str = cells[3].get_text().strip().replace("%", "")

        try:
            yoy = float(yoy_str)
            mom = float(mom_str)
        except ValueError:
            continue

        records.append({
            "date": date,
            "country": "CN",
            "value": yoy,
            "mom": mom,
            "core": None,  # Core не публикуется в этой таблице
        })

    df = pd.DataFrame(records)
    if df.empty:
        print("[ERROR] China CPI: не удалось распарсить данные")
        return pd.DataFrame()

    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_china_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
