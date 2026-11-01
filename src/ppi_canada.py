
"""Canada IPPI historical YoY / MoM from official Statistics Canada index.

Primary source: Statistics Canada, table 18-10-0265-01 (18100265).
The table contains index levels, not published percentage changes.
Simple transparent growth calculation: (I[t] / I[t-k] - 1) * 100.
Only the headline Canada IPPI series (NSA, Jan 2020 = 100) is used.
The source label explicitly distinguishes calculated from published values.

Usage:
    python -m src.ppi_canada

Requires the existing src.eurostat_extra.save_eurostat_extra() function.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile
import re
import sys
import time

import pandas as pd
import requests

from src.eurostat_extra import save_eurostat_extra


URL = "https://www150.statcan.gc.ca/n1/tbl/csv/18100265-eng.zip"

SOURCE = (
    "Statistics Canada 18-10-0265-01; "
    "расчёт по официальному индексу"
)

START = pd.Period("2020-01", freq="M")

COLUMNS = [
    "country",
    "date",
    "metric",
    "value",
    "source",
    "unit",
    "adjustment",
]

PRODUCT_LABEL = "Total, Industrial product price index (IPPI)"
FILE_NAME = "18100265.csv"


def _download() -> bytes:
    """Read the official ZIP. Retry only temporary networking errors."""

    for attempt in range(3):
        try:
            response = requests.get(
                URL,
                timeout=(20, 90),
            )
            response.raise_for_status()

            payload = response.content

            if (
                len(payload) > 30_000_000
                or not payload.startswith(b"PK")
            ):
                raise ValueError(
                    "Statistics Canada: invalid or oversized ZIP"
                )

            return payload

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code", None,
            )

            retryable = (
                isinstance(
                    exc,
                    (requests.Timeout, requests.ConnectionError),
                )
                and not isinstance(
                    exc,
                    requests.exceptions.SSLError,
                )
            ) or status in (429, 500, 502, 503, 504)

            if not retryable or attempt == 2:
                raise

            print(
                "[WARN] CA/IPPI: network "
                f"{type(exc).__name__}, "
                f"retry {attempt + 2}/3"
            )

            time.sleep(2 ** attempt)

    raise RuntimeError("Unreachable")


def _read_zip(payload: bytes) -> pd.DataFrame:
    """Extract only the known CSV member and bound uncompressed size."""

    try:
        with ZipFile(BytesIO(payload)) as archive:
            items = [
                entry
                for entry in archive.infolist()
                if (
                    entry.filename.replace("\\", "/").split("/")[-1]
                    == FILE_NAME
                )
            ]

            if len(items) != 1:
                raise ValueError(
                    f"Statistics Canada: {FILE_NAME} not found once"
                )

            if items[0].file_size > 60_000_000:
                raise ValueError(
                    "Statistics Canada: CSV too large"
                )

            with archive.open(items[0]) as handle:
                return pd.read_csv(
                    handle,
                    dtype=str,
                    encoding="utf-8-sig",
                    low_memory=False,
                )

    except BadZipFile as exc:
        raise ValueError(
            "Statistics Canada: corrupt ZIP"
        ) from exc


def _month(text: object) -> pd.Period | None:
    item = str(text).strip()

    if not re.fullmatch(
        r"\d{4}-(0[1-9]|1[0-2])",
        item,
    ):
        return None

    return pd.Period(item, freq="M")


def parse_canada_index(data: pd.DataFrame) -> pd.DataFrame:
    """Calculate YoY/MoM only from the uniquely identified IPPI series.

    Values from 2019 can be used as the reference for 2020 YoY.
    Output starts in January 2020.

    No interpolation or imputation of missing periods.
    """

    required = {
        "REF_DATE",
        "GEO",
        "UOM",
        "VALUE",
    }

    missing = required - set(data.columns)

    if missing:
        raise ValueError(
            f"Statistics Canada: missing columns {sorted(missing)}"
        )

    product_columns = [
        column
        for column in data.columns
        if (
            "north american product classification"
            in column.lower()
            or "napcs" in column.lower()
        )
    ]

    if len(product_columns) != 1:
        raise ValueError(
            "Statistics Canada: cannot uniquely determine "
            "NAPCS dimension; "
            f"candidates={product_columns}"
        )

    product_column = product_columns[0]

    product_name = (
        data[product_column]
        .fillna("")
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    rows = data.loc[
        data["GEO"].fillna("").str.strip().eq("Canada")
        & product_name.eq(PRODUCT_LABEL)
    ].copy()

    if rows.empty:
        raise ValueError(
            "Statistics Canada: headline Canada IPPI series not found"
        )

    # Reject percentages, unrelated units and incompatible bases.
    unit = rows["UOM"].fillna("").str.strip()
    units = sorted(set(unit))

    if (
        len(units) != 1
        or not re.search(r"\bIndex\b", units[0], re.I)
    ):
        raise ValueError(
            f"Statistics Canada: unexpected index units {units}"
        )

    if not re.search(
        r"2020\s*0?1\s*=\s*100",
        units[0],
    ):
        raise ValueError(
            "Statistics Canada: index base is not "
            f"Jan 2020=100: {units[0]}"
        )

    # Do not combine distinct statistical vectors.
    if "VECTOR" in rows.columns:
        vectors = (
            set(rows["VECTOR"].dropna().str.strip()) - {""}
        )

        if len(vectors) > 1:
            raise ValueError(
                "Statistics Canada: multiple headline "
                f"series vectors: {vectors}"
            )

    rows["_period"] = rows["REF_DATE"].map(_month)

    if rows["_period"].isna().any():
        raise ValueError(
            "Statistics Canada: unexpected reference-period format"
        )

    if rows.duplicated("_period").any():
        raise ValueError(
            "Statistics Canada: duplicate index "
            "observations per month"
        )

    rows["_value"] = pd.to_numeric(
        rows["VALUE"],
        errors="coerce",
    )

    if rows["_value"].dropna().le(0).any():
        raise ValueError(
            "Statistics Canada: index contains "
            "zero or negative values"
        )

    # Statistics Canada publishes one chain-linked index
    # through the basket updates.
    levels = {
        period: float(value)
        for period, value in zip(
            rows["_period"],
            rows["_value"],
        )
        if pd.notna(value)
    }

    if not levels:
        raise ValueError(
            "Statistics Canada: no numeric index levels"
        )

    last = max(levels)

    if last < START:
        raise ValueError(
            "Statistics Canada: no headline IPPI since 2020"
        )

    result_rows = []
    missing_pairs = []

    for period in pd.period_range(
        START,
        last,
        freq="M",
    ):
        for metric, lag in (
            ("ppi_mom", 1),
            ("ppi_yoy", 12),
        ):
            older = period - lag

            if (
                period not in levels
                or older not in levels
            ):
                missing_pairs.append(
                    f"{period}/{metric}"
                )
                continue

            # One division of two official index levels.
            ratio = (
                levels[period] / levels[older] - 1.0
            ) * 100.0

            # Published indices have limited precision.
            # Do not pretend that more decimal places
            # are supported by the source.
            value = round(ratio, 1)

            result_rows.append(
                (
                    "CA",
                    period.start_time,
                    metric,
                    value,
                    SOURCE,
                    "%",
                    "NSA",
                )
            )

    result = pd.DataFrame(
        result_rows,
        columns=COLUMNS,
    )

    if (
        result.empty
        or result.metric.nunique() != 2
    ):
        raise ValueError(
            "Statistics Canada: insufficient paired "
            "headline IPPI observations"
        )

    if result.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "Statistics Canada: duplicate calculated indicators"
        )

    if missing_pairs:
        result.attrs["source_issues"] = tuple(
            missing_pairs
        )

    return (
        result.sort_values(["date", "metric"])
        .reset_index(drop=True)
    )


def fetch_canada_ppi() -> pd.DataFrame:
    return parse_canada_index(
        _read_zip(_download())
    )


def run() -> int:
    try:
        series = fetch_canada_ppi()

        save_eurostat_extra(series)

        for metric, part in series.groupby("metric"):
            print(
                f"[OK] CA/{metric}: "
                f"{len(part)} months; "
                f"{part.date.min():%Y-%m} ... "
                f"{part.date.max():%Y-%m}; "
                "calculated from official NSA IPPI index"
            )

        problems = series.attrs.get(
            "source_issues",
            (),
        )

        if problems:
            print(
                "[WARN] CA/IPPI missing reference pairs "
                f"({len(problems)}): "
                + ", ".join(problems)
            )
            return 1

        print(
            "[SUMMARY] CA/IPPI both historical "
            "series updated"
        )
        return 0

    except (
        requests.RequestException,
        ValueError,
        OSError,
    ) as exc:
        print(
            f"[ERROR] CA/IPPI: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run())
