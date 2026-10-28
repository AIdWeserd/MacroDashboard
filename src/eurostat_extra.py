
"""Official Eurostat series and shared official PPI storage.

Uses published observations only.
No calculation of economic growth rates.
"""

from __future__ import annotations

import sqlite3
import time

from contextlib import closing
from dataclasses import dataclass

import pandas as pd
import requests

from config import DB_PATH
from src.euro_area_geo import (
    EURO_AREA_GEOS,
    keep_period_geo,
)
from src.fetch_eurostat_quarterly import _parse_jsonstat


API = (
    "https://ec.europa.eu/eurostat/api/"
    "dissemination/statistics/1.0/data"
)

COUNTRIES = {
    "EU": "EA21",
    "DE": "DE",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
}

GEOS = list(dict.fromkeys([
    *COUNTRIES.values(),
    *EURO_AREA_GEOS,
]))

GEO_TO_COUNTRY = {
    value: key
    for key, value in COUNTRIES.items()
}

GEO_TO_COUNTRY.update({
    geo: "EU"
    for geo in EURO_AREA_GEOS
})

TABLE = "official_eurostat_extra"

MONTHS = (
    "", "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


@dataclass(frozen=True)
class Series:
    metric: str
    dataset: str
    freq: str
    unit: str
    s_adj: str
    filters: dict
    label: str


SERIES = {
    "ppi_yoy": Series(
        "ppi_yoy",
        "sts_inppd_m",
        "M",
        "PCH_SM",
        "NSA",
        {
            "indic_bt": "PRC_PRR_DOM",
            "nace_r2": "B-E36",
        },
        "PPI domestic industrial, YoY %, NSA",
    ),
    "ppi_mom": Series(
        "ppi_mom",
        "sts_inppd_m",
        "M",
        "PCH_PRE",
        "NSA",
        {
            "indic_bt": "PRC_PRR_DOM",
            "nace_r2": "B-E36",
        },
        "PPI domestic industrial, MoM %, NSA",
    ),
    "gdp_qoq": Series(
        "gdp_qoq",
        "namq_10_gdp",
        "Q",
        "CLV_PCH_PRE",
        "SCA",
        {
            "na_item": "B1GQ",
        },
        "Real GDP, QoQ %, SCA",
    ),
}


def fetch_eurostat_extra(
    metric: str,
) -> pd.DataFrame:
    """Download exactly one official Eurostat series."""

    if metric not in SERIES:
        raise ValueError(
            f"Unknown Eurostat metric: {metric}"
        )

    spec = SERIES[metric]

    params = {
        "format": "JSON",
        "lang": "EN",
        "freq": spec.freq,
        "unit": spec.unit,
        "s_adj": spec.s_adj,
        "geo": GEOS,
        "lastTimePeriod": 36,
        **spec.filters,
    }

    max_attempts = 3

    for attempt in range(
        1, max_attempts + 1
    ):
        try:
            print(
                f"[HTTP] Eurostat {metric}: "
                f"attempt={attempt}/{max_attempts}, "
                "timeout=(20, 90)"
            )

            response = requests.get(
                f"{API}/{spec.dataset}",
                params=params,
                timeout=(20, 90),
            )

            response.raise_for_status()
            break

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
        ) as exc:
            http_status = getattr(
                getattr(
                    exc, "response", None
                ),
                "status_code",
                None,
            )

            temporary = (
                isinstance(
                    exc,
                    requests.exceptions.Timeout,
                )
                or (
                    isinstance(
                        exc,
                        requests.exceptions.ConnectionError,
                    )
                    and not isinstance(
                        exc,
                        requests.exceptions.SSLError,
                    )
                )
                or http_status in {
                    429, 500, 502, 503, 504,
                }
            )

            if (
                not temporary
                or attempt >= max_attempts
            ):
                raise

            pause = 1.5 * (
                2 ** (attempt - 1)
            )

            print(
                f"[WARN] Eurostat {metric}: "
                f"{type(exc).__name__}; "
                f"retry in {pause:g} s"
            )

            time.sleep(pause)

    frame = _parse_jsonstat(
        response.json()
    )

    if frame.empty:
        print(
            f"[WARN] Eurostat {metric}: "
            "empty official series"
        )

        return pd.DataFrame(
            columns=[
                "country", "date", "metric",
                "value", "source", "unit",
                "adjustment",
            ]
        )

    expected = {
        "geo", "time", "value",
        "unit", "s_adj", "freq",
    }

    if not expected.issubset(
        frame.columns
    ):
        raise ValueError(
            f"Eurostat {metric}: missing dimensions: "
            f"{expected - set(frame.columns)}"
        )

    frame = frame.loc[
        (frame.unit == spec.unit)
        & (frame.s_adj == spec.s_adj)
        & (frame.freq == spec.freq)
    ].copy()

    for key, value in spec.filters.items():
        if key not in frame.columns:
            raise ValueError(
                f"Eurostat {metric}: "
                f"missing dimension {key}"
            )

        frame = frame.loc[
            frame[key] == value
        ]

    frame["date"] = frame[
        "time"
    ].map(_period_date)

    frame = frame.dropna(
        subset=["date", "value"]
    )

    frame = keep_period_geo(
        frame,
        "geo",
        "date",
    )

    frame["country"] = frame.geo.map(
        GEO_TO_COUNTRY
    )

    frame = frame.dropna(
        subset=["country"]
    )

    frame["metric"] = metric
    frame["source"] = (
        f"Eurostat/{spec.dataset}"
    )
    frame["unit"] = spec.unit
    frame["adjustment"] = spec.s_adj

    result = frame[
        [
            "country", "date", "metric",
            "value", "source", "unit",
            "adjustment",
        ]
    ].copy()

    result["value"] = pd.to_numeric(
        result.value,
        errors="coerce",
    )

    result = result.dropna(
        subset=["value"]
    )

    result = result.drop_duplicates(
        ["country", "date", "metric"],
        keep="last",
    )

    print(
        f"[OK] Eurostat {metric}: "
        f"{len(result)} rows; "
        f"{result.country.nunique()} geographies"
    )

    return result.sort_values(
        ["country", "date"]
    ).reset_index(drop=True)


def _period_date(
    code: str,
) -> pd.Timestamp:
    """Keep monthly and quarterly periods distinct."""

    try:
        period = pd.Period(
            str(code),
            freq=(
                "Q"
                if "-Q" in str(code)
                else "M"
            ),
        )

        return period.end_time.normalize()

    except (TypeError, ValueError):
        return pd.NaT


def save_eurostat_extra(
    data: pd.DataFrame,
) -> None:
    """Upsert official data, leaving unrelated tables unchanged."""

    if data is None or data.empty:
        raise ValueError(
            "No official observations to save"
        )

    required = {
        "country", "date", "metric",
        "value", "source", "unit",
        "adjustment",
    }

    if not required.issubset(
        data.columns
    ):
        raise ValueError(
            "Incomplete official observations"
        )

    source = data.copy()

    source["date"] = pd.to_datetime(
        source.date,
        errors="coerce",
    )

    source["value"] = pd.to_numeric(
        source.value,
        errors="coerce",
    )

    if source[
        ["country", "date", "metric", "value"]
    ].isna().any().any():
        raise ValueError(
            "Null key or value: refusing write"
        )

    if not set(
        source.metric
    ).issubset(SERIES):
        raise ValueError(
            "Unknown metric: refusing write"
        )

    source = source.drop_duplicates(
        ["country", "date", "metric"],
        keep="last",
    )

    # Explicitly close connections for Windows.
    with closing(
        sqlite3.connect(
            str(DB_PATH),
            timeout=30,
        )
    ) as con:
        with con:
            _ensure_table(con)

            con.executemany(
                f"""
                INSERT INTO {TABLE}
                    (
                        country, date, metric,
                        value, source, unit,
                        adjustment
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(country, date, metric)
                DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    unit = excluded.unit,
                    adjustment = excluded.adjustment
                """,
                [
                    (
                        str(row.country),
                        row.date.strftime(
                            "%Y-%m-%d"
                        ),
                        str(row.metric),
                        float(row.value),
                        str(row.source),
                        str(row.unit),
                        str(row.adjustment),
                    )
                    for row in source.itertuples(
                        index=False
                    )
                ],
            )

    print(
        f"[SAVE] {TABLE}: "
        f"{len(source)} observations updated"
    )


def _ensure_table(
    con: sqlite3.Connection,
) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            country TEXT NOT NULL,
            date TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT NOT NULL,
            unit TEXT NOT NULL,
            adjustment TEXT NOT NULL,
            PRIMARY KEY(country, date, metric)
        )
        """
    )


def load_eurostat_extra() -> pd.DataFrame:
    """Read saved observations without creating tables."""

    cols = [
        "country", "date", "metric",
        "value", "source", "unit",
        "adjustment",
    ]

    if not DB_PATH.is_file():
        return pd.DataFrame(
            columns=cols
        )

    uri = (
        DB_PATH.resolve().as_uri()
        + "?mode=ro"
    )

    with closing(
        sqlite3.connect(
            uri,
            uri=True,
            timeout=15,
        )
    ) as con:
        exists = con.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table'
              AND name=?
            """,
            (TABLE,),
        ).fetchone()

        if not exists:
            return pd.DataFrame(
                columns=cols
            )

        df = pd.read_sql_query(
            f"""
            SELECT {', '.join(cols)}
            FROM {TABLE}
            """,
            con,
        )

    df["date"] = pd.to_datetime(
        df.date,
        errors="coerce",
    )

    return df.dropna(
        subset=["date", "value"]
    )


def _source_short(
    source: str,
) -> str:
    """Use the real publisher instead of assuming Eurostat."""

    source = str(source)

    if source.startswith("Eurostat/"):
        return "Eurostat"

    if source == "BLS/Final Demand":
        return "BLS, Final Demand"

    if source == "BoJ/CGPI":
        return "BoJ, CGPI"

    return source or "источник не указан"


def _series_description(
    metric: str,
    source: str,
) -> str:
    if metric in (
        "ppi_yoy", "ppi_mom"
    ):
        suffix = (
            "YoY"
            if metric == "ppi_yoy"
            else "MoM"
        )

        if source == "BLS/Final Demand":
            return (
                f"Final Demand PPI {suffix}, % (BLS)"
            )

        if source == "BoJ/CGPI":
            return (
                f"CGPI {suffix}, % (BoJ)"
            )

    return SERIES[metric].label


def enrich_summary(
    summary: pd.DataFrame,
    extra: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Add supplemental indicators without changing existing ones."""

    result = summary.copy()

    cutoff = pd.Period(
        f"{year}-{month:02d}",
        freq="M",
    ).end_time.normalize()

    for metric in SERIES:
        result[metric] = None
        result[f"{metric}_date"] = None

    if extra is None or extra.empty:
        return result

    eligible = extra.loc[
        extra.date.le(cutoff)
    ].sort_values("date")

    latest = eligible.drop_duplicates(
        ["country", "metric"],
        keep="last",
    )

    for obs in latest.itertuples(
        index=False
    ):
        if obs.metric not in SERIES:
            continue

        mask = result.country.eq(
            obs.country
        )

        if not mask.any():
            continue

        date = pd.Timestamp(
            obs.date
        )

        label = (
            f"Q{date.quarter} {date.year}"
            if obs.metric == "gdp_qoq"
            else f"{MONTHS[date.month]} {date.year}"
        )

        result.loc[
            mask, obs.metric
        ] = round(
            float(obs.value),
            2,
        )

        result.loc[
            mask, f"{obs.metric}_date"
        ] = (
            f"{label} "
            f"({_source_short(obs.source)}, "
            f"{obs.adjustment})"
        )

    return result


def previous_published(
    extra: pd.DataFrame,
    countries: list[str],
    year: int,
    month: int,
) -> pd.DataFrame:
    """Compare adjacent published observations, not weekly snapshots."""

    fields = [
        "Страна",
        "Показатель",
        "Текущий период",
        "Текущее",
        "Предыдущий период",
        "Предыдущее",
    ]

    if extra is None or extra.empty:
        return pd.DataFrame(
            columns=fields
        )

    cutoff = pd.Period(
        f"{year}-{month:02d}",
        freq="M",
    ).end_time.normalize()

    frame = extra.loc[
        extra.date.le(cutoff)
        & extra.country.isin(countries)
    ]

    rows = []

    for (country, metric), x in frame.groupby(
        ["country", "metric"]
    ):
        if metric not in SERIES:
            continue

        x = (
            x.sort_values("date")
            .drop_duplicates(
                "date",
                keep="last",
            )
            .tail(2)
        )

        if len(x) < 2:
            continue

        past, latest = (
            x.iloc[-2],
            x.iloc[-1],
        )

        rows.append(
            {
                "Страна": country,
                "Показатель": _series_description(
                    metric,
                    str(latest.source),
                ),
                "Текущий период": str(
                    latest.date.date()
                ),
                "Текущее": float(
                    latest.value
                ),
                "Предыдущий период": str(
                    past.date.date()
                ),
                "Предыдущее": float(
                    past.value
                ),
            }
        )

    return pd.DataFrame(
        rows,
        columns=fields,
    )
