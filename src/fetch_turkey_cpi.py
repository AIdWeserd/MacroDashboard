import requests
from bs4 import BeautifulSoup
import pandas as pd

TCMB_URL = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Main+Menu/"
    "Statistics/Inflation+Data/"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def fetch_turkey_cpi() -> pd.DataFrame:
    """
    Тянет месячную инфляцию Турции (CPI YoY + MoM) с сайта TCMB (источник TURKSTAT).
    Возвращает DataFrame с колонками: date, country, value, mom, core.
        value — YoY headline, %
        mom   — MoM headline, %
        core  — Core C-index YoY, % — публикуется в PDF Price Developments,
                здесь не парсится, всегда None
    """
    try:
        r = requests.get(TCMB_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Turkey CPI: {e}")
        return pd.DataFrame()

    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        print("[ERROR] Turkey CPI: таблицы не найдены")
        return pd.DataFrame()

    # Перебираем таблицы: ищем ту, где первая колонка "MM-YYYY",
    # вторая — YoY, третья — MoM
    data_rows = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            date_str = cells[0].get_text(strip=True)
            if "-" not in date_str:
                continue

            try:
                month_str, year_str = date_str.split("-")
                month = int(month_str)
                year = int(year_str)
                date = pd.Timestamp(year=year, month=month, day=1)
                yoy = float(cells[1].get_text(strip=True).replace(",", "."))
                mom = float(cells[2].get_text(strip=True).replace(",", "."))
            except (ValueError, TypeError):
                continue

            data_rows.append({
                "date": date,
                "country": "TR",
                "value": yoy,
                "mom": mom,
                "core": None,  # Core — в PDF Price Developments
            })

        if data_rows:
            break

    if not data_rows:
        print("[ERROR] Turkey CPI: не удалось распарсить таблицу")
        return pd.DataFrame()

    df = pd.DataFrame(data_rows)
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_turkey_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
