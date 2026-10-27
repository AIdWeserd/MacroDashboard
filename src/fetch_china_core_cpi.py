"""
Core CPI Китая напрямую из NBS (Национальное бюро статистики Китая).

NBS публикует Core CPI (扣除食品和能源价格的核心CPI) в статьях-интерпретациях
к релизам «居民消费价格指数» на stats.gov.cn.

Источник: https://www.stats.gov.cn/sj/zxfbhjd/
"""

import re
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd

NBS_LIST_URL = "https://www.stats.gov.cn/sj/zxfbhjd/"
NBS_BASE = "https://www.stats.gov.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _fetch_html(url: str, retries: int = 3, timeout: int = 60) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] NBS {url}: {e}")
                return None
            time.sleep(2 * attempt)
    return None


def _find_cpi_releases(max_pages: int = 5) -> list[tuple[str, str]]:
    """Ищет статьи-интерпретации CPI на stats.gov.cn."""
    releases = []
    seen = set()

    for page in range(1, max_pages + 1):
        if page == 1:
            url = NBS_LIST_URL
        else:
            # После корневой страницы NBS идёт index_1.html, а не index_2.html.
            url = f"{NBS_LIST_URL}index_{page - 1}.html"

        html = _fetch_html(url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip()
            if ("解读" in text and "CPI" in text) or \
                    ("CPI" in text and "核心" in text) or \
                    ("居民消费价格" in text and "解读" in text):
                href = a["href"]
                if href.startswith("/"):
                    href = NBS_BASE + href
                elif not href.startswith("http"):
                    href = NBS_BASE + "/sj/zxfbhjd/" + href
                if href not in seen:
                    seen.add(href)
                    releases.append((text, href))
                    found += 1

        # На соседней странице может не оказаться CPI-статей, поэтому
        # продолжаем просмотр до max_pages, не пропуская более старые релизы.

    return releases


def _parse_date_from_title(title: str) -> pd.Timestamp | None:
    """'...2026年9月份CPI和PPI数据' → 2026-09-01"""
    m = re.search(r"(\d{4})年(\d{1,2})月", title)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    try:
        return pd.Timestamp(year=year, month=month, day=1)
    except ValueError:
        return None


def _extract_core_cpi(text: str) -> float | None:
    """Извлекает Core CPI YoY из текста статьи."""
    patterns = [
        r"扣除食品和能源价格的核心CPI[^。]*?同比上涨\s*([\d.]+)%",
        r"扣除食品和能源价格的核心CPI[^。]*?同比\s*([\d.]+)%",
        r"核心CPI[^。]*?同比上涨\s*([\d.]+)%",
        r"核心CPI[^。]*?同比\s*([\d.]+)%",
        r"核心CPI[^。]*?上涨\s*([\d.]+)%",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue

    idx = text.find("核心CPI")
    if idx >= 0:
        snippet = text[idx:idx + 300]
        m = re.search(r"([\d.]+)\s*%", snippet)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def fetch_china_core_cpi() -> pd.DataFrame:
    """Тянет Core CPI YoY Китая напрямую из NBS."""
    releases = _find_cpi_releases()
    if not releases:
        print("[ERROR] NBS: интерпретации CPI не найдены")
        return pd.DataFrame()

    print(f"[INFO] NBS: найдено интерпретаций — {len(releases)}")

    rows = []
    for title, url in releases[:24]:
        date = _parse_date_from_title(title)
        if date is None:
            continue

        html = _fetch_html(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        value = _extract_core_cpi(text)
        if value is None:
            print(f"[WARN] NBS {date.strftime('%Y-%m')}: Core CPI не найден")
            continue

        rows.append({
            "date": date,
            "country": "CN",
            "inflation_core": value,
        })
        print(f"[OK] NBS {date.strftime('%Y-%m')}: Core CPI YoY = {value}%")

    if not rows:
        print("[ERROR] NBS: не удалось извлечь ни одного значения")
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = fetch_china_core_cpi()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print(df.tail(12).to_string(index=False))
