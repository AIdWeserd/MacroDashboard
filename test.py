
import sqlite3
import pandas as pd

from config import DB_PATH
from src.fetch_policy_rates import fetch_policy_rate_ru
from src.storage import load_policy_rates

existing = load_policy_rates()
ru = fetch_policy_rate_ru()

print("Существующих строк:", len(existing))
print("Стран до добавления:", sorted(existing["country"].dropna().unique().tolist()) if not existing.empty else [])

assert not ru.empty
assert list(ru.columns) == ["date", "country", "rate"]

if existing.empty:
    combined = ru.copy()
else:
    combined = pd.concat(
        [existing[["date", "country", "rate"]], ru],
        ignore_index=True,
    )
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.drop_duplicates(
        subset=["date", "country"],
        keep="last",
    )

# Только временная SQLite-база в оперативной памяти
with sqlite3.connect(":memory:") as con:
    combined.to_sql("policy_rates", con, index=False)
    check = pd.read_sql("SELECT * FROM policy_rates", con)

print("Строк после добавления:", len(check))
print("Стран после добавления:", sorted(check["country"].unique().tolist()))
print("Строк России:", (check["country"] == "RU").sum())

assert (check["country"] == "RU").sum() == len(ru)
assert len(check) == len(combined)

print("\n[OK] Объединение и сохранение проверены без изменения macro.db")
