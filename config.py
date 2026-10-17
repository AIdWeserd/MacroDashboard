import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "macro.db"

# API-ключи
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
ESTAT_APP_ID = os.getenv("ESTAT_APP_ID", "")
BEA_API_KEY = os.getenv("BEA_API_KEY", "")

# Страны, которые отслеживаем (код -> полное имя)
COUNTRIES = {
    "US": "United States",
    "EU": "Euro Area",
    "GB": "United Kingdom",
    "JP": "Japan",
    "CN": "China",
    "DE": "Germany",
    "FR": "France",
    "CA": "Canada",
    "AU": "Australia",
    "CH": "Switzerland",
}

# Индикаторы, которые отслеживаем через FRED
INDICATORS = {
    "CPI": "Inflation (CPI)",
    "PPI": "Producer Prices (PPI)",
    "RATE": "Policy Rate",
    "GDP": "GDP Growth",
}

# RSS-ленты для новостей
NEWS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.investing.com/rss/news_25.rss",
]

# Для календаря: сколько дней вперёд тянуть
CALENDAR_DAYS_AHEAD = 7
CALENDAR_DAYS_BACK = 1
