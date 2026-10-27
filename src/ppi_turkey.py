
"""Historical domestic producer price inflation (D-PPI) for Turkiye.

Official source: TCMB producer-price table, containing published
TURKSTAT annual and monthly percentage changes (not index levels).

Run from the project root:
    python -m src.ppi_turkey
"""

from __future__ import annotations

import math
import re
import sys
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.eurostat_extra import save_eurostat_extra


URL = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/EN/"
    "TCMB%2BEN/Main%2BMenu/Statistics/"
    "Inflation%2BData/Producer%2BPrices"
)

START = pd.Period("2020-01", freq="M")

SOURCE = (
    "TCMB/TURKSTAT D-PPI; "
    "published percentage changes"
)

COLUMNS = [
    "country",
    "date",
    "metric",
    "value",
    "source",
    "unit",
    "adjustment",
]

PERIOD_RE = re.compile(
    r"^(0[1-9]|1[0-2])[-/](20\d{2})$"
)

NUMBER_RE = re.compile(
    r"^[+-]?\d+(?:[.,]\d+)?$"
)

RETRY_STATUS = {
    429, 500, 502, 503, 504
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; MacroDashboard/1.0)"
    )
}

# Контроль по официальной таблице TCMB.
OFFICIAL_CHECKS = {
    ("2022-12", "ppi_mom"): -0.24,
    ("2026-09", "ppi_yoy"): 27.38,
    ("2026-09", "ppi_mom"): 2.07,
}


def _request_html() -> str:
    """Download TCMB HTML, retrying temporary connection errors."""

    for attempt in range(3):
        try:
            response = requests.get(
                URL,
                headers=HEADERS,
                timeout=(20, 90),
            )

            response.raise_for_status()

            if len(response.content) > 10_000_000:
                raise ValueError(
                    "TCMB: HTML exceeds expected size"
                )

            content_type = response.headers.get(
                "content-type", ""
            ).lower()

            if "html" not in content_type:
                raise ValueError(
                    "TCMB: expected HTML document"
                )

            return response.text

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

            if not transient or attempt == 2:
                raise

            print(
                "[WARN] TR/TCMB connection: "
                f"{type(exc).__name__}; "
                f"retry {attempt + 2}/3"
            )

            time.sleep(
                1.5 * (2 ** attempt)
            )

    raise RuntimeError(
        "TCMB: HTTP retry loop unexpectedly exhausted"
    )


def _published_number(
    raw: object,
) -> float | None:
    """Read official percentages with '.' or ',' decimal separator."""

    text = (
        str(raw)
        .strip()
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace("\u2212", "-")
        .replace(" ", "")
    )

    if text in {
        "", "-", "—", "..", "...", "None", "nan"
    }:
        return None

    # Поддерживаются:
    #   -0,24
    #   2.07
    #   27.38
    #
    # Неоднозначные форматы с двумя
    # разделителями намеренно отклоняются.
    if not NUMBER_RE.fullmatch(text):
        raise ValueError(
            "TCMB: unrecognized published "
            f"percentage {raw!r}"
        )

    value = float(
        text.replace(",", ".")
    )

    # В Турции годовая инфляция производителей
    # исторически превышала 100%.
    if (
        not math.isfinite(value)
        or not (-100 < value < 1000)
    ):
        raise ValueError(
            "TCMB: percentage outside "
            f"expected range {raw!r}"
        )

    return value


def parse_tcmb_ppi(
    html: str,
) -> pd.DataFrame:
    """Read D-PPI columns, excluding discontinued legacy PPI."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    for token in (
        "Domestic Producer Price Index",
        "Year to Year",
        "Month to Month",
        "D-PPI",
    ):
        if token not in text:
            raise ValueError(
                "TCMB: official table "
                f"heading missing: {token}"
            )

    candidates = []

    now = pd.Period(
        pd.Timestamp.now(),
        freq="M",
    )

    for table in soup.find_all("table"):
        table_text = table.get_text(
            " ",
            strip=True,
        )

        if not all(
            item in table_text
            for item in (
                "Year to Year",
                "Month to Month",
                "D-PPI",
            )
        ):
            continue

        rows = []

        for tr in table.find_all("tr"):
            cells = [
                re.sub(
                    r"\s+",
                    " ",
                    cell.get_text(
                        " ",
                        strip=True,
                    ),
                ).strip()
                for cell in tr.find_all(
                    ["th", "td"],
                    recursive=False,
                )
            ]

            if not cells:
                continue

            match = PERIOD_RE.fullmatch(
                cells[0]
            )

            if not match:
                continue

            if len(cells) != 5:
                raise ValueError(
                    "TCMB: unexpected five-column "
                    f"D-PPI layout: {cells[0]}"
                )

            month = int(match.group(1))
            year = int(match.group(2))

            period = pd.Period(
                f"{year}-{month:02d}",
                freq="M",
            )

            if period < START:
                continue

            if period > now:
                raise ValueError(
                    f"TCMB: future report period {period}"
                )

            # Официальная таблица:
            #
            # 0. Период
            # 1. Старый PPI YoY
            # 2. D-PPI YoY
            # 3. Старый PPI MoM
            # 4. D-PPI MoM
            #
            # Используем только D-PPI.

            yoy = _published_number(
                cells[2]
            )

            mom = _published_number(
                cells[4]
            )

            if yoy is None or mom is None:
                raise ValueError(
                    "TCMB: missing D-PPI "
                    f"change for {period}"
                )

            for metric, value in (
                ("ppi_yoy", yoy),
                ("ppi_mom", mom),
            ):
                rows.append(
                    (
                        "TR",
                        period.start_time,
                        metric,
                        value,
                        SOURCE,
                        "%",
                        "NSA",
                    )
                )

        if rows:
            candidates.append(
                pd.DataFrame(
                    rows,
                    columns=COLUMNS,
                )
            )

    if len(candidates) != 1:
        raise ValueError(
            "TCMB: expected exactly one "
            "historical D-PPI table; "
            f"got {len(candidates)}"
        )

    result = (
        candidates[0]
        .sort_values(["date", "metric"])
        .reset_index(drop=True)
    )

    if result.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "TCMB: duplicate D-PPI observation"
        )

    months = set(
        result.date.dt.to_period("M")
    )

    if (
        len(months) < 60
        or min(months) != START
    ):
        raise ValueError(
            "TCMB: incomplete starting history: "
            f"first={min(months)}, "
            f"months={len(months)}"
        )

    # Дополнительные проверки конкретных
    # опубликованных значений.
    indexed = {
        (
            str(date.to_period("M")),
            metric,
        ): float(value)
        for date, metric, value in result[
            ["date", "metric", "value"]
        ].itertuples(
            index=False,
            name=None,
        )
    }

    for key, expected in OFFICIAL_CHECKS.items():
        if (
            key in indexed
            and abs(
                indexed[key] - expected
            ) > 0.005
        ):
            raise ValueError(
                "TCMB identity check failed "
                f"for {key}: "
                f"observed={indexed[key]}, "
                f"published={expected}"
            )

    gaps = [
        str(month)
        for month in pd.period_range(
            START,
            max(months),
            freq="M",
        )
        if month not in months
    ]

    if gaps:
        result.attrs["source_issues"] = (
            "Missing months: "
            + ", ".join(gaps),
        )

    return result


def fetch_turkey_ppi() -> pd.DataFrame:
    result = parse_tcmb_ppi(
        _request_html()
    )

    for metric, part in result.groupby(
        "metric"
    ):
        print(
            f"[OK] TR/{metric}: "
            f"{len(part)} months; "
            f"{part.date.min():%Y-%m} ... "
            f"{part.date.max():%Y-%m}; "
            "TCMB/TURKSTAT published rates"
        )

    return result


def run() -> int:
    try:
        result = fetch_turkey_ppi()

        issues = tuple(
            result.attrs.get(
                "source_issues",
                (),
            )
        )

        save_eurostat_extra(
            result
        )

        if issues:
            print(
                "[SUMMARY] TR/D-PPI partial: "
                + "; ".join(issues)
            )
            return 1

        print(
            "[SUMMARY] TR/D-PPI YoY "
            "and MoM history updated"
        )
        return 0

    except (
        requests.RequestException,
        ValueError,
        OSError,
    ) as exc:
        print(
            f"[ERROR] TR/D-PPI: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run())
