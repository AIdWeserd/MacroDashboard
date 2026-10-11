import time
import requests
import pandas as pd

BASE = "https://api.beta.ons.gov.uk/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

START_DATE = pd.Timestamp("2024-01-01")

# CDID: (ключ в результирующей таблице, инвертировать знак?)
SERIES = {
    "HF6X": ("debt_gdp", False),
    "A3PT": ("budget_gdp", True),
    "AA6H": ("trade_gdp", False),
}


def _get(uri: str, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/data",
                params={"uri": uri},
                headers=HEADERS,
                timeout=60,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"ONS не ответил по {uri}: {last_err}")


def _find_uri(cdid: str) -> str | None:
    r = requests.get(
        f"{BASE}/search",
        params={"content_type": "timeseries", "cdids": cdid},
        headers=HEADERS,
        timeout=60,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return None
    return items[0].get("uri")


def _parse_quarter(date_str: str) -> pd.Timestamp | None:
    """'2026 Q2' -> Timestamp(2026-04-01)."""
    try:
        parts = date_str.split()
        year = int(parts[0])
        q = int(parts[1].replace("Q", ""))
        month = (q - 1) * 3 + 1
        return pd.Timestamp(year=year, month=month, day=1)
    except Exception:
        return None


def fetch_uk_quarterly() -> pd.DataFrame:
    rows_by_date: dict[pd.Timestamp, dict] = {}

    for cdid, (col_name, invert) in SERIES.items():
        uri = _find_uri(cdid)
        if uri is None:
            print(f"[WARN] UK: CDID {cdid} не найден")
            continue

        data = _get(uri)
        quarters = data.get("quarters", [])
        for q in quarters:
            ts = _parse_quarter(q.get("date", ""))
            if ts is None or ts < START_DATE:
                continue
            raw = q.get("value")
            if raw in (None, ""):
                continue
            try:
                val = float(raw)
            except (ValueError, TypeError):
                continue
            if invert:
                val = -val
            rows_by_date.setdefault(ts, {})[col_name] = val

    if not rows_by_date:
        return pd.DataFrame()

    df = pd.DataFrame([
        {"date": ts, **vals}
        for ts, vals in rows_by_date.items()
    ]).sort_values("date").reset_index(drop=True)

    df["country"] = "GB"
    return df
