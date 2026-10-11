import re
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd

SAFE_BASE = "http://www.safe.gov.cn"
SAFE_EN_NEWS = "http://www.safe.gov.cn/en/SAFENews/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

MONTH_END = {1: 3, 2: 6, 3: 9, 4: 12}


def _fetch_html(url: str, retries: int = 3, timeout: int = 60) -> str | None:
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
                print(f"[WARN] SAFE {url}: {e}")
                return None
            wait = 3 * attempt
            print(f"[RETRY] SAFE: попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return None


def _find_bop_releases() -> list[str]:
    """Ищет ссылки на все релизы Balance of Payments (английский SAFE)."""
    releases = []
    seen = set()

    for page in range(1, 8):
        url = SAFE_EN_NEWS if page == 1 else f"{SAFE_BASE}/en/SAFENews/index_{page}.html"
        html = _fetch_html(url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        found_this_page = False
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip()
            if "Balance of Payments" in text and "Quarter" in text:
                href = a["href"]
                if href.startswith("/"):
                    href = SAFE_BASE + href
                if href not in seen:
                    seen.add(href)
                    releases.append(href)
                    found_this_page = True

        if not found_this_page and page > 1:
            break

    return releases


def _parse_release_title(title: str) -> dict:
    """
    Из заголовка релиза определяет год, квартал и флаги накопления.
    Возвращает {"year": int, "quarter": int|None, "h1": bool, "q3": bool, "y": bool, "preliminary": bool}.
    """
    t = title.lower()

    year_match = re.search(r"(\d{4})", title)
    if not year_match:
        return {}
    year = int(year_match.group(1))

    result = {
        "year": year,
        "quarter": None,
        "h1": False,
        "q3": False,
        "y": False,
        "preliminary": "preliminary" in t,
    }

    if "second quarter" in t:
        result["quarter"] = 2
        result["h1"] = True
    elif "third quarter" in t:
        result["quarter"] = 3
        result["q3"] = True
    elif "fourth quarter" in t:
        result["quarter"] = 4
        result["y"] = True
    elif "first quarter" in t:
        result["quarter"] = 1

    return result


def _extract_value(text: str, pattern: str) -> float | None:
    """Извлекает число (RMB billions) по регулярному выражению."""
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _extract_quarter_value(text: str, year: int, quarter: int) -> float | None:
    """Извлекает квартальное значение current account (RMB billions)."""
    q_names = {1: "first", 2: "second", 3: "third", 4: "fourth"}
    q_name = q_names[quarter]
    pattern = (
        rf"in the {q_name} quarter of {year}[^.]*?current account[^.]*?RMB\s*([\d,\.]+)\s*billion"
    )
    return _extract_value(text, pattern)


def _extract_cumulative_value(text: str, year: int, kind: str) -> float | None:
    """kind = 'h1' | 'q3' | 'y'."""
    if kind == "h1":
        pattern = rf"in the first half of {year}[^.]*?current account[^.]*?RMB\s*([\d,\.]+)\s*billion"
    elif kind == "q3":
        pattern = rf"in the first three quarters of {year}[^.]*?current account[^.]*?RMB\s*([\d,\.]+)\s*billion"
    elif kind == "y":
        pattern = rf"in {year}[^.]*?current account[^.]*?RMB\s*([\d,\.]+)\s*billion"
    else:
        return None
    return _extract_value(text, pattern)


def _store(target: dict, key, val: float, prelim: bool, label: str):
    """
    Сохраняет значение с приоритетом:
      - если ключа нет — пишем;
      - если новый финальный — перезаписываем;
      - если новый prelim и уже есть финал — игнорируем.
    """
    if key not in target:
        target[key] = (val, prelim)
    elif not prelim:
        target[key] = (val, prelim)
    tag = " (prelim)" if prelim else ""
    print(f"[OK] SAFE {label}: {val:.1f} RMB bln{tag}")


def fetch_china_trade() -> pd.DataFrame:
    """
    Тянет квартальный текущий счёт Китая (RMB billions) из SAFE за все доступные кварталы.
    Возвращает DataFrame: date, country, trade.
    """
    releases = _find_bop_releases()
    print(f"[INFO] SAFE: найдено релизов — {len(releases)}")

    # quarters[(year, q)] = (value, is_preliminary)
    quarters = {}
    # cumulative[year]["h1"|"q3"|"y"] = (value, is_preliminary)
    cumulative = {}

    for url in releases:
        html = _fetch_html(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text() if soup.title else ""
        text = soup.get_text()

        meta = _parse_release_title(title)
        if not meta:
            continue

        year = meta["year"]
        quarter = meta["quarter"]
        prelim = meta["preliminary"]

        if year not in cumulative:
            cumulative[year] = {}

        # Квартальное значение
        if quarter:
            val = _extract_quarter_value(text, year, quarter)
            if val is not None:
                _store(quarters, (year, quarter), val, prelim, f"{year}-Q{quarter}")

        # H1
        if meta["h1"]:
            val = _extract_cumulative_value(text, year, "h1")
            if val is not None:
                _store(cumulative[year], "h1", val, prelim, f"{year}-H1")

        # 3Q
        if meta["q3"]:
            val = _extract_cumulative_value(text, year, "q3")
            if val is not None:
                _store(cumulative[year], "q3", val, prelim, f"{year}-Q1-Q3")

        # Year
        if meta["y"]:
            val = _extract_cumulative_value(text, year, "y")
            if val is not None:
                _store(cumulative[year], "y", val, prelim, f"{year}-Y")

    # Распаковываем кортежи
    quarters_val = {k: v[0] for k, v in quarters.items()}
    cumulative_val = {y: {k: v[0] for k, v in d.items()} for y, d in cumulative.items()}

    # Считаем поквартальные значения
    final = {}

    # 1. Прямые значения из релизов (Q1, Q2, Q3, Q4 — если есть)
    for (year, q), val in quarters_val.items():
        final[(year, q)] = val

    # 2. Восстанавливаем пропущенные кварталы из накопленных
    for year, cum in cumulative_val.items():
        # Q2 = H1 − Q1 (если Q2 нет напрямую)
        if "h1" in cum and (year, 1) in final and (year, 2) not in final:
            final[(year, 2)] = round(cum["h1"] - final[(year, 1)], 1)

        # Q3 = 3Q − H1 (если Q3 нет напрямую)
        if "q3" in cum and "h1" in cum and (year, 3) not in final:
            final[(year, 3)] = round(cum["q3"] - cum["h1"], 1)

        # Q4 = Y − 3Q (если Q4 нет напрямую)
        if "y" in cum and "q3" in cum and (year, 4) not in final:
            final[(year, 4)] = round(cum["y"] - cum["q3"], 1)

    if not final:
        print("[WARN] SAFE: ничего не извлечено")
        return pd.DataFrame()

    rows = []
    for (year, quarter), value in sorted(final.items()):
        month = MONTH_END[quarter]
        date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        rows.append({"date": date, "country": "CN", "trade": value})

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_china_trade()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print(df.to_string(index=False))
