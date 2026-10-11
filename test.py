import pandas as pd
from src.fetch_policy_rates import fetch_policy_rates

pd.set_option("display.width", 200)

df = fetch_policy_rates()
print(f"Тип: {type(df)}")
print(f"Empty: {df.empty}")
print(f"Shape: {df.shape}")
print(f"Колонки: {list(df.columns)}")
if not df.empty:
    print(f"Страны: {sorted(df['country'].unique())}")
    print(f"dtype date: {df['date'].dtype}")
    print()
    print("Последние значения:")
    last = df.sort_values("date").groupby("country").tail(1)
    print(last.sort_values("country").to_string(index=False))
