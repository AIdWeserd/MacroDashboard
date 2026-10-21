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
    load_russia_credit,
    load_russia_mortgage,
    load_russia_cbr_reference,
    load_russia_money,
    load_russia_trade,
    load_russia_trade_estimates,
    load_russia_investors,
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
                ru_rates["date"] >= "2020-01-01"
                ].sort_values("date")

        st.caption(
            "Россия · История по доступности источника · "
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
                    pd.to_datetime(data["date"]).min(),
                    max(pd.Timestamp.now(), pd.to_datetime(data["date"]).max()),
                ]
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
            )


        # ----------------------------------------------------
        # Сопоставление динамики разных единиц измерения
        # Только для графиков, SQLite не изменяется.
        # ----------------------------------------------------
        def ru_indexed_chart(rows, title):
            fig = go.Figure()
            plotted = 0
            for dataset, key, label, unit in rows:
                if dataset.empty or key not in dataset.columns:
                    continue
                series = dataset[["date", key]].copy()
                series["date"] = pd.to_datetime(series["date"])
                series[key] = pd.to_numeric(series[key], errors="coerce")
                series = series.dropna().sort_values("date")
                series = series.loc[series["date"] >= "2020-01-01"]
                if series.empty:
                    continue
                # Даты всех показателей соотносятся по отчётному месяцу.
                series["month"] = series["date"].dt.to_period("M").dt.to_timestamp()
                series = series.drop_duplicates("month", keep="last")
                first = float(series[key].iloc[0])
                if first == 0:
                    st.caption(f"{label}: нельзя построить индекс от нулевой базы.")
                    continue
                fig.add_trace(go.Scatter(
                    x=series["month"],
                    y=series[key].astype(float) / first * 100,
                    mode="lines",
                    name=label,
                    customdata=series[[key, "date"]].to_numpy(),
                    hovertemplate=(
                        "%{fullData.name}<br>Месяц: %{x|%m.%Y}"
                        "<br>Индекс: %{y:.2f}"
                        "<br>Исходное значение: %{customdata[0]:,.3f} " + unit +
                        "<br>Отчётная дата: %{customdata[1]|%d.%m.%Y}"
                        "<extra></extra>"
                    ),
                ))
                plotted += 1
            if not plotted:
                st.info("Для выбранных рядов пока нет опубликованных данных.")
                return
            fig.update_layout(
                title=title,
                yaxis_title="Индекс, первое доступное значение = 100",
                xaxis_title="Месяц",
                hovermode="closest",
                legend={"orientation": "h", "y": -0.22},
                margin={"l": 30, "r": 20, "t": 60, "b": 90},
            )
            st.plotly_chart(fig, use_container_width=True)

        # ====================================================
        # РАЗДЕЛЫ ДЕТАЛЬНОЙ СТРАНИЦЫ
        # ====================================================

        (
            rates_tab,
            inflation_tab,
            economy_tab,
            finance_tab,
            credit_tab,
            mortgage_tab,
            compare_tab,
            money_tab,
            trade_tab,
            investors_tab,
            reference_tab,
            other_tab,
        ) = st.tabs([
            "Ставки",
            "Инфляция",
            "ВВП и занятость",
            "Госфинансы",
            "Кредитование",
            "Ипотека",
            "Сравнение: все показатели",
            "Денежная масса",
            "Внешняя торговля",
            "Частные инвесторы",
            "Статистика ЦБ РФ",
            "Другие показатели",
        ])


        with rates_tab:
            st.subheader(
                "Процентные ставки Банка России"
            )

            st.caption(
                "Рублёвые кредиты и депозиты. "
                "Средневзвешенные ставки, % годовых. "
                "История с января 2020 года, где доступна."
            )

            labels = {
                "rate": "Ключевая ставка ЦБ РФ",
                "sme_loans_1y":
                    "Кредиты МСП в рублях до 1 года",
                "company_loans_1y":
                    "Кредиты компаниям до 1 года",
                "personal_loans_all":
                    "Кредиты физлицам — все сроки",
                "personal_deposits_1y":
                    "Вклады физлиц до 1 года",
                "company_deposits_1y":
                    "Депозиты компаний до 1 года",
                "auto_loans_old_1y_plus":
                    "Автокредиты свыше 1 года (архив до 2026)",
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
                    detail_rates["date"] >= "2020-01-01"
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
                    key_rates["date"] >= "2020-01-01"
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
                # Выпадающий список с галочками вместо красных тегов.
                for rate_key in available:
                    widget_key = f"ru_rate_checked_{rate_key}"
                    if widget_key not in st.session_state:
                        st.session_state[widget_key] = True

                checked_count = sum(
                    bool(st.session_state[f"ru_rate_checked_{key}"])
                    for key in available
                )

                with st.popover(
                    f"Выбери ставки для сравнения ({checked_count} из {len(available)})",
                    use_container_width=True,
                ):
                    col_all, col_none = st.columns(2)
                    with col_all:
                        if st.button(
                            "Выбрать все",
                            key="ru_rate_select_all",
                            use_container_width=True,
                        ):
                            for key in available:
                                st.session_state[f"ru_rate_checked_{key}"] = True
                            st.rerun()
                    with col_none:
                        if st.button(
                            "Снять все",
                            key="ru_rate_clear_all",
                            use_container_width=True,
                        ):
                            for key in available:
                                st.session_state[f"ru_rate_checked_{key}"] = False
                            st.rerun()

                    for key, label in available.items():
                        st.checkbox(label, key=f"ru_rate_checked_{key}")

                selected = [
                    key for key in available
                    if st.session_state[f"ru_rate_checked_{key}"]
                ]

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
                "Автокредиты: до 2026 года "
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

        with credit_tab:
            st.subheader("Задолженность по кредитам")
            st.caption(
                "Банк России · Остатки задолженности на 1-е число месяца · "
                "млрд рублей · Период с января 2020 года"
            )

            credit_data = load_russia_credit()
            credit_labels = {
                "personal_debt": "Кредиты физическим лицам",
                "company_debt": "Кредиты юридическим лицам и ИП",
                "sme_debt": "Кредиты субъектам МСП",
            }

            if credit_data.empty:
                st.warning(
                    "История задолженности пока не загружена. "
                    "Выполни python scheduler.py ru."
                )
            else:
                credit_data = credit_data.loc[
                    credit_data["country"] == "RU"
                ].copy()
                credit_data["date"] = pd.to_datetime(
                    credit_data["date"]
                )
                credit_data = credit_data.loc[
                    credit_data["date"] >= "2020-01-01"
                ].sort_values("date")

                available_credit = {
                    key: label
                    for key, label in credit_labels.items()
                    if key in credit_data.columns
                    and credit_data[key].notna().any()
                }

                if not available_credit:
                    st.info("Нет доступных показателей задолженности.")
                else:
                    with st.popover(
                        "Показатели кредитования: выбрать галочками",
                        use_container_width=True,
                    ):
                        for key, label in available_credit.items():
                            widget = f"ru_credit_checked_{key}"
                            if widget not in st.session_state:
                                st.session_state[widget] = True
                            st.checkbox(label, key=widget)
                    selected_credit = [
                        key for key in available_credit
                        if st.session_state.get(f"ru_credit_checked_{key}", False)
                    ]

                    if selected_credit:
                        ru_line_chart(
                            credit_data,
                            "Задолженность по кредитам в России",
                            {
                                key: available_credit[key]
                                for key in selected_credit
                            },
                            unit="млрд ₽",
                        )
                    else:
                        st.info("Выбери хотя бы один показатель.")

                    last_values = []
                    for key, label in available_credit.items():
                        observed = credit_data[["date", key]].dropna(
                            subset=[key]
                        ).sort_values("date")
                        if observed.empty:
                            continue
                        last = observed.iloc[-1]
                        last_values.append({
                            "Показатель": label,
                            "Отчётная дата": last["date"].strftime("%d.%m.%Y"),
                            "Задолженность, млрд ₽": round(float(last[key]), 3),
                        })

                    if last_values:
                        st.subheader("Последние опубликованные значения")
                        st.dataframe(
                            pd.DataFrame(last_values),
                            hide_index=True,
                            use_container_width=True,
                        )

            st.caption(
                "Источник: Банк России, раздел статистики банковского "
                "сектора. Физлица — все кредиты резидентам; "
                "компании — юридические лица-резиденты и ИП; "
                "МСП — отдельная пересекающаяся категория. "
                "Показатели нельзя суммировать между собой."
            )

        with mortgage_tab:
            st.subheader("Ипотечное жилищное кредитование")
            st.caption(
                "Банк России · Кредиты в рублях · Отчётные даты "
                "с января 2020 года"
            )

            mortgage = load_russia_mortgage()
            if mortgage.empty:
                st.warning(
                    "Ипотечные данные пока не загружены. "
                    "Выполни python scheduler.py ru."
                )
            else:
                mortgage = mortgage.loc[
                    mortgage["country"] == "RU"
                ].copy()
                mortgage["date"] = pd.to_datetime(mortgage["date"])
                mortgage = mortgage.loc[
                    mortgage["date"] >= "2020-01-01"
                ].sort_values("date")

                mortgage_metrics = {
                    "rate_pct": ("Средневзвешенная ставка", "% годовых"),
                    "term_months": ("Средневзвешенный срок", "месяцев"),
                    "issued_count": ("Количество выданных кредитов", "шт."),
                    "issued_bln": ("Объём выданных кредитов", "млрд ₽"),
                    "debt_bln": ("Задолженность по ипотеке", "млрд ₽"),
                    "overdue_bln": ("Просроченная задолженность", "млрд ₽"),
                }

                st.subheader("Последние опубликованные показатели")
                latest_rows = []
                for key, (label, unit) in mortgage_metrics.items():
                    if key not in mortgage.columns:
                        continue
                    valid = mortgage[["date", key]].dropna(subset=[key])
                    if valid.empty:
                        continue
                    last = valid.iloc[-1]
                    latest_rows.append({
                        "Показатель": label,
                        "Отчётная дата": last["date"].strftime("%d.%m.%Y"),
                        "Значение": round(float(last[key]), 3),
                        "Единица": unit,
                    })
                if latest_rows:
                    st.dataframe(
                        pd.DataFrame(latest_rows),
                        hide_index=True,
                        use_container_width=True,
                    )

                st.subheader("Исторические ряды: шесть показателей")
                st.caption(
                    "Из-за разных единиц на общем ипотечном графике "
                    "каждый ряд показан как индекс (первое доступное "
                    "значение = 100). Исходные значения видны при наведении."
                )
                mortgage_selection = list(mortgage_metrics)
                with st.popover(
                    "Показатели ипотеки: выбрать галочками",
                    use_container_width=True,
                ):
                    for key, (label, unit) in mortgage_metrics.items():
                        cb = f"ru_mortgage_checked_{key}"
                        if cb not in st.session_state:
                            st.session_state[cb] = True
                        st.checkbox(f"{label} ({unit})", key=cb)
                mortgage_selection = [
                    key for key in mortgage_metrics
                    if st.session_state.get(f"ru_mortgage_checked_{key}", False)
                ]
                mortgage_plot = [
                    (mortgage, key, mortgage_metrics[key][0], mortgage_metrics[key][1])
                    for key in mortgage_selection
                ]
                ru_indexed_chart(
                    mortgage_plot,
                    "Ипотека: динамика шести показателей",
                )

            st.caption(
                "Источник: Банк России, 02_02_Mortgage.xlsx, "
                "лист «в рублях». Количество, объём выдач, ставка и срок "
                "относятся к кредитам, выданным в течение месяца; "
                "задолженность и просрочка — остатки на отчётную дату. "
                "Задолженность здесь — только по предоставленным кредитам, "
                "без присоединения приобретённых прав требования."
            )

        with compare_tab:
            st.subheader("Сравнение всех 15 обязательных показателей")
            st.caption(
                "Три блока: 6 категорий ставок, 3 показателя кредитования, "
                "6 ипотечных метрик. Разные единицы приведены к индексу "
                "100 только для сравнения динамики. Исходные значения "
                "и единицы доступны при наведении на линию."
            )
            all_rows = []
            all_labels = {}

            def include_series(data, key, title, unit):
                if not data.empty and key in data.columns and data[key].notna().any():
                    all_rows.append((data, key, title, unit))
                    all_labels[key] = title

            # Ставки, включая дополнительный корпоративный ряд.
            for key, title in labels.items():
                include_series(detail_rates, key, title, "% годовых")

            # Задолженность.
            credit_for_compare = load_russia_credit()
            if not credit_for_compare.empty:
                credit_for_compare = credit_for_compare.loc[
                    credit_for_compare["country"] == "RU"
                ].copy()
            for key, title in {
                "personal_debt": "Задолженность физических лиц",
                "company_debt": "Задолженность юридических лиц и ИП",
                "sme_debt": "Задолженность МСП",
            }.items():
                include_series(credit_for_compare, key, title, "млрд ₽")

            # Ипотека.
            mortgage_for_compare = load_russia_mortgage()
            if not mortgage_for_compare.empty:
                mortgage_for_compare = mortgage_for_compare.loc[
                    mortgage_for_compare["country"] == "RU"
                ].copy()
            for key, (title, unit) in {
                "rate_pct": ("Ипотека: ставка", "% годовых"),
                "term_months": ("Ипотека: срок", "месяцев"),
                "issued_count": ("Ипотека: количество выдач", "шт."),
                "issued_bln": ("Ипотека: объём выдач", "млрд ₽"),
                "debt_bln": ("Ипотека: задолженность", "млрд ₽"),
                "overdue_bln": ("Ипотека: просроченная задолженность", "млрд ₽"),
            }.items():
                include_series(mortgage_for_compare, key, title, unit)

            if "sme_loans_1y" not in detail_rates.columns or not detail_rates["sme_loans_1y"].notna().any():
                st.warning(
                    "Ставка МСП пока не загружена в SQLite. "
                    "Запусти python scheduler.py ru."
                )
            with st.popover("Показатели общего графика", use_container_width=True):
                for _, key, title, _ in all_rows:
                    widget = f"ru_compare_checked_{key}"
                    if widget not in st.session_state:
                        st.session_state[widget] = True
                    st.checkbox(title, key=widget)
            selected_rows = [
                row for row in all_rows
                if st.session_state.get(f"ru_compare_checked_{row[1]}", False)
            ]
            st.caption(f"Выбрано рядов: {len(selected_rows)} из {len(all_rows)} доступных")
            ru_indexed_chart(selected_rows, "Общая динамика показателей России")

        with money_tab:
            st.subheader("Денежная масса России — M0, M1, M2, M2X")
            st.caption(
                "Банк России · опубликованные уровни на 1-е число месяца · "
                "млрд рублей · история с января 2020 года"
            )
            money = load_russia_money()
            if money.empty:
                st.warning("Денежные агрегаты ещё не загружены. Запусти python scheduler.py ru.")
            else:
                money = money.loc[money["country"] == "RU"].copy()
                money["date"] = pd.to_datetime(money["date"])
                money = money.loc[money["date"] >= "2020-01-01"].sort_values("date")
                money_labels = {
                    "m0": "M0 — наличные деньги",
                    "m1": "M1 — наличные и переводные депозиты",
                    "m2": "M2 — рублёвая денежная масса",
                    "m2x": "M2X — широкая денежная масса",
                }
                valid_money = {
                    k: v for k, v in money_labels.items()
                    if k in money.columns and money[k].notna().any()
                }
                if valid_money:
                    for metric in valid_money:
                        state_key = f"ru_money_checked_{metric}"
                        if state_key not in st.session_state:
                            st.session_state[state_key] = True
                    with st.popover("Выбрать денежные агрегаты", use_container_width=True):
                        all_col, none_col = st.columns(2)
                        with all_col:
                            if st.button("Выбрать все", key="ru_money_all", use_container_width=True):
                                for metric in valid_money:
                                    st.session_state[f"ru_money_checked_{metric}"] = True
                                st.rerun()
                        with none_col:
                            if st.button("Снять все", key="ru_money_none", use_container_width=True):
                                for metric in valid_money:
                                    st.session_state[f"ru_money_checked_{metric}"] = False
                                st.rerun()
                        for metric, label in valid_money.items():
                            st.checkbox(label, key=f"ru_money_checked_{metric}")
                    selected_money = {
                        k: label for k, label in valid_money.items()
                        if st.session_state.get(f"ru_money_checked_{k}", False)
                    }
                    if selected_money:
                        ru_line_chart(
                            money, "Денежные агрегаты России", selected_money, unit="млрд ₽"
                        )
                    else:
                        st.info("Выбери хотя бы один денежный агрегат.")
                    last_rows = []
                    for metric, label in valid_money.items():
                        valid = money[["date", metric]].dropna(subset=[metric])
                        if not valid.empty:
                            last = valid.iloc[-1]
                            last_rows.append({
                                "Агрегат": label,
                                "Отчётная дата": last["date"].strftime("%d.%m.%Y"),
                                "млрд ₽": round(float(last[metric]), 1),
                            })
                    if last_rows:
                        st.subheader("Последние опубликованные значения")
                        st.dataframe(pd.DataFrame(last_rows), hide_index=True, use_container_width=True)
            st.caption(
                "Источник: Банк России, денежные агрегаты, лист «Денежные агрегаты»; "
                "значения опубликованы в млрд рублей на отчётную дату. "
                "M2X включает валютные депозиты."
            )

        with trade_tab:
            st.subheader("Экспорт и импорт товаров России")
            st.caption(
                "Банк России · внешняя торговля по методологии платёжного баланса · "
                "месячные потоки в млрд долларов США · с января 2020 года"
            )
            trade = load_russia_trade()
            estimates = load_russia_trade_estimates()
            trade_labels = {
                "exports_goods_bln_usd": "Экспорт товаров (ФОБ)",
                "imports_goods_bln_usd": "Импорт товаров (ФОБ)",
                "balance_goods_bln_usd": "Сальдо торгового баланса",
            }
            if trade.empty:
                st.warning("Нет данных внешней торговли. Запусти python scheduler.py ru.")
            else:
                trade = trade.loc[trade["country"] == "RU"].copy()
                trade["date"] = pd.to_datetime(trade["date"])
                trade = trade.loc[trade["date"] >= "2020-01-01"].sort_values("date")
                available_trade = {
                    k:v for k,v in trade_labels.items()
                    if k in trade.columns and trade[k].notna().any()
                }
                for key in available_trade:
                    w = f"ru_trade_checked_{key}"
                    if w not in st.session_state:
                        st.session_state[w] = True
                with st.popover("Выбрать показатели внешней торговли", use_container_width=True):
                    left, right = st.columns(2)
                    with left:
                        if st.button("Выбрать все", key="ru_trade_all", use_container_width=True):
                            for key in available_trade:
                                st.session_state[f"ru_trade_checked_{key}"] = True
                            st.rerun()
                    with right:
                        if st.button("Снять все", key="ru_trade_none", use_container_width=True):
                            for key in available_trade:
                                st.session_state[f"ru_trade_checked_{key}"] = False
                            st.rerun()
                    for key, title in available_trade.items():
                        st.checkbox(title, key=f"ru_trade_checked_{key}")
                selection = {
                    key: title for key,title in available_trade.items()
                    if st.session_state.get(f"ru_trade_checked_{key}", False)
                }
                if selection:
                    ru_line_chart(trade, "Внешняя торговля товарами", selection, unit="млрд USD")
                else:
                    st.info("Выбери хотя бы один ряд.")
                recent=[]
                for key,title in available_trade.items():
                    v=trade[["date",key]].dropna(subset=[key]).sort_values("date")
                    if not v.empty:
                        last=v.iloc[-1]
                        recent.append({"Показатель":title,"Дата":last["date"].strftime("%m.%Y"),
                                       "млрд USD":round(float(last[key]),3)})
                if recent:
                    st.subheader("Последние опубликованные месячные значения")
                    st.dataframe(pd.DataFrame(recent), hide_index=True, use_container_width=True)
            st.caption("Источник истории: ЦБ РФ, trade.xls, лист «Ежемесячные». "
                       "Данные могут пересматриваться. Сальдо берётся из отдельной опубликованной колонки, "
                       "не рассчитывается как разность экспорта и импорта.")
            st.subheader("Оперативные оценки ЦБ")
            if estimates.empty:
                st.info("Оценки ещё не загружены или в свежем выпуске нет отдельных месячных оценок.")
            else:
                estimates = estimates.loc[estimates["country"] == "RU"].copy()
                estimates["date"] = pd.to_datetime(estimates["date"])
                estimates = estimates.sort_values("date")
                cols = ["date"] + [k for k in trade_labels if k in estimates.columns]
                view = estimates[cols].rename(columns={"date":"Период", **trade_labels})
                st.dataframe(view, hide_index=True, use_container_width=True)
                st.caption("Источник: ЦБ РФ, bop_est.xlsx. Только месяцы с явной пометкой «оценка». "
                           "Оценки хранятся отдельно и не перезаписывают исторические значения.")

        with investors_tab:
            st.subheader("Частные инвесторы Московской биржи")
            st.caption(
                "Официальные месячные публикации Мосбиржи · с января 2024 года. "
                "Каждое значение берётся из первоисточника; отсутствующие данные не рассчитываются."
            )

            investors = load_russia_investors()
            investor_metrics = {
                "invested_total_bln": ("Вложения всего", "млрд ₽"),
                "invested_shares_bln": ("Вложения в акции", "млрд ₽"),
                "invested_bonds_bln": ("Вложения в облигации", "млрд ₽"),
                "invested_funds_bln": ("Вложения в фонды", "млрд ₽"),
                "active_investors_mln": ("Активные инвесторы", "млн чел."),
                "brokerage_clients_mln": ("Клиенты с брокерскими счетами", "млн чел."),
                "share_equity_pct": ("Доля физлиц в торгах акциями", "%"),
                "share_bonds_pct": ("Доля физлиц в торгах облигациями", "%"),
                "share_derivatives_pct": ("Доля физлиц на срочном рынке", "%"),
                "iis_accounts_mln": ("Количество ИИС", "млн счетов"),
                "iis_turnover_bln": ("Оборот по ИИС", "млрд ₽"),
            }

            if investors.empty or "country" not in investors:
                st.warning(
                    "Нет подтверждённых данных. Запусти `python scheduler.py ru` "
                    "и проверь раздел `[RU INVESTORS]` в журнале."
                )
            else:
                investors = investors.loc[investors["country"] == "RU"].copy()
                investors["date"] = pd.to_datetime(investors["date"], errors="coerce")
                investors = investors.dropna(subset=["date"]).sort_values("date")
                investors = investors.loc[investors["date"] >= pd.Timestamp("2024-01-01")]
                investors = investors.drop_duplicates(subset=["date"], keep="last")
                # Руководитель запросил только точные значения.
                # Приблизительные формулировки MOEX скрываем и не экспортируем.
                for metric_key in investor_metrics:
                    qualifier_key = metric_key + "_qualifier"
                    if qualifier_key in investors.columns and metric_key in investors.columns:
                        approximated = investors[qualifier_key].fillna("").astype(str).str.strip().ne("")
                        investors.loc[approximated, metric_key] = float("nan")


                def _latest_investor_value(key):
                    if key not in investors.columns:
                        return None
                    observed = investors.loc[investors[key].notna(), ["date", key]]
                    if observed.empty:
                        return None
                    return observed.iloc[-1]

                def _metric_value(key):
                    last = _latest_investor_value(key)
                    if last is None:
                        return "—", "Нет опубликованных значений"
                    label, unit = investor_metrics[key]
                    value = float(last[key])
                    qualifier_col = key + "_qualifier"
                    qualifier = ""
                    if qualifier_col in investors.columns:
                        hit = investors.loc[investors["date"] == last["date"]]
                        if not hit.empty and pd.notna(hit.iloc[-1][qualifier_col]):
                            qualifier = str(hit.iloc[-1][qualifier_col]) + " "
                    return (qualifier + f"{value:,.2f}".replace(",", " ").replace(".", ",")
                            + " " + unit, last["date"].strftime("%m.%Y"))

                # KPI-карточки: разные показатели могут иметь разные последние месяцы.
                kpi_keys = [
                    "invested_total_bln", "invested_shares_bln", "invested_bonds_bln",
                    "invested_funds_bln", "active_investors_mln", "share_equity_pct",
                ]
                for offset in (0, 3):
                    cols = st.columns(3)
                    for column, key in zip(cols, kpi_keys[offset:offset + 3]):
                        with column:
                            value_text, period_text = _metric_value(key)
                            st.metric(investor_metrics[key][0], value_text, help=f"Отчётный период: {period_text}")
                            st.caption("Период: " + period_text)

                st.divider()
                period_col, info_col = st.columns([2, 3], vertical_alignment="bottom")
                with period_col:
                    investor_range = st.segmented_control(
                        "Период", options=["3 года", "5 лет", "Вся история"],
                        default="3 года", key="ru_investors_period",
                    )
                now_month = pd.Timestamp.now().to_period("M").to_timestamp()
                if investor_range == "3 года":
                    from_date = max(pd.Timestamp("2024-01-01"), now_month - pd.DateOffset(years=3))
                elif investor_range == "5 лет":
                    from_date = max(pd.Timestamp("2024-01-01"), now_month - pd.DateOffset(years=5))
                else:
                    from_date = pd.Timestamp("2024-01-01")
                shown = investors.loc[investors["date"] >= from_date].copy()
                with info_col:
                    if not shown.empty:
                        st.caption(
                            f"Отчётные месяцы: {shown['date'].min():%m.%Y} — "
                            f"{shown['date'].max():%m.%Y}. "
                            "Отсутствующие месяцы и показатели не интерполируются."
                        )

                investments_tab, persons_tab, turnover_tab, iis_tab = st.tabs([
                    "Вложения", "Инвесторы", "Доля в обороте", "ИИС",
                ])

                def _choose_investor_metrics(group_id, metric_keys):
                    available = [key for key in metric_keys
                                 if key in shown.columns and shown[key].notna().any()]
                    if not available:
                        st.info("Для этого раздела пока нет точных месячных данных из официальных публикаций.")
                        return []
                    for key in available:
                        state_key = "ru_investor_visual_" + key
                        if state_key not in st.session_state:
                            st.session_state[state_key] = True
                    chosen = [key for key in available
                              if st.session_state.get("ru_investor_visual_" + key, False)]
                    with st.popover(f"Показатели на графике ({len(chosen)} из {len(available)})", use_container_width=True):
                        c1, c2 = st.columns(2)
                        if c1.button("Выбрать все", key="ru_inv_all_" + group_id, use_container_width=True):
                            for key in available:
                                st.session_state["ru_investor_visual_" + key] = True
                            st.rerun()
                        if c2.button("Снять все", key="ru_inv_none_" + group_id, use_container_width=True):
                            for key in available:
                                st.session_state["ru_investor_visual_" + key] = False
                            st.rerun()
                        for key in available:
                            st.checkbox(investor_metrics[key][0], key="ru_investor_visual_" + key)
                    return [key for key in available
                            if st.session_state.get("ru_investor_visual_" + key, False)]

                def _investor_plot(keys, title, unit):
                    if not keys:
                        st.info("Выбери хотя бы один показатель для графика.")
                        return
                    fig = go.Figure()
                    for key in keys:
                        values = shown[["date", key]].dropna(subset=[key]).sort_values("date")
                        if values.empty:
                            continue
                        qualifier_col = key + "_qualifier"
                        if qualifier_col in shown.columns:
                            values = shown[["date", key, qualifier_col]].dropna(subset=[key]).sort_values("date")
                            notes = values[qualifier_col].fillna("").astype(str)
                        else:
                            notes = pd.Series([""] * len(values), index=values.index)
                        symbols = ["diamond" if note else "circle" for note in notes]
                        hover_notes = [((note + " (оценка): ") if note else "") for note in notes]
                        fig.add_trace(go.Scatter(
                            x=values["date"], y=values[key], mode="lines+markers",
                            name=investor_metrics[key][0], connectgaps=False,
                            line={"width": 2}, marker={"size": 7, "symbol": symbols},
                            customdata=hover_notes,
                            hovertemplate="%{x|%m.%Y}: %{customdata}%{y:,.2f} " + unit + "<extra>%{fullData.name}</extra>",
                        ))
                    fig.update_layout(
                        title=title, xaxis_title="Отчётный месяц", yaxis_title=unit,
                        hovermode="x unified", height=440,
                        legend={"orientation": "h", "y": -0.25},
                        margin={"l": 25, "r": 20, "t": 60, "b": 85},
                    )
                    fig.update_xaxes(range=[from_date, max(now_month, shown["date"].max())])
                    st.plotly_chart(fig, use_container_width=True)

                with investments_tab:
                    st.markdown("#### Вложения частных инвесторов")
                    st.caption(
                        "Млрд рублей за месяц. Столбцы — отдельно опубликованные категории, "
                        "линия — только официальный общий итог. Они не суммируются друг с другом."
                    )
                    investment_keys = ["invested_total_bln", "invested_shares_bln",
                                       "invested_bonds_bln", "invested_funds_bln"]
                    chosen = _choose_investor_metrics("invest", investment_keys)
                    if chosen:
                        chart = go.Figure()
                        chart_colors = {
                            "invested_shares_bln": "#f59e0b",
                            "invested_bonds_bln": "#10b981",
                            "invested_funds_bln": "#8b5cf6",
                        }
                        for key in chosen:
                            if key == "invested_total_bln":
                                continue
                            valid = shown[["date", key]].dropna(subset=[key])
                            chart.add_trace(go.Bar(
                                x=valid["date"], y=valid[key], name=investor_metrics[key][0],
                                marker_color=chart_colors[key],
                                hovertemplate="%{x|%m.%Y}: %{y:,.2f} млрд ₽<extra>%{fullData.name}</extra>",
                            ))
                        if "invested_total_bln" in chosen:
                            valid = shown[["date", "invested_total_bln"]].dropna(subset=["invested_total_bln"])
                            chart.add_trace(go.Scatter(
                                x=valid["date"], y=valid["invested_total_bln"],
                                mode="lines+markers", name="Вложения всего (публикация биржи)",
                                line={"color": "#2563eb", "width": 3}, marker={"size": 6},
                                connectgaps=False,
                                hovertemplate="%{x|%m.%Y}: %{y:,.2f} млрд ₽<extra>%{fullData.name}</extra>",
                            ))
                        chart.update_layout(
                            barmode="group", title="Вложения частных инвесторов, млрд ₽",
                            xaxis_title="Отчётный месяц", yaxis_title="млрд ₽",
                            hovermode="x unified", height=500,
                            legend={"orientation": "h", "y": -0.25},
                            margin={"l": 25, "r": 20, "t": 65, "b": 95},
                        )
                        chart.update_xaxes(range=[from_date, max(now_month, shown["date"].max())])
                        st.plotly_chart(chart, use_container_width=True)
                    else:
                        st.info("Выбери хотя бы один показатель для графика.")
                    st.caption("Отрицательные значения означают чистый отток. Пропуски не означают ноль.")

                with persons_tab:
                    st.markdown("#### Активность частных инвесторов")
                    keys = _choose_investor_metrics("persons", [
                        "active_investors_mln", "brokerage_clients_mln"])
                    _investor_plot(keys, "Частные инвесторы Московской биржи", "млн человек")
                    st.caption("Показаны только точные опубликованные значения; приблизительные оценки исключены.")

                with turnover_tab:
                    st.markdown("#### Доля физлиц в торговом обороте")
                    keys = _choose_investor_metrics("turnover", [
                        "share_equity_pct", "share_bonds_pct", "share_derivatives_pct"])
                    _investor_plot(keys, "Доля физлиц в обороте по рынкам", "%")

                with iis_tab:
                    st.markdown("#### Индивидуальные инвестиционные счета")
                    st.caption("Счета и денежный оборот имеют разные единицы измерения; поэтому графики разделены.")
                    keys = _choose_investor_metrics("iis", ["iis_accounts_mln", "iis_turnover_bln"])
                    for key in keys:
                        _investor_plot([key], investor_metrics[key][0], investor_metrics[key][1])

                st.subheader("Последние опубликованные значения")
                latest_rows = []
                for key, (label, unit) in investor_metrics.items():
                    row = _latest_investor_value(key)
                    if row is None:
                        continue
                    source_rows = investors.loc[
                        investors["date"] == row["date"]
                    ]
                    source_url = source_rows.iloc[-1].get("source_url", "") if not source_rows.empty else ""
                    latest_rows.append({
                        "Показатель": label,
                        "Период": row["date"].strftime("%m.%Y"),
                        "Значение": round(float(row[key]), 3),
                        "Точность": (
                            str(source_rows.iloc[-1].get(key + "_qualifier"))
                            if not source_rows.empty and pd.notna(source_rows.iloc[-1].get(key + "_qualifier"))
                            else "точное"
                        ),
                        "Единица": unit,
                        "Источник": source_url if isinstance(source_url, str) else "",
                    })
                if latest_rows:
                    st.dataframe(
                        pd.DataFrame(latest_rows), hide_index=True,
                        use_container_width=True,
                        column_config={"Источник": st.column_config.LinkColumn("Источник")},
                    )
                export_columns = ["date"] + [
                    key for key in investor_metrics if key in shown.columns
                ] + [key for key in ("active_investors_mln_qualifier", "brokerage_clients_mln_qualifier",
                                      "source_url", "publication_date") if key in shown.columns]
                export = shown[export_columns].copy()
                export["date"] = export["date"].dt.strftime("%Y-%m")
                st.download_button(
                    "📥 Скачать месячные данные CSV",
                    export.to_csv(index=False).encode("utf-8-sig"),
                    file_name="russia_private_investors.csv", mime="text/csv",
                    key="ru_investors_export_csv",
                )
                with st.expander("Полнота данных и методология"):
                    expected = pd.date_range(
                        "2024-01-01",
                        pd.Timestamp.now().to_period("M").to_timestamp() - pd.DateOffset(months=1),
                        freq="MS",
                    )
                    observed = set(investors["date"].dt.to_period("M"))
                    missing = [d.strftime("%m.%Y") for d in expected if d.to_period("M") not in observed]
                    st.write(f"Периодов без подтверждённой публикации: {len(missing)}")
                    if missing:
                        st.caption("Месяцы без публикаций: " + ", ".join(missing))
                    for key, (label, _) in investor_metrics.items():
                        count = int(investors[key].notna().sum()) if key in investors else 0
                        st.caption(f"{label}: {count} подтверждённых наблюдений")
                    st.caption(
                        "Не восстанавливаем пропуски и не рассчитываем сумму категорий. "
                        "Разные показатели могут иметь разные последние месяцы. "
                        "Даты относятся к отчётным периодам, а не к датам публикаций."
                    )

        with reference_tab:
            st.subheader("Статистика ЦБ РФ — справочные показатели")
            st.caption(
                "Только опубликованные точные уровни; без графиков и самостоятельных расчётов. "
                "Брокеры и ИИС — квартальные данные, ПИФ — месячные данные. "
                "Периоды в таблицах — отчётные, не даты публикаций."
            )
            reference = load_russia_cbr_reference()
            expected = {
                "Брокеры и ПУРЦБ": [
                    ("Средний размер портфеля физлица-резидента", "broker_average_portfolio"),
                    ("Активы клиентов на брокерских счетах", "broker_assets"),
                    ("Нетто-взносы физлиц на брокерские счета", "broker_net_contributions"),
                    ("Количество клиентов на брокерском обслуживании", "broker_clients"),
                    ("Количество ПУРЦБ", "purcb_count"),
                ],
                "ИИС": [
                    ("Количество ИИС", "iis_count"),
                    ("Активы ИИС", "iis_assets"),
                    ("Средний размер ИИС", "iis_average"),
                    ("Закрытые ИИС за квартал", "iis_closed"),
                    ("Нетто-взносы на ИИС", "iis_net_contributions"),
                ],
                "Коллективные инвестиции": [
                    ("Количество зарегистрированных ПИФ", "pif_count"),
                    ("Выдача инвестиционных паёв", "pif_issued"),
                    ("СЧА ПИФ", "pif_nav"),
                    ("Погашение инвестиционных паёв", "pif_redeemed"),
                ],
            }
            sections = st.tabs(list(expected))
            for tab, (section, requested) in zip(sections, expected.items()):
                with tab:
                    rows = []
                    for title, metric in requested:
                        subset = pd.DataFrame()
                        if not reference.empty and metric is not None:
                            subset = reference.loc[reference["metric"] == metric].sort_values("date")
                        if subset.empty:
                            rows.append({"Показатель": title, "Значение": "—",
                                         "Ед. изм.": "—", "Отчётный период": "—",
                                         "Статус": "Источник точного готового ряда пока не подтверждён",
                                         "Источник ЦБ": "—"})
                        else:
                            last = subset.iloc[-1]
                            number = float(last["value"])
                            display = (f"{int(number):,}" if number.is_integer()
                                       else f"{number:,.3f}".rstrip("0").rstrip("."))
                            display = display.replace(",", " ")
                            rows.append({"Показатель": title, "Значение": display,
                                         "Ед. изм.": str(last["unit"]),
                                         "Отчётный период": pd.Timestamp(last["date"]).strftime("%d.%m.%Y"),
                                         "Статус": ("Опубликован ЦБ (архивный отчёт)"
                                                    if last["source_row"] == -1
                                                    else "Опубликован ЦБ"),
                                         "Источник ЦБ": str(last["source_url"])})
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                    st.caption("Пустые карточки не рассчитываются из других рядов. "
                               "Архивные значения указываются с собственным отчётным периодом, "
                               "а не с датой последней публикации другого показателя. "
                               "Средний брокерский портфель — без небольших счетов; "
                               "средний ИИС — только брокерские ИИС. "
                               "Погашение паёв показано положительным опубликованным объёмом.")
            if reference.empty:
                st.info("Чтобы загрузить справочные показатели: python scheduler.py ru")

        with other_tab:
            st.subheader("Идеи для дальнейшего развития")
            st.caption(
                "Не входят в исходное задание. Возможные дополнительные "
                "направления после завершения обязательных показателей."
            )
            st.markdown(
                """
                **Рынок облигаций**
                - Доходности ОФЗ по срокам погашения и кривая бескупонной доходности

                **Платёжная инфраструктура**
                - Объём и количество операций через Систему быстрых платежей (СБП)

                **Рыночные индикаторы**
                - Индекс МосБиржи и индекс РТС: исторические уровни
                """
            )
