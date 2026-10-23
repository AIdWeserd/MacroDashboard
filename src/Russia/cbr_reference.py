"""Official CBR reference indicators for brokers, IIS and mutual funds.

Only directly published source rows are extracted. No averages, net flows,
component sums or other economic indicators are calculated locally.
"""
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import requests

SOURCES = {
    "broker": ("https://www.cbr.ru/Content/Document/File/156473/d_broker.xlsx", "Брокерское обслуживание", 0, 1, 0),
    "iis": ("https://www.cbr.ru/Content/Document/File/156269/d_iis.xlsx", "ИИС ", 1, 2, 1),
    "purcb": ("https://www.cbr.ru/Content/Document/File/139979/purcb_stat.XLSX", "Компании и лицензии", 1, 2, 0),
    "pif": ("https://www.cbr.ru/Content/Document/File/131793/d_pif_aif.XLSX", "ПИФ_АИФ_Ряды данных", 0, 1, 0),
}
# (code, section, name, source, 0-based row, expected source label, conversion factor, unit)
METRICS = [
    ("broker_assets", "Брокеры и ПУРЦБ", "Активы клиентов на брокерских счетах", "broker", 100, "Объем клиентских активов на брокерских счетах", 1, "млрд ₽"),
    ("broker_clients", "Брокеры и ПУРЦБ", "Количество клиентов на брокерском обслуживании", "broker", 14, "Количество клиентов на брокерском обслуживании", 1000, "чел."),
    ("purcb_count", "Брокеры и ПУРЦБ", "Количество ПУРЦБ", "purcb", 1, "Количество ПУРЦБ", 1, "ед."),
    ("iis_count", "ИИС", "Количество ИИС", "iis", 2, "Количество индивидуальных инвестиционных счетов (ИИС)", 1000, "ед."),
    ("iis_assets", "ИИС", "Активы ИИС", "iis", 13, "Совокупный объем активов на индивидуальных инвестиционных счетах (ИИС)", 1, "млрд ₽"),
    ("iis_closed", "ИИС", "Прекращённые договоры ИИС за квартал", "iis", 91, "Количество прекращенных договоров на ведение ИИС за квартал", 1000, "ед."),
    ("pif_count", "Коллективные инвестиции", "Количество зарегистрированных ПИФ", "pif", 2, "Количество зарегистрированных ПИФ", 1, "ед."),
    ("pif_nav", "Коллективные инвестиции", "СЧА ПИФ", "pif", 91, "Стоимость чистых активов ПИФ", 0.001, "млрд ₽"),
]


# Directly published OFFICIAL historical observations, not constructed from
# other series. These are conservative fallback datapoints when the four XLSX
# workbooks have no corresponding ready-made metric. Every item has its own
# reporting period and exact primary-source URL. Do NOT propagate to other dates.
OFFICIAL_PUBLICATIONS = [
    # CBR Review of Brokers, Q1 2026, pp. 4–6; excludes small accounts
    ('broker_average_portfolio', 'Брокеры и ПУРЦБ',
     'Средний размер портфеля физлица-резидента (без счетов до 10 тыс. ₽)',
     '2026-03-31', 2.3, 'млн ₽',
     'https://www.cbr.ru/Collection/Collection/File/61013/review_broker_Q1_2026.pdf',
     'Обзор брокеров, I квартал 2026', 'квартальная'),
    ('broker_net_contributions', 'Брокеры и ПУРЦБ',
     'Нетто-взносы физлиц на брокерские счета',
     '2026-03-31', 910.0, 'млрд ₽',
     'https://www.cbr.ru/Collection/Collection/File/61013/review_broker_Q1_2026.pdf',
     'Обзор брокеров, I квартал 2026', 'квартальная'),
    # CBR IIS review, Q1 2026: published 145 thousand for brokerage IIS.
    ('iis_average', 'ИИС', 'Средний размер брокерского ИИС',
     '2026-03-31', 145.0, 'тыс. ₽',
     'https://www.cbr.ru/analytics/rcb/iis_1q_2026/',
     'Обзор ИИС, I квартал 2026', 'квартальная'),
    # CBR IIS review, Q4 2025: explicitly stated TOTAL net flows 104 bn.
    ('iis_net_contributions', 'ИИС', 'Нетто-взносы на ИИС (все счета)',
     '2025-12-31', 104.0, 'млрд ₽',
     'https://www.cbr.ru/analytics/rcb/rcbiis_4q_2025',
     'Обзор ИИС, IV квартал 2025', 'квартальная'),
    # CBR Statistical Bulletin 2025 No.6, table 4.5.4, Q1 2025.
    # Both values are official published million-RUB figures; no computations.
    ('pif_issued', 'Коллективные инвестиции', 'Выдача инвестиционных паёв ПИФ',
     '2025-03-31', 757302.7, 'млн ₽',
     'https://www.cbr.ru/Collection/Collection/File/57006/Bbs2506r.pdf',
     'Статистический бюллетень, таблица 4.5.4, I квартал 2025', 'квартальная'),
    ('pif_redeemed', 'Коллективные инвестиции',
     'Погашение инвестиционных паёв ПИФ (объём, положительная величина)',
     '2025-03-31', 302017.2, 'млн ₽',
     'https://www.cbr.ru/Collection/Collection/File/57006/Bbs2506r.pdf',
     'Статистический бюллетень, таблица 4.5.4, I квартал 2025', 'квартальная'),
]


CACHE_DIR = Path(__file__).resolve().parents[2] / 'data' / 'cbr_reference_cache'
CACHE_NAMES = {
    'broker': 'd_broker.xlsx', 'iis': 'd_iis.xlsx',
    'purcb': 'purcb_stat.XLSX', 'pif': 'd_pif_aif.XLSX',
}


def _parse_workbook(data: bytes, source: str) -> pd.DataFrame:
    _, sheet, _, _, _ = SOURCES[source]
    if not data.startswith(b'PK'):
        raise ValueError('Ответ не является XLSX')
    frame = pd.read_excel(BytesIO(data), sheet_name=sheet, header=None)
    if frame.empty or frame.shape[1] < 10:
        raise ValueError('Неожиданная структура таблицы')
    return frame


def _load(source):
    """Prefer current official Excel; use last verified download during outage."""
    url, _, _, _, _ = SOURCES[source]
    urls = [url]
    if 'www.cbr.ru' in url:
        urls.append(url.replace('www.cbr.ru', 'cbr.ru'))
    failures = []
    for candidate in urls:
        try:
            r = requests.get(
                candidate,
                headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'},
                timeout=(8, 35),
            )
            r.raise_for_status()
            frame = _parse_workbook(r.content, source)
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                (CACHE_DIR / CACHE_NAMES[source]).write_bytes(r.content)
            except OSError as cache_exc:
                print(f'[RU REFERENCE] WARNING {source}: не удалось обновить локальный кэш: {cache_exc}')
            return frame
        except (requests.RequestException, ValueError, OSError, KeyError) as exc:
            failures.append(f'{candidate}: {exc}')

    cached = CACHE_DIR / CACHE_NAMES[source]
    if cached.is_file():
        print(f'[RU REFERENCE] WARNING {source}: ЦБ недоступен; '
              f'используем прежний официальный файл {cached.name} (может быть устаревшим)')
        return _parse_workbook(cached.read_bytes(), source)
    raise RuntimeError('; '.join(failures))


def _date(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).normalize()
    if isinstance(value, (float, int)) and 40000 < float(value) < 60000:
        return pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(value))
    return pd.to_datetime(value, errors='coerce')


def fetch_russia_cbr_reference():
    """Return validated official values and previously stored history.

    Partial network outages do not wipe previously downloaded metrics. The
    standard save function uses SQLite replace, so this merge is essential.
    """
    print('[RU REFERENCE] Загружаем официальные книги ЦБ независимо...')
    frames = {}
    for source in SOURCES:
        try:
            frames[source] = _load(source)
            print(f'[RU REFERENCE] {source}: Excel загружен')
        except Exception as exc:
            print(f'[RU REFERENCE] WARNING {source}: источник недоступен: {exc}')

    records = []
    for code, section, title, source, row_index, expected, multiplier, unit in METRICS:
        if source not in frames:
            print(f'[RU REFERENCE] {code}: пропущен (файл источника недоступен)')
            continue
        frame = frames[source]
        url, sheet, label_col, unit_col, date_row = SOURCES[source]
        try:
            observed = str(frame.iat[row_index, label_col]).strip()
            if not observed.startswith(expected):
                raise ValueError(f'Изменился заголовок: {observed!r}')
            metric_records = []
            for col in range(max(label_col, unit_col) + 1, frame.shape[1]):
                d = _date(frame.iat[date_row, col])
                if pd.isna(d) or d < pd.Timestamp('2020-01-01'):
                    continue
                v = pd.to_numeric(frame.iat[row_index, col], errors='coerce')
                if pd.isna(v):
                    continue
                metric_records.append({
                    'date': d.strftime('%Y-%m-%d'), 'country': 'RU',
                    'section': section, 'metric': code, 'label': title,
                    'value': float(v) * multiplier, 'unit': unit,
                    'source_url': url, 'source_sheet': sheet,
                    'source_row': row_index + 1,
                    'periodicity': 'квартальная/месячная' if source == 'pif' else 'квартальная',
                })
            if not metric_records:
                raise ValueError('Нет датированных опубликованных значений')
            records.extend(metric_records)
            print(f'[RU REFERENCE] {code}: {len(metric_records)} опубликованных значений')
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            print(f'[RU REFERENCE] WARNING {code}: данные не прошли проверку: {exc}')

    # Supplement sources only with source-authored values for named periods.
    # These are historical reference points; the existing 4-workbook loader
    # continues updating the other eight metrics automatically.
    for code, section, title, date, value, unit, url, document, frequency in OFFICIAL_PUBLICATIONS:
        records.append({
            'date': date, 'country': 'RU', 'section': section,
            'metric': code, 'label': title, 'value': value, 'unit': unit,
            'source_url': url, 'source_sheet': document,
            'source_row': -1, 'periodicity': frequency,
        })
    print(f'[RU REFERENCE] Исторические официальные публикации: {len(OFFICIAL_PUBLICATIONS)} точных показателей')

    # АВТОМАТИЧЕСКИЙ ПОИСК НОВЫХ ВЫПУСКОВ ЦБ:
    # - обзоры брокеров (PDF),
    # - обзоры ИИС (HTML),
    # - статистические бюллетени, таблица 4.5.4 (PDF).
    # Вновь опубликованные точные значения перекрывают резервные строки
    # только для того же показателя и того же отчетного периода.
    from src.Russia.publications_auto import fetch_official_publications
    automatic_publications = fetch_official_publications()
    print(f'[RU REFERENCE] Из новых публикаций: {len(automatic_publications)} наблюдений')
    records.extend(automatic_publications)

    # Load old SQLite rows BEFORE scheduler calls save(... if_exists="replace").
    from src.storage import load_russia_cbr_reference
    previous = load_russia_cbr_reference()
    fresh = pd.DataFrame(records)
    if not previous.empty:
        required = set(fresh.columns) if not fresh.empty else {
            'date', 'country', 'section', 'metric', 'label', 'value',
            'unit', 'source_url', 'source_sheet', 'source_row', 'periodicity'
        }
        if required.issubset(previous.columns):
            previous = previous[list(required)].copy()
            previous['date'] = pd.to_datetime(previous['date']).dt.strftime('%Y-%m-%d')
            print(f'[RU REFERENCE] Сохраняем исторические строки из SQLite: {len(previous)}')
        else:
            print('[RU REFERENCE] WARNING: прежняя таблица имеет другую структуру; перенос пропущен')
            previous = pd.DataFrame()

    if not previous.empty:
        # New official publication wins for matching (metric, date).
        output = pd.concat([previous, fresh], ignore_index=True)
        output = output.drop_duplicates(['metric', 'date'], keep='last')
    else:
        output = fresh

    if output.empty:
        raise RuntimeError('[RU REFERENCE] Нет ни новых данных, ни ранее сохранённой истории; SQLite не трогаем')
    if output.duplicated(['date', 'metric']).any():
        raise ValueError('[RU REFERENCE] Дубли дат и метрик')
    print(f'[RU REFERENCE] Готово: {len(output)} строк; {output.metric.nunique()} показателей')
    return output.sort_values(['section', 'metric', 'date']).reset_index(drop=True)
