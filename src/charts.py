# src/charts.py
import plotly.express as px
import pandas as pd


def line_chart(df: pd.DataFrame, country: str, indicator: str):
    sub = df[(df["country"] == country) & (df["indicator"] == indicator)]
    if sub.empty:
        return None
    sub = sub.sort_values("date")
    fig = px.line(
        sub, x="date", y="value",
        title=f"{indicator} — {country}",
        markers=True,
    )
    fig.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20))
    return fig
