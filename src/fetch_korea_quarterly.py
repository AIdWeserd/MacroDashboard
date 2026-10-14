import time
import requests
import re
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

URL = "https://mods.go.kr/imfDsbbArcPage.es?mid=a20302010000&page_code=EIDN001"

START_DATE = pd.Timestamp("2024-01-01")


def _get(url: str, retries: int = 3) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"IMF DSBB не ответил: {last_err}")


def _strip_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _parse_value(text: str, label: str) -> tuple[str, float] | None:
    """Ищет 'label ... период ... значение' и возвращает (период, значение)."""
    idx = text.find(label)
    if idx < 0:
        return None
    snippet = text[idx:idx + 500]
    # -? захватывает знак минус
    m = re.search(r'(\w+/\d{2,4}|\d{4})\s+(-?[\d,]+(?:\.\d+)?)', snippet)
    if not m:
        return None
    try:
        return m.group(1), float(m.group(2).replace(",", ""))
    except ValueError:
        return None


def _parse_quarter(period: str) -> pd.Timestamp | None:
    """'Q2/26' -> Timestamp(2026-04-01)."""
    try:
        m = re.match(r'Q(\d)/(\d{2,4})', period)
        if not m:
            return None
        q = int(m.group(1))
        year = int(m.group(2))
        if year < 100:
            year += 2000
        month = (q - 1) * 3 + 1
        return pd.Timestamp(year=year, month=month, day=1)
    except Exception:
        return None


def fetch_korea_quarterly() -> pd.DataFrame:
    """
    Тянет из IMF DSBB (EIDN001):
    - Номинальный ВВП (Q2/26)
    - Central Government Debt (Q2/26)

    Считает долг/ВВП = debt / (gdp * 4) * 100.
    Возвращает DataFrame [date, country, debt_gdp].

    Бюджет и трейд — только в IMF (годовое), квартальных
    официальных данных нет.
    """
    html = _get(URL)
    text = _strip_html(html)

    # ВВП (current prices)
    gdp = _parse_value(text, "* Gross Domestic Product (current prices)")
    # Долг (Central Government Debt)
    debt = _parse_value(text, "* Total gross outstanding of the central government debt")

    if gdp is None or debt is None:
        print("[WARN] Korea DSBB: не найдены GDP или Debt")
        return pd.DataFrame()

    gdp_period, gdp_value = gdp
    debt_period, debt_value = debt

    gdp_ts = _parse_quarter(gdp_period)
    debt_ts = _parse_quarter(debt_period)

    if gdp_ts is None or debt_ts is None:
        print(f"[WARN] Korea DSBB: не удалось распарсить периоды "
              f"(GDP={gdp_period}, Debt={debt_period})")
        return pd.DataFrame()

    # Берём общий период (обычно совпадают — Q2/26)
    quarter = max(gdp_ts, debt_ts)

    # ВВП в DSBB — квартальный SAAR (уже аннуализированный)
    # Единицы: и ВВП, и долг — в млрд вон.
    debt_gdp = debt_value / gdp_value * 100

    df = pd.DataFrame([{
        "date": quarter,
        "country": "KR",
        "debt_gdp": round(debt_gdp, 2),
    }])

    df = df[df["date"] >= START_DATE].reset_index(drop=True)
    return df
