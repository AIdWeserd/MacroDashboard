from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import pandas as pd

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
API_KEY = "sample"
STAT_CODE = "901Y009"
ITEM_CODE1 = "0"


def _build_periods(months_back: int = 36, chunk_size: int = 10) -> list[tuple[str, str]]:
    """
    Генерирует чанки по chunk_size месяцев, покрывающие последние months_back месяцев.
    ECOS с sample-ключом отдаёт максимум 10 строк на запрос, поэтому chunk_size=10.
    """
    now = datetime.now()
    end = now.replace(day=1)
    start = end - relativedelta(months=months_back)

    periods = []
    current = start
    while current <= end:
        chunk_end = current + relativedelta(months=chunk_size - 1)
        if chunk_end > end:
            chunk_end = end

        periods.append((
            current.strftime("%Y%m"),
            chunk_end.strftime("%Y%m"),
        ))

        current = chunk_end + relativedelta(months=1)

    return periods


def fetch_korea_cpi() -> pd.DataFrame:
    """
    Тянет CPI Кореи из ECOS.
    Возвращает DataFrame с колонками: date, country, value, mom, core.
        value — YoY headline, % (считается из индекса, pct_change(12))
        mom   — MoM headline, % (считается из индекса, pct_change(1))
        core  — Core YoY, % — недоступен через sample-ключ, всегда None
    """
    # 36 месяцев + ещё 12 для корректного YoY = ~48 месяцев запаса
    periods = _build_periods(months_back=48, chunk_size=10)
    all_rows = []

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=1))

    for start, end in periods:
        url = (
            f"{ECOS_BASE}/{API_KEY}/json/kr/"
            f"1/10/{STAT_CODE}/M/{start}/{end}/{ITEM_CODE1}/"
        )
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[WARN] Korea CPI chunk {start}-{end}: {e}")
            continue

        rows = data.get("StatisticSearch", {}).get("row", [])
        for rec in rows:
            time_str = rec.get("TIME", "")
            value_str = rec.get("DATA_VALUE")
            if not time_str or value_str is None:
                continue
            try:
                date = pd.to_datetime(time_str, format="%Y%m")
                value = float(value_str)
            except (ValueError, TypeError):
                continue
            all_rows.append({"date": date, "index": value})

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("[ERROR] Korea CPI: нет данных")
        return pd.DataFrame()

    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Сохраняем исходный индекс — от него считаем и MoM, и YoY
    raw_index = df["index"]
    df["mom"] = raw_index.pct_change(periods=1) * 100
    df["value"] = raw_index.pct_change(periods=12) * 100

    # Core через sample-ключ ECOS недоступен
    df["core"] = None

    # Отбрасываем строки без YoY (первые 12 месяцев)
    df = df.dropna(subset=["value"])

    df["country"] = "KR"
    df = df[["date", "country", "value", "mom", "core"]]

    # Оставляем последние 3 года
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_korea_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
