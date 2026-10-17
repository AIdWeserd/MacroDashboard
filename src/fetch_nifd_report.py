import re
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
import pdfplumber
import pandas as pd

NIFD_LIST_URL = "http://www.nifd.cn/SeriesReport/SeriesReportList"
NIFD_BASE = "http://www.nifd.cn"

# Куда складывать скачанные PDF
PDF_DIR = Path("data/nifd_reports")

# Сколько страниц пагинации просматривать
MAX_PAGES = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Китайские цифры для кварталов
QUARTER_MAP = {"一": 1, "二": 2, "三": 3, "四": 4}


def _parse_quarter(title: str) -> tuple[int, int] | None:
    """
    Извлекает (year, quarter) из заголовка отчёта.
    Для годовых отчётов ('2024年度') возвращает (year, 4).
    """
    # Квартальный: "2026年二季度" или "2025 年三季度"
    m = re.search(r"(\d{4})\s*年\s*([一二三四])\s*季度", title)
    if m:
        year = int(m.group(1))
        quarter = QUARTER_MAP.get(m.group(2))
        if quarter:
            return year, quarter

    # Годовой: "2024年度" или "2024 年度"
    m = re.search(r"(\d{4})\s*年度", title)
    if m:
        year = int(m.group(1))
        return year, 4

    return None


def _quarter_to_date(year: int, quarter: int) -> pd.Timestamp:
    """Q1→31.03, Q2→30.06, Q3→30.09, Q4→31.12."""
    month = quarter * 3
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def find_all_leverage_reports() -> list[tuple[str, str]]:
    """
    Обходит страницы пагинации NIFD и собирает все отчёты по макро-левереджу.
    Возвращает список (title, href).
    """
    reports = []
    empty_streak = 0

    for page_index in range(1, MAX_PAGES + 1):
        url = f"{NIFD_LIST_URL}?pageSize=20&pageIndex={page_index}&type=RC"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"[WARN] NIFD list page {page_index}: HTTP {r.status_code}")
                break
        except Exception as e:
            print(f"[WARN] NIFD list page {page_index}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        found = []
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip()
            if "NIFD季报" in text and "宏观杠杆率" in text:
                href = a["href"]
                if href.startswith("/"):
                    href = NIFD_BASE + href
                found.append((text, href))

        if found:
            empty_streak = 0
            reports.extend(found)
        else:
            empty_streak += 1
            if empty_streak >= 3:
                break

    return reports


def _find_pdf_url(details_url: str, retries: int = 3, timeout: int = 60) -> str | None:
    """Открывает страницу деталей и находит ссылку на PDF. С retry."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(details_url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.lower().endswith(".pdf"):
                    if href.startswith("/"):
                        href = NIFD_BASE + href
                    return href
            return None
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] NIFD details {details_url}: {e}")
                return None
            wait = 3 * attempt
            print(f"[RETRY] NIFD details: попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return None


def _download_pdf(pdf_url: str, save_path: Path, retries: int = 3, timeout: int = 90) -> bool:
    """Скачивает PDF в save_path с retry."""
    if save_path.exists() and save_path.stat().st_size > 1000:
        return True

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(pdf_url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(r.content)
            return True
        except Exception as e:
            if attempt == retries:
                print(f"[WARN] NIFD PDF download {pdf_url}: {e}")
                return False
            wait = 3 * attempt
            print(f"[RETRY] NIFD PDF: попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return False


def _extract_gov_leverage(pdf_path: Path) -> float | None:
    """
    Читает PDF и извлекает '政府部门杠杆率'
    (консолидированный долг правительства, % от ВВП).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as e:
        print(f"[WARN] NIFD PDF parse {pdf_path}: {e}")
        return None

    # Основной паттерн: "... 从一季度的 70.3%上升至 71.0%。"
    m = re.search(
        r"政府部门杠杆率[^。]*?(\d+\.\d+)%[^。]*?上升至\s*(\d+\.\d+)%",
        full_text,
    )
    if m:
        return float(m.group(2))

    # Fallback: первое число после "政府部门杠杆率"
    m = re.search(r"政府部门杠杆率[^。]*?(\d+\.\d+)%", full_text)
    if m:
        return float(m.group(1))

    return None


def fetch_all_nifd_debt() -> pd.DataFrame:
    """
    Скачивает все отчёты NIFD по макро-левереджу и извлекает долг правительства Китая.
    Возвращает DataFrame с колонками: date, country, debt_gdp.
    """
    reports = find_all_leverage_reports()
    if not reports:
        print("[ERROR] NIFD: не найдено ни одного отчёта по левереджу")
        return pd.DataFrame()

    print(f"[INFO] NIFD: найдено отчётов — {len(reports)}")

    rows = []
    for title, details_url in reports:
        parsed = _parse_quarter(title)
        if parsed is None:
            print(f"[WARN] NIFD: не удалось определить квартал из «{title[:80]}»")
            continue

        year, quarter = parsed
        date = _quarter_to_date(year, quarter)

        pdf_name = f"{year}-Q{quarter}.pdf"
        pdf_path = PDF_DIR / pdf_name

        if not pdf_path.exists():
            pdf_url = _find_pdf_url(details_url)
            if pdf_url is None:
                print(f"[WARN] NIFD: PDF-ссылка не найдена для {details_url}")
                continue
            if not _download_pdf(pdf_url, pdf_path):
                continue

        value = _extract_gov_leverage(pdf_path)
        if value is None:
            print(f"[WARN] NIFD: не удалось извлечь значение из {pdf_path}")
            continue

        rows.append({
            "date": date,
            "country": "CN",
            "debt_gdp": value,
        })
        print(f"[OK] NIFD {year}-Q{quarter}: debt_gdp = {value:.1f}")

    if not rows:
        print("[ERROR] NIFD: не удалось собрать ни одной строки")
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = fetch_all_nifd_debt()
    print(f"\nВсего строк: {len(df)}")
    if not df.empty:
        print(df.to_string(index=False))
