"""UK headline Output PPI: official ONS historical data.

Priority:
1. Published YoY/MoM from Table 1 of the current ONS bulletin.
2. Historical values calculated from official GB7S index levels.

Calculated percentages are explicitly labelled because ONS publishes
index levels rounded to one decimal.

No interpolation or mixing of input/output PPI.
Run: python -m src.ppi_uk
"""

from __future__ import annotations

import calendar
import re
import sys
import time

from datetime import date
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.eurostat_extra import save_eurostat_extra

INDEX_URL = (
    "https://www.ons.gov.uk/economy/"
    "inflationandpriceindices/timeseries/gb7s/ppi"
)

BULLETIN_URL = (
    "https://www.ons.gov.uk/economy/"
    "inflationandpriceindices/bulletins/"
    "producerpriceinflation/latest"
)

START = pd.Period("2020-01", freq="M")

COLS = [
    "country",
    "date",
    "metric",
    "value",
    "source",
    "unit",
    "adjustment",
]

MONTH_NUMBER = {
    name.upper(): i
    for i in range(1, 13)
    for name in (
        calendar.month_abbr[i],
        calendar.month_name[i],
    )
}

MONTH_NUMBER["SEPT"] = 9

MONTH_RE = "|".join(
    sorted(
        MONTH_NUMBER,
        key=len,
        reverse=True,
    )
)

INDEX_ROW = re.compile(
    rf"^(20\d{{2}})\s+({MONTH_RE})$",
    re.I,
)

NUMBER = re.compile(
    r"^[+\-−]?\d+(?:\.\d+)?$"
)

RETRY_STATUSES = {
    429, 500, 502, 503, 504
}

INDEX_SOURCE = (
    "ONS/GB7S; расчёт по официальному "
    "округлённому индексу"
)

PUBLISHED_SOURCE = (
    "ONS/PPI Table 1; опубликованные YoY/MoM"
)


def _get(url: str) -> str:
    parsed = urlparse(url)

    if (
            parsed.scheme != "https"
            or parsed.hostname not in {
        "www.ons.gov.uk",
        "ons.gov.uk",
    }
    ):
        raise ValueError(
            "Only official ONS HTTPS URLs are accepted"
        )

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                timeout=(20, 80),
                headers={
                    "User-Agent": (
                        "MacroDashboard/1.0 "
                        "(official economic time series)"
                    )
                },
            )

            response.raise_for_status()

            final = urlparse(response.url)

            if (
                    final.scheme != "https"
                    or final.hostname not in {
                "www.ons.gov.uk",
                "ons.gov.uk",
            }
            ):
                raise ValueError(
                    "ONS redirected outside official domain"
                )

            if len(response.content) > 8_000_000:
                raise ValueError(
                    "ONS HTML response unexpectedly large"
                )

            return response.text

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            retryable = (
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
                    or status in RETRY_STATUSES
            )

            if not retryable or attempt == 2:
                raise

            print(
                "[WARN] ONS connection: "
                f"{type(exc).__name__}; "
                f"attempt {attempt + 2}/3"
            )

            time.sleep(
                1.5 * (2 ** attempt)
            )

    raise AssertionError("Unreachable")


def _num(text: object) -> float:
    raw = (
        str(text)
        .strip()
        .replace("−", "-")
        .replace(",", "")
    )

    if not NUMBER.fullmatch(raw):
        raise ValueError(
            f"Not a numeric ONS cell: {raw!r}"
        )

    value = float(raw)

    if not (-100000 < value < 100000):
        raise ValueError(
            "Invalid ONS numeric value"
        )

    return value


def parse_index_levels(
        html: str,
) -> dict[pd.Period, float]:
    """Read only monthly GB7S index observations."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    h1 = soup.find("h1")

    heading = (
        h1.get_text(" ", strip=True)
        if h1
        else ""
    )

    if not (
            "PPI INDEX OUTPUT DOMESTIC"
            in heading.upper()
            and "MANUFACTURED PRODUCTS"
            in heading.upper()
            and "2015=100"
            in heading.upper()
    ):
        raise ValueError(
            "ONS GB7S headline or index base changed: "
            f"{heading!r}"
        )

    if not re.search(
            r"\bGB7S\b",
            soup.get_text(" ", strip=True),
            re.I,
    ):
        raise ValueError(
            "ONS series ID GB7S missing"
        )

    result = {}

    for tr in soup.find_all("tr"):
        cells = [
            x.get_text(" ", strip=True)
            for x in tr.find_all(
                ["th", "td"],
                recursive=False,
            )
        ]

        if len(cells) != 2:
            continue

        label = re.sub(
            r"\s+",
            " ",
            cells[0],
        ).strip()

        match = INDEX_ROW.fullmatch(label)

        if not match:
            continue

        year = int(match.group(1))
        month = MONTH_NUMBER[
            match.group(2).upper()
        ]

        period = pd.Period(
            f"{year}-{month:02d}",
            freq="M",
        )

        try:
            level = _num(cells[1])
        except ValueError:
            continue

        if level <= 0:
            raise ValueError(
                f"ONS GB7S nonpositive index at {period}"
            )

        if (
                period in result
                and result[period] != level
        ):
            raise ValueError(
                "ONS GB7S contradictory observations "
                f"at {period}"
            )

        result[period] = level

    if (
            not result
            or max(result) < START
            or len([
        x for x in result
        if x >= START
    ]) < 12
    ):
        raise ValueError(
            "ONS GB7S monthly history "
            "missing or too short"
        )

    return result


def _bulletin_table_candidates(
        soup: BeautifulSoup,
):
    for table in soup.find_all("table"):
        text = re.sub(
            r"\s+",
            " ",
            table.get_text(
                " ",
                strip=True,
            ),
        ).lower()

        if (
                "all manufactured" in text
                and "output ppi" in text
                and "monthly" in text
                and "annual" in text
        ):
            yield table


def parse_published_rates(
        html: str,
) -> dict[pd.Period, tuple[float, float]]:
    """Published UK output PPI MoM and YoY from Table 1."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    heading = soup.find("h1")

    if (
            not heading
            or "producer price inflation"
            not in heading.get_text(
        " ",
        strip=True,
    ).lower()
    ):
        raise ValueError(
            "ONS PPI bulletin identity not confirmed"
        )

    candidates = list(
        _bulletin_table_candidates(soup)
    )

    if len(candidates) != 1:
        raise ValueError(
            "ONS PPI Table 1 ambiguous: "
            f"{len(candidates)} matches"
        )

    current_year = None
    rates = {}

    for tr in candidates[0].find_all("tr"):
        cells = [
            re.sub(
                r"\s+",
                " ",
                x.get_text(
                    " ",
                    strip=True,
                ),
            ).strip()
            for x in tr.find_all(
                ["th", "td"],
                recursive=False,
            )
        ]

        if not cells:
            continue

        years = [
            int(c)
            for c in cells
            if re.fullmatch(
                r"20\d{2}",
                c,
            )
        ]

        if len(years) > 1:
            raise ValueError(
                "ONS Table 1 has ambiguous reference years"
            )

        if years:
            current_year = years[0]

        months = [
            MONTH_NUMBER[c.upper()]
            for c in cells
            if c.upper() in MONTH_NUMBER
        ]

        if not months:
            continue

        if (
                current_year is None
                or len(months) != 1
        ):
            raise ValueError(
                "ONS Table 1 reference month/year unclear"
            )

        numeric_cells = [
            c for c in cells
            if (
                    NUMBER.fullmatch(
                        c.replace("−", "-")
                    )
                    and not re.fullmatch(
                r"20\d{2}",
                c,
            )
            )
        ]

        # Six numeric columns:
        # input index, input MoM, input YoY,
        # output index, output MoM, output YoY.
        if len(numeric_cells) != 6:
            raise ValueError(
                "ONS Table 1 numeric layout changed: "
                f"{cells!r}"
            )

        period = pd.Period(
            f"{current_year}-{months[0]:02d}",
            freq="M",
        )

        mom = _num(numeric_cells[4])
        yoy = _num(numeric_cells[5])

        if not (
                -100 < mom < 100
                and -100 < yoy < 100
        ):
            raise ValueError(
                "ONS published rate out of range "
                f"at {period}"
            )

        if period in rates:
            raise ValueError(
                f"ONS Table 1 duplicate month: {period}"
            )

        rates[period] = (mom, yoy)

    if len(rates) < 6:
        raise ValueError(
            "ONS Table 1 yielded too few monthly rates"
        )

    return rates


def build_uk_ppi(
        levels: dict[pd.Period, float],
        published: dict[
                       pd.Period,
                       tuple[float, float],
                   ] | None = None,
) -> pd.DataFrame:
    if not levels:
        raise ValueError(
            "Missing official GB7S index levels"
        )

    published = published or {}

    last = max(levels)

    if last < START:
        raise ValueError(
            "GB7S does not reach 2020"
        )

    if last > pd.Period(
            date.today(),
            freq="M",
    ):
        raise ValueError(
            "Future UK PPI period in official series"
        )

    output = []
    gaps = []

    for period in pd.period_range(
            START,
            last,
            freq="M",
    ):
        for metric, lag in (
                ("ppi_mom", 1),
                ("ppi_yoy", 12),
        ):
            if period in published:
                value = published[period][
                    0 if metric == "ppi_mom" else 1
                ]
                source = PUBLISHED_SOURCE

            elif (
                    period in levels
                    and period - lag in levels
            ):
                value = round(
                    (
                            levels[period]
                            / levels[period - lag]
                            - 1.0
                    ) * 100.0,
                    1,
                )
                source = INDEX_SOURCE

            else:
                gaps.append(
                    f"{period}/{metric}"
                )
                continue

            output.append(
                (
                    "GB",
                    period.start_time,
                    metric,
                    value,
                    source,
                    "%",
                    "NSA",
                )
            )

    result = pd.DataFrame(
        output,
        columns=COLS,
    )

    if (
            result.empty
            or result.metric.nunique() != 2
            or result.duplicated(
        ["country", "date", "metric"]
    ).any()
    ):
        raise ValueError(
            "ONS PPI result empty, "
            "one-sided or contains duplicates"
        )

    result.attrs["source_issues"] = tuple(gaps)

    return result.sort_values(
        ["date", "metric"]
    ).reset_index(drop=True)


def fetch_uk_ppi() -> pd.DataFrame:
    levels = parse_index_levels(
        _get(INDEX_URL)
    )

    published = {}

    try:
        table = parse_published_rates(
            _get(BULLETIN_URL)
        )

        published = {
            period: values
            for period, values in table.items()
            if period in levels
        }

        print(
            "[ONS] Published output PPI rates: "
            f"{len(published)} months"
        )

    except (
            requests.RequestException,
            ValueError,
    ) as exc:
        print(
            "[WARN] ONS Table 1 unavailable: "
            f"{type(exc).__name__}; "
            "calculated rates will be labelled"
        )

    result = build_uk_ppi(
        levels,
        published,
    )

    print(
        f"[ONS] UK PPI: {len(result)} observations; "
        f"{result.date.min():%Y-%m} ... "
        f"{result.date.max():%Y-%m}"
    )

    return result


def run() -> int:
    try:
        result = fetch_uk_ppi()

        save_eurostat_extra(result)

        for metric, group in result.groupby("metric"):
            print(
                f"[OK] GB/{metric}: "
                f"{len(group)} observations; "
                f"{group.date.min():%Y-%m} ... "
                f"{group.date.max():%Y-%m}"
            )

        issues = result.attrs.get(
            "source_issues",
            (),
        )

        if issues:
            print(
                "[WARN] GB PPI missing periods: "
                + ", ".join(issues)
            )
            return 1

        print(
            "[SUMMARY] GB/ONS historical PPI saved"
        )
        return 0

    except (
            requests.RequestException,
            ValueError,
            OSError,
    ) as exc:
        print(
            "[ERROR] GB/ONS PPI: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run())
