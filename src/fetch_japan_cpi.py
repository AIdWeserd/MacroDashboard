import requests
import xml.etree.ElementTree as ET
import pandas as pd
from config import ESTAT_APP_ID

ESTAT_URL = "https://api.e-stat.go.jp/rest/3.0/app/getStatsData"

# 2025年基準 CPI
STATS_DATA_ID = "0004052037"

# Срезы e-Stat:
#   cdTab  — тип показателя (2 = MoM SA, 3 = YoY)
#   cat01  — категория (0001 = all items, 0161 = ex fresh food)
SLICES = {
    "value": {"cd_tab": "3", "cd_cat01": "0001"},  # YoY headline
    "mom": {"cd_tab": "2", "cd_cat01": "0001"},  # MoM headline (SA)
    "core": {"cd_tab": "3", "cd_cat01": "0161"},  # Core YoY (ex fresh food)
}


def _fetch_slice(cd_tab: str, cd_cat01: str) -> pd.DataFrame:
    """
    Тянет один срез CPI из e-Stat.
    Возвращает DataFrame с колонками: date, value.
    """
    params = {
        "appId": ESTAT_APP_ID,
        "statsDataId": STATS_DATA_ID,
        "cdTab": cd_tab,
        "cdCat01": cd_cat01,
        "cdArea": "00000",
        "limit": "60",  # последние 60 месяцев
        "metaGetFlg": "N",
    }

    r = requests.get(ESTAT_URL, params=params, timeout=60)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    rows = []
    for value_elem in root.iter("VALUE"):
        time_code = value_elem.get("time", "")
        value_str = value_elem.text
        if not time_code or value_str is None:
            continue
        try:
            year = int(time_code[:4])
            month = int(time_code[6:8])
            date = pd.Timestamp(year=year, month=month, day=1)
            value = float(value_str)
        except (ValueError, TypeError):
            continue
        rows.append({"date": date, "value": value})

    if not rows:
        return pd.DataFrame(columns=["date", "value"])

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fetch_japan_cpi() -> pd.DataFrame:
    """
    Тянет CPI Японии через e-Stat:
        value — YoY headline (cdTab=3, cat01=0001)
        mom   — MoM headline, SA (cdTab=2, cat01=0001)
        core  — Core YoY, ex fresh food (cdTab=3, cat01=0161)
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    if not ESTAT_APP_ID:
        print("[ERROR] Japan CPI: ESTAT_APP_ID не задан в .env")
        return pd.DataFrame()

    try:
        yoy = _fetch_slice(**SLICES["value"]).rename(columns={"value": "value"})
        mom = _fetch_slice(**SLICES["mom"]).rename(columns={"value": "mom"})
        core = _fetch_slice(**SLICES["core"]).rename(columns={"value": "core"})
    except Exception as e:
        print(f"[ERROR] Japan CPI: {e}")
        return pd.DataFrame()

    if yoy.empty:
        print("[WARN] Japan CPI: пусто (YoY)")
        return pd.DataFrame()

    df = yoy.merge(mom, on="date", how="left").merge(core, on="date", how="left")
    df["country"] = "JP"
    df = df[["date", "country", "value", "mom", "core"]]

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_japan_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
