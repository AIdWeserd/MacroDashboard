
import time

import pandas as pd
import requests


BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
START_DATE = pd.Timestamp("2020-01-01")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Исходные координаты официальных рядов сохранены.
SERIES = {
    "gdp_cad_mn": (
        36100104,
        "1.2.1.30.0.0.0.0.0.0",
    ),
    "debt_cad_mn": (
        36100467,
        "1.1.0.0.0.0.0.0.0.0",
    ),
    "budget_cad_mn": (
        36100118,
        "1.2.1.74.0.0.0.0.0.0",
    ),
    "ca_cad_mn": (
        36100018,
        "1.3.1.0.0.0.0.0.0.0",
    ),
}


def _quarters_to_request() -> int:
    """Динамическая глубина с начала 2020 года."""
    current = pd.Timestamp.now().to_period("Q")
    start = START_DATE.to_period("Q")

    return max(
        1,
        current.ordinal - start.ordinal + 5,
    )


def _get_points(
    product_id: int,
    coordinate: str,
    latest_n: int = None,
    retries: int = 3,
) -> pd.DataFrame:
    url = (
        f"{BASE}/"
        "getDataFromCubePidCoordAndLatestNPeriods"
    )

    payload = [
        {
            "productId": product_id,
            "coordinate": coordinate,
            "latestN": (
                latest_n
                if latest_n is not None
                else _quarters_to_request()
            ),
        }
    ]

    last_error = None

    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                headers=HEADERS,
                json=payload,
                timeout=90,
            )
            response.raise_for_status()

            data = response.json()

            if not (
                isinstance(data, list)
                and data
            ):
                raise ValueError(
                    "Неожиданный формат StatCan"
                )

            if data[0].get("status") != "SUCCESS":
                raise ValueError(
                    "Неуспешный статус StatCan"
                )

            obj = data[0].get("object") or {}

            if not isinstance(obj, dict):
                raise ValueError(
                    "Некорректный объект StatCan"
                )

            points = obj.get(
                "vectorDataPoint", []
            )

            if not points:
                return pd.DataFrame(
                    columns=["date", "value"]
                )

            rows = []

            for point in points:
                try:
                    date = pd.Timestamp(
                        point["refPer"]
                    )

                    value = pd.to_numeric(
                        point.get("value"),
                        errors="coerce",
                    )

                except (
                    ValueError,
                    TypeError,
                    KeyError,
                ):
                    continue

                rows.append(
                    {
                        "date": date,
                        "value": value,
                    }
                )

            if not rows:
                return pd.DataFrame(
                    columns=["date", "value"]
                )

            return (
                pd.DataFrame(rows)
                .dropna()
                .drop_duplicates("date", keep="last")
                .sort_values("date")
                .reset_index(drop=True)
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ) as exc:
            last_error = exc

            if attempt + 1 < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"StatCan {product_id}: запрос не выполнен "
        f"({type(last_error).__name__})"
    ) from None


def fetch_canada_quarterly() -> pd.DataFrame:
    """
    Квартальные показатели Канады.

    Формулы debt_gdp, budget_gdp и trade_gdp
    сохранены из исходной версии.
    """
    frames = {}

    for column, (product_id, coordinate) in SERIES.items():
        df = _get_points(
            product_id,
            coordinate,
        )

        if df.empty:
            print(
                f"[WARN] Canada {column}: пусто"
            )
            return pd.DataFrame()

        frames[column] = df.rename(
            columns={"value": column}
        )

    result = frames["gdp_cad_mn"]

    for column in (
        "debt_cad_mn",
        "budget_cad_mn",
        "ca_cad_mn",
    ):
        result = result.merge(
            frames[column],
            on="date",
            how="inner",
        )

    # Проверенные ранее формулы не меняем.
    result["gdp_q_cad_mn"] = (
        result["gdp_cad_mn"] / 4
    )

    result["debt_gdp"] = (
        result["debt_cad_mn"]
        / result["gdp_cad_mn"]
        * 100
    )

    result["budget_gdp"] = (
        result["budget_cad_mn"]
        / result["gdp_q_cad_mn"]
        * 100
    )

    result["trade_gdp"] = (
        result["ca_cad_mn"]
        / result["gdp_q_cad_mn"]
        * 100
    )

    result["country"] = "CA"

    current_quarter = (
        pd.Timestamp.now().to_period("Q")
    )

    result = result[
        (result["date"] >= START_DATE)
        & (
            result["date"].dt.to_period("Q")
            < current_quarter
        )
    ]

    return (
        result[
            [
                "date",
                "country",
                "debt_gdp",
                "budget_gdp",
                "trade_gdp",
            ]
        ]
        .sort_values("date")
        .reset_index(drop=True)
    )
