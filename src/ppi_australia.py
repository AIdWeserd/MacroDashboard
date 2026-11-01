"""Official Australian Producer Price Index, ABS Table 1 (642701.xlsx).

Final demand (excluding exports), original quarterly series:
  A2314866J -- percentage change from previous quarter (ppi_qoq)
  A2314867K -- percentage change from corresponding quarter (ppi_yoy)

Unlike monthly PPI, these are QUARTERLY changes; never write as ppi_mom.
All values are taken directly from published ABS rates, not calculated.

Run from the Macro Dashboard project root:
  python -m src.ppi_australia --dry-run
  python -m src.ppi_australia
  python -m src.ppi_australia --dry-run --xlsx C:\\path\\to\\642701.xlsx
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
import time
import zipfile
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from openpyxl import load_workbook

from config import DB_PATH

URL = (
    "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
    "producer-price-indexes-australia/latest-release/642701.xlsx"
)
START = pd.Period("2020Q1", freq="Q")
MIN_LATEST = pd.Period("2026Q2", freq="Q")
TABLE = "official_eurostat_extra"
COLUMNS = ["country", "date", "metric", "value", "source", "unit", "adjustment"]
SOURCES = {
    "ppi_qoq": ("A2314866J", "previous quarter"),
    "ppi_yoy": ("A2314867K", "corresponding quarter of previous year"),
}
SOURCE = "ABS 6427.0 Table 1, Final demand excl exports; published ABS %"
HEADERS = {"User-Agent": "MacroDashboard/1.0 (ABS official statistics)"}
CONTROLS = {
    "2025Q4": (0.8, 3.5),
    "2026Q1": (0.4, 3.0),
    "2026Q2": (1.3, 3.6),
}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
MAX_XLSX_BYTES = 3_000_000


def _get() -> bytes:
    for attempt in range(3):
        try:
            response = requests.get(URL, timeout=(20, 90), headers=HEADERS)
            response.raise_for_status()
            final = urlparse(response.url)
            if final.scheme != "https" or final.hostname not in ("www.abs.gov.au", "abs.gov.au"):
                raise ValueError("ABS: download redirected away from official site")
            if len(response.content) > MAX_XLSX_BYTES:
                raise ValueError("ABS: unexpectedly large spreadsheet")
            return response.content
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retry = ((isinstance(exc, (requests.Timeout, requests.ConnectionError))
                     and not isinstance(exc, requests.exceptions.SSLError))
                     or status in (429, 500, 502, 503, 504))
            if not retry or attempt == 2:
                raise
            print(f"[WARN] ABS: retry {attempt + 2}/3")
            time.sleep(2 ** attempt)
    raise RuntimeError("ABS request failed")


def _quarter(value: object) -> pd.Period | None:
    """ABS period labels (e.g. 'Jun-2026', datetime, '2026-Q2')."""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        stamp = pd.Timestamp(value)
        if stamp.month not in (3, 6, 9, 12):
            return None
        return stamp.to_period("Q")
    if not isinstance(value, str):
        return None
    label = re.sub(r"\s+", " ", value.strip().lower())
    match = re.fullmatch(r"(19\d{2}|20\d{2})\s*[-/]?\s*q([1-4])", label)
    if match:
        return pd.Period(f"{match.group(1)}Q{match.group(2)}", freq="Q")
    match = re.fullmatch(r"(19\d{2}|20\d{2})[-/](\d{1,2})(?:[-/]\d{1,2})?", label)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if month in (3, 6, 9, 12):
            return pd.Period(f"{year}-{month:02d}", freq="M").asfreq("Q")
    match = re.fullmatch(r"([a-z]{3,4})[- /]*(\d{2,4})", label)
    if not match or match.group(1) not in MONTHS:
        return None
    month = MONTHS[match.group(1)]
    if month not in (3, 6, 9, 12):
        return None
    year = int(match.group(2))
    if year < 100:
        year += 1900 if year >= 70 else 2000  # 1999 must not become 2099
    return pd.Period(f"{year}-{month:02d}", freq="M").asfreq("Q")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace("−", "-").replace(",", ""))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number) or not (-100 < number < 300):
        raise ValueError(f"ABS: invalid published percentage: {value!r}")
    return number


def _read_xlsx(blob: bytes):
    if len(blob) > MAX_XLSX_BYTES or not blob.startswith(b"PK\x03\x04"):
        raise ValueError("ABS: invalid or oversized XLSX")
    # Reject decompression bombs before passing the workbook to openpyxl.
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        members = archive.infolist()
        if len(members) > 250 or sum(e.file_size for e in members) > 20_000_000:
            raise ValueError("ABS: unexpected XLSX archive size")
    return load_workbook(BytesIO(blob), read_only=True, data_only=True)


def _normal(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _series_columns(workbook) -> dict[str, tuple[object, int, int]]:
    """Identify the official series from the Series ID metadata row on Data*.

    ABS documents a stable metadata layout on Data sheets, with ten header
    rows and a Series ID row. Do not guess columns from matching numbers.
    """
    found = {}
    target_ids = {series_id: metric for metric, (series_id, _) in SOURCES.items()}
    for sheet in workbook.worksheets:
        if not re.fullmatch(r"Data\d+", sheet.title, re.IGNORECASE):
            continue
        top = list(sheet.iter_rows(min_row=1, max_row=min(30, sheet.max_row), values_only=True))
        headings = {}
        for row_idx, row in enumerate(top, 1):
            if row and _normal(row[0]) in {
                "series description", "series type", "series id", "unit",
                "data type", "frequency", "freq", "collection month",
            }:
                headings[_normal(row[0])] = row_idx
        idrow = headings.get("series id")
        if not idrow:
            continue
        row = top[idrow - 1]
        for col_idx, value in enumerate(row, 1):
            series_id = str(value).strip().upper()
            if series_id not in target_ids:
                continue
            metric = target_ids[series_id]
            if metric in found:
                raise ValueError(f"ABS: duplicate official series ID {series_id}")
            metadata = {
                name: str(top[index - 1][col_idx - 1] or "").strip()
                for name, index in headings.items()
                if col_idx <= len(top[index - 1])
            }
            description = metadata.get("series description", "")
            # Series ID is the unique ABS key. A blank description in the
            # worksheet is not evidence of a wrong series: ABS documents that
            # metadata text can vary, while Series IDs remain stable.
            # Still reject a nonempty, clearly unrelated description.
            if description and "final demand" not in _normal(description):
                raise ValueError(f"ABS: unexpected series description for {series_id}: {description}")
            frequency = metadata.get("frequency", metadata.get("freq", ""))
            if frequency and _normal(frequency) not in ("quarter", "quarterly"):
                raise ValueError(f"ABS: wrong frequency for {series_id}: {frequency}")
            unit = metadata.get("unit", "")
            if unit and "percent" not in unit.lower() and unit.strip() != "%":
                raise ValueError(f"ABS: wrong unit for {series_id}: {unit}")
            series_type = metadata.get("series type", "")
            if series_type and _normal(series_type) != "original":
                raise ValueError(f"ABS: wrong adjustment for {series_id}: {series_type}")
            found[metric] = (sheet, col_idx, idrow)

    missing = set(SOURCES) - set(found)
    if missing:
        raise ValueError(f"ABS: official series IDs missing in Data sheets: {sorted(missing)}")
    return found


def _series_values(sheet, column: int, idrow: int) -> dict[pd.Period, float]:
    values = {}
    # ABS Data sheets contain dates in column A, immediately below metadata.
    for cells in sheet.iter_rows(min_row=idrow + 1, values_only=True):
        if not cells:
            continue
        period = _quarter(cells[0])
        if period is None or period < START:
            continue
        if period in values:
            raise ValueError(f"ABS: duplicate quarter {period} in {sheet.title}")
        raw = cells[column - 1] if len(cells) >= column else None
        number = _number(raw)
        if number is None:
            raise ValueError(f"ABS: missing official value for {period} in {sheet.title}/{column}")
        values[period] = number
    return values


def parse_abs_workbook(blob: bytes) -> pd.DataFrame:
    """Extract published quarterly values by stable ABS IDs, validate, format."""
    workbook = _read_xlsx(blob)
    try:
        locations = _series_columns(workbook)
        series = {
            metric: _series_values(*location)
            for metric, location in locations.items()
        }
    finally:
        workbook.close()

    periods = set(series["ppi_qoq"])
    if periods != set(series["ppi_yoy"]):
        raise ValueError("ABS: QoQ and YoY have different quarterly coverage")
    if not periods or max(periods) < MIN_LATEST:
        raise ValueError("ABS: workbook has no published June 2026 quarter")
    if max(periods) > pd.Period(pd.Timestamp.now(), freq="Q"):
        raise ValueError("ABS: future quarter in workbook")
    expected = set(pd.period_range(START, max(periods), freq="Q"))
    if periods != expected:
        raise ValueError(f"ABS: gaps/unexpected quarters: {sorted(map(str, expected ^ periods))}")

    for key, (qoq, yoy) in CONTROLS.items():
        period = pd.Period(key, freq="Q")
        if (abs(series["ppi_qoq"][period] - qoq) > 0.051 or
                abs(series["ppi_yoy"][period] - yoy) > 0.051):
            raise ValueError(f"ABS: published control mismatch in {period}")

    rows = []
    for period in sorted(periods):
        for metric in ("ppi_qoq", "ppi_yoy"):
            rows.append((
                "AU", period.end_time.normalize(), metric, series[metric][period],
                f"{SOURCE} ({SOURCES[metric][0]})", "%", "Original (quarterly)",
            ))
    return pd.DataFrame(rows, columns=COLUMNS).sort_values(
        ["date", "metric"]
    ).reset_index(drop=True)


def fetch_australia_ppi(*, xlsx: str | Path | None = None) -> pd.DataFrame:
    if xlsx is None:
        print(f"[ABS] GET {URL}")
        blob = _get()
    else:
        print(f"[ABS] Local XLSX: {xlsx} (check trusted source)")
        blob = Path(xlsx).read_bytes()
    return parse_abs_workbook(blob)


def save_australia_ppi(frame: pd.DataFrame) -> None:
    """Preserve other country metrics; ppi_qoq is not in Eurostat SERIES."""
    if (frame.empty or set(frame.metric) != set(SOURCES)
            or set(frame.country) != {"AU"}
            or frame[COLUMNS].isna().any().any()
            or frame.duplicated(["country", "date", "metric"]).any()):
        raise ValueError("ABS: refusing incomplete or non-Australian data")
    with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as con:
        with con:
            con.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                country TEXT NOT NULL, date TEXT NOT NULL,
                metric TEXT NOT NULL, value REAL NOT NULL,
                source TEXT NOT NULL, unit TEXT NOT NULL,
                adjustment TEXT NOT NULL,
                PRIMARY KEY(country, date, metric))""")
            con.executemany(
                f"""INSERT INTO {TABLE}
                    (country,date,metric,value,source,unit,adjustment)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(country,date,metric) DO UPDATE SET
                    value=excluded.value,source=excluded.source,
                    unit=excluded.unit,adjustment=excluded.adjustment""",
                [(str(r.country), pd.Timestamp(r.date).strftime("%Y-%m-%d"),
                  str(r.metric), float(r.value), str(r.source), str(r.unit),
                  str(r.adjustment)) for r in frame.itertuples(index=False)],
            )
    print(f"[SAVE] {TABLE}: {len(frame)} AU published observations updated")


def run(*, dry_run: bool = False, xlsx: str | None = None) -> int:
    try:
        frame = fetch_australia_ppi(xlsx=xlsx)
        for metric, subset in frame.groupby("metric"):
            last = subset.iloc[-1]
            print(f"[OK] AU/{metric}: {len(subset)} quarters, "
                  f"{subset.date.min():%Y-%m} .. {last.date:%Y-%m}; "
                  f"last={last.value:+.1f}%")
        if dry_run:
            print("[DRY RUN] No SQLite writes")
            return 0
        save_australia_ppi(frame)
        return 0
    except (ValueError, OSError, zipfile.BadZipFile, requests.RequestException,
            KeyError, TypeError) as exc:
        print(f"[ERROR] AU/ABS: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ABS Australia quarterly PPI")
    parser.add_argument("--dry-run", action="store_true", help="no database writes")
    parser.add_argument("--xlsx", help="use previously downloaded official 642701.xlsx")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run, xlsx=args.xlsx))
