import pandas as pd
from datetime import datetime, timedelta, timezone
from market_calendar_tool import scrape_calendar, clean_data, Site
from config import CALENDAR_DAYS_AHEAD, CALENDAR_DAYS_BACK

# Маппинг валюты в код страны
CURRENCY_TO_COUNTRY = {
    "USD": "US",
    "EUR": "EU",
    "GBP": "GB",
    "JPY": "JP",
    "CNY": "CN",
    "CHF": "CH",
    "CAD": "CA",
    "AUD": "AU",
    "NZD": "NZ",
}

# Маппинг важности: текст -> звёздочки
IMPACT_TO_STARS = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


def fetch_calendar() -> pd.DataFrame:
    """Тянет экономический календарь с ForexFactory на ближайшие N дней."""
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=CALENDAR_DAYS_BACK)).strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=CALENDAR_DAYS_AHEAD)).strftime("%Y-%m-%d")

    raw = scrape_calendar(site=Site.FOREXFACTORY, date_from=date_from, date_to=date_to)
    cleaned = clean_data(raw)

    df = cleaned.base.copy()
    if df.empty:
        return pd.DataFrame()

    # Нормализация
    df["country"] = df["currency"].map(CURRENCY_TO_COUNTRY).fillna(df["currency"])
    df["importance"] = df["impact"].map(IMPACT_TO_STARS).fillna(0).astype(int)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.rename(columns={"name": "event"})

    # Оставляем только нужные колонки
    cols = ["datetime", "country", "currency", "event", "importance",
            "actual", "forecast", "previous", "revision"]
    df = df[[c for c in cols if c in df.columns]]

    return df.sort_values(["datetime", "importance"], ascending=[True, False]).reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_calendar()
    print(f"Событий: {len(df)}")
    if not df.empty:
        print(df.head(20).to_string())
