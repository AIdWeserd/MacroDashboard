import requests
import pandas as pd

STATCAN_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"

# Vector ID для CPI All-items (индекс, 2002=100) — Canada
CANADA_CPI_INDEX_VECTOR = 41690973

# Vector ID для CPI-trim (Core, YoY %) — Bank of Canada definition
CANADA_CPI_TRIM_VECTOR = 108785715


def _fetch_vector(vector_id: int, latest_n: int = 60) -> pd.DataFrame:
    """
    Тянет одну серию StatCan по vector ID.
    Возвращает DataFrame с колонками: date, value.
    """
    payload = [{"vectorId": vector_id, "latestN": latest_n}]

    r = requests.post(STATCAN_URL, json=payload, timeout=30)
    r.raise_for_status()

    data = r.json()
    if not data or data[0].get("status") != "SUCCESS":
        raise RuntimeError(f"bad status: {data[:1]}")

    points = data[0]["object"]["vectorDataPoint"]
    if not points:
        return pd.DataFrame(columns=["date", "value"])

    rows = []
    for pt in points:
        try:
            date = pd.to_datetime(pt["refPer"])
            value = float(pt["value"])
        except (ValueError, TypeError, KeyError):
            continue
        rows.append({"date": date, "value": value})

    if not rows:
        return pd.DataFrame(columns=["date", "value"])

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fetch_canada_cpi() -> pd.DataFrame:
    """
    Тянет CPI Канады из StatCan:
        value — YoY headline, % (из индекса, pct_change(12))
        mom   — MoM headline, % (из индекса, pct_change(1))
        core  — CPI-trim YoY, % (Bank of Canada preferred core)
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    try:
        index_df = _fetch_vector(CANADA_CPI_INDEX_VECTOR, latest_n=60)
        core_df = _fetch_vector(CANADA_CPI_TRIM_VECTOR, latest_n=60)
    except Exception as e:
        print(f"[ERROR] Canada CPI: {e}")
        return pd.DataFrame()

    if index_df.empty:
        print("[WARN] Canada CPI: пусто (index)")
        return pd.DataFrame()

    # Сохраняем исходный индекс в отдельной переменной,
    # чтобы MoM и YoY считались от одного и того же ряда.
    raw_index = index_df["value"]
    index_df["mom"] = raw_index.pct_change(periods=1) * 100
    index_df["value"] = raw_index.pct_change(periods=12) * 100

    # Core — уже готовый YoY, просто переименовываем
    core = core_df.rename(columns={"value": "core"})

    # Мержим
    df = index_df.merge(core, on="date", how="left")

    df["country"] = "CA"
    df = df[["date", "country", "value", "mom", "core"]]
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    return df


if __name__ == "__main__":
    df = fetch_canada_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))