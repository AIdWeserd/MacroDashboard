
"""Brazilian industrial producer prices (IPP), published MoM and YoY.

Official source: IBGE SIDRA table 6903; national Indústria Geral.
Variables: 1396 = M/M-1, 1394 = M/M-12 (published percentages).
Uses SIDRA directly; Aggregates API v3 only as a fallback.
History: January 2020 onward. No calculation from index levels.

Run: python -m src.ppi_brazil
"""

from __future__ import annotations

import math
import re
import sys
import time
import unicodedata

import pandas as pd
import requests

from src.eurostat_extra import save_eurostat_extra


START = pd.Period("2020-01", freq="M")
TABLE = "6903"
CATEGORY = "46608"  # Indústria Geral
CLASSIFICATION = "842"

VARIABLES = {
    "1394": "ppi_yoy",
    "1396": "ppi_mom",
}

SOURCE = (
    "IBGE/SIDRA 6903, Indústria Geral; published rates"
)

SIDRA_URL = (
    "https://apisidra.ibge.gov.br/values/t/6903/n1/1/"
    "v/1394,1396/p/all/c842/46608"
)

AGGREGATES_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6903"
)

HEADERS = {
    "User-Agent": (
        "MacroDashboard/1.0 (official IBGE statistics)"
    ),
    "Accept": "application/json",
}

COLS = [
    "country",
    "date",
    "metric",
    "value",
    "source",
    "unit",
    "adjustment",
]

MISSING = {
    "",
    "-",
    "..",
    "...",
    "x",
    "nan",
    "none",
    "null",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    return "".join(
        c for c in text
        if not unicodedata.combining(c)
    ).lower().strip()


def _get_json(
    url: str,
    *,
    params: dict | None = None,
    read_timeout: int = 50,
) -> object:

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=(15, read_timeout),
            )

            response.raise_for_status()

            if len(response.content) > 12_000_000:
                raise ValueError(
                    "IBGE response exceeds 12 MB limit"
                )

            if "html" in response.headers.get(
                "Content-Type", ""
            ).lower():
                raise ValueError(
                    "IBGE returned HTML instead of JSON"
                )

            return response.json()

        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            retryable = (
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
            ) or status in {
                429, 500, 502, 503, 504
            }

            if not retryable or attempt == 2:
                raise

            print(
                f"[WARN] IBGE connection retry "
                f"{attempt + 2}/3"
            )

            time.sleep(
                1.5 * 2 ** attempt
            )

    raise RuntimeError(
        "IBGE requests exhausted"
    )


def _month(raw: object) -> pd.Period:
    text = str(raw).strip()

    if not re.fullmatch(
        r"20\d{2}(0[1-9]|1[0-2])",
        text,
    ):
        raise ValueError(
            f"IBGE invalid monthly period: {text!r}"
        )

    return pd.Period(
        f"{text[:4]}-{text[4:]}",
        freq="M",
    )


def _rate(raw: object) -> float | None:
    text = (
        str(raw)
        .strip()
        .replace("−", "-")
        .replace("\u00a0", "")
    )

    if text.lower() in MISSING:
        return None

    if not re.fullmatch(
        r"[+-]?\d+(?:[.,]\d+)?",
        text,
    ):
        raise ValueError(
            "IBGE unexpected published percentage: "
            f"{text!r}"
        )

    result = float(
        text.replace(",", ".")
    )

    if (
        not math.isfinite(result)
        or not (-100 < result < 250)
    ):
        raise ValueError(
            f"IBGE implausible percentage: {result}"
        )

    return result


def _verified_variable_name(
    code: str,
    name: str,
) -> bool:
    """Validate the official IPP comparison definition."""

    label = _norm(name)

    if (
        not label
        or "ipp" not in label
        or "variacao" not in label
    ):
        return False

    if code == "1394":
        return re.search(
            r"m\s*/\s*m\s*-\s*12\b",
            label,
        ) is not None

    if code == "1396":
        return re.search(
            r"m\s*/\s*m\s*-\s*1\b",
            label,
        ) is not None

    return False


def _check_unit(
    unit: str,
    variable_name: str,
    code: str,
) -> None:
    """Validate published-rate identity independently of unit wording."""

    normalized = _norm(unit)

    # Never interpret index levels or other quantities as rates.
    if any(
        token in normalized
        for token in (
            "indice",
            "index",
            "reais",
            "quantidade",
        )
    ):
        raise ValueError(
            f"IBGE variable {code}: "
            f"index/non-percent unit {unit!r}"
        )

    # Official variable code and definition must both agree.
    if not _verified_variable_name(
        code,
        variable_name,
    ):
        raise ValueError(
            f"IBGE variable {code}: "
            f"ambiguous definition {variable_name!r}; "
            f"unit={unit!r}"
        )


# =====================================================
# Primary route: official SIDRA API
# =====================================================

def parse_sidra(
    payload: object,
) -> list[tuple[str, pd.Period, float]]:
    """Parse and validate the actual SIDRA dimensions."""

    if (
        not isinstance(payload, list)
        or len(payload) < 2
        or not isinstance(payload[0], dict)
    ):
        raise ValueError(
            "SIDRA: missing header or data rows"
        )

    header = payload[0]

    def dim(term: str) -> str:
        matches = [
            key
            for key, title in header.items()
            if (
                re.fullmatch(
                    r"D\d+C",
                    str(key),
                )
                and term in _norm(title)
            )
        ]

        if len(matches) != 1:
            raise ValueError(
                f"SIDRA: ambiguous {term!r} "
                f"dimension: {matches}"
            )

        return matches[0]

    month_key = dim("mes")
    variable_key = dim("variavel")

    if (
        month_key == variable_key
        or "D1C" in {
            month_key,
            variable_key,
        }
    ):
        raise ValueError(
            "SIDRA: geographic/period/variable "
            "dimensions conflated"
        )

    categories = [
        key
        for key in header
        if (
            re.fullmatch(
                r"D\d+C",
                str(key),
            )
            and key not in {
                "D1C",
                month_key,
                variable_key,
            }
        )
    ]

    if len(categories) != 1:
        raise ValueError(
            "SIDRA: expected one industry dimension, "
            f"got {categories}"
        )

    category_key = categories[0]

    if "industr" not in _norm(
        header.get(category_key, "")
    ):
        raise ValueError(
            "SIDRA: unexpected industry "
            "classification title"
        )

    observations = []
    now = pd.Period(
        pd.Timestamp.now(),
        freq="M",
    )

    seen = set()
    units = set()

    for row in payload[1:]:
        if not isinstance(row, dict):
            raise ValueError(
                "SIDRA: invalid row type"
            )

        if (
            str(row.get("D1C", "")) != "1"
            or _norm(row.get("D1N", ""))
            != "brasil"
        ):
            raise ValueError(
                "SIDRA: not the official Brazil aggregate"
            )

        if str(row.get(
            category_key, ""
        )) != CATEGORY:
            raise ValueError(
                "SIDRA: not the total "
                "Indústria Geral category"
            )

        category_name_key = (
            category_key[:-1] + "N"
        )

        if "industria geral" not in _norm(
            row.get(category_name_key, "")
        ):
            raise ValueError(
                "SIDRA: industry category "
                "label mismatch"
            )

        code = str(
            row.get(variable_key, "")
        ).strip()

        if code not in VARIABLES:
            raise ValueError(
                "SIDRA: unexpected variable "
                f"code {code!r}"
            )

        variable_name_key = (
            variable_key[:-1] + "N"
        )

        name = str(
            row.get(variable_name_key, "")
        )

        unit = str(
            row.get("MN", "")
        ).strip()

        _check_unit(
            unit,
            name,
            code,
        )

        units.add(
            unit or "<empty>"
        )

        month = _month(
            row.get(month_key, "")
        )

        if month < START or month > now:
            continue

        key = (code, month)

        if key in seen:
            raise ValueError(
                "SIDRA: duplicate observation "
                f"{key}"
            )

        seen.add(key)

        value = _rate(
            row.get("V", "")
        )

        if value is not None:
            observations.append(
                (
                    VARIABLES[code],
                    month,
                    value,
                )
            )

    print(
        "[IBGE/SIDRA] unit labels: "
        + ", ".join(sorted(units))
    )

    return observations


# =====================================================
# Fallback: official IBGE Aggregates API v3
# =====================================================

def parse_aggregates(
    payload: object,
) -> list[tuple[str, pd.Period, float]]:

    if (
        not isinstance(payload, list)
        or len(payload) != len(VARIABLES)
    ):
        raise ValueError(
            "IBGE Aggregates: expected "
            "two variable blocks"
        )

    observed = set()
    rows = []

    now = pd.Period(
        pd.Timestamp.now(),
        freq="M",
    )

    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(
                "IBGE Aggregates: malformed variable"
            )

        code = str(
            item.get("id", "")
        )

        if (
            code not in VARIABLES
            or code in observed
        ):
            raise ValueError(
                "IBGE Aggregates: unexpected "
                f"variable {code!r}"
            )

        observed.add(code)

        title = str(
            item.get("variavel", "")
        )

        _check_unit(
            str(item.get("unidade", "")),
            title,
            code,
        )

        groups = item.get(
            "resultados", []
        )

        if (
            not isinstance(groups, list)
            or len(groups) != 1
        ):
            raise ValueError(
                "IBGE Aggregates: "
                "ambiguous classification"
            )

        group = groups[0]
        classes = group.get(
            "classificacoes", []
        )

        if (
            not isinstance(classes, list)
            or len(classes) != 1
        ):
            raise ValueError(
                "IBGE Aggregates: "
                "unexpected classifications"
            )

        classification = classes[0]
        categories = classification.get(
            "categoria", {}
        )

        if (
            str(classification.get("id"))
            != CLASSIFICATION
            or not isinstance(
                categories, dict
            )
            or set(
                map(str, categories)
            ) != {CATEGORY}
            or "industria geral" not in _norm(
                next(iter(categories.values()))
            )
        ):
            raise ValueError(
                "IBGE Aggregates: "
                "wrong industry category"
            )

        series = group.get(
            "series", []
        )

        if (
            not isinstance(series, list)
            or len(series) != 1
        ):
            raise ValueError(
                "IBGE Aggregates: expected "
                "one national series"
            )

        one = series[0]
        geo = one.get(
            "localidade", {}
        )

        if (
            str(geo.get("id", "")) != "1"
            or _norm(geo.get("nome", ""))
            != "brasil"
        ):
            raise ValueError(
                "IBGE Aggregates: wrong geography"
            )

        data = one.get(
            "serie", {}
        )

        if not isinstance(data, dict):
            raise ValueError(
                "IBGE Aggregates: "
                "invalid time series"
            )

        for period_code, value in data.items():
            month = _month(
                period_code
            )

            if not START <= month <= now:
                continue

            number = _rate(value)

            if number is not None:
                rows.append(
                    (
                        VARIABLES[code],
                        month,
                        number,
                    )
                )

    return rows


# =====================================================
# Common data validation
# =====================================================

def _build(
    observations: list[
        tuple[str, pd.Period, float]
    ],
) -> pd.DataFrame:

    seen = set()
    rows = []

    periods = {
        metric: set()
        for metric in VARIABLES.values()
    }

    for metric, period, value in observations:
        key = (metric, period)

        if key in seen:
            raise ValueError(
                "IBGE duplicate published rate "
                f"{key}"
            )

        seen.add(key)
        periods[metric].add(period)

        rows.append(
            (
                "BR",
                period.start_time,
                metric,
                value,
                SOURCE,
                "%",
                "NSA",
            )
        )

    for metric, months in periods.items():
        if (
            len(months) < 60
            or START not in months
        ):
            raise ValueError(
                f"IBGE {metric}: insufficient "
                "published history "
                f"({len(months)} months)"
            )

    # Cross-check with official August 2026 release.
    checks = {
        (
            "ppi_mom",
            pd.Period("2026-08", freq="M"),
        ): 0.36,
        (
            "ppi_yoy",
            pd.Period("2026-08", freq="M"),
        ): 2.53,
    }

    for metric, month, value in observations:
        expected = checks.get(
            (metric, month)
        )

        if (
            expected is not None
            and abs(value - expected) > 0.30
        ):
            raise ValueError(
                f"IBGE {metric} {month}: "
                "official cross-check failed: "
                f"{value} vs {expected}"
            )

    frame = pd.DataFrame(
        rows,
        columns=COLS,
    )

    if frame.duplicated(
        ["country", "date", "metric"]
    ).any():
        raise ValueError(
            "IBGE: duplicate database key"
        )

    latest = max(
        max(months)
        for months in periods.values()
    )

    gaps = [
        f"{month}/{metric}"
        for metric, months in periods.items()
        for month in pd.period_range(
            START,
            latest,
            freq="M",
        )
        if month not in months
    ]

    result = (
        frame.sort_values(
            ["date", "metric"]
        )
        .reset_index(drop=True)
    )

    result.attrs["source_issues"] = tuple(
        gaps
    )

    return result


# =====================================================
# Fetch, with SIDRA as primary
# =====================================================

def fetch_brazil_ppi() -> pd.DataFrame:
    try:
        data = _build(
            parse_sidra(
                _get_json(
                    SIDRA_URL,
                    read_timeout=60,
                )
            )
        )

        print(
            "[IBGE] Official SIDRA values API"
        )

        return data

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            "[WARN] SIDRA route failed: "
            f"{type(exc).__name__}: {exc}"
        )

    # Only if SIDRA failed.
    end = (
        pd.Period(
            pd.Timestamp.now(),
            freq="M",
        ) - 1
    ).strftime("%Y%m")

    url = (
        f"{AGGREGATES_URL}/"
        f"periodos/202001-{end}/"
        "variaveis/1394%7C1396"
    )

    params = {
        "localidades": "N1[1]",
        "classificacao": "842[46608]",
    }

    data = _build(
        parse_aggregates(
            _get_json(
                url,
                params=params,
                read_timeout=35,
            )
        )
    )

    print(
        "[IBGE] Official Aggregates API v3 "
        "(fallback)"
    )

    return data


# =====================================================
# Standalone execution
# =====================================================

def run() -> int:
    try:
        frame = fetch_brazil_ppi()

        issues = tuple(
            frame.attrs.get(
                "source_issues", ()
            )
        )

        save_eurostat_extra(
            frame
        )

        for metric, chunk in frame.groupby(
            "metric"
        ):
            print(
                f"[OK] BR/{metric}: "
                f"{len(chunk)} months; "
                f"{chunk.date.min():%Y-%m} ... "
                f"{chunk.date.max():%Y-%m}; "
                "IBGE published percentages"
            )

        if issues:
            print(
                "[WARN] BR/IPP missing periods: "
                + ", ".join(issues)
            )
            return 1

        print(
            "[SUMMARY] BR/IPP official historical "
            "YoY and MoM updated"
        )

        return 0

    except (
        requests.RequestException,
        ValueError,
        OSError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            "[ERROR] BR/IPP: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run())
