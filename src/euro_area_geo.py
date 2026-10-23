"""One geographic meaning for the dashboard code EU: the euro area, not EU27.

The code EU is a legacy dashboard identifier; geographic composition follows the
reference period. These composition changes are documented by Eurostat.
"""

import pandas as pd

EURO_AREA_GEOS = ("EA19", "EA20", "EA21")


def all_requested_geos(country_to_geo: dict[str, str]) -> list[str]:
    """Always request every euro-area vintage needed for the saved history."""
    return list(dict.fromkeys([*country_to_geo.values(), *EURO_AREA_GEOS]))


def geo_for_year(year: int) -> str:
    """Euro-area membership for observations from 2015 onward."""
    if year >= 2026:
        return "EA21"
    if year >= 2023:
        return "EA20"
    return "EA19"


def keep_period_geo(frame: pd.DataFrame, geo_col: str, date_col: str) -> pd.DataFrame:
    """Keep one euro-area vintage for each reference year; preserve other geos."""
    if frame.empty:
        return frame
    result = frame.copy()
    geo = result[geo_col].astype(str)
    dates = pd.to_datetime(result[date_col], errors="coerce")
    expected = dates.dt.year.map(
        lambda year: geo_for_year(int(year)) if pd.notna(year) else ""
    )
    mask = (~geo.isin(EURO_AREA_GEOS)) | geo.eq(expected)
    return result.loc[mask].copy()
