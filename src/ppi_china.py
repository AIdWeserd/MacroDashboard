
"""China NBS ex-factory PPI: monthly YoY and MoM history since 2020.

Uses the official National Bureau of Statistics (NBS) data API directly.
Source series are official comparison indices:
    same month of previous year = 100  ->  PPI YoY = index - 100
    previous month = 100                ->  PPI MoM = index - 100
No interpolation, averaging or YTD substitution.

Run from the Macro Dashboard project root:
    python -m src.ppi_china
"""

from __future__ import annotations

import math
import re
import sys
import time
from dataclasses import dataclass

import pandas as pd
import requests

from src.eurostat_extra import load_eurostat_extra, save_eurostat_extra


START = pd.Period("2020-01", freq="M")

BASE_URL = (
    "https://data.stats.gov.cn/dg/website/"
    "publicrelease/web/external"
)

ENDPOINTS = (
    "stream/esData",
    "getEsDataByCidAndDt",
)

ROOT_MONTHLY = "fc982599aa684be7969d7b90b1bd0e84"

SOURCE = (
    "NBS China/PPI ex-factory; "
    "расчёт по официальному индексу сравнения (=100)"
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

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://data.stats.gov.cn/dg/website/page.html",
    "User-Agent": "MacroDashboard/1.0 (official statistics)",
}


@dataclass(frozen=True)
class Indicator:
    metric: str
    catalog_id: str
    indicator_id: str
    comparison: str


INDICATORS = (
    Indicator(
        "ppi_yoy",
        "60e8b361f11c4a878c652a6487a25561",
        "150633e52b9a470a9a9fd1b296dd6c5b",
        "same month last year=100",
    ),
    Indicator(
        "ppi_mom",
        "677cfbb4f06941af8c1761c4804e58cf",
        "e64079bae9064aebad1c4c5fe0c8a6ef",
        "previous month=100",
    ),
)

# Контроль по официальному релизу NBS за сентябрь 2026 года.
CONTROL = {
    "ppi_yoy": (
        pd.Period("2026-09", freq="M"),
        5.0,
    ),
    "ppi_mom": (
        pd.Period("2026-09", freq="M"),
        1.2,
    ),
}


def _payload(spec: Indicator) -> dict:
    year = pd.Timestamp.now().year

    return {
        "cid": spec.catalog_id,
        "indicatorIds": [spec.indicator_id],
        "daCatalogId": "",
        "das": [
            {
                "text": "全国",
                "value": "000000000000",
            }
        ],
        "showType": "1",
        "dts": [
            f"202001MM-{year}12MM"
        ],
        "rootId": ROOT_MONTHLY,
    }


def _request(spec: Indicator) -> dict:
    """Request the official NBS monthly series.

    The old easyquery API is intentionally not used.
    A 404/405 can mean that NBS renamed the endpoint.
    """

    body = _payload(spec)
    last_error = None

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for endpoint in ENDPOINTS:
            url = f"{BASE_URL}/{endpoint}"

            for attempt in range(1, 4):
                try:
                    print(
                        f"[NBS] {spec.metric}: "
                        f"{endpoint}; attempt {attempt}/3"
                    )

                    response = session.post(
                        url,
                        json=body,
                        timeout=(20, 75),
                    )

                    if response.status_code in (404, 405):
                        last_error = (
                            f"HTTP {response.status_code}: "
                            f"{endpoint}"
                        )
                        break

                    response.raise_for_status()

                    if len(response.content) > 12_000_000:
                        raise ValueError(
                            "NBS response too large"
                        )

                    content_type = response.headers.get(
                        "Content-Type", ""
                    ).lower()

                    if "html" in content_type:
                        raise ValueError(
                            "NBS returned HTML instead "
                            "of official JSON"
                        )

                    result = response.json()

                    if not isinstance(result, dict):
                        raise ValueError(
                            "Unexpected NBS JSON structure"
                        )

                    return result

                except (
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                ) as exc:

                    if isinstance(
                        exc,
                        requests.exceptions.SSLError,
                    ):
                        raise

                    last_error = exc

                    if attempt == 3:
                        raise

                except requests.exceptions.HTTPError as exc:
                    code = (
                        exc.response.status_code
                        if exc.response is not None
                        else None
                    )

                    last_error = exc

                    if (
                        code not in (429, 500, 502, 503, 504)
                        or attempt == 3
                    ):
                        raise

                if attempt < 3:
                    time.sleep(
                        1.5 * (2 ** (attempt - 1))
                    )

    raise RuntimeError(
        f"NBS API endpoints unavailable: {last_error}"
    )


def parse_nbs_history(
    payload: dict,
    spec: Indicator,
) -> pd.DataFrame:
    """Parse one official comparison-index series.

    Rejects an unexpected indicator, geography or layout.
    """

    if (
        str(payload.get("state")) != "20000"
        or payload.get("success") is False
    ):
        raise ValueError(
            f"NBS {spec.metric}: "
            f"state={payload.get('state')}, "
            f"message={str(payload.get('message', ''))[:150]}"
        )

    blocks = payload.get("data")

    if not isinstance(blocks, list):
        raise ValueError(
            "NBS response missing data list"
        )

    now = pd.Period(
        pd.Timestamp.now(),
        freq="M",
    )

    rows = []
    seen = set()

    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError(
                "Malformed NBS data block"
            )

        code = str(
            block.get("code", "")
        )

        if not re.fullmatch(
            r"20\d{4}MM",
            code,
        ):
            continue

        try:
            period = pd.Period(
                code[:6],
                freq="M",
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid NBS period {code}"
            ) from exc

        if period < START or period > now:
            continue

        values = block.get(
            "values", []
        )

        if not isinstance(values, list):
            raise ValueError(
                f"NBS {code}: expected values list"
            )

        if not values:
            continue

        matched = [
            entry
            for entry in values
            if (
                isinstance(entry, dict)
                and str(
                    entry.get(
                        "_id",
                        entry.get(
                            "indicatorId",
                            spec.indicator_id,
                        ),
                    )
                ) == spec.indicator_id
            )
        ]

        if len(matched) != 1 or len(values) != 1:
            raise ValueError(
                f"NBS {code}: ambiguous indicator "
                "or national dimension"
            )

        entry = matched[0]

        geo_name = str(
            entry.get("da_name", "全国")
        ).strip()

        if geo_name not in (
            "全国",
            "National",
            "China",
        ):
            raise ValueError(
                f"NBS {code}: wrong geography: "
                f"{geo_name!r}"
            )

        raw = entry.get("value")

        if raw in (
            None,
            "",
            "--",
            "—",
        ):
            continue

        try:
            index = float(
                str(raw).replace(",", "")
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"NBS {code}: invalid index "
                f"{raw!r}"
            ) from exc

        if (
            not math.isfinite(index)
            or not (50 <= index <= 200)
        ):
            raise ValueError(
                f"NBS {code}: not a valid "
                f"comparison index: {index}"
            )

        if period in seen:
            raise ValueError(
                f"NBS duplicate period: {period}"
            )

        seen.add(period)

        # Элементарное преобразование официального
        # сравнительного индекса, где база = 100.
        rate = round(
            index - 100,
            2,
        )

        rows.append(
            (
                "CN",
                period.start_time,
                spec.metric,
                rate,
                SOURCE,
                "%",
                "NSA",
            )
        )

    result = pd.DataFrame(
        rows,
        columns=COLS,
    )

    if len(result) < 12:
        raise ValueError(
            f"NBS {spec.metric}: insufficient "
            f"monthly history ({len(result)} rows)"
        )

    # Контроль идентичности рядов:
    # NBS за сентябрь 2026 опубликовал
    # PPI YoY +5.0% и PPI MoM +1.2%.
    control_period, expected_rate = CONTROL[
        spec.metric
    ]

    control_rows = result.loc[
        result.date.dt.to_period("M").eq(
            control_period
        )
    ]

    if not control_rows.empty:
        actual = float(
            control_rows.iloc[0].value
        )

        if abs(
            actual - expected_rate
        ) > 0.11:
            raise ValueError(
                f"NBS {spec.metric}: "
                "September 2026 identity check failed: "
                f"actual={actual}, "
                f"officially published={expected_rate}"
            )

    return (
        result.sort_values("date")
        .reset_index(drop=True)
    )


def fetch_china_ppi() -> pd.DataFrame:
    """Fetch YoY and MoM independently.

    One failed source must not discard the
    successfully obtained second indicator.
    """

    parts = []
    issues = []

    for spec in INDICATORS:
        try:
            response = _request(spec)

            frame = parse_nbs_history(
                response,
                spec,
            )

            parts.append(frame)

            print(
                f"[OK] CN/{spec.metric}: "
                f"{len(frame)} observations; "
                f"{frame.date.min():%Y-%m} ... "
                f"{frame.date.max():%Y-%m}"
            )

        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
        ) as exc:

            reason = (
                f"{spec.metric}: "
                f"{type(exc).__name__}: {exc}"
            )

            issues.append(reason)

            print(
                f"[WARN] CN/PPI {reason}"
            )

    if not parts:
        raise RuntimeError(
            "NBS: neither PPI history "
            "could be obtained"
        )

    result = (
        pd.concat(
            parts,
            ignore_index=True,
        )
        .sort_values(
            ["date", "metric"]
        )
    )

    if result.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "NBS PPI duplicate key"
        )

    result.attrs[
        "source_issues"
    ] = tuple(issues)

    return result.reset_index(
        drop=True
    )


def run() -> int:
    try:
        frame = fetch_china_ppi()

        issues = frame.attrs.get(
            "source_issues",
            (),
        )

        save_eurostat_extra(frame)

    except (
        requests.RequestException,
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        print(
            f"[ERROR] CN/PPI: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2

    stored = load_eurostat_extra()

    for metric in (
        "ppi_yoy",
        "ppi_mom",
    ):
        series = stored.loc[
            (stored.country == "CN")
            & (stored.metric == metric)
        ].copy()

        if series.empty:
            print(
                f"[COVERAGE] CN/{metric}: EMPTY"
            )
            continue

        months = set(
            series.date.dt.to_period("M")
        )

        last = max(months)

        missing = [
            str(period)
            for period in pd.period_range(
                START,
                last,
                freq="M",
            )
            if period not in months
        ]

        print(
            f"[COVERAGE] CN/{metric}: "
            f"{len(months)} months; "
            f"{min(months)} ... {last}; "
            f"missing={len(missing)}"
        )

        if missing:
            print(
                "[MISSING] "
                + ", ".join(missing)
            )

    if issues:
        print(
            "[SUMMARY] PARTIAL: "
            + "; ".join(issues)
        )
        return 1

    print(
        "[SUMMARY] CN/PPI: both official "
        "NBS histories updated"
    )

    return 0


if __name__ == "__main__":
    sys.exit(run())
