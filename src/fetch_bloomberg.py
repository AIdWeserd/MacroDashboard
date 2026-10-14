"""
Чтение ручных выгрузок Bloomberg Excel Add-in.

Файлы лежат в data/bloomberg/ под именем bbg_YYYY-MM-DD.xlsx.
Формат листа (любое имя — ищется по колонкам):
    country | metric | ticker | field | value | date | frequency

- country  : JP, AU, KR, IN, TR, CH, BR, CN, SG
- metric   : budget_gdp, trade_gdp, debt_gdp, core_cpi, policy_rate
- ticker   : Bloomberg-тикер (пусто, если метрика недоступна)
- field    : PX_LAST и т.п.
- value    : значение (число)
- date     : дата выгрузки (BTODAY в Excel)
- frequency: Q (квартал), M (месяц), пусто

Парсер берёт самый свежий bbg_*.xlsx, читает лист с нужными колонками,
оставляет строки с заполненным ticker и непустым value.

Дата читается через openpyxl, чтобы сохранить исходный формат DD.MM.YYYY
и не путать день с месяцем.
"""

from pathlib import Path
import re
import pandas as pd
from config import DATA_DIR

BLOOMBERG_DIR = DATA_DIR / "bloomberg"

REQUIRED_COLS = {"country", "metric", "ticker", "field", "value", "date", "frequency"}


def _latest_file() -> Path | None:
    """Возвращает самый свежий bbg_*.xlsx в data/bloomberg/."""
    if not BLOOMBERG_DIR.exists():
        return None

    files = sorted(BLOOMBERG_DIR.glob("bbg_*.xlsx"))
    if not files:
        return None

    def _key(p: Path):
        m = re.search(r"bbg_(\d{4}-\d{2}-\d{2})", p.stem)
        return m.group(1) if m else p.stem

    files.sort(key=_key)
    return files[-1]


def _find_sheet(path: Path) -> str:
    """Ищет лист с нужными колонками. Приоритет — 'data'."""
    xl = pd.ExcelFile(path)

    if "data" in xl.sheet_names:
        return "data"

    for name in xl.sheet_names:
        try:
            probe = pd.read_excel(path, sheet_name=name, nrows=0)
            cols = {str(c).strip().lower() for c in probe.columns}
            if {"country", "metric", "ticker", "value"} <= cols:
                return name
        except Exception:
            continue

    # Фолбэк — первый лист
    print(f"[BLOOMBERG] Лист с нужными колонками не найден, беру: '{xl.sheet_names[0]}'")
    return xl.sheet_names[0]


def _read_xlsx(path: Path) -> pd.DataFrame:
    """
    Читает xlsx через openpyxl. Даты оставляет в формате DD.MM.YYYY,
    чтобы не терять день/месяц.
    """
    from openpyxl import load_workbook

    sheet = _find_sheet(path)
    print(f"[BLOOMBERG] Читаю лист: '{sheet}'")

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet]

    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return pd.DataFrame()

    # Заголовки
    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    df = pd.DataFrame(rows[1:], columns=header)

    # Приводим всё к строке, но даты — к DD.MM.YYYY
    def _fmt(v):
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            return v.strftime("%d.%m.%Y")
        return str(v).strip()

    for col in df.columns:
        df[col] = df[col].apply(_fmt)

    return df


def _parse_date(s: str) -> pd.Timestamp | None:
    """
    Парсит дату из строки. Понимает:
      - DD.MM.YYYY (12.10.2026)
      - YYYY-MM-DD (2026-10-12) — ISO
      - DD/MM/YYYY (12/10/2026)
    Возвращает Timestamp или None.
    """
    s = str(s).strip()
    if not s:
        return None

    # ISO-формат: 2026-10-12
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
        except Exception:
            pass

    # Русский: 12.10.2026
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return pd.Timestamp(year=y, month=mo, day=d)
        except Exception:
            pass

    # Слэш: 12/10/2026 (dayfirst)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return pd.Timestamp(year=y, month=mo, day=d)
        except Exception:
            pass

    # Общий fallback
    try:
        return pd.to_datetime(s, dayfirst=True).normalize()
    except Exception:
        return None


def fetch_bloomberg() -> pd.DataFrame:
    """
    Возвращает DataFrame с колонками:
        date, country, metric, value, period, source
    Только для строк, где ticker не пуст и value парсится в число.
    """
    path = _latest_file()
    if path is None:
        print("[BLOOMBERG] Нет файлов bbg_*.xlsx в data/bloomberg/")
        return pd.DataFrame()

    print(f"[BLOOMBERG] Файл: {path.name}")

    try:
        df = _read_xlsx(path)
    except Exception as e:
        print(f"[BLOOMBERG] Ошибка чтения {path.name}: {e}")
        return pd.DataFrame()

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        print(f"[BLOOMBERG] Нет колонок: {missing}")
        return pd.DataFrame()

    # Дата выгрузки — берём из первой непустой ячейки date
    export_date = None
    for v in df["date"]:
        d = _parse_date(v)
        if d is not None:
            export_date = d.normalize()
            break

    if export_date is None:
        print("[BLOOMBERG] Не удалось определить дату выгрузки")
        return pd.DataFrame()

    q = (export_date.month - 1) // 3 + 1
    period = f"Q{q} {export_date.year}"

    rows = []
    for _, r in df.iterrows():
        ticker = str(r.get("ticker", "") or "").strip()
        if not ticker or ticker.lower() in {"nan", "none", "-"}:
            continue

        country = str(r.get("country", "") or "").strip().upper()
        metric = str(r.get("metric", "") or "").strip().lower()
        if not country or not metric:
            continue

        raw_value = r.get("value")
        if raw_value is None or str(raw_value).strip() == "":
            continue

        s = str(raw_value).strip().replace("\u00a0", " ").replace(" ", "")
        s = s.replace(",", ".").replace("%", "")
        try:
            value = float(s)
        except ValueError:
            continue

        rows.append({
            "date": export_date,
            "country": country,
            "metric": metric,
            "value": value,
            "period": period,
            "source": "BBG",
        })

    if not rows:
        print("[BLOOMBERG] Нет валидных строк с данными")
        return pd.DataFrame()

    out = pd.DataFrame(rows).drop_duplicates(
        subset=["date", "country", "metric"], keep="last"
    ).sort_values(["country", "metric"]).reset_index(drop=True)

    print(f"[BLOOMBERG] Валидных строк: {len(out)}")
    return out


if __name__ == "__main__":
    df = fetch_bloomberg()
    if df.empty:
        print("Пусто.")
    else:
        print(df.to_string(index=False))
