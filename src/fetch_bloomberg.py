"""
Чтение ручных выгрузок Bloomberg Excel Add-in.

Файлы лежат в data/bloomberg/ под именем bbg_YYYY-MM-DD.xlsx.
Формат листа:
    country | metric | ticker | field | last_update | value | date | frequency

- last_update — дата последнего обновления тикера (BDP(ticker, "LAST_UPDATE")).
                Для квартальных данных это конец квартала (30.06.2026 → Q2 2026).
- date        — дата выгрузки (BTODAY в Excel).
"""

from pathlib import Path
import re
import pandas as pd
from config import DATA_DIR

BLOOMBERG_DIR = DATA_DIR / "bloomberg"

REQUIRED_COLS = {"country", "metric", "ticker", "value", "date", "last_update"}


def _latest_file() -> Path | None:
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
    return xl.sheet_names[0]


def _read_xlsx(path: Path) -> pd.DataFrame:
    """Читает xlsx через openpyxl, даты — строкой DD.MM.YYYY."""
    from openpyxl import load_workbook

    sheet = _find_sheet(path)
    print(f"[BLOOMBERG] Читаю лист: '{sheet}'")

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return pd.DataFrame()

    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    df = pd.DataFrame(rows[1:], columns=header)

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
    """DD.MM.YYYY / YYYY-MM-DD / DD/MM/YYYY → Timestamp."""
    s = str(s).strip()
    if not s:
        return None

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
        except Exception:
            pass

    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return pd.Timestamp(year=y, month=mo, day=d)
        except Exception:
            pass

    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return pd.Timestamp(year=y, month=mo, day=d)
        except Exception:
            pass

    try:
        return pd.to_datetime(s, dayfirst=True).normalize()
    except Exception:
        return None


def _last_update_to_period(dt: pd.Timestamp | None) -> str:
    """
    Конец квартала → строка 'QN YYYY'.
    30.06.2026 → 'Q2 2026'
    31.12.2025 → 'Q4 2025'
    """
    if dt is None:
        return ""
    month = dt.month
    q = (month - 1) // 3 + 1
    return f"Q{q} {dt.year}"


def fetch_bloomberg() -> pd.DataFrame:
    """
    Возвращает DataFrame: date, country, metric, value, period, source.
    period вычисляется из last_update (конец квартала).
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

    # Дата выгрузки — из первой непустой ячейки date
    export_date = None
    for v in df["date"]:
        d = _parse_date(v)
        if d is not None:
            export_date = d.normalize()
            break

    if export_date is None:
        print("[BLOOMBERG] Не удалось определить дату выгрузки")
        return pd.DataFrame()

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

        # Period — из last_update (конец квартала)
        last_update_dt = _parse_date(str(r.get("last_update", "") or ""))
        period = _last_update_to_period(last_update_dt)

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
