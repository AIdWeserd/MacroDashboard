import pandas as pd
from src.fetch_us_treasury import fetch_us_treasury
from src.fetch_us_bea import fetch_us_bea


def fetch_us_quarterly() -> pd.DataFrame:
    """
    Квартальные метрики США (любой месяц, кроме декабря):
    - debt_gdp   — Federal (Treasury)
    - budget_gdp — Federal (Treasury, MTS)
    - trade_gdp  — Current Account (BEA ITA)
    """
    treasury = fetch_us_treasury()
    bea = fetch_us_bea()

    if treasury.empty or bea.empty:
        return pd.DataFrame()

    df = bea.merge(treasury, on="date", how="inner")
    df = df.dropna(subset=["gdp_usd_mn"])

    df["debt_mn"] = df["debt_usd"] / 1e6
    df["debt_gdp"] = df["debt_mn"] / df["gdp_usd_mn"] * 100
    df["budget_gdp"] = -df["deficit_usd"] / 1e6 * 4 / df["gdp_usd_mn"] * 100
    df["trade_gdp"] = df["trade_usd_mn"] / df["gdp_usd_mn"] * 100

    df["country"] = "US"
    return df[[
        "date", "country",
        "debt_gdp", "budget_gdp", "trade_gdp",
        "gdp_usd_mn", "debt_mn", "deficit_usd", "trade_usd_mn",
    ]].sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    print(fetch_us_quarterly().tail(5).to_string(index=False))
