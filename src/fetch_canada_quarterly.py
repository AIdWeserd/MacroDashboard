import time
import requests
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

BASE = "https://www150.statcan.gc.ca/t1/wds/rest"

START_DATE = pd.Timestamp("2024-01-01")

# (productId, coordinate, колонка)
SERIES = {
    "gdp_cad_mn": (36100104, "1.2.1.30.0.0.0.0.0.0"),  # GDP, Current prices, SAAR
    "debt_cad_mn": (36100467, "1.1.0.0.0.0.0.0.0.0"),  # Gross debt
    "budget_cad_mn": (36100118, "1.2.1.74.0.0.0.0.0.0"),  # Net lending/borrowing, Unadjusted
    "ca_cad_mn": (36100018, "1.3.1.0.0.0.0.0.0.0"),  # Current Account Balance, SA
}


def _get_points(product_id: int, coordinate: str, latest_n: int = 20,
                retries: int = 3) -> pd.DataFrame:
    url = f"{BASE}/getDataFromCubePidCoordAndLatestNPeriods"
    payload = [{
        "productId": product_id,
        "coordinate": coordinate,
        "latestN": latest_n,
    }]
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=90)
            r.raise_for_status()
            data = r.json()
            if not (isinstance(data, list) and data):
                return pd.DataFrame()
            obj = data[0].get("object", {})
            points = obj.get("vectorDataPoint", [])
            if not points:
                return pd.DataFrame()
            rows = []
            for p in points:
                try:
                    ts = pd.Timestamp(p["refPer"])
                    val = float(p["value"]) if p.get("value") not in (None, "") else None
                except (ValueError, TypeError, KeyError):
                    continue
                rows.append({"date": ts, "value": val})
            return pd.DataFrame(rows).dropna().sort_values("date").reset_index(drop=True)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"StatCan не ответил по {product_id}/{coordinate}: {last_err}")


def fetch_canada_quarterly() -> pd.DataFrame:
    """
    Квартальные метрики Канады из StatCan WDS.

    - debt_gdp   = Gross Debt / GDP (SAAR) × 100
    - budget_gdp = Net Lending/Borrowing (Unadjusted, quarterly) / (GDP / 4) × 100
    - trade_gdp  = Current Account Balance / (GDP / 4) × 100
    """
    frames = {}
    for col, (pid, coord) in SERIES.items():
        df = _get_points(pid, coord, latest_n=20)
        if df.empty:
            print(f"[WARN] Canada {col}: пусто")
            return pd.DataFrame()
        df = df.rename(columns={"value": col})
        frames[col] = df

    result = frames["gdp_cad_mn"]
    for col in ["debt_cad_mn", "budget_cad_mn", "ca_cad_mn"]:
        result = result.merge(frames[col], on="date", how="inner")

    # GDP в SAAR — для бюджета и трейда переводим в квартальное значение (÷ 4)
    result["gdp_q_cad_mn"] = result["gdp_cad_mn"] / 4

    result["debt_gdp"] = result["debt_cad_mn"] / result["gdp_cad_mn"] * 100
    result["budget_gdp"] = result["budget_cad_mn"] / result["gdp_q_cad_mn"] * 100
    result["trade_gdp"] = result["ca_cad_mn"] / result["gdp_q_cad_mn"] * 100

    result["country"] = "CA"
    result = result[result["date"] >= START_DATE].reset_index(drop=True)

    return result[["date", "country", "debt_gdp", "budget_gdp", "trade_gdp"]]
