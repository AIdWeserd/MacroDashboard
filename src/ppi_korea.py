"""Historical Korean producer prices from UN Statistics Division MBS.

Series: Republic of Korea, Producer: domestic production, base 2020=100.
Source page: https://unstats.un.org/unsd/mbs/app/DataView.aspx

MoM and YoY are transparent calculations from two comparable, official
monthly index levels. No interpolation or mix with domestic supply PPI.

Run from Macro Dashboard root:
    python -m src.ppi_korea
"""

from __future__ import annotations

import math
import re
import sys
import time
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.eurostat_extra import save_eurostat_extra


URL = (
    "https://unstats.un.org/unsd/mbs/app/DataView.aspx"
    "?cid=410&p=A&tid=7&yearfrom=1997&yearto=2099"
)

START = pd.Period("2020-01", freq="M")
SOURCE = (
    "UN Statistics Division/MBS, Korea Producer: domestic production; "
    "расчёт по официальному индексу (2020=100)"
)

COLUMNS = [
    "country", "date", "metric", "value", "source", "unit", "adjustment"
]

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

MONTH_ABBREVIATIONS = "|".join(MONTHS)
OBSERVATION_RE = re.compile(
    rf"\b((?:19|20)\d{{2}})({MONTH_ABBREVIATIONS})\s+"
    r"(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"Price indices\s*-\s*Producer:\s*domestic production\b",
    re.IGNORECASE,
)
NEXT_SECTION_RE = re.compile(
    r"Price indices\s*-\s*Producer:",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": "MacroDashboard/1.0 (UN official statistics)",
    "Accept": "text/html,application/xhtml+xml",
}


def _fetch_html() -> str:
    """Fetch the public UN statistical table, retrying temporary errors."""
    for attempt in range(3):
        try:
            response = requests.get(
                URL, headers=HEADERS, timeout=(20, 75)
            )
            response.raise_for_status()

            destination = urlparse(response.url)
            if (
                destination.scheme != "https"
                or destination.hostname != "unstats.un.org"
            ):
                raise ValueError("UN MBS: redirected outside official host")

            if len(response.content) > 12_000_000:
                raise ValueError("UN MBS: response too large")

            if "html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("UN MBS: response is not HTML")

            return response.text

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            retry = (
                isinstance(exc, (requests.Timeout, requests.ConnectionError))
                and not isinstance(exc, requests.exceptions.SSLError)
            ) or status in {429, 500, 502, 503, 504}

            if not retry or attempt == 2:
                raise

            print(f"[WARN] KR/UN MBS: retry {attempt + 2}/3")
            time.sleep(1.5 * 2 ** attempt)

    raise RuntimeError("UN MBS: retry loop exhausted")


def _extract_levels(html: str) -> dict[pd.Period, float]:
    """Isolate ONLY the Korean domestic-production producer price series."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    if "Republic of Korea" not in text or "Producer price indices" not in text:
        raise ValueError("UN MBS: cannot confirm country and PPI table")

    headings = list(SECTION_RE.finditer(text))
    if len(headings) != 1:
        raise ValueError(
            f"UN MBS: expected one domestic-production section, "
            f"got {len(headings)}"
        )

    start = headings[0].end()
    following = NEXT_SECTION_RE.search(text, start)
    end = following.start() if following else len(text)
    section = text[start:end]

    if not re.search(r"Republic\s+of\s+Korea\s+Period\s+Data", section):
        raise ValueError("UN MBS: domestic production geography mismatch")

    # The page has a legacy '2010=100' heading, but the footnote
    # explicitly establishes the current data base as 2020=100.
    if not re.search(r"3328\s*/\s*Base:\s*2020\s*=\s*100\b", section):
        raise ValueError("UN MBS: current 2020=100 index base not confirmed")

    average = re.search(r"\b2020YEAR\s+(\d+(?:\.\d+)?)\b", section)
    if not average or abs(float(average.group(1)) - 100.0) > 0.05:
        raise ValueError("UN MBS: 2020 average/base cross-check failed")

    observations: dict[pd.Period, float] = {}

    for match in OBSERVATION_RE.finditer(section):
        year, month_code, raw_value = match.groups()
        month = MONTHS[month_code.upper()]
        period = pd.Period(f"{year}-{month:02d}", freq="M")
        value = float(raw_value)

        if not math.isfinite(value) or not 10 < value < 1000:
            raise ValueError(f"UN MBS: implausible index for {period}")
        if period in observations:
            raise ValueError(f"UN MBS: duplicate index period {period}")

        observations[period] = value

    if len([period for period in observations if period >= START]) < 60:
        raise ValueError("UN MBS: insufficient history since January 2020")

    if not all(
        pd.Period(f"2019-{month:02d}", freq="M") in observations
        for month in range(1, 13)
    ):
        raise ValueError("UN MBS: 2019 index reference months missing")

    return observations


def parse_korea_ppi(html: str) -> pd.DataFrame:
    """Calculate simple YoY/MoM from comparable published index levels."""
    levels = _extract_levels(html)
    latest = max(period for period in levels if period >= START)
    now = pd.Period(pd.Timestamp.now(), freq="M")

    if latest > now:
        raise ValueError(f"UN MBS: future month {latest}")

    rows = []
    gaps = []

    for period in pd.period_range(START, latest, freq="M"):
        for metric, lag in (("ppi_mom", 1), ("ppi_yoy", 12)):
            older = period - lag
            if period not in levels or older not in levels:
                gaps.append(f"{period}/{metric}")
                continue

            # Exactly one division of two values of the same official series.
            change = round((levels[period] / levels[older] - 1.0) * 100, 1)
            rows.append((
                "KR", period.start_time, metric, change,
                SOURCE, "%", "not specified by UN MBS",
            ))

    result = pd.DataFrame(rows, columns=COLUMNS)

    for metric in ("ppi_yoy", "ppi_mom"):
        if (result.metric == metric).sum() < 60:
            raise ValueError(f"UN MBS: insufficient {metric} observations")

    if result.duplicated(["country", "date", "metric"]).any():
        raise ValueError("UN MBS: duplicate saved keys")

    result = result.sort_values(["date", "metric"]).reset_index(drop=True)
    result.attrs["source_issues"] = tuple(gaps)
    return result


def fetch_korea_ppi() -> pd.DataFrame:
    return parse_korea_ppi(_fetch_html())


def run() -> int:
    try:
        frame = fetch_korea_ppi()
        issues = tuple(frame.attrs.get("source_issues", ()))
        save_eurostat_extra(frame)

        for metric, part in frame.groupby("metric"):
            print(
                f"[OK] KR/{metric}: {len(part)} months; "
                f"{part.date.min():%Y-%m} ... {part.date.max():%Y-%m}; "
                "UN MBS, calculated from official index"
            )

        if issues:
            print("[WARN] KR/PPI missing: " + ", ".join(issues))
            return 1

        print("[SUMMARY] KR/PPI historical YoY and MoM updated")
        return 0

    except (requests.RequestException, ValueError, OSError, RuntimeError) as exc:
        print(f"[ERROR] KR/PPI: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(run())
