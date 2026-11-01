"""Singapore: historical SMPPI YoY and MoM from official SingStat levels.

Official series: Singapore Manufactured Products Price Index, Overall Items,
2023=100, MONTHLY table M213431 (NOT quarterly M213621 and NOT DSPI).

The API publishes rounded index levels. Percentage changes calculated from
those levels can differ from DOS's independently published percentage rates
by 0.1 percentage point; the source field explicitly identifies this method.

Commands (from Macro Dashboard root):
    python -m src.ppi_singapore --dry-run  # NO SQLite writes
    python -m src.ppi_singapore            # validated upsert
"""
from __future__ import annotations

import re
import sys
import time
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

import pandas as pd
import requests

from src.eurostat_extra import save_eurostat_extra

TABLE_ID = "M213431"  # MONTHLY. M213621 is QUARTERLY!
API = f"https://tablebuilder.singstat.gov.sg/api/table/tabledata/{TABLE_ID}"
START = pd.Period("2020-01", freq="M")
BASE_YEAR = 2023
COLS = ["country", "date", "metric", "value", "source", "unit", "adjustment"]
SOURCE = (
    "SingStat DOS / M213431, monthly SMPPI Overall Items (2023=100); "
    "расчёт из опубликованных округлённых месячных индексов"
)
HEADERS = {
    "User-Agent": "MacroDashboard/1.0 (official SingStat data)",
    "Accept": "application/json",
}
MONTHS = {s.lower(): n for n, s in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
     "Sep", "Oct", "Nov", "Dec"), start=1,
)}
# Published ALL-ITEMS index-level checks, Aug 2026 release vintage.
# Tolerance is for later ordinary data revisions; never substitute hardcoded
# controls for API observations.
CONTROLS = {
    pd.Period("2026-06", freq="M"): 132.9,
    pd.Period("2026-07", freq="M"): 136.2,
    pd.Period("2026-08", freq="M"): 142.2,
}


def _get_json() -> dict:
    """Read from the exact HTTPS Singapore-government API, without a key."""
    for attempt in range(3):
        try:
            response = requests.get(API, headers=HEADERS, timeout=(20, 75))
            response.raise_for_status()
            final = urlparse(response.url)
            if (final.scheme, final.hostname) != (
                "https", "tablebuilder.singstat.gov.sg"
            ):
                raise ValueError("SingStat: redirected outside official API")
            if len(response.content) > 10_000_000:
                raise ValueError("SingStat: unexpectedly large response")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("SingStat: unexpected JSON root")
            return payload
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            temporary = (
                (isinstance(exc, (requests.Timeout, requests.ConnectionError))
                 and not isinstance(exc, requests.exceptions.SSLError))
                or status in (429, 500, 502, 503, 504)
            )
            if not temporary or attempt == 2:
                raise
            time.sleep(1.5 * (2 ** attempt))
    raise RuntimeError("SingStat: unreachable")


def _month(key: object) -> pd.Period | None:
    """Accept only exact API month labels such as '2026 Aug'."""
    if not isinstance(key, str):
        return None
    match = re.fullmatch(r"\s*(20\d{2})\s+([A-Za-z]{3})\s*", key)
    if not match or match.group(2).lower() not in MONTHS:
        return None
    year, mon = int(match.group(1)), MONTHS[match.group(2).lower()]
    return pd.Period(f"{year}-{mon:02d}", freq="M")


def _levels(payload: dict) -> dict[pd.Period, Decimal]:
    """Select ONE exact overall SMPPI series; reject non-oil/component rows."""
    data = payload.get("Data")
    if not isinstance(data, dict) or not isinstance(data.get("row"), list):
        raise ValueError("SingStat: Data.row not present; API layout changed")
    # Validate the table identity and frequency when returned by the API.
    # The old M213621 endpoint is quarterly, so its observations cannot
    # establish month-on-month rates, even if the series name is identical.
    data_id = data.get("id")
    if data_id is not None and str(data_id).upper() != TABLE_ID:
        raise ValueError(f"SingStat: wrong table ID {data_id!r}, expected {TABLE_ID}")
    frequency = data.get("frequency")
    if frequency is not None and str(frequency).strip().casefold() != "monthly":
        raise ValueError(f"SingStat: expected monthly table, got {frequency!r}")
    rows = data["row"]
    # SingStat labels the aggregate as "... - Overall Items" in M213621.
    # The earlier "All Items" label is also supported for API compatibility.
    # Exact matching prevents accidentally selecting the "Non-Oil ..." series.
    official_names = {
        "all items",
        "overall items",
        "singapore manufactured products price index - overall items",
    }
    candidates = [
        row for row in rows
        if isinstance(row, dict)
        and re.sub(r"\s+", " ", str(row.get("rowText", "")).strip()).casefold()
        in official_names
    ]
    if len(candidates) != 1:
        names = [str(r.get("rowText", ""))[:65] for r in rows[:12]
                 if isinstance(r, dict)]
        raise ValueError(
            f"SingStat M213431: expected exactly one overall SMPPI row, "
            f"got {len(candidates)}; available rows: {names}"
        )
    columns = candidates[0].get("columns")
    if not isinstance(columns, list):
        raise ValueError("SingStat: overall SMPPI columns are missing")

    levels: dict[pd.Period, Decimal] = {}
    for cell in columns:
        if not isinstance(cell, dict):
            raise ValueError("SingStat: malformed observation")
        period = _month(cell.get("key"))
        if period is None:
            continue  # other frequencies such as annual/quarterly are excluded
        raw = cell.get("value")
        if raw is None or str(raw).strip().lower() in ("na", "-", ""):
            continue
        try:
            value = Decimal(str(raw).strip().replace(",", ""))
        except ArithmeticError as exc:
            raise ValueError(f"SingStat: invalid value for {period}") from exc
        if not value.is_finite() or not (Decimal(10) < value < Decimal(1000)):
            raise ValueError(f"SingStat: implausible level for {period}")
        if period in levels:
            raise ValueError(f"SingStat: duplicate overall SMPPI month {period}")
        levels[period] = value

    latest = max(levels, default=None)
    if latest is None or latest < pd.Period("2026-08", freq="M"):
        raise ValueError("SingStat M213431: monthly source lacks confirmed 2026-08 release")
    if latest > pd.Period(pd.Timestamp.now(), freq="M"):
        raise ValueError(f"SingStat: future observation {latest}")

    # The published 2023=100 reference is the mean of the 12 months.
    year_values = [levels.get(pd.Period(f"{BASE_YEAR}-{n:02d}", freq="M"))
                   for n in range(1, 13)]
    if any(v is None for v in year_values):
        raise ValueError("SingStat: missing 2023 reference-year observations")
    base_average = sum(year_values) / 12
    if abs(base_average - 100) > Decimal("0.2"):
        raise ValueError(f"SingStat: wrong index/base, 2023 average={base_average}")

    for period, expected in CONTROLS.items():
        actual = levels.get(period)
        if actual is None or abs(actual - Decimal(str(expected))) > Decimal("0.6"):
            raise ValueError(
                f"SingStat: control {period} expected about {expected}; "
                f"API returned {actual}; not saving"
            )

    # A missing earlier month must not silently turn into a fabricated 0%.
    history_start = START - 12
    missing = [str(p) for p in pd.period_range(history_start, latest, freq="M")
               if p not in levels]
    if missing:
        raise ValueError("SingStat: missing index months: " + ", ".join(missing[:15]))
    return levels


def _change(current: Decimal, previous: Decimal) -> float:
    if previous <= 0:
        raise ValueError("SingStat: nonpositive base level")
    result = (current / previous - 1) * 100
    if not result.is_finite() or abs(result) > 300:
        raise ValueError("SingStat: out-of-range percentage change")
    return float(result.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def parse_singapore_ppi(payload: dict) -> pd.DataFrame:
    levels = _levels(payload)
    latest = max(levels)
    records = []
    for period in pd.period_range(START, latest, freq="M"):
        for metric, lag in (("ppi_mom", 1), ("ppi_yoy", 12)):
            records.append((
                "SG", period.start_time, metric,
                _change(levels[period], levels[period - lag]),
                SOURCE, "%", "NSA; ratio of rounded index levels",
            ))
    result = pd.DataFrame(records, columns=COLS)
    expected = len(pd.period_range(START, latest, freq="M"))
    if (len(result) != expected * 2 or
            result.duplicated(["country", "date", "metric"]).any()):
        raise ValueError("SingStat: unexpected number of observations")
    return result.sort_values(["date", "metric"]).reset_index(drop=True)


def fetch_singapore_ppi() -> pd.DataFrame:
    return parse_singapore_ppi(_get_json())


def run(*, dry_run: bool = False) -> int:
    try:
        frame = fetch_singapore_ppi()
        for metric, part in frame.groupby("metric"):
            print(f"[OK] SG/{metric}: {len(part)} observations, "
                  f"{part.date.min():%Y-%m} to {part.date.max():%Y-%m}")
        print("[INFO] Rates computed from rounded DOS indices; "
              "they can differ from separately published rates by 0.1 p.p.")
        if dry_run:
            print("[DRY RUN] SQLite not modified")
            return 0
        save_eurostat_extra(frame)
        print("[SUMMARY] SG SMPPI saved to official_eurostat_extra")
        return 0
    except (ValueError, TypeError, ArithmeticError, requests.RequestException,
            OSError, RuntimeError) as exc:
        print(f"[ERROR] SG/SMPPI: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--dry-run"]):
        print("Usage: python -m src.ppi_singapore [--dry-run]")
        sys.exit(2)
    sys.exit(run(dry_run="--dry-run" in sys.argv[1:]))
