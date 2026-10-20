"""Официальные месячные данные о частных инвесторах Московской биржи.

История от 2024-01; без самостоятельного расчёта агрегатов. Каталог
проверенных ссылок плюс поиск новых релизов. При недоступности источника
ранее сохранённые значения остаются без изменений. Пропуски = NaN.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlencode, urlparse, unquote
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup

START = pd.Timestamp('2024-01-01')
FIELDS = [
    'invested_total_bln', 'invested_shares_bln', 'invested_bonds_bln',
    'invested_funds_bln', 'active_investors_mln', 'brokerage_clients_mln',
    'share_equity_pct', 'share_bonds_pct', 'share_derivatives_pct',
    'iis_accounts_mln', 'iis_turnover_bln',
]
COLUMNS = ['date', 'country', *FIELDS, 'source_url', 'publication_date', 'source_title']
MONTHS = ('январе', 'феврале', 'марте', 'апреле', 'мае', 'июне', 'июле',
          'августе', 'сентябре', 'октябре', 'ноябре', 'декабре')
GENITIVE = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
            'августа', 'сентября', 'октября', 'ноября', 'декабря')
# Вручную сверенный с официальными релизами MOEX каталог — не цифры!
# Отсутствующие месяцы ищутся автоматически через несколько вариантов запросов.
RELEASES = {
    '2024-01': 67292, '2024-02': 68157, '2024-03': 68762,
    '2024-04': 69393, '2024-05': 69982, '2024-06': 70897,
    '2024-07': 71711, '2024-08': 72763, '2024-09': 73724,
    '2024-10': 74568, '2024-11': 75459,
    '2025-01': 77432, '2025-02': 78262, '2025-03': 89174,
    '2025-04': 90170, '2025-05': 90818, '2025-06': 91719,
    '2025-07': 92582, '2025-08': 93371, '2025-09': 94152,
    '2025-10': 95149, '2025-11': 95808,
    '2026-03': 99083, '2026-07': 103240,
    '2026-08': 103939, '2026-09': 104958,
}
MOEX_RE = re.compile(r'https?://(?:www\.)?moex\.com/n\d+(?:\?[^\s"<>]*)?', re.I)
NUM = r'(-?\d[\d\s\u00a0\u202f]*(?:[,.]\d+)?)'
BILLION = rf'{NUM}\s*(?:млрд|миллиард(?:а|ов)?)\s*(?:руб(?:лей|ля|\.)?)?'
MILLION = rf'{NUM}\s*(?:млн|миллион(?:а|ов)?)\s*(?:человек|частных|физических|россиян|счетов|сч[её]тов)?'


def _num(raw):
    return float(re.sub(r'[\s\u00a0\u202f]', '', raw).replace(',', '.'))


def _get(session, url):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=(12, 35))
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def _url(candidate):
    candidate = unquote(candidate).split('?')[0]
    m = MOEX_RE.match(candidate)
    return m.group(0).split('?')[0].replace('http://', 'https://') if m else None


def _search_urls(session, period):
    """Поисковые системы используются только для обнаружения официальных URL."""
    month, gen = MONTHS[period.month - 1], GENITIVE[period.month - 1]
    queries = (
        f'site:moex.com/n "частных инвесторов" "{month}" "{period.year}"',
        f'site:moex.com/n "вложения" "{gen}" "{period.year}"',
        f'site:moex.com/n "брокерские счета" "{gen}" "{period.year}"',
    )
    found = []
    for q in queries:
        url = 'https://www.bing.com/search?' + urlencode({'q': q, 'format': 'rss'})
        try:
            root = ET.fromstring(_get(session, url))
            for item in root.findall('.//item'):
                link = _url(item.findtext('link') or '')
                if link:
                    found.append(link)
        except (ET.ParseError, requests.RequestException):
            pass
    return list(dict.fromkeys(found))


def _find(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            before = text[max(0, match.start('value') - 24):match.start('value')].lower()
            if re.search(r'(?:более|свыше|почти|около|примерно|превысил\w*)\s*$', before):
                continue
            return _num(match.group('value'))
    return None


def _billion(text, context):
    """Единицы всегда млрд рублей; не превращаем млн в млрд."""
    return _find(text, [rf'{context}[^.!?]{{0,130}}?(?:составил[аои]?|достигл[аои]?|вложил[иа]?|[-—:]|на сумму)\s*(?P<value>{NUM[1:-1]})\s*(?:млрд|миллиард)',
                        rf'{context}[^.!?]{{0,65}}?(?P<value>{NUM[1:-1]})\s*(?:млрд|миллиард)'])


def _article(html, url, expected):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.find('h1')
    if heading is None:
        return None
    title = heading.get_text(' ', strip=True)
    if not re.search('инвестор|физлиц|физическ', title, re.I):
        return None
    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()
    body = soup.get_text(' ', strip=True)
    start = body.find(title)
    if start >= 0:
        body = body[start:]
    body = re.sub(r'\s+', ' ', body).replace('\xa0', ' ').replace('–', '—')
    beginning = (title + ' ' + body[:1600]).lower()
    month, gen = MONTHS[expected.month - 1], GENITIVE[expected.month - 1]
    # Отказываемся от релиза, не подтверждающего нужный месяц.
    if not re.search(rf'\b(?:в\s+{month}|за\s+{gen}|по\s+итогам\s+{gen})\b', beginning):
        return None
    if str(expected.year) not in beginning[:1300]:
        return None
    # Если в заголовке назван отчётный месяц — он должен совпадать.
    mentioned = [i for i, m in enumerate(MONTHS) if re.search(rf'\b{m}\b', title.lower())]
    if mentioned and expected.month - 1 not in mentioned:
        return None

    result = {f: None for f in FIELDS}
    result.update(date=expected, country='RU', source_url=url,
                  publication_date=None, source_title=title)
    part = body[:7500]
    val = rf'(?P<value>{NUM[1:-1]})'
    bn = rf'{val}\s*(?:млрд|миллиард(?:а|ов)?)\s*(?:руб(?:лей|ля|\.)?)?'
    mn = rf'{val}\s*(?:млн|миллион(?:а|ов)?)'

    # Суммарные вложения — только явно опубликованный общий показатель.
    result['invested_total_bln'] = _find(part, [
        rf'(?:суммарный\s+об[ъь]ем\s+(?:вложений|инвестиций)|об[ъь]ем\s+инвестиций\s+(?:физлиц|физических\s+лиц)\s+в\s+ценные\s+бумаги|инвестиции\s+физических\s+лиц\s+в\s+ценные\s+бумаги|физлица\s+вложили\s+в\s+ценные\s+бумаги|частные\s+инвесторы\s+вложили\s+в\s+ценные\s+бумаги)[^.!?]{{0,220}}?(?:составил[аои]?|достигл[аои]?|—|-)\s*(?:рекордн(?:ых|ые|ого)\s+)?{bn}',
        rf'(?:вложения|инвестиции)\s+(?:физлиц|частных\s+инвесторов)[^.!?]{{0,100}}?в\s+ценные\s+бумаги[^.!?]{{0,90}}?{bn}',
        rf'в\s+{month}\s+{expected.year}\s+года\s+физлица\s+вложили\s+в\s+ценные\s+бумаги\s+{bn}',
    ])
    # В ряде выпусков итог стоит ДО фразы «из них»; суммы категорий не складываем.
    # В каждом компоненте допускаем только явное упоминание класса активов.
    assets = {
        'invested_shares_bln': r'акци[ийюи]',
        'invested_bonds_bln': r'облигаци[ийюи]',
        'invested_funds_bln': r'(?:паи\s+(?:биржевых\s+)?фондов|паи\s+ПИФов|БПИФы|биржевые\s+фонды|паевые\s+инвестиционные\s+фонды)',
    }
    for field, token in assets.items():
        patterns = [
            rf'(?:вложения|инвестиции|вложено|вложили|приток(?:\s+средств)?)\s+в\s+{token}\s*(?:составил[аои]?|—|-|на\s+сумму)?\s*{bn}',
            rf'(?:в\s+{token}|{token})\s*(?:—|-|составил[аои]?|вложено|вложили|на\s+сумму)\s*{bn}',
            rf'в\s+{token}\s+вложено\s+{bn}',
            rf'приток\s+в\s+{token}\s+составил\s+{bn}',
        ]
        result[field] = _find(part, patterns)
    # Предложения с «из них в ...» и вариант «облигации — 63,7».
    for field, asset in [('invested_shares_bln', 'акци'), ('invested_bonds_bln', 'облигаци'),
                         ('invested_funds_bln', '(?:фонды|БПИФ|паи)')]:
        if result[field] is not None:
            continue
        result[field] = _find(part, [rf'(?:в\s+)?{asset}\w*\s*(?:—|-)\s*{bn}'])
    # Отрицательное сальдо покупок: «продажи акций превысили покупки на...», не абсолютные покупки.
    for field, asset in [('invested_shares_bln', 'акци[ий]'),
                         ('invested_funds_bln', r'(?:паев|активов\s+фондов)')]:
        if result[field] is None:
            negative = _find(part, [rf'продажи\s+{asset}\s+превысили\s+покупки\s+на\s+{bn}',
                                    rf'сократили\s+(?:об[ъь]ем\s+)?инвестиц(?:ии|ий)\s+в\s+{asset}\s+на\s+{bn}'])
            if negative is not None:
                result[field] = -negative
    # Active: только число совершавших сделки в ОТЧЁТНОМ месяце, без «более/почти/около».
    result['active_investors_mln'] = _find(part[:3400], [
        rf'(?:сделки|операции)\s+(?:на\s+фондовом\s+рынке\s+)?(?:Московской\s+биржи\s+)?в\s+{month}\s+(?:заключали|совершали)\s+{mn}\s*(?:частных\s+инвесторов|человек)',
        rf'(?:сделки|операции)[^.!?]{{0,95}}?\b(?:заключали|совершали)\s+{mn}\s*(?:частных\s+инвесторов|человек)',
        rf'\b{mn}\s+(?:человек|частных\s+инвесторов)\s+(?:заключали|совершали)\s+сделки',
    ])
    result['brokerage_clients_mln'] = _find(part[:3600], [
        rf'(?:число|количество)\s+(?:физических\s+лиц|частных\s+инвесторов|россиян)[^.!?]{{0,110}}?брокерские\s+счета[^.!?]{{0,80}}?(?:составил[оаи]?|достигл[оаи]?|превысил[оаи]?)\s*{mn}',
        rf'количество\s+частных\s+инвесторов\s+с\s+брокерскими\s+счетами[^.!?]{{0,85}}?(?:составил[оаи]?|достигл[оаи]?)\s*{mn}',
    ])
    # Проценты: недопустимо превращать долю «акции и паи» в чистую долю акций.
    for field, market in [('share_equity_pct', r'акци\w*'),
                          ('share_bonds_pct', r'облигаци\w*'),
                          ('share_derivatives_pct', r'срочн\w*\s+рынк\w*')]:
        result[field] = _find(part[:5000], [
            rf'дол[яи]\s+(?:физлиц|частных\s+инвесторов)[^.!?]{{0,110}}?(?:торг\w*\s+{market}|на\s+{market})[^.!?]{{0,80}}?(?:составил[оаи]?|—|-)\s*{val}\s*%',
            rf'дол[яи]\s+(?:физлиц|частных\s+инвесторов)[^.!?]{{0,60}}?(?:торг\w*\s+{market}|на\s+{market})[^.!?]{{0,30}}?{val}\s*%',
        ])
    result['iis_accounts_mln'] = _find(part[:6000], [
        rf'количество\s+индивидуальных\s+инвестиционных\s+счетов\s*\(ИИС\)[^.!?]{{0,80}}?(?:составил[оаи]?|достигл[оаи]?|—|-)\s*{mn}',
        rf'количество\s+индивидуальных\s+инвестиционных\s+счетов[^.!?]{{0,70}}?(?:составил[оаи]?|достигл[оаи]?|—|-)\s*{mn}',
    ])
    result['iis_turnover_bln'] = _find(part[:6500], [
        rf'(?:торговый\s+)?оборот\s+(?:на\s+счетах\s+ИИС|по\s+ИИС|по\s+счетам\s+ИИС)[^.!?]{{0,130}}?(?:составил[оаи]?|—|-)\s*{bn}',
        rf'оборот\s+по\s+ИИС[^.!?]{{0,85}}?{bn}',
    ])
    pub = re.search(r'\b(\d{2})\.(\d{2})\.(20\d{2})\b', body[:350])
    if pub:
        try:
            result['publication_date'] = pd.Timestamp(int(pub[3]), int(pub[2]), int(pub[1]))
        except ValueError:
            pass
    if not any(result[f] is not None for f in FIELDS):
        return None
    return result


def fetch_russia_investors():
    from src.storage import load_russia_investors
    existing = load_russia_investors()
    if existing is None or existing.empty:
        existing = pd.DataFrame(columns=COLUMNS)
    existing = existing.reindex(columns=COLUMNS).copy()
    existing['date'] = pd.to_datetime(existing['date'], errors='coerce')
    existing = existing.dropna(subset=['date']).drop_duplicates('date', keep='last')
    existing = existing.set_index('date')

    last_month = (pd.Timestamp.today().to_period('M') - 1).to_timestamp()
    periods = pd.date_range(START, max(START, last_month), freq='MS')
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'})
    cache = {}
    rows = []
    for period in periods:
        key = period.strftime('%Y-%m')
        candidates = []
        if key in RELEASES:
            candidates.append(f'https://www.moex.com/n{RELEASES[key]}')
        # Сначала каноническая ссылка: быстрее и намного надёжнее поиска RSS.
        # Поиск выполняем, если её нет или она ничего не дала.
        best = None
        for attempt in range(2):
            if attempt == 1:
                candidates.extend(_search_urls(session, period))
            for url in dict.fromkeys(candidates):
                if url not in cache:
                    try:
                        cache[url] = _get(session, url)
                    except requests.RequestException as e:
                        print(f'[RU INVESTORS] Недоступно: {url}: {str(e)[:90]}')
                        cache[url] = ''
                if not cache[url]:
                    continue
                data = _article(cache[url], url, period)
                if data is not None:
                    if best is None or sum(data[f] is not None for f in FIELDS) > sum(best[f] is not None for f in FIELDS):
                        best = data
            if best is not None:
                break
        if best is not None:
            rows.append(best)
            print(f'[RU INVESTORS] {key}: {sum(best[f] is not None for f in FIELDS)}/{len(FIELDS)} метрик; {best["source_url"]}')
        elif period not in existing.index:
            print(f'[RU INVESTORS] {key}: не найден подтверждённый месячный ряд')

    new = pd.DataFrame(rows, columns=COLUMNS)
    new = new.set_index('date') if not new.empty else pd.DataFrame(columns=COLUMNS).set_index('date')
    # Важно: обновления по отдельным показателям, но исторические значения сохраняются.
    combined = existing.combine_first(new)
    for field in FIELDS:
        if not new.empty:
            combined.loc[new.index, field] = new[field].combine_first(combined.loc[new.index, field])
    for meta in ['source_url', 'source_title', 'publication_date']:
        if not new.empty:
            combined.loc[new.index, meta] = new[meta].combine_first(combined.loc[new.index, meta])
    if combined.empty:
        print('[RU INVESTORS] Нет данных; база не изменяется')
        return pd.DataFrame(columns=COLUMNS)
    combined['country'] = 'RU'
    result = combined.reset_index().reindex(columns=COLUMNS).sort_values('date')
    # SQLite не принимает pandas.Timestamp внутри object-столбца.
    # publication_date — метаданные публикации, храним в ISO 8601.
    result['publication_date'] = pd.to_datetime(
        result['publication_date'], errors='coerce'
    ).dt.strftime('%Y-%m-%d')
    result['publication_date'] = result['publication_date'].where(
        result['publication_date'].notna(), None
    )
    present = set(result.loc[result[FIELDS].notna().any(axis=1), 'date'])
    missing = [p for p in periods if p not in present]
    print(f'[RU INVESTORS] Подтверждено месяцев: {len(periods)-len(missing)}/{len(periods)}')
    if missing:
        print('[RU INVESTORS] Без подтверждённых значений: ' + ', '.join(p.strftime('%Y-%m') for p in missing))
    for f in FIELDS:
        print(f'[RU INVESTORS] {f}: {result[f].notna().sum()} наблюдений')
    return result
