from src.storage import load_russia_rates
import io
import streamlit as st
import pandas as pd
from config import COUNTRIES, INDICATORS
from src.storage import (
    load_fred, load_rss, load_forexfactory, load_imf,
    load_eurostat, load_eurostat_unemployment,
    load_policy_rates,
    load_bloomberg,
)
from src.build_summary import (
    build_summary, COUNTRY_NAMES, MONTH_NAMES,
    REGION_MAP, REGION_ORDER,
)
from src.snapshot import (
    save_weekly_snapshot, load_previous_snapshot,
    compare_with_previous, SUMMARY_METRICS,
)
from src.fetch_forexfactory import fetch_calendar
from src.charts import line_chart

st.set_page_config(page_title="Macro Dashboard", layout="wide")
st.title("📈 Макро-дашборд")


@st.dialog("График", width="large")
def show_chart_fullscreen(fig):
    st.plotly_chart(fig, width='stretch')
    if st.button("Закрыть"):
        st.rerun()


# ============================================================
# Хелперы для экспорта
# ============================================================
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Macro")

        from openpyxl.styles import Alignment
        ws = writer.sheets["Macro"]
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                if cell.value:
                    for line in str(cell.value).split("\n"):
                        max_len = max(max_len, len(line))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

    return buf.getvalue()


def to_html_bytes(df: pd.DataFrame) -> bytes:
    html = df.to_html(index=False, escape=False, border=1, justify="center")
    return html.encode("utf-8-sig")


def to_pdf_bytes(df: pd.DataFrame) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[PDF] Playwright не установлен.")
        return b""

    from datetime import datetime

    df_html = df.copy()
    for col in df_html.columns:
        df_html[col] = df_html[col].apply(
            lambda x: str(x).replace("\n", "<br>") if pd.notna(x) else ""
        )

    table_html = df_html.to_html(
        index=False,
        escape=False,
        border=0,
        classes="macro-table",
    )

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
    @page {{ size: A4 landscape; margin: 10mm; }}
    * {{ box-sizing: border-box; }}
    body {{
        font-family: "Arial", "DejaVu Sans", sans-serif;
        font-size: 9px;
        color: #222;
        margin: 0;
        padding: 0;
    }}
    h1 {{ font-size: 14px; margin: 0 0 4px 0; }}
    .meta {{ font-size: 8px; color: #666; margin-bottom: 8px; }}
    table.macro-table {{
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
    }}
    table.macro-table th {{
        background-color: #f0f0f0;
        border: 1px solid #999;
        padding: 4px 5px;
        font-size: 9px;
        text-align: center;
        vertical-align: middle;
        word-wrap: break-word;
    }}
    table.macro-table td {{
        border: 1px solid #bbb;
        padding: 3px 5px;
        font-size: 8.5px;
        vertical-align: top;
        word-wrap: break-word;
    }}
    table.macro-table tr:nth-child(even) td {{ background-color: #fafafa; }}
    table.macro-table td:first-child {{
        font-weight: bold;
        text-align: left;
        white-space: nowrap;
        width: 100px;
    }}
</style>
</head>
<body>
    <h1>Макро-дашборд — сводная таблица</h1>
    <div class="meta">Сформировано: {now_str}. Источники: IMF WEO, Eurostat, FRED, BEA, Treasury, национальные службы, Bloomberg.</div>
    {table_html}
</body>
</html>
"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            pdf_bytes = page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()
        return pdf_bytes
    except Exception as e:
        print(f"[PDF] Ошибка Playwright: {e}")
        return b""


# ============================================================
# value_if_in_period (для таблицы "без дат")
# ============================================================
def parse_date_label(date_label: str) -> tuple[str, int] | None:
    if not date_label:
        return None
    s = str(date_label).strip()
    parts = s.replace(",", "").split()
    if len(parts) < 2:
        return None

    if "IMF" in s or "год" in s:
        try:
            return ("year", int(parts[0]))
        except ValueError:
            return None

    if parts[0].startswith("Q"):
        try:
            q = int(parts[0][1:])
            y = int(parts[1])
            return ("quarter", y * 10 + q)
        except ValueError:
            return None

    month_str, year_str = parts[0], parts[1]
    inv_months = {v: k for k, v in MONTH_NAMES.items()}
    if month_str in inv_months:
        try:
            y = int(year_str)
            return ("month", y * 100 + inv_months[month_str])
        except ValueError:
            return None

    return None


def value_if_in_period(value, date_label, target_year, target_month) -> str:
    if pd.isna(value) or value is None:
        return "—"

    parsed = parse_date_label(date_label)
    if parsed is None:
        return "—"

    kind, num = parsed
    target_month_num = target_year * 100 + target_month

    if kind == "month":
        return f"{value:.2f}" if num == target_month_num else "—"

    if kind == "quarter":
        q_year = num // 10
        q_num = num % 10
        q_end_month = q_num * 3
        q_end = q_year * 100 + q_end_month
        return f"{value:.2f}" if q_end <= target_month_num else "—"

    if kind == "year":
        return f"{value:.2f}" if num <= target_year else "—"

    return "—"


# ============================================================
# Слияние значения и даты в ячейке ("5.26 · Q4 2026 (BBG)")
# ============================================================
def merge_value_date(value, date) -> str:
    if pd.isna(value) or value is None:
        return "—"
    val_str = f"{value:.2f}"
    if date is None or (isinstance(date, float) and pd.isna(date)):
        return val_str
    return f"{val_str} · {date}"


# ============================================================
# ГЛАВНАЯ
# ============================================================
st.subheader("🌍 Сводная таблица по странам")

imf = load_imf()
now = pd.Timestamp.now()

if not imf.empty:
    available_years = sorted(
        set(imf["year"].unique()) | {now.year},
        reverse=True,
    )
else:
    available_years = [now.year]

default_year_idx = available_years.index(now.year) if now.year in available_years else 0

MONTH_OPTIONS = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр",
    5: "май", 6: "июн", 7: "июл", 8: "авг",
    9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}

col_year, col_month = st.columns(2)
with col_year:
    selected_year = st.selectbox(
        "Год",
        available_years,
        index=default_year_idx,
        key="summary_year",
    )
with col_month:
    selected_month_name = st.selectbox(
        "Месяц",
        list(MONTH_OPTIONS.values()),
        index=now.month - 1,
        key="summary_month",
    )
    selected_month = [k for k, v in MONTH_OPTIONS.items() if v == selected_month_name][0]

# Регион — pills, как метрики
selected_regions = st.pills(
    "Регион",
    options=REGION_ORDER,
    default=REGION_ORDER,
    selection_mode="multi",
    key="summary_region",
)
if not selected_regions:
    selected_regions = REGION_ORDER

summary = build_summary(year=selected_year, month=selected_month)

if summary.empty:
    st.warning("Нет данных. Запусти: python scheduler.py")
else:
    summary = summary[summary["region"].isin(selected_regions)].reset_index(drop=True)

    previous = load_previous_snapshot()
    changed = compare_with_previous(summary, previous)

    display = summary.copy()

    # Сливаем значение + дату в одну ячейку
    display["Ставка ЦБ, %"] = [
        merge_value_date(v, d) for v, d in zip(display["policy_rate"], display["policy_rate_date"])
    ]
    display["Инфляция YoY, %"] = [
        merge_value_date(v, d) for v, d in zip(display["inflation"], display["inflation_date"])
    ]
    display["Инфляция MoM, %"] = [
        merge_value_date(v, d) for v, d in zip(display["inflation_mom"], display["inflation_mom_date"])
    ]
    display["Core CPI YoY, %"] = [
        merge_value_date(v, d) for v, d in zip(display["inflation_core"], display["inflation_core_date"])
    ]
    display["Рост ВВП, % YoY"] = [
        merge_value_date(v, d) for v, d in zip(display["gdp_growth"], display["gdp_growth_date"])
    ]
    display["Безработица, %"] = [
        merge_value_date(v, d) for v, d in zip(display["unemployment"], display["unemployment_date"])
    ]
    display["Долг/ВВП, %"] = [
        merge_value_date(v, d) for v, d in zip(display["debt_gdp"], display["debt_gdp_date"])
    ]
    display["Бюджет/ВВП, %"] = [
        merge_value_date(v, d) for v, d in zip(display["budget_gdp"], display["budget_gdp_date"])
    ]
    display["Трейд/ВВП, %"] = [
        merge_value_date(v, d) for v, d in zip(display["trade_gdp"], display["trade_gdp_date"])
    ]

    display = display.rename(columns={"country_name": "Страна"})

    # Порядок колонок и фильтров — синхронный
    METRIC_COLS = [
        "Ставка ЦБ, %",
        "Инфляция YoY, %",
        "Инфляция MoM, %",
        "Core CPI YoY, %",
        "Рост ВВП, % YoY",
        "Безработица, %",
        "Долг/ВВП, %",
        "Бюджет/ВВП, %",
        "Трейд/ВВП, %",
    ]

    selected_cols = st.pills(
        "Какие метрики показывать",
        options=METRIC_COLS,
        default=METRIC_COLS,
        selection_mode="multi",
        key="summary_cols_pills",
    )
    if not selected_cols:
        selected_cols = METRIC_COLS

    display_with_dates = display[["country", "Страна"]].copy()
    for c in METRIC_COLS:
        if c in selected_cols:
            display_with_dates[c] = display[c]

    metric_to_key = {human: key for key, human in SUMMARY_METRICS}
    highlight_color_changed = "background-color: #fff3b0"
    highlight_color_bbg = "background-color: #ffcccc"

    # BBG-подсветка — только для тех ячеек, где реально применилось
    # значение из Bloomberg для выбранного года/месяца.
    # Определяем по метке *_date, содержащей "(BBG)".
    bbg_set: set[tuple[str, str]] = set()
    for _, r in summary.iterrows():
        country = str(r["country"])
        for col in summary.columns:
            if not col.endswith("_date"):
                continue
            metric = col[:-len("_date")]
            val = r[col]
            if val is None or pd.isna(val):
                continue
            if "(BBG)" in str(val):
                bbg_set.add((country, metric))


    def highlight_row(row):
        country = row["country"]
        styles = [""] * len(row)
        for i, col in enumerate(row.index):
            if col in ("country", "Страна"):
                continue
            metric_key = metric_to_key.get(col)
            if metric_key is None:
                continue
            if (country, metric_key) in bbg_set:
                styles[i] = highlight_color_bbg
            elif (country, metric_key) in changed:
                styles[i] = highlight_color_changed
        return styles


    styled = display_with_dates.style.apply(highlight_row, axis=1)

    st.dataframe(
        styled,
        width='stretch',
        hide_index=True,
        column_config={
            "country": None,
            "Страна": st.column_config.TextColumn("Страна", width="small"),
            "Ставка ЦБ, %": st.column_config.TextColumn("Ставка ЦБ, %", width="small"),
            "Инфляция YoY, %": st.column_config.TextColumn("Инфляция YoY, %", width="small"),
            "Инфляция MoM, %": st.column_config.TextColumn("Инфляция MoM, %", width="small"),
            "Core CPI YoY, %": st.column_config.TextColumn("Core CPI YoY, %", width="small"),
            "Рост ВВП, % YoY": st.column_config.TextColumn("Рост ВВП, % YoY", width="small"),
            "Безработица, %": st.column_config.TextColumn("Безработица, %", width="small"),
            "Долг/ВВП, %": st.column_config.TextColumn("Долг/ВВП, %", width="medium"),
            "Бюджет/ВВП, %": st.column_config.TextColumn("Бюджет/ВВП, %", width="medium"),
            "Трейд/ВВП, %": st.column_config.TextColumn("Трейд/ВВП, %", width="medium"),
        },
    )

    bbg_count = len(bbg_set)
    changed_count = len(changed)

    parts = []
    if bbg_count:
        parts.append(
            f"🔴 Красным — {bbg_count} метрик из Bloomberg "
            f"(методология может отличаться от IMF/национальных источников)."
        )
    if changed_count:
        parts.append(f"🟡 Жёлтым — {changed_count} обновившихся метрик за неделю.")
    if not bbg_count and not changed_count:
        if previous.empty:
            parts.append("📸 Прошлый снимок ещё не накоплен.")
        else:
            parts.append("Свежих изменений нет.")

    for p in parts:
        st.caption(p)

    # ============================================================
    # ВТОРАЯ ТАБЛИЦА — без дат
    # ============================================================
    st.markdown("---")
    st.subheader("🔢 Таблица без дат (только значения)")
    st.caption(
        "Показаны значения, чей период **завершился не позже выбранного месяца**."
    )

    col2_year, col2_month = st.columns(2)
    with col2_year:
        selected_year_2 = st.selectbox(
            "Год (без дат)",
            available_years,
            index=default_year_idx,
            key="no_dates_year",
        )
    with col2_month:
        selected_month_name_2 = st.selectbox(
            "Месяц (без дат)",
            list(MONTH_OPTIONS.values()),
            index=now.month - 1,
            key="no_dates_month",
        )
        selected_month_2 = [k for k, v in MONTH_OPTIONS.items() if v == selected_month_name_2][0]

    selected_regions_2 = st.pills(
        "Регион (без дат)",
        options=REGION_ORDER,
        default=REGION_ORDER,
        selection_mode="multi",
        key="no_dates_region",
    )
    if not selected_regions_2:
        selected_regions_2 = REGION_ORDER

    selected_cols_2 = st.pills(
        "Какие метрики показывать (без дат)",
        options=METRIC_COLS,
        default=METRIC_COLS,
        selection_mode="multi",
        key="no_dates_cols_pills",
    )
    if not selected_cols_2:
        selected_cols_2 = METRIC_COLS

    if selected_year_2 != selected_year or selected_month_2 != selected_month:
        summary_2 = build_summary(year=selected_year_2, month=selected_month_2)
    else:
        summary_2 = summary

    summary_2 = summary_2[summary_2["region"].isin(selected_regions_2)].reset_index(drop=True)

    display_no_dates = summary_2[["country", "country_name"]].copy()
    display_no_dates = display_no_dates.rename(columns={"country_name": "Страна"})

    for col in selected_cols_2:
        key = metric_to_key.get(col)
        if key is None:
            display_no_dates[col] = "—"
            continue
        value_col = key
        date_col = f"{key}_date"
        if value_col not in summary_2.columns or date_col not in summary_2.columns:
            display_no_dates[col] = "—"
            continue
        display_no_dates[col] = [
            value_if_in_period(v, d, selected_year_2, selected_month_2)
            for v, d in zip(summary_2[value_col], summary_2[date_col])
        ]

    st.dataframe(
        display_no_dates.drop(columns=["country"]),
        width='stretch',
        hide_index=True,
    )

    # ============================================================
    # ЭКСПОРТ
    # ============================================================
    st.markdown("---")
    st.subheader("📥 Скачать таблицу")

    col_fmt, col_which = st.columns(2)
    with col_fmt:
        export_format = st.selectbox(
            "Формат",
            ["CSV", "Excel (.xlsx)", "HTML", "PDF"],
            key="export_format",
        )
    with col_which:
        export_which = st.selectbox(
            "Какую таблицу",
            ["С датами", "Без дат"],
            key="export_which",
        )

    if export_which == "С датами":
        export_df = display_with_dates.drop(columns=["country"])
    else:
        export_df = display_no_dates.drop(columns=["country"])

    if export_format == "CSV":
        data = export_df.to_csv(index=False).encode("utf-8-sig")
        mime, ext = "text/csv", "csv"
    elif export_format == "Excel (.xlsx)":
        data = to_excel_bytes(export_df)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif export_format == "HTML":
        data = to_html_bytes(export_df)
        mime, ext = "text/html", "html"
    else:
        data = to_pdf_bytes(export_df)
        mime, ext = "application/pdf", "pdf"

    st.download_button(
        label=f"📥 Скачать {export_format}",
        data=data,
        file_name=f"macro_{'with' if export_which == 'С датами' else 'no'}_dates.{ext}",
        mime=mime,
        key="download_table",
    )

    st.caption(
        "📌 **Источники:** IMF WEO, Eurostat, FRED, BEA, Treasury Fiscal Data, "
        "национальные статистические службы, Bloomberg (ручные выгрузки). "
        "Дата указана в ячейке после `·`."
    )
    st.caption(
        "📅 **Сезонная корректировка:** большинство показателей — сезонно сглаженные (SA). "
        "Если в пометке указано `NSA` — данные без сезонной корректировки."
    )

st.divider()

# ============================================================
# Expander'ы
# ============================================================

with st.expander("📆 Месячные метрики (детально)", expanded=False):
    eurostat = load_eurostat()
    unemp = load_eurostat_unemployment()

    if not eurostat.empty:
        st.markdown("**Инфляция (HICP, ЕС) — YoY / MoM / Core**")
        es_rows = []
        for country in eurostat["country"].unique():
            sub = eurostat[eurostat["country"] == country].sort_values("date")
            if sub.empty:
                continue
            last = sub.iloc[-1]
            es_rows.append({
                "Страна": COUNTRY_NAMES.get(country, country),
                "Месяц": f"{MONTH_NAMES[last['date'].month]} {last['date'].year}",
                "YoY, %": round(last["value"], 2) if pd.notna(last.get("value")) else None,
                "MoM, %": round(last["mom"], 2) if pd.notna(last.get("mom")) else None,
                "Core YoY, %": round(last["core"], 2) if pd.notna(last.get("core")) else None,
            })
        if es_rows:
            st.dataframe(pd.DataFrame(es_rows), width='stretch', hide_index=True)

    if not unemp.empty:
        st.markdown("**Безработица (%, SA)**")
        un_rows = []
        for country in unemp["country"].unique():
            sub = unemp[unemp["country"] == country].sort_values("date")
            if len(sub) < 2:
                continue
            last = sub.iloc[-1]
            prev = sub.iloc[-2]
            un_rows.append({
                "Страна": COUNTRY_NAMES.get(country, country),
                "Месяц": f"{MONTH_NAMES[last['date'].month]} {last['date'].year}",
                "Безработица, %": round(last["value"], 2),
                "Пред. месяц, %": round(prev["value"], 2),
                "Изм., п.п.": round(last["value"] - prev["value"], 2),
            })
        if un_rows:
            st.dataframe(pd.DataFrame(un_rows), width='stretch', hide_index=True)

with st.expander("💰 Ставки ЦБ (исторические)", expanded=False):
    pr = load_policy_rates()
    if pr.empty:
        st.caption("Нет данных. Запусти: python scheduler.py rates")
    else:
        months_back = st.slider("Месяцев назад", 6, 36, 12, key="rates_months")
        cutoff_pr = pd.Timestamp.now() - pd.DateOffset(months=months_back)
        pr_filtered = pr[pr["date"] >= cutoff_pr].copy()

        pr_filtered["month_label"] = pr_filtered["date"].apply(
            lambda d: f"{MONTH_NAMES[d.month]} {d.year}"
        )
        month_order = (
            pr_filtered[["date", "month_label"]]
            .drop_duplicates()
            .sort_values("date")["month_label"]
            .tolist()
        )
        pivot = pr_filtered.pivot_table(
            index="country",
            columns="month_label",
            values="rate",
            aggfunc="last",
        )
        pivot.index = [COUNTRY_NAMES.get(c, c) for c in pivot.index]
        pivot = pivot[[c for c in month_order if c in pivot.columns]]

        st.dataframe(pivot, width="stretch")

        csv_pr = pivot.to_csv().encode("utf-8-sig")
        st.download_button(
            label="📥 Скачать ставки в CSV",
            data=csv_pr,
            file_name="policy_rates.csv",
            mime="text/csv",
            key="download_rates",
        )

with st.expander("📅 Экономический календарь", expanded=False):
    with st.spinner("Загружаю календарь..."):
        try:
            cal = fetch_calendar()
        except Exception as e:
            st.error(f"Ошибка: {e}")
            cal = pd.DataFrame()

    if not cal.empty:
        min_imp = st.slider("Мин. важность", 1, 3, 2, key="cal_imp")
        filtered = cal[cal["importance"] >= min_imp]
        st.caption(f"Событий: {len(filtered)}")
        for _, row in filtered.head(30).iterrows():
            dt = row["datetime"].strftime("%Y-%m-%d %H:%M")
            stars = "⭐" * int(row["importance"])
            actual = row.get("actual") or "—"
            forecast = row.get("forecast") or "—"
            previous = row.get("previous") or "—"
            st.markdown(
                f"**{dt} — {row['country']} — {row['event']}** {stars}  \n"
                f"Actual: `{actual}` | Forecast: `{forecast}` | Previous: `{previous}`"
            )
            st.divider()

with st.expander("📊 FRED (исторические ряды)", expanded=False):
    macro = load_fred()
    if not macro.empty:
        col1, col2 = st.columns(2)
        country = col1.selectbox("Страна", list(COUNTRIES.keys()), key="fred_c")
        indicator = col2.selectbox("Индикатор", list(INDICATORS.keys()), key="fred_i")
        fig = line_chart(macro, country, indicator)
        if fig:
            st.plotly_chart(fig, width='stretch')
            if st.button("🔍 Открыть график на весь экран", key="fred_fullscreen"):
                show_chart_fullscreen(fig)

with st.expander("📰 Новости", expanded=False):
    news = load_rss()
    if not news.empty:
        for _, row in news.head(20).iterrows():
            st.markdown(
                f"**[{row['title']}]({row['link']})**  \n"
                f"<small>{row['source']} — {row['published']:%Y-%m-%d %H:%M}</small>",
                unsafe_allow_html=True,
            )
            st.divider()

# ============================================================
# ДЕТАЛЬНЫЕ ДАННЫЕ ПО СТРАНАМ
# ============================================================

import plotly.graph_objects as go

from src.build_summary import COUNTRY_ORDER
from src.storage import (
    load_russia_cpi,
    load_russia_quarterly,
)

st.divider()
st.header("🌍 Данные по странам")

country_options = {
    code: COUNTRY_NAMES[code]
    for code in COUNTRY_ORDER
}

select_col, button_col = st.columns([4, 1])

with select_col:
    selected_detail_country = st.selectbox(
        "Выберите страну",
        options=COUNTRY_ORDER,
        format_func=lambda code: country_options[code],
        key="detail_country_selector",
    )

with button_col:
    st.write("")
    st.write("")
    open_details = st.button(
        "Данные",
        key="open_country_details",
        type="primary",
        use_container_width=True,
    )

if open_details:
    st.session_state["active_detail_country"] = (
        selected_detail_country
    )

active_country = st.session_state.get(
    "active_detail_country"
)

if active_country is not None:
    st.divider()
    st.subheader(
        f"📊 {country_options[active_country]} — "
        "детальные данные"
    )

    if active_country != "RU":
        st.info(
            "Детальные показатели этой страны "
            "пока не подключены. "
            "Раздел готов к последующему наполнению."
        )

    else:
        # ====================================================
        # РОССИЯ — ПОДКЛЮЧЁННЫЕ РЯДЫ
        # ====================================================

        ru_cpi = load_russia_cpi()
        ru_quarterly = load_russia_quarterly()
        ru_rates = load_policy_rates()

        if not ru_cpi.empty:
            ru_cpi = (
                ru_cpi.loc[
                    ru_cpi["country"] == "RU"
                    ]
                .copy()
            )
            ru_cpi["date"] = pd.to_datetime(
                ru_cpi["date"]
            )
            ru_cpi = ru_cpi.loc[
                ru_cpi["date"] >= "2024-01-01"
                ].sort_values("date")

        if not ru_quarterly.empty:
            ru_quarterly = (
                ru_quarterly.loc[
                    ru_quarterly["country"] == "RU"
                    ]
                .copy()
            )
            ru_quarterly["date"] = pd.to_datetime(
                ru_quarterly["date"]
            )
            ru_quarterly = ru_quarterly.loc[
                ru_quarterly["date"] >= "2024-01-01"
                ].sort_values("date")

        if not ru_rates.empty:
            ru_rates = (
                ru_rates.loc[
                    ru_rates["country"] == "RU"
                    ]
                .copy()
            )
            ru_rates["date"] = pd.to_datetime(
                ru_rates["date"]
            )
            ru_rates = ru_rates.loc[
                ru_rates["date"] >= "2024-01-01"
                ].sort_values("date")

        st.caption(
            "Россия · История с января 2024 года · "
            "Официальные данные ЦБ РФ, Росстата "
            "и Федерального казначейства"
        )

        # Обзор текущих значений
        current = build_summary(
            year=pd.Timestamp.now().year,
            month=pd.Timestamp.now().month,
        )

        current_ru = current.loc[
            current["country"] == "RU"
            ]

        if not current_ru.empty:
            latest = current_ru.iloc[0]

            overview = [
                ("Ключевая ставка", "policy_rate"),
                ("Инфляция YoY", "inflation"),
                ("Рост ВВП YoY", "gdp_growth"),
                ("Безработица", "unemployment"),
            ]

            overview_cols = st.columns(4)

            for column, (label, metric) in zip(
                    overview_cols, overview
            ):
                value = latest.get(metric)
                period = latest.get(
                    f"{metric}_date"
                )

                value_text = (
                    f"{float(value):.2f}%"
                    if pd.notna(value)
                    else "—"
                )

                with column:
                    st.metric(
                        label,
                        value_text,
                        help=(
                            str(period)
                            if pd.notna(period)
                            else None
                        ),
                    )


        # ----------------------------------------------------
        # Настройка линейных графиков
        # ----------------------------------------------------

        def ru_line_chart(
                data,
                title,
                series,
                unit="%",
        ):
            if data.empty:
                st.info(
                    f"{title}: данные пока отсутствуют."
                )
                return

            fig = go.Figure()
            plotted = False

            for column, label in series.items():
                if column not in data.columns:
                    continue

                valid = data.dropna(
                    subset=["date", column]
                ).sort_values("date")

                if valid.empty:
                    continue

                fig.add_trace(
                    go.Scatter(
                        x=valid["date"],
                        y=valid[column],
                        mode="lines+markers",
                        name=label,
                        line={"width": 2},
                        marker={"size": 4},
                    )
                )
                plotted = True

            if not plotted:
                st.info(
                    f"{title}: данные пока отсутствуют."
                )
                return

            fig.update_layout(
                title=title,
                xaxis_title="Период",
                yaxis_title=unit,
                hovermode="x unified",
                legend={
                    "orientation": "h",
                    "y": -0.25,
                },
                margin={
                    "l": 30,
                    "r": 20,
                    "t": 60,
                    "b": 70,
                },
            )

            fig.update_xaxes(
                range=[
                    "2024-01-01",
                    max(
                        pd.Timestamp.now(),
                        pd.Timestamp("2024-12-31"),
                    ),
                ]
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
            )


        # ====================================================
        # РАЗДЕЛЫ ДЕТАЛЬНОЙ СТРАНИЦЫ
        # ====================================================

        (
            rates_tab,
            inflation_tab,
            economy_tab,
            finance_tab,
            other_tab,
        ) = st.tabs([
            "Ставки",
            "Инфляция",
            "ВВП и занятость",
            "Госфинансы",
            "Другие показатели",
        ])


        with rates_tab:
            st.subheader(
                "Процентные ставки Банка России"
            )

            st.caption(
                "Рублёвые кредиты и депозиты. "
                "Средневзвешенные ставки, % годовых. "
                "История с января 2024 года."
            )

            labels = {
                "rate": "Ключевая ставка ЦБ РФ",
                "company_loans_1y":
                    "Кредиты компаниям до 1 года",
                "personal_loans_all":
                    "Кредиты физлицам — все сроки",
                "personal_deposits_1y":
                    "Вклады физлиц до 1 года",
                "company_deposits_1y":
                    "Депозиты компаний до 1 года",
                "auto_loans_old_1y_plus":
                    "Автокредиты свыше 1 года (2024–2025)",
                "auto_loans_new_all":
                    "Автокредиты, все сроки (с февраля 2026)",
            }

            detail_rates = load_russia_rates()

            if not detail_rates.empty:
                detail_rates = detail_rates.loc[
                    detail_rates["country"] == "RU"
                ].copy()

                detail_rates["date"] = pd.to_datetime(
                    detail_rates["date"]
                )

                detail_rates = detail_rates.loc[
                    detail_rates["date"] >= "2024-01-01"
                ]

            else:
                detail_rates = pd.DataFrame(
                    columns=["date", "country"]
                )

            # Ключевая ставка из существующей БД.
            key_rates = load_policy_rates()

            if not key_rates.empty:
                key_rates = key_rates.loc[
                    key_rates["country"] == "RU",
                    ["date", "rate"],
                ].copy()

                key_rates["date"] = pd.to_datetime(
                    key_rates["date"]
                )

                key_rates = key_rates.loc[
                    key_rates["date"] >= "2024-01-01"
                ]

                detail_rates = detail_rates.merge(
                    key_rates,
                    on="date",
                    how="outer",
                )

            detail_rates = detail_rates.sort_values(
                "date"
            )

            available = {
                key: label
                for key, label in labels.items()
                if (
                    key in detail_rates.columns
                    and detail_rates[key].notna().any()
                )
            }

            if not available:
                st.warning(
                    "Данные пока отсутствуют. "
                    "Выполни python scheduler.py ru "
                    "и python scheduler.py rates."
                )

            else:
                selected = st.multiselect(
                    "Выбери ставки для сравнения",
                    options=list(available.keys()),
                    default=list(available.keys()),
                    format_func=lambda key: available[key],
                    key="ru_rates_detail_select",
                )

                if selected:
                    ru_line_chart(
                        detail_rates,
                        "Процентные ставки России",
                        {
                            key: available[key]
                            for key in selected
                        },
                        unit="% годовых",
                    )
                else:
                    st.info(
                        "Выбери хотя бы один показатель."
                    )

                # Таблица последних значений.
                latest_rows = []

                for key, label in available.items():
                    valid = detail_rates[
                        ["date", key]
                    ].dropna(subset=[key])

                    valid = valid.sort_values("date")

                    if valid.empty:
                        continue

                    last = valid.iloc[-1]

                    latest_rows.append({
                        "Показатель": label,
                        "Период": last["date"].strftime(
                            "%m.%Y"
                        ),
                        "Ставка, %": round(
                            float(last[key]), 2
                        ),
                    })

                if latest_rows:
                    st.subheader(
                        "Последние опубликованные значения"
                    )

                    st.dataframe(
                        pd.DataFrame(latest_rows),
                        hide_index=True,
                        use_container_width=True,
                    )

            st.info(
                "Автокредиты: в 2024–2025 годах "
                "показана ставка по кредитам "
                "свыше одного года. С февраля 2026 "
                "года — ставка по всем срокам. "
                "Методологии различаются; "
                "ряды показаны отдельно."
            )

            st.caption(
                "Источник: Банк России — статистика "
                "процентных ставок по кредитам "
                "и депозитам."
            )

        with inflation_tab:
            st.subheader("Инфляция")

            ru_line_chart(
                ru_cpi,
                "Потребительские цены",
                {
                    "value": "CPI YoY",
                    "mom": "CPI MoM",
                    "core": "Core CPI YoY",
                },
            )

        with economy_tab:
            st.subheader("Экономическая активность")

            ru_line_chart(
                ru_quarterly,
                "Рост реального ВВП YoY",
                {"gdp_growth": "Рост ВВП YoY"},
            )

            ru_line_chart(
                ru_quarterly,
                "Уровень безработицы",
                {"unemployment": "Безработица"},
            )

            st.caption(
                "Квартальные показатели: "
                "по завершённым кварталам."
            )

        with finance_tab:
            st.subheader("Государственные финансы")

            ru_line_chart(
                ru_quarterly,
                "Государственный долг / ВВП",
                {"debt_gdp": "Gen Gov, broad debt"},
            )

            ru_line_chart(
                ru_quarterly,
                "Сальдо бюджета / ВВП",
                {"budget_gdp": "Gen Gov"},
            )

            ru_line_chart(
                ru_quarterly,
                "Текущий счёт / ВВП",
                {"trade_gdp": "Текущий счёт"},
            )

            annual_columns = {
                "annual_debt_gdp": "Долг/ВВП, %",
                "annual_budget_gdp": "Бюджет/ВВП, %",
                "annual_trade_gdp": "Текущий счёт/ВВП, %",
                "annual_gdp_growth": "Рост ВВП YoY, %",
                "annual_unemployment": "Безработица, %",
            }

            if not ru_quarterly.empty:
                available = [
                    column
                    for column in annual_columns
                    if column in ru_quarterly.columns
                ]

                if available:
                    annual = ru_quarterly[
                        ["date"] + available
                        ].copy()

                    annual = annual.loc[
                        annual["date"].dt.month == 12
                        ]

                    annual = annual.dropna(
                        subset=available,
                        how="all",
                    )

                    if not annual.empty:
                        annual["Год"] = (
                            annual["date"].dt.year
                        )

                        annual = annual.rename(
                            columns=annual_columns
                        )

                        st.subheader(
                            "Годовые показатели"
                        )

                        st.dataframe(
                            annual[
                                ["Год"]
                                + list(
                                    annual_columns[c]
                                    for c in available
                                )
                                ].round(2),
                            hide_index=True,
                            use_container_width=True,
                        )

        with other_tab:
            st.subheader(
                "Дополнительные показатели России"
            )

            st.markdown(
                """
                **Банковский сектор**
                - Кредитование физлиц, компаний и МСП
                - Денежная масса: M0, M1, M2 и широкая
                - Ипотечное кредитование

                **Денежный рынок**
                - RUONIA: объём сделок

                **Внешний сектор**
                - Экспорт и импорт
                - Дополнительные показатели
                  платёжного баланса

                **Финансовые рынки**
                - Вложения частных инвесторов
                - Активные инвесторы
                - Доля физлиц в обороте
                - Индивидуальные инвестиционные счета

                **Справочные данные ЦБ РФ**
                - Брокеры
                - ИИС
                - Коллективные инвестиции
                """
            )

            st.caption(
                "Эти показатели предусмотрены "
                "в детальном разделе, но загрузчики "
                "для них пока не подключены."
            )
