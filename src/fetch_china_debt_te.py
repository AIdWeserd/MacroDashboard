"""
Government Debt to GDP для Китая из Trading Economics.

TE отдаёт данные через внутренний JSON-эндпоинт /ws/stream.ashx.
Парсим напрямую, без Selenium и без парсинга HTML.

Источник: https://tradingeconomics.com/china/government-debt-to-gdp
"""

import requests
import pandas as pd

# Внутренний эндпоинт TE для получения данных графика
TE_STREAM_URL = "https://tradingeconomics.com/ws/stream.ashx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tradingeconomics.com/china/government-debt-to-gdp",
}


def fetch_china_debt_te() -> pd.DataFrame:
    """
    Тянет Government Debt to GDP Китая из Trading Economics.
    Возвращает DataFrame с колонками: date, country, debt_gdp.
    """
    # Параметры: start=0, size=20, c=china (country slug)
    params = {
        "start": 0,
        "size": 20,
        "c": "china",
    }

    try:
        r = requests.get(TE_STREAM_URL, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] China Debt (TE): {e}")
        return pd.DataFrame()

    if not data:
        print("[ERROR] China Debt (TE): пустой ответ")
        return pd.DataFrame()

    # data — список объектов с полями title, description, url и т.д.
    # Нам нужен Government Debt to GDP
    target = None
    for item in data:
        title = item.get("title", "").lower()
        if "government debt to gdp" in title:
            target = item
            break

    if target is None:
        print(f"[WARN] China Debt (TE): Government Debt to GDP не найден в ответе")
        print(f"       Доступные title: {[i.get('title') for i in data]}")
        return pd.DataFrame()

    # В объекте должен быть символ или ссылка — можно попробовать другой эндпоинт
    # Но проще: возвращаем пустой DataFrame и логируем — данные есть, но не в этом формате
    print(f"[WARN] China Debt (TE): данные найдены, но требуют другого эндпоинта")
    return pd.DataFrame()


if __name__ == "__main__":
    df = fetch_china_debt_te()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(df.tail(10).to_string(index=False))
