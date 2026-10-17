import re
import requests
import pandas as pd

# SIDRA — таблица 5932: Contas Nacionais Trimestrais
# v=6561: Taxa trimestral (YoY, %)
# c11255=90707: PIB a preços de mercado
URL = "https://apisidra.ibge.gov.br/values/t/5932/n1/all/v/6561/p/last%2012/c11255/90707"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _parse_quarter(d3c: str) -> pd.Timestamp | None:
    """
    '202303' → 2023-09-30 (конец Q3)
    '202401' → 2024-03-31 (конец Q1)
    """
    if len(d3c) != 6:
        return None
    try:
        year = int(d3c[:4])
        quarter = int(d3c[4:6])
        if quarter < 1 or quarter > 4:
            return None
        month = quarter * 3
        return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    except (ValueError, TypeError):
        return None


def fetch_brazil_gdp() -> pd.DataFrame:
    """
    Тянет квартальный рост ВВП Бразилии (YoY, %) из IBGE SIDRA (таблица 5932).
    Возвращает DataFrame: date, country, gdp_growth.
    """
    try:
        r = requests.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] Brazil GDP: {e}")
        return pd.DataFrame()

    if not isinstance(data, list) or len(data) < 2:
        print("[ERROR] Brazil GDP: пустой ответ")
        return pd.DataFrame()

    rows = []
    for rec in data[1:]:
        d3c = rec.get("D3C", "")
        date = _parse_quarter(d3c)
        if date is None:
            continue

        try:
            value = float(rec.get("V"))
        except (ValueError, TypeError):
            continue

        rows.append({
            "date": date,
            "country": "BR",
            "gdp_growth": value,
        })

    if not rows:
        print("[ERROR] Brazil GDP: не удалось распарсить данные")
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 5 лет
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=5)
    df = df[df["date"] >= cutoff]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_brazil_gdp()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(8).to_string(index=False))
