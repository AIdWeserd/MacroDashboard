
"""Historical official producer-price changes: US BLS and Japan BoJ.

Reads ready-made percentages, never derives MoM/YoY from index levels.
The existing 'official_eurostat_extra' table is reused for ppi_yoy/ppi_mom.
API secret is loaded exclusively from config.BLS_API_KEY.

Run: python -m src.ppi_national
"""

from __future__ import annotations

import re
import sys
import time
from io import BytesIO
from urllib.parse import urljoin, urlparse

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

from config import BLS_API_KEY
from src.eurostat_extra import load_eurostat_extra, save_eurostat_extra


START_YEAR = 2020

BLS_API = (
    "https://api.bls.gov/publicAPI/v2/timeseries/data/"
)

BLS_SERIES = {
    "WPUFD4": ("ppi_yoy", "12", "NSA"),
    "WPSFD4": ("ppi_mom", "1", "SA"),
}

BOJ_HISTORY = (
    "https://www.stat-search.boj.or.jp/"
    "ssi/mtshtml/pr01_m_1_en.html"
)

BOJ_RELEASES = (
    "https://www.boj.or.jp/en/statistics/"
    "pi/cgpi_release/index.htm"
)

BOJ_PDF_PATTERN = re.compile(
    r"/cgpi(\d{2})(0[1-9]|1[0-2])\.pdf$",
    re.I,
)

COLS = [
    "country",
    "date",
    "metric",
    "value",
    "source",
    "unit",
    "adjustment",
]

RETRY_STATUS = {
    429, 500, 502, 503, 504
}

HEADERS = {
    "User-Agent": (
        "MacroDashboard/1.0 "
        "(official statistical data)"
    )
}


def _numeric(value: object) -> float:
    raw = (
        str(value)
        .strip()
        .replace("−", "-")
        .replace(",", "")
    )

    if raw in {
        "", "-", "—", "NA", "ND", "N/A", "None"
    }:
        raise ValueError("Value is missing")

    number = float(raw)

    if not (-100.0 < number < 100.0):
        raise ValueError(
            "Published percentage is not finite "
            "or outside expected range"
        )

    return number


def _frame(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows,
        columns=COLS,
    )

    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(
        frame["date"],
        errors="raise",
    )

    if frame.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "Duplicate observation within "
            "official source response"
        )

    return (
        frame.sort_values(
            ["country", "date", "metric"]
        )
        .reset_index(drop=True)
    )


def _http_get(
    url: str,
    *,
    read_timeout: int = 60,
) -> requests.Response:

    for attempt in range(1, 4):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=(20, read_timeout),
            )

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            transient = (
                (
                    isinstance(
                        exc,
                        (
                            requests.Timeout,
                            requests.ConnectionError,
                        ),
                    )
                    and not isinstance(
                        exc,
                        requests.exceptions.SSLError,
                    )
                )
                or status in RETRY_STATUS
            )

            if not transient or attempt == 3:
                raise

            time.sleep(
                1.5 * (2 ** (attempt - 1))
            )

    raise AssertionError("Unreachable")


def _bls_post(payload: dict) -> dict:
    for attempt in range(1, 4):
        try:
            response = requests.post(
                BLS_API,
                json=payload,
                headers=HEADERS,
                timeout=(20, 90),
            )

            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            transient = (
                (
                    isinstance(
                        exc,
                        (
                            requests.Timeout,
                            requests.ConnectionError,
                        ),
                    )
                    and not isinstance(
                        exc,
                        requests.exceptions.SSLError,
                    )
                )
                or status in RETRY_STATUS
            )

            if not transient or attempt == 3:
                raise

            time.sleep(
                1.5 * (2 ** (attempt - 1))
            )

    raise AssertionError("Unreachable")


# =====================================================
# США: BLS API v2, история с января 2020 года
# =====================================================

def parse_bls_history(
    payload: dict,
) -> pd.DataFrame:
    """Use BLS calculations.pct_changes, not index values."""

    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(
            "BLS API request status: "
            f"{payload.get('status')!r}"
        )

    series = (
        payload.get("Results", {})
        .get("series", [])
    )

    by_id = {
        item.get("seriesID"): item.get("data", [])
        for item in series
    }

    if not set(BLS_SERIES).issubset(by_id):
        raise ValueError(
            "BLS response is missing expected "
            "Final Demand series"
        )

    today = pd.Timestamp.now().normalize()
    rows = []

    for series_id, (
        metric,
        change_period,
        adjustment,
    ) in BLS_SERIES.items():

        for observation in by_id[series_id]:
            period = str(
                observation.get("period", "")
            )

            if not re.fullmatch(
                r"M(0[1-9]|1[0-2])",
                period,
            ):
                continue

            try:
                year = int(observation["year"])

                date = pd.Timestamp(
                    year,
                    int(period[1:]),
                    1,
                )

            except (
                ValueError,
                TypeError,
                KeyError,
            ):
                continue

            if year < START_YEAR or date > today:
                continue

            changes = (
                (observation.get("calculations") or {})
                .get("pct_changes")
                or {}
            )

            raw = changes.get(change_period)

            if (
                raw is None
                or str(raw).strip() in {
                    "", "-", "N/A"
                }
            ):
                continue

            rows.append(
                (
                    "US",
                    date,
                    metric,
                    _numeric(raw),
                    "BLS/Final Demand",
                    "%",
                    adjustment,
                )
            )

    result = _frame(rows)

    for metric in (
        "ppi_yoy",
        "ppi_mom",
    ):
        if (
            result.empty
            or (result.metric == metric).sum() < 12
        ):
            raise ValueError(
                "BLS supplied insufficient published "
                f"{metric} history"
            )

    return result


def fetch_us_history() -> pd.DataFrame:
    """Use the key already loaded in config.py."""

    if not BLS_API_KEY or not BLS_API_KEY.strip():
        raise ValueError(
            "BLS_API_KEY is empty in config.py / .env"
        )

    year = pd.Timestamp.now().year

    payload = {
        "seriesid": list(BLS_SERIES),
        "startyear": str(START_YEAR - 1),
        "endyear": str(year),
        "calculations": True,
        "registrationkey": BLS_API_KEY,
    }

    return parse_bls_history(
        _bls_post(payload)
    )


# =====================================================
# ЯПОНИЯ: исторический PPI YoY из BoJ
# =====================================================

def parse_boj_yoy_history(
    html: str,
) -> pd.DataFrame:
    """Read the published CGPI all-commodities YoY series."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    description = soup.get_text(
        " ",
        strip=True,
    )

    if (
        "Producer Price Index" not in description
        or "Year-on-year change" not in description
        or "PRCG20_2200000000%" not in description
    ):
        raise ValueError(
            "BoJ CGPI historic table header changed"
        )

    today = pd.Timestamp.now().normalize()
    rows = []

    for tr in soup.select("tr"):
        cells = [
            x.get_text(" ", strip=True)
            for x in tr.find_all(
                ["th", "td"],
                recursive=False,
            )
        ]

        if (
            len(cells) < 2
            or not re.fullmatch(
                r"20\d{2}/(0[1-9]|1[0-2])",
                cells[0],
            )
        ):
            continue

        year, month = (
            int(x)
            for x in cells[0].split("/")
        )

        date = pd.Timestamp(
            year, month, 1
        )

        if year < START_YEAR or date > today:
            continue

        try:
            yoy = _numeric(cells[1])
        except ValueError:
            continue

        rows.append(
            (
                "JP",
                date,
                "ppi_yoy",
                yoy,
                "BoJ/CGPI",
                "%",
                "NSA",
            )
        )

    result = _frame(rows)

    if len(result) < 12:
        raise ValueError(
            "BoJ historic CGPI YoY table returned "
            "insufficient monthly data"
        )

    return result


# =====================================================
# ЯПОНИЯ: история PPI MoM из опубликованных PDF
# =====================================================

def _boj_pdf_catalog(
    html: str,
) -> list[tuple[pd.Timestamp, str]]:

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = {}

    for link in soup.select("a[href]"):
        url = urljoin(
            BOJ_RELEASES,
            link["href"],
        )

        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname not in {
                "boj.or.jp",
                "www.boj.or.jp",
            }
        ):
            continue

        match = BOJ_PDF_PATTERN.search(
            parsed.path
        )

        if match is None:
            continue

        date = pd.Timestamp(
            2000 + int(match.group(1)),
            int(match.group(2)),
            1,
        )

        if (
            START_YEAR <= date.year
            and date <= pd.Timestamp.now().normalize()
        ):
            results[date] = url

    if not results:
        raise ValueError(
            "BoJ official release catalog has "
            "no usable monthly CGPI PDFs"
        )

    return sorted(
        results.items()
    )


def parse_boj_mom_pdf(
    pdf_data: bytes,
    date: pd.Timestamp,
) -> pd.DataFrame:
    """Use the published PPI All commodities MoM."""

    if (
        not pdf_data.startswith(b"%PDF-")
        or len(pdf_data) > 6_000_000
    ):
        raise ValueError(
            "Invalid or oversized BoJ CGPI PDF"
        )

    with pdfplumber.open(
        BytesIO(pdf_data)
    ) as document:
        if len(document.pages) < 3:
            raise ValueError(
                "BoJ CGPI PDF has unexpected page count"
            )

        cover = (
            document.pages[0].extract_text()
            or ""
        )

        table = (
            document.pages[2].extract_text(
                layout=False
            )
            or ""
        )

    if (
        "Producer Price Index" not in cover
        or str(date.year) not in cover
    ):
        raise ValueError(
            "BoJ CGPI PDF release title/period "
            "does not match"
        )

    if "Producer Price Index" not in table:
        raise ValueError(
            "BoJ PPI table is missing"
        )

    line = next(
        (
            x.strip()
            for x in table.splitlines()
            if re.match(
                r"^\s*All commodities\s+1,?000\.0\b",
                x,
            )
        ),
        None,
    )

    if line is None:
        raise ValueError(
            "BoJ all-commodities row is missing"
        )

    rest = re.split(
        r"\b1,?000\.0\b",
        line,
        maxsplit=1,
    )[1]

    numbers = re.findall(
        r"(?<![\d.])[-−]?\d+(?:\.\d+)?(?![\d.])",
        re.sub(
            r"\br\b",
            "",
            rest,
        ),
    )

    if len(numbers) != 6:
        raise ValueError(
            "BoJ published MoM column layout "
            "is unrecognized"
        )

    # Порядок столбцов:
    # Index now / previous,
    # Published MoM now / previous,
    # Published YoY now / previous.
    mom = _numeric(numbers[2])

    return _frame(
        [
            (
                "JP",
                date,
                "ppi_mom",
                mom,
                "BoJ/CGPI",
                "%",
                "NSA",
            )
        ]
    )


# =====================================================
# Сохранение и обновление истории
# =====================================================

def _save_with_report(
    label: str,
    values: pd.DataFrame,
) -> None:

    if values.empty:
        raise ValueError(
            f"{label}: no official data to save"
        )

    save_eurostat_extra(values)

    print(
        f"[OK] {label}: "
        f"{len(values)} observations, "
        f"{values.date.nunique()} months; "
        f"{values.date.min():%Y-%m} ... "
        f"{values.date.max():%Y-%m}"
    )


def _update_japan_mom() -> bool:
    """Backfill missing months and refresh the newest three."""

    catalog = _boj_pdf_catalog(
        _http_get(BOJ_RELEASES).text
    )

    saved = load_eurostat_extra()

    if not saved.empty:
        seen = set(
            pd.to_datetime(
                saved.loc[
                    (saved.country == "JP")
                    & (saved.metric == "ppi_mom"),
                    "date",
                ]
            ).dt.to_period("M")
        )
    else:
        seen = set()

    recent = {
        date.to_period("M")
        for date, _ in catalog[-3:]
    }

    work = [
        (date, url)
        for date, url in catalog
        if (
            date.to_period("M") not in seen
            or date.to_period("M") in recent
        )
    ]

    print(
        "[JP/BoJ MoM] "
        f"official catalog: {len(catalog)} months; "
        f"fetch: {len(work)}"
    )

    failures = []

    for index, (date, url) in enumerate(
        work,
        1,
    ):
        try:
            release = _http_get(
                url,
                read_timeout=90,
            )

            frame = parse_boj_mom_pdf(
                release.content,
                date,
            )

            save_eurostat_extra(frame)

        except (
            ValueError,
            OSError,
            requests.RequestException,
        ) as exc:
            failures.append(
                date.strftime("%Y-%m")
            )

            print(
                f"[WARN] JP/BoJ MoM {date:%Y-%m}: "
                f"{type(exc).__name__}: {exc}"
            )

        if (
            index % 12 == 0
            or index == len(work)
        ):
            print(
                f"[JP/BoJ MoM] processed "
                f"{index}/{len(work)}"
            )

    now_saved = load_eurostat_extra()

    if not now_saved.empty:
        dates = set(
            pd.to_datetime(
                now_saved.loc[
                    (now_saved.country == "JP")
                    & (now_saved.metric == "ppi_mom"),
                    "date",
                ]
            ).dt.to_period("M")
        )
    else:
        dates = set()

    first = pd.Period(
        f"{START_YEAR}-01",
        freq="M",
    )

    last = max(
        date.to_period("M")
        for date, _ in catalog
    )

    gaps = [
        str(period)
        for period in pd.period_range(
            first,
            last,
            freq="M",
        )
        if period not in dates
    ]

    if gaps:
        print(
            "[COVERAGE] JP/ppi_mom missing months: "
            + ", ".join(gaps)
        )

    if failures:
        print(
            "[WARN] JP/BoJ MoM PDF parsing failed: "
            + ", ".join(failures)
        )

    # Пропуски вне опубликованного каталога
    # показываем, но не считаем ошибкой сети.
    return not failures


# =====================================================
# Диагностика заполненности исторических рядов
# =====================================================

def _coverage() -> None:
    saved = load_eurostat_extra()

    for country in ("US", "JP"):
        for metric in (
            "ppi_yoy",
            "ppi_mom",
        ):
            if saved.empty:
                filtered = saved
            else:
                filtered = saved.loc[
                    (saved.country == country)
                    & (saved.metric == metric)
                ]

            if filtered.empty:
                print(
                    f"[COVERAGE] "
                    f"{country}/{metric}: EMPTY"
                )
            else:
                print(
                    f"[COVERAGE] "
                    f"{country}/{metric}: "
                    f"{len(filtered)} months; "
                    f"{filtered.date.min():%Y-%m} ... "
                    f"{filtered.date.max():%Y-%m}"
                )


# =====================================================
# Основной запуск
# =====================================================

def run() -> int:
    failed = []

    # США: два исторических ряда BLS.
    try:
        _save_with_report(
            "US/BLS ppi_yoy + ppi_mom",
            fetch_us_history(),
        )

    except (
        ValueError,
        OSError,
        requests.RequestException,
    ) as exc:
        failed.append("US")

        print(
            f"[ERROR] US/BLS: "
            f"{type(exc).__name__}: {exc}"
        )

    # Япония: готовый исторический ряд YoY.
    try:
        _save_with_report(
            "JP/BoJ ppi_yoy",
            parse_boj_yoy_history(
                _http_get(BOJ_HISTORY).text
            ),
        )

    except (
        ValueError,
        OSError,
        requests.RequestException,
    ) as exc:
        failed.append("JP_YOY")

        print(
            f"[ERROR] JP/BoJ YoY: "
            f"{type(exc).__name__}: {exc}"
        )

    # Япония: доступная история MoM по PDF.
    try:
        if not _update_japan_mom():
            failed.append(
                "JP_MOM_INCOMPLETE"
            )

    except (
        ValueError,
        OSError,
        requests.RequestException,
    ) as exc:
        failed.append("JP_MOM")

        print(
            f"[ERROR] JP/BoJ MoM: "
            f"{type(exc).__name__}: {exc}"
        )

    _coverage()

    if failed:
        print(
            "[SUMMARY] incomplete: "
            + ", ".join(failed)
        )
        return 1

    print(
        "[SUMMARY] available sources updated "
        "(check coverage for gaps)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(run())
