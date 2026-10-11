import requests
import pandas as pd
from io import StringIO

# dataseries.org — швейцарские временные ряды
DATASERIES_URL = "https://api.dataseries.org/series.csv"

# item-коды FSO:
#   100_100  — headline CPI (Total)
#   100_9490 — Core inflation 1 (Total excluding fresh and seasonal products, energy and fuel)
ITEM_HEADLINE = "100_100"
ITEM_CORE = "100_9490"


def _fetch_item(item: str) -> pd.DataFrame:
    """Тянет один item из dataseries.org. Возвращает DataFrame с колонками date, value."""
    url = f"{DATASERIES_URL}?dataset=ch_fso_cpi&dims=item={item}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text))
    if df.empty or "date" not in df.columns or "value" not in df.columns:
        return pd.DataFrame(columns=["date", "value"])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return df


def fetch_switzerland_cpi() -> pd.DataFrame:
    """
    Тянет CPI Швейцарии из dataseries.org (FSO):
        value — YoY headline, %
        mom   — MoM headline, %
        core  — YoY Core inflation 1, %
    Возвращает DataFrame с колонками: date, country, value, mom, core.
    """
    try:
        headline = _fetch_item(ITEM_HEADLINE)
        core = _fetch_item(ITEM_CORE)
    except Exception as e:
        print(f"[ERROR] Switzerland CPI: {e}")
        return pd.DataFrame()

    if headline.empty:
        print("[WARN] Switzerland CPI: пусто (headline)")
        return pd.DataFrame()

    # Считаем YoY и MoM из индекса headline
    raw = headline["value"]
    headline["mom"] = raw.pct_change(periods=1) * 100
    headline["value"] = raw.pct_change(periods=12) * 100

    # Core: считаем YoY из индекса Core
    core_yoy = core.copy()
    core_yoy["core"] = core_yoy["value"].pct_change(periods=12) * 100
    core_yoy = core_yoy[["date", "core"]]

    # Мерж
    df = headline.merge(core_yoy, on="date", how="left")
    df["country"] = "CH"
    df = df[["date", "country", "value", "mom", "core"]]
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_switzerland_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
