import requests
import pandas as pd

# Таблица 4099: Taxa de desocupação (PNAD Contínua)
BRAZIL_URL = "https://apisidra.ibge.gov.br/values/t/4099/n1/all/v/all/p/last%2012"


def fetch_brazil_unemployment() -> pd.DataFrame:
    """
    Тянет квартальную безработицу Бразилии из IBGE SIDRA.
    Возвращает DataFrame с колонками: date, country, indicator, value.
    """
    try:
        r = requests.get(BRAZIL_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Brazil IBGE: {e}")
        return pd.DataFrame()

    data = r.json()
    if not isinstance(data, list) or len(data) < 2:
        return pd.DataFrame()

    # Первый элемент — заголовки, пропускаем
    rows = []
    for rec in data[1:]:
        # Период: "202602" -> 2026, Q2 -> дата первого месяца квартала
        d3c = rec.get("D3C", "")
        if not d3c or len(d3c) < 6:
            continue
        try:
            year = int(d3c[:4])
            quarter = int(d3c[4:6])  # 01, 02, 03, 04
            month = (quarter - 1) * 3 + 1
            date = pd.Timestamp(year=year, month=month, day=1)
        except Exception:
            continue

        value = rec.get("V")
        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        rows.append({
            "date": date,
            "country": "BR",
            "indicator": "UNEMPLOYMENT",
            "value": value,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    return df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_brazil_unemployment()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print("\nПоследние 5 кварталов:")
        print(df.tail(5).to_string())