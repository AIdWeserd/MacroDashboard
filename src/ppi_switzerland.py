"""Switzerland: monthly industrial producer price inflation from Eurostat.

Dataset: sts_inpp_m (producer prices, total industrial output).
Country: CH; NACE: B-E36; unadjusted data (NSA).

Uses published percentage changes:
    PCH_PRE = MoM
    PCH_SM  = YoY

This is the Eurostat industrial PPI, not the broader
Swiss FSO headline PPI.

Run:
    python -m src.ppi_switzerland
"""

from __future__ import annotations

import math
import re
import sys
import time

import pandas as pd
import requests

from src.eurostat_extra import save_eurostat_extra

URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/"
    "statistics/1.0/data/sts_inpp_m"
)

START = pd.Period("2020-01", freq="M")

DIMENSIONS = {
    "freq": "M",
    "indic_bt": "PRC_PRR",
    "nace_r2": "B-E36",
    "s_adj": "NSA",
    "geo": "CH",
}

UNITS = {
    "ppi_yoy": "PCH_SM",
    "ppi_mom": "PCH_PRE",
}

SOURCE = (
    "Eurostat/CH sts_inpp_m, total industry B-E36; "
    "published rates"
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

RETRY_CODES = {429, 500, 502, 503, 504}

HEADERS = {
    "User-Agent": (
        "MacroDashboard/1.0 "
        "(Eurostat public statistics)"
    ),
    "Accept": "application/json",
}


# =====================================================
# Official Eurostat API
# =====================================================

def _request(unit: str) -> dict:
    params = {
        **DIMENSIONS,
        "unit": unit,
        "sinceTimePeriod": "2020-01",
        "lang": "EN",
    }

    for attempt in range(3):
        try:
            response = requests.get(
                URL,
                params=params,
                headers=HEADERS,
                timeout=(20, 90),
            )

            response.raise_for_status()

            if len(response.content) > 5_000_000:
                raise ValueError(
                    "Eurostat: unexpectedly large response"
                )

            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError(
                    "Eurostat: expected JSON-stat object"
                )

            return payload

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            temporary = (
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
                        ) or status in RETRY_CODES

            if not temporary or attempt == 2:
                raise

            print(
                f"[WARN] CH/Eurostat {unit}: "
                f"network retry {attempt + 2}/3"
            )

            time.sleep(
                1.5 * (2 ** attempt)
            )

    raise RuntimeError(
        "Eurostat: request retry exhausted"
    )


# =====================================================
# JSON-stat structure
# =====================================================

def _index(category: dict) -> dict[str, int]:
    positions = category.get("index")

    if isinstance(positions, dict):
        return {
            str(key): int(pos)
            for key, pos in positions.items()
        }

    if isinstance(positions, list):
        return {
            str(key): i
            for i, key in enumerate(positions)
        }

    raise ValueError(
        "Eurostat: JSON-stat category index missing"
    )


def parse_eurostat_ch(
        payload: dict,
        metric: str,
) -> pd.DataFrame:
    """Decode exactly one Swiss industrial PPI series."""

    if metric not in UNITS:
        raise ValueError(
            "Unknown PPI metric"
        )

    if payload.get("class") != "dataset":
        raise ValueError(
            "Eurostat: not a JSON-stat dataset"
        )

    title = str(
        payload.get("label", "")
    ).lower()

    if (
            "producer prices" not in title
            and "producer price" not in title
    ):
        raise ValueError(
            "Eurostat: unexpected dataset title: "
            + title[:120]
        )

    ids = payload.get("id")
    sizes = payload.get("size")
    dimensions = payload.get("dimension")

    if (
            not isinstance(ids, list)
            or not isinstance(sizes, list)
            or len(ids) != len(sizes)
    ):
        raise ValueError(
            "Eurostat: malformed JSON-stat dimensions"
        )

    required = set(DIMENSIONS) | {
        "unit",
        "time",
    }

    if (
            not isinstance(dimensions, dict)
            or set(ids) != required
    ):
        raise ValueError(
            "Eurostat: unexpected dimensional structure"
        )

    if any(
            not isinstance(n, int) or n < 1
            for n in sizes
    ):
        raise ValueError(
            "Eurostat: invalid shape"
        )

    maps = {
        name: _index(
            dimensions[name]["category"]
        )
        for name in ids
    }

    expected = {
        **DIMENSIONS,
        "unit": UNITS[metric],
    }

    # All dimensions except time must contain
    # exactly the requested statistical series.
    for name, value in expected.items():
        if (
                sizes[ids.index(name)] != 1
                or maps[name] != {value: 0}
        ):
            raise ValueError(
                f"Eurostat: unexpected selection "
                f"{name}: {maps[name]}"
            )

    time_map = maps["time"]

    if (
            sizes[ids.index("time")]
            != len(time_map)
    ):
        raise ValueError(
            "Eurostat: invalid time dimension"
        )

    raw_values = payload.get("value")

    if not isinstance(
            raw_values,
            (dict, list),
    ):
        raise ValueError(
            "Eurostat: no observation values"
        )

    statuses = payload.get("status") or {}

    if not isinstance(
            statuses,
            (dict, list),
    ):
        raise ValueError(
            "Eurostat: unexpected observation status"
        )

    # JSON-stat flattening:
    # the position of each dimension
    # is multiplied by the product of
    # subsequent dimension lengths.
    multipliers = {}
    stride = 1

    for name, length in reversed(
            list(zip(ids, sizes))
    ):
        multipliers[name] = stride
        stride *= length

    today = pd.Period(
        pd.Timestamp.now(),
        freq="M",
    )

    rows = []

    for period_text, period_position in time_map.items():
        if not re.fullmatch(
                r"20\d{2}-(0[1-9]|1[0-2])",
                period_text,
        ):
            continue

        month = pd.Period(
            period_text,
            freq="M",
        )

        if month < START or month > today:
            continue

        # Non-time dimensions are verified
        # to be singleton selections.
        offset = (
                period_position
                * multipliers["time"]
        )

        if isinstance(raw_values, dict):
            raw = raw_values.get(
                str(offset),
                raw_values.get(offset),
            )
        else:
            raw = (
                raw_values[offset]
                if offset < len(raw_values)
                else None
            )

        if raw is None:
            continue

        if isinstance(statuses, dict):
            flag = statuses.get(
                str(offset),
                statuses.get(offset, ""),
            )
        else:
            flag = (
                statuses[offset]
                if offset < len(statuses)
                else ""
            )

        # Do not store suppressed or confidential data.
        if any(
                code in str(flag).lower()
                for code in ("c", "u")
        ):
            continue

        value = float(raw)

        if (
                not math.isfinite(value)
                or not -100 < value < 300
        ):
            raise ValueError(
                f"Eurostat: implausible rate "
                f"{period_text}: {raw}"
            )

        label = SOURCE

        if "p" in str(flag).lower():
            label += "; provisional"

        rows.append(
            (
                "CH",
                month.start_time,
                metric,
                value,
                label,
                "%",
                "NSA",
            )
        )

    frame = pd.DataFrame(
        rows,
        columns=COLS,
    )

    frame = (
        frame.sort_values("date")
        .reset_index(drop=True)
    )

    if (
            len(frame) < 48
            or (
            not frame.empty
            and frame.date.min().to_period("M")
            != START
    )
    ):
        raise ValueError(
            f"Eurostat/CH {metric}: history "
            f"missing or too short "
            f"({len(frame)} months)"
        )

    if frame.date.duplicated().any():
        raise ValueError(
            "Eurostat/CH: duplicate monthly observations"
        )

    return frame


# =====================================================
# Independent YoY and MoM retrieval
# =====================================================

def fetch_switzerland_ppi() -> pd.DataFrame:
    pieces = []
    issues = []

    for metric, unit in UNITS.items():
        try:
            part = parse_eurostat_ch(
                _request(unit),
                metric,
            )

            pieces.append(part)

            print(
                f"[OK] CH/{metric}: "
                f"{len(part)} months; "
                f"{part.date.min():%Y-%m} ... "
                f"{part.date.max():%Y-%m}; "
                "Eurostat, industrial PPI, NSA"
            )

        except (
                requests.RequestException,
                ValueError,
                TypeError,
                KeyError,
        ) as exc:
            issues.append(
                f"{metric}: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                f"[WARN] CH/{metric}: "
                f"{type(exc).__name__}: {exc}"
            )

    if not pieces:
        raise RuntimeError(
            "CH: both official Eurostat "
            "PPI rates unavailable"
        )

    frame = pd.concat(
        pieces,
        ignore_index=True,
    )

    frame = (
        frame.sort_values(
            ["date", "metric"]
        )
        .reset_index(drop=True)
    )

    if frame.duplicated(
            ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "CH: duplicate country/date/metric"
        )

    latest = max(
        frame.date
    ).to_period("M")

    for metric in UNITS:
        actual = set(
            frame.loc[
                frame.metric.eq(metric),
                "date",
            ].dt.to_period("M")
        )

        gaps = [
            str(month)
            for month in pd.period_range(
                START,
                latest,
                freq="M",
            )
            if month not in actual
        ]

        if gaps:
            issues.append(
                f"{metric}: missing "
                f"{len(gaps)} months: "
                + ", ".join(gaps)
            )

    frame.attrs[
        "source_issues"
    ] = tuple(issues)

    return frame


# =====================================================
# Standalone execution
# =====================================================

def run() -> int:
    try:
        frame = fetch_switzerland_ppi()

        issues = frame.attrs.get(
            "source_issues",
            (),
        )

        save_eurostat_extra(
            frame
        )

        print(
            f"[COVERAGE] CH: {len(frame)} "
            "published observations saved"
        )

        if issues:
            print(
                "[SUMMARY] CH/PPI partial: "
                + "; ".join(issues)
            )
            return 1

        print(
            "[SUMMARY] CH/PPI history updated"
        )
        return 0

    except (
            RuntimeError,
            ValueError,
            requests.RequestException,
            OSError,
    ) as exc:
        print(
            f"[ERROR] CH/PPI: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run())
