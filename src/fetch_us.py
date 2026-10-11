import pandas as pd
from src.fetch_us_treasury import fetch_us_treasury
from src.fetch_us_bea import fetch_us_bea


def fetch_us_quarterly() -> pd.DataFrame:
    """
    Квартальные метрики США: Долг/ВВП, Бюджет/ВВП, Трейд/ВВП.

    Логика:
    - Берём квартальный ВВП (SAAR, млн $) из BEA.
    - Долг (на конец квартала, млн $) / ВВП × 100.
    - Бюджет (сумма за квартал, млн $) × 4 / ВВП × 100.
    - Трейд (за квартал, млн $) × 4 / ВВП × 100.
    - Показываем только те кварталы, где есть ВВП.
    """
    treasury = fetch_us_treasury()
    bea = fetch_us_bea()

    if treasury.empty or bea.empty:
        return pd.DataFrame()

    df = bea.merge(treasury, on="date", how="inner")
    df = df.dropna(subset=["gdp_usd_mn"])

    # Приводим долг к млн (Treasury — в $, BEA — в млн $)
    df["debt_mn"] = df["debt_usd"] / 1e6

    df["debt_gdp"] = df["debt_mn"] / df["gdp_usd_mn"] * 100
    df["budget_gdp"] = -df["deficit_usd"] / 1e6 * 4 / df["gdp_usd_mn"] * 100
    df["trade_gdp"] = df["trade_usd_mn"] * 4 / df["gdp_usd_mn"] * 100

    df["country"] = "US"

    return df[[
        "date", "country",
        "debt_gdp", "budget_gdp", "trade_gdp",
        "gdp_usd_mn", "debt_mn", "deficit_usd", "trade_usd_mn",
    ]].sort_values("date").reset_index(drop=True)
