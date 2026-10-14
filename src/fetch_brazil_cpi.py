import time
import requests
import pandas as pd

BRAZIL_CPI_URL = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2265,63/p/last%2024"

MOM_LABEL = "IPCA - Variação mensal"
YOY_LABEL = "IPCA - Variação acumulada em 12 meses"


def _fetch_sidra(url: str, retries: int = 3, timeout: int = 60) -> list | None:
    """Тянет SIDRA с retry. Возвращает JSON-список или None."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries:
                print(f"[ERROR] SIDRA: {e}")
                return None
            wait = 3 * attempt
            print(f"[RETRY] SIDRA: {e}, попытка {attempt}/{retries}, пауза {wait}s")
            time.sleep(wait)
    return None


def fetch_brazil_cpi() -> pd.DataFrame:
    """
    Тянет IPCA Бразилии (YoY + MoM) из IBGE SIDRA, таблица 1737.
    Возвращает DataFrame с колонками: date, country, value, mom, core.
        value — YoY headline, %
        mom   — MoM headline, %
        core  — Core YoY, % — IBGE не публикует Core в SIDRA, всегда None
    """
    data = _fetch_sidra(BRAZIL_CPI_URL)
    if not data or not isinstance(data, list) or len(data) < 2:
        print("[ERROR] Brazil CPI: пустой ответ")
        return pd.DataFrame()

    yoy_by_date = {}
    mom_by_date = {}

    for rec in data[1:]:
        d3c = rec.get("D3C", "")
        if not d3c or len(d3c) < 6:
            continue
        try:
            date = pd.Timestamp(year=int(d3c[:4]), month=int(d3c[4:6]), day=1)
            value = float(rec.get("V"))
        except (ValueError, TypeError):
            continue

        label = rec.get("D2N", "")
        if label == YOY_LABEL:
            yoy_by_date[date] = value
        elif label == MOM_LABEL:
            mom_by_date[date] = value

    if not yoy_by_date:
        print("[ERROR] Brazil CPI: YoY не найден в ответе")
        return pd.DataFrame()

    rows = []
    for date, yoy in yoy_by_date.items():
        rows.append({
            "date": date,
            "country": "BR",
            "value": yoy,
            "mom": mom_by_date.get(date),
            "core": None,
        })

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
    df = df[df["date"] >= cutoff]

    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    df = fetch_brazil_cpi()
    print(f"Всего строк: {len(df)}")
    if not df.empty:
        print(f"Колонки: {list(df.columns)}")
        print(df.tail(8).to_string(index=False))
