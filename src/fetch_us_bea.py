
import time

import pandas as pd
import requests

from config import BEA_API_KEY, FRED_API_KEY


BEA_BASE = "https://apps.bea.gov/api/data/"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
START_YEAR = 2020


def _requested_years() -> str:
    """История с 2020 года до текущего календарного года."""
    return ",".join(
        str(year)
        for year in range(START_YEAR, pd.Timestamp.now().year + 1)
    )


def _get(params: dict, retries: int = 3) -> dict:
    last_error = None

    for attempt in range(retries):
        try:
            response = requests.get(
                BEA_BASE,
                params=params,
                timeout=90,
            )
            response.raise_for_status()

            data = response.json()
            results = data.get("BEAAPI", {}).get("Results", {})

            if (
                not isinstance(results, dict)
                or not isinstance(results.get("Data"), list)
            ):
                raise ValueError("BEA: ответ без массива Data")

            return data

        except (requests.RequestException, ValueError) as exc:
            last_error = exc

            if attempt + 1 < retries:
                time.sleep(2 ** attempt)

    # Исключения requests могут содержать URL с UserID.
    raise RuntimeError(
        "BEA: запрос не выполнен "
        f"({type(last_error).__name__}); ключ API скрыт"
    ) from None


def _parse_time_period(value: str) -> pd.Timestamp:
    year, quarter = str(value).split("Q")
    quarter = int(quarter)

    if quarter not in (1, 2, 3, 4):
        raise ValueError("Некорректный квартал BEA")

    return pd.Timestamp(
        year=int(year),
        month=(quarter - 1) * 3 + 1,
        day=1,
    )


def fetch_us_gdp() -> pd.DataFrame:
    """Квартальный номинальный ВВП BEA, SAAR, млн USD."""
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": "T10105",
        "Frequency": "Q",
        "Year": _requested_years(),
        "ResultFormat": "JSON",
    }

    rows = _get(params)["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)

    df = df[df["SeriesCode"] == "A191RC"].copy()
    df["date"] = df["TimePeriod"].map(_parse_time_period)

    df["gdp_usd_mn"] = pd.to_numeric(
        df["DataValue"].astype(str).str.replace(
            ",", "", regex=False
        ),
        errors="coerce",
    )

    return (
        df[["date", "gdp_usd_mn"]]
        .dropna()
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_us_current_account() -> pd.DataFrame:
    """Квартальный текущий счёт BEA ITA, BalCurrAcct, QSA."""
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "ITA",
        "Indicator": "BalCurrAcct",
        "AreaOrCountry": "AllCountries",
        "Frequency": "QSA",
        "Year": _requested_years(),
        "ResultFormat": "JSON",
    }

    rows = _get(params)["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)

    df["date"] = df["TimePeriod"].map(_parse_time_period)

    df["trade_usd_mn"] = pd.to_numeric(
        df["DataValue"].astype(str).str.replace(
            ",", "", regex=False
        ),
        errors="coerce",
    )

    return (
        df[["date", "trade_usd_mn"]]
        .dropna()
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_us_bea() -> pd.DataFrame:
    """Квартальные данные BEA: GDP + Current Account."""
    gdp = fetch_us_gdp()
    ca = fetch_us_current_account()

    if gdp.empty or ca.empty:
        print("[WARN] BEA US: GDP или Current Account пуст")
        return pd.DataFrame()

    result = gdp.merge(ca, on="date", how="outer")
    result["country"] = "US"

    return result.sort_values("date").reset_index(drop=True)


def _fetch_nipa_annual(
    table: str,
    year: str,
) -> pd.DataFrame:
    """Годовой Net lending or net borrowing из NIPA."""
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": table,
        "Frequency": "A",
        "Year": year,
        "ResultFormat": "JSON",
    }

    rows = _get(params)["BEAAPI"]["Results"]["Data"]
    df = pd.DataFrame(rows)

    mask = df["LineDescription"].str.contains(
        "Net lending or net borrowing",
        case=False,
        na=False,
    )

    sub = df[mask].copy()

    if sub.empty:
        return pd.DataFrame(columns=["date", "value"])

    sub["date"] = pd.to_datetime(
        sub["TimePeriod"].astype(str) + "-01-01"
    )

    sub["value"] = pd.to_numeric(
        sub["DataValue"].astype(str).str.replace(
            ",", "", regex=False
        ),
        errors="coerce",
    )

    return sub[["date", "value"]].dropna()


def fetch_us_general_gov_debt_annual() -> pd.DataFrame:
    """Годовой General Gov Gross Debt (% GDP), FRED/IMF."""
    if not FRED_API_KEY:
        print("[WARN] FRED_API_KEY не задан")
        return pd.DataFrame()

    params = {
        "series_id": "USAGGXWDGGDP",
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": f"{START_YEAR}-01-01",
    }

    try:
        response = requests.get(
            FRED_BASE,
            params=params,
            timeout=60,
        )
        response.raise_for_status()

        observations = response.json().get(
            "observations", []
        )

    except (requests.RequestException, ValueError) as exc:
        print(
            "[WARN] FRED USAGGXWDGGDP:",
            type(exc).__name__,
        )
        return pd.DataFrame()

    if not observations:
        return pd.DataFrame()

    df = pd.DataFrame(observations)[["date", "value"]]

    df["date"] = pd.to_datetime(
        df["date"], errors="coerce"
    )
    df["debt_gdp"] = pd.to_numeric(
        df["value"], errors="coerce"
    )

    df = (
        df[["date", "debt_gdp"]]
        .dropna()
        .sort_values("date")
    )

    # Годовые факты: не включаем текущий и будущие годы.
    df = df[
        df["date"].dt.year < pd.Timestamp.now().year
    ]

    df["country"] = "US"

    return df.reset_index(drop=True)


def _complete_year_mean(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """Среднее значение только за полный завершённый год."""
    if frame.empty:
        return pd.DataFrame(columns=["date", column])

    df = frame[["date", column]].dropna().copy()
    df["year"] = df["date"].dt.year

    df = df[
        df["year"] < pd.Timestamp.now().year
    ]

    annual = df.groupby("year")[column].agg(
        ["mean", "count"]
    )

    # Нельзя считать годовое значение из 1–3 кварталов.
    annual = annual[annual["count"] == 4]

    result = (
        annual[["mean"]]
        .reset_index()
        .rename(columns={"mean": column})
    )

    result["date"] = pd.to_datetime(
        result["year"].astype(str) + "-01-01"
    )

    return result[["date", column]]


def fetch_us_general_gov_annual() -> pd.DataFrame:
    """
    Годовой General Government.

    Методологии сохранены:
    budget_gdp = (T30100 + T30300) / GDP * 100
    trade_gdp  = Current Account / GDP * 100
    debt_gdp   = FRED USAGGXWDGGDP
    """
    years = _requested_years()

    fed = _fetch_nipa_annual("T30100", years)
    state_local = _fetch_nipa_annual("T30300", years)

    if fed.empty or state_local.empty:
        return pd.DataFrame()

    fed = fed.rename(columns={"value": "federal"})
    state_local = state_local.rename(
        columns={"value": "state_local"}
    )

    df = fed.merge(
        state_local,
        on="date",
        how="inner",
    )

    df["general_gov"] = (
        df["federal"] + df["state_local"]
    )

    gdp = _complete_year_mean(
        fetch_us_gdp(),
        "gdp_usd_mn",
    )

    if gdp.empty:
        return pd.DataFrame()

    df = df.merge(gdp, on="date", how="inner")

    df["budget_gdp"] = (
        df["general_gov"] / df["gdp_usd_mn"] * 100
    )

    ca = _complete_year_mean(
        fetch_us_current_account(),
        "trade_usd_mn",
    )

    df = df.merge(ca, on="date", how="left")

    df["trade_gdp"] = (
        df["trade_usd_mn"] / df["gdp_usd_mn"] * 100
    )

    debt = fetch_us_general_gov_debt_annual()

    if debt.empty:
        raise RuntimeError(
            "US General Gov: годовая серия долга FRED недоступна"
        )

    debt = debt[
        ["date", "debt_gdp"]
    ].drop_duplicates("date", keep="last")

    df = df.merge(debt, on="date", how="left")

    df["country"] = "US"

    return (
        df[
            [
                "date",
                "country",
                "budget_gdp",
                "trade_gdp",
                "debt_gdp",
                "gdp_usd_mn",
            ]
        ]
        .sort_values("date")
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    print("=== General Gov Annual ===")
    print(
        fetch_us_general_gov_annual()
        .to_string(index=False)
    )
