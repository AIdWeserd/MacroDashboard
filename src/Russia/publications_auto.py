"""Официальные опубликованные значения ЦБ, извлеченные из PDF и HTML.

Принципы: только явно опубликованные цифры, их собственные отчетные периоды,
строгая проверка контекста/единиц; не подменять пропуски вычислениями.
"""
from datetime import date
from io import BytesIO
from urllib.parse import urljoin, urlparse
import re
import time

from bs4 import BeautifulSoup
import pandas as pd
import pdfplumber
import requests

BASE = "https://www.cbr.ru"
INDEX_BROKER = f"{BASE}/analytics/rcb/review_broker/"
INDEX_IIS = f"{BASE}/analytics/rcb/"
INDEX_BULLETINS = f"{BASE}/statistics/bbs/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacroDashboard/1.0)"}


# Обозначение метрик, заголовок, раздел, единица измерения.
METADATA = {
    "broker_average_portfolio": ("Брокеры и ПУРЦБ", "Средний размер портфеля физлица-резидента (без счетов до 10 тыс. ₽)", "млн ₽"),
    "broker_net_contributions": ("Брокеры и ПУРЦБ", "Нетто-взносы физлиц на брокерские счета", "млрд ₽"),
    "iis_average": ("ИИС", "Средний размер брокерского ИИС", "тыс. ₽"),
    "iis_net_contributions": ("ИИС", "Нетто-взносы на ИИС (все счета)", "млрд ₽"),
    "pif_issued": ("Коллективные инвестиции", "Выдача инвестиционных паёв ПИФ", "млн ₽"),
    "pif_redeemed": ("Коллективные инвестиции", "Погашение инвестиционных паёв ПИФ (объём, положительная величина)", "млн ₽"),
}


def _request(url):
    """Скачивает ресурс ЦБ с ограниченными повторами при временных сбоях сети.

    Не отключает проверку TLS. Ошибки 4xx, кроме 429, не повторяются.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.cbr.ru", "cbr.ru"}:
        raise ValueError(f"Запрещен внешний источник: {url}")

    attempts = 3
    retry_status = {429, 500, 502, 503, 504}
    for attempt in range(1, attempts + 1):
        try:
            # connect=15с, read=90с; ЦБ иногда медленно отдает объемные PDF.
            response = requests.get(
                url, headers=HEADERS, timeout=(15, 90),
                allow_redirects=True,
            )
            if urlparse(response.url).hostname not in {"www.cbr.ru", "cbr.ru"}:
                raise ValueError("Источник перенаправил запрос за пределы сайта ЦБ")
            if response.status_code in retry_status and attempt < attempts:
                response.close()
                print(f"[RU PUBLICATIONS] Повтор {attempt}/{attempts - 1}: HTTP {response.status_code}")
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            if len(response.content) > 30_000_000:
                raise ValueError("Слишком большой ответ источника")
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == attempts:
                raise
            print(
                f"[RU PUBLICATIONS] Повтор {attempt}/{attempts - 1}: "
                f"{type(exc).__name__} при получении документа ЦБ"
            )
            time.sleep(attempt * 2)

    raise RuntimeError("Не удалось завершить загрузку")


def _html(url):
    response = _request(url)
    return BeautifulSoup(response.content, "html.parser")


def _pdf(url):
    response = _request(url)
    if not response.content.startswith(b"%PDF"):
        raise ValueError("Источник не прислал PDF")
    return pdfplumber.open(BytesIO(response.content))


def _normalized(text):
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ").replace("\u202f", " ").replace("‑", "-").replace("–", "-").replace("—", "-"))


def _num(raw):
    text = _normalized(raw).replace(" ", "").replace(",", ".")
    number = float(text)
    if not 0 <= number < 100_000_000:
        raise ValueError(f"Показатель вне допустимых границ: {raw}")
    return number


def _quarter_end(year, quarter):
    return str((pd.Period(f"{year}Q{quarter}", freq="Q").end_time.normalize()).date())


def _record(metric, year, quarter, value, source, document):
    if metric not in METADATA:
        raise KeyError(metric)
    if not 2020 <= year <= date.today().year or not 1 <= quarter <= 4:
        raise ValueError("Неверный отчетный период")
    section, label, unit = METADATA[metric]
    return {
        "date": _quarter_end(year, quarter), "country": "RU",
        "section": section, "metric": metric, "label": label,
        "value": float(value), "unit": unit,
        "source_url": source, "source_sheet": document,
        "source_row": -2, "periodicity": "квартальная",
    }


def _link_list(index_url, regex):
    html = _html(index_url)
    output = []
    for a in html.find_all("a", href=True):
        url = urljoin(index_url, a["href"])
        if urlparse(url).hostname not in {"www.cbr.ru", "cbr.ru"}:
            continue
        match = regex.search(url)
        if match:
            output.append((url, match))
    return output


def _parse_broker_text(full_text, year, quarter, url):
    """Квартальные значения из фраз ЦБ; не использовать годовой поток как квартальный.

    Термины «пробные» (2024) и «небольшие» (2025+) счета в обзорах
    относятся к счетам с остатком до 10 тысяч рублей.
    """
    text = _normalized(full_text)
    rows = []
    number = r"(\d+(?:[,.]\d+)?)"
    unit_mln = r"млн\s*руб"
    # Ищем именно средний портфель с исключенными маленькими счетами,
    # а не средний по ВСЕМ счетам в тысячах рублей.
    main_start = (
        r"Средний\s+размер\s+брокерского\s+счета\s*"
        r"\(без\s+учета\s+(?:небольших(?:\s+счетов)?|пробных(?:\s+счетов)?)\)"
    )
    old_start = r"Средний\s+размер\s+счета\s+физических\s+лиц"
    average = None
    for start in (main_start, old_start):
        for match in re.finditer(start, text, re.IGNORECASE):
            context = text[match.end():match.end() + 340]
            if start == old_start:
                # Не брать среднее ВСЕХ счетов (242 тыс.), а искать уточнение
                # «без учета пробных счетов» с суммой в млн рублей.
                lower = re.search(r"без\s+учета\s+пробных\s+счетов", context, re.I)
                if lower is None:
                    continue
                context = context[lower.end():]
            # Типовые формулы: «составил 2,2 млн», «вырос ... до 2,3 млн»,
            # «снизился с 2,2 млн до 2,1 млн», «... практически не изменился».
            candidates = list(re.finditer(
                rf"(?:составил|составлял|достиг|достигла|до)\s*{number}\s*{unit_mln}",
                context[:190], re.I,
            ))
            if candidates:
                average = _num(candidates[0].group(1))
                break
        if average is not None:
            break
    if average is not None:
        rows.append(_record(
            "broker_average_portfolio", year, quarter, average, url,
            f"Обзор брокеров, {quarter} кв. {year}, текст PDF",
        ))

    # Требуем упоминание вида потока, охвата клиентов и отчетного периода.
    # В IV кв. отчет может содержать «за год 2,5 трлн» — это НЕ 4к25.
    client = (
        r"(?:физических\s+лиц\s+на\s+брокерские\s+счета|"
        r"на\s+брокерские\s+счета\s+физических\s+лиц|"
        r"на\s+брокерские\s+счета\s+физических\s+лиц)"
    )
    roman = ("I", "II", "III", "IV")[quarter - 1]
    period = (
        rf"(?:за\s+квартал|за\s*{quarter}\s*[кk]\s*{year % 100:02d}|"
        rf"за\s*{roman}\s+квартал\s+{year}\s*г?\.?|"
        rf"за\s+{roman}\s+квартал\s+{year}\s*г?\.?)"
    )
    net = None
    anchors = re.finditer(r"(?:Объем\s+)?нетто-взносов\d{0,2}", text, re.I)
    for anchor in anchors:
        # Формулировки меняются, поэтому допускаем перестановку «лиц»/«счетов».
        fragment = text[anchor.end():anchor.end() + 260]
        if not re.search(client, fragment[:130], re.I):
            continue
        match = re.search(
            rf"{period}\s*(?:составил|достиг|равнялся|составлял)\s*"
            rf"{number}\s*(трлн|млрд)\s*руб",
            fragment, re.I,
        )
        if match:
            net = _num(match.group(1)) * (1000 if match.group(2).lower() == "трлн" else 1)
            break
    # IV кв. 2024: годовой объем указан на одной странице, а фраза
    # «737 млрд руб. поступило в IV квартале» — на следующей после сносок.
    # Не требуем, чтобы эти фрагменты шли подряд. Но проверяем и годовой
    # контекст, и буквальную публикацию отдельного значения за квартал.
    if net is None and quarter == 4:
        has_context = re.search(
            r"нетто-взносов\s+на\s+брокерские\s+счета\s+физических\s+лиц"
            r".{{0,85}}?за\s+год\s+составил",
            text, re.I,
        )
        quarter_values = re.findall(
            rf"{number}\s*млрд\s*руб\.?\s+поступило\s+в\s+IV\s+квартале",
            text, re.I,
        )
        if has_context and len(quarter_values) == 1:
            net = _num(quarter_values[0])

    if net is not None:
        rows.append(_record(
            "broker_net_contributions", year, quarter, net, url,
            f"Обзор брокеров, {quarter} кв. {year}, текст PDF",
        ))
    return rows


def _previous_quarter(year, quarter):
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _parse_broker_comparison_text(text, year, quarter, url, current_net=None):
    """Берет ПРЕДЫДУЩИЙ квартал из подписанной сравнительной таблицы PDF.

    Формат официального обзора: «1к25 4к25 1к26 / 471 626 910».
    Не превращает годовое значение в квартальное и не хранит контрольные числа.
    Дополнительная проверка: последнее число совпадает с нетто-взносами
    отчетного квартала, извлеченными из основного текста этого же PDF.
    """
    text = _normalized(text)
    if not re.search(r"нетто[- ]взносы\s+(?:ФЛ|физических\s+лиц)", text, re.I):
        return []
    if current_net is None:
        return []

    prev_year, prev_quarter = _previous_quarter(year, quarter)
    labels = [
        f"{quarter}к{(year - 1) % 100:02d}",
        f"{prev_quarter}к{prev_year % 100:02d}",
        f"{quarter}к{year % 100:02d}",
    ]
    label_regex = r"\s+".join(re.escape(x).replace("к", "[кk]") for x in labels)
    matches = re.findall(
        rf"{label_regex}\s+([0-9]{{1,4}})\s+([0-9]{{1,4}})\s+([0-9]{{1,4}})(?![0-9])",
        text, re.I,
    )
    if not matches:
        return []
    candidates = set()
    for first, previous, current in matches:
        previous_value = float(previous)
        current_value = float(current)
        if (0 <= previous_value <= 5000
                and abs(current_value - current_net) < 0.01):
            candidates.add(previous_value)
    if len(candidates) != 1:
        return []
    value = candidates.pop()
    return [_record(
        "broker_net_contributions", prev_year, prev_quarter, value, url,
        f"Обзор брокеров {year}Q{quarter}, сравнительная таблица «Нетто-взносы ФЛ»",
    )]



def _parse_broker_comparison_words(page, year, quarter, url, current_net=None):
    """Читает 3 колонки сравнительной таблицы по координатам PDF.

    В pdfplumber текст таблицы иногда перемешан с боковыми KPI; координаты
    слов надёжнее порядка extract_text(). Никаких значений по датам не задано.
    """
    if current_net is None or not hasattr(page, "extract_words"):
        return []
    full = _normalized(page.extract_text() or "")
    if not re.search(r"нетто[- ]взносы\s+(?:ФЛ|физических\s+лиц)", full, re.I):
        return []

    try:
        words = page.extract_words(x_tolerance=2, y_tolerance=3)
    except (TypeError, ValueError):
        return []
    words = [w for w in words if all(k in w for k in ("text", "x0", "x1", "top", "bottom"))]
    py, pq = _previous_quarter(year, quarter)
    tags = (
        f"{quarter}к{(year - 1) % 100:02d}",
        f"{pq}к{py % 100:02d}",
        f"{quarter}к{year % 100:02d}",
    )
    tags = tuple(t.replace("к", "k") for t in tags)

    def token(w):
        return _normalized(w["text"]).replace("к", "k").replace("К", "k").lower()

    candidates = set()
    for head in (w for w in words if token(w) == tags[0]):
        row = sorted((w for w in words
                      if abs(float(w["top"]) - float(head["top"])) <= 5
                      and token(w) in tags), key=lambda w: float(w["x0"]))
        if len(row) != 3 or tuple(token(w) for w in row) != tags:
            continue
        nums = []
        for h in row:
            hx = (float(h["x0"]) + float(h["x1"])) / 2
            below = [w for w in words
                     if 0 <= float(w["top"]) - float(h["bottom"]) <= 32
                     and abs((float(w["x0"]) + float(w["x1"])) / 2 - hx) <= 32
                     and re.fullmatch(r"[0-9]{1,4}", token(w))]
            if not below:
                break
            # Среди возможных совпадений выбираем ближайшее под заголовком.
            closest = min(below, key=lambda w: (
                float(w["top"]) - float(h["bottom"]),
                abs((float(w["x0"]) + float(w["x1"])) / 2 - hx)))
            nums.append(float(token(closest)))
        if len(nums) == 3 and abs(nums[2] - float(current_net)) < 0.01:
            candidates.add(nums[1])

    if len(candidates) != 1:
        return []
    return [_record(
        "broker_net_contributions", py, pq, candidates.pop(), url,
        f"Обзор брокеров {year}Q{quarter}, сравнительная таблица «Нетто-взносы ФЛ»",
    )]


def _parse_broker_document(document, year, quarter, url):
    """Официальные значения из текста, основной колонки и таблицы PDF.

    Сравнительная таблица может содержать предшествующий квартал, поэтому
    возвращаемые записи необязательно датированы кварталом самого PDF.
    """
    pages = document.pages[:8]
    full_text = " ".join(page.extract_text() or "" for page in pages)
    rows = _parse_broker_text(full_text, year, quarter, url)
    existing = {row["metric"] for row in rows}

    # Раздельное чтение колонки необходимо некоторым PDF с боковыми KPI.
    if "broker_average_portfolio" not in existing:
        for page in pages:
            if not hasattr(page, "crop"):
                continue
            column = page.crop((page.width * 0.33, 0, page.width, page.height))
            column_text = column.extract_text() or ""
            extra = _parse_broker_text(column_text, year, quarter, url)
            for row in extra:
                if row["metric"] == "broker_average_portfolio":
                    rows.append(row)
                    print(f"[RU PUBLICATIONS] broker {year}Q{quarter}: "
                          "средний счёт распознан в основной колонке PDF")
                    break
            if any(row["metric"] == "broker_average_portfolio" for row in rows):
                break

    current_net = next((row["value"] for row in rows
                        if row["metric"] == "broker_net_contributions"
                        and row["date"] == _quarter_end(year, quarter)), None)
    if current_net is not None:
        # Таблица бывает набрана отдельными текстовыми блоками. Сначала
        # используем геометрию трех столбцов, затем старый текстовый способ.
        for page in pages:
            previous = _parse_broker_comparison_words(
                page, year, quarter, url, current_net=current_net)
            if previous:
                existing_keys = {(r["metric"], r["date"]) for r in rows}
                for row in previous:
                    if (row["metric"], row["date"]) not in existing_keys:
                        rows.append(row)
                        print(f"[RU PUBLICATIONS] broker {year}Q{quarter}: "
                              f"из сравнительной таблицы получен {row['date']}")
                return rows
        for page in pages:
            if not hasattr(page, "extract_text"):
                continue
            # Сначала ищем в полной странице; затем в центральной колонке.
            # Таблица обычно на странице 5 PDF.
            variants = [page.extract_text() or ""]
            if hasattr(page, "crop"):
                region = page.crop((page.width * 0.32, page.height * 0.22,
                                    page.width, page.height * 0.55))
                variants.append(region.extract_text() or "")
            # Заголовок таблицы в левом поле, поэтому при чтении правой
            # колонки соединяем его только с уже подтвержденным названием.
            if re.search(r"нетто[- ]взносы\s+(?:ФЛ|физических\s+лиц)",
                         variants[0], re.I):
                variants[1:] = ["Нетто-взносы ФЛ " + variant
                                for variant in variants[1:]
                                if "к" in variant.lower()]
            else:
                variants = variants[:1]
            for text_version in variants:
                previous = _parse_broker_comparison_text(
                    text_version, year, quarter, url, current_net=current_net)
                if previous:
                    key_set = {(r["metric"], r["date"]) for r in rows}
                    for row in previous:
                        if (row["metric"], row["date"]) not in key_set:
                            rows.append(row)
                            print(f"[RU PUBLICATIONS] broker {year}Q{quarter}: "
                                  f"из сравнительной таблицы получен {row['date']}")
                    return rows
    return rows


def _broker():
    pat = re.compile(r"review_broker_Q([1-4])_(20\d{2})\.pdf", re.I)
    links = {}
    for url, m in _link_list(INDEX_BROKER, pat):
        quarter, year = int(m.group(1)), int(m.group(2))
        if 2024 <= year <= date.today().year:
            links[(year, quarter)] = url
    if not links:
        raise ValueError("Обзоры брокеров не найдены на сайте ЦБ")
    found = []
    for (year, quarter), url in sorted(links.items(), reverse=True)[:12]:
        try:
            with _pdf(url) as document:
                if len(document.pages) < 5:
                    raise ValueError("Слишком короткий обзор")
                # Текст с показателями в первых 8 страницах, не читаем все приложения.
                data = _parse_broker_document(document, year, quarter, url)
                if not data:
                    raise ValueError("Не найдены опубликованные показатели с нужным контекстом")
                found.extend(data)
        except (requests.RequestException, ValueError, OSError) as exc:
            print(f"[RU PUBLICATIONS] WARNING broker {year}Q{quarter}: {exc}")
    return found


def _parse_iis_text(full_text, year, quarter, url):
    """Опубликованные квартальные данные ИИС; брокерский поток != общему.

    В 2024 году в ЦБ использовалось единственное число «брокерского ИИС»;
    формулировки «составил», «вырос ... до» и «остался вблизи» также
    различались. Значение «вблизи» маркируется как приблизительное.
    """
    text = _normalized(full_text)
    rows = []
    number = r"(\d+(?:[,.]\d+)?)"
    avg = None
    approximate = False

    anchors = (
        # В IV кв. 2024 рядом опубликованы два РАЗНЫХ средних: 93 тыс. ₽
        # по всем брокерским ИИС и 891 тыс. ₽ без пробных счетов.
        # Первым ищем строго целевой показатель.
        r"Средний\s+размер\s+ИИС\s+в\s+рамках\s+брокерского\s+обслуживания",
        r"Средний\s+размер\s+брокерск(?:их\s+ИИС|ого\s+ИИС)",
    )
    for anchor in anchors:
        for found in re.finditer(anchor, text, re.I):
            # «Без учета пробных счетов» — другая методология показателя.
            preceding = text[max(0, found.start() - 100):found.start()]
            if re.search(r"без\s+учета\s+(?:пробных|небольших|пустых)\s+счетов", preceding, re.I):
                continue
            fragment = text[found.end():found.end() + 170]
            patterns = (
                rf"(?:увеличился|вырос|снизился).{{0,105}}?\bдо\s*{number}\s*тыс",
                rf"(?:составил|составлял|достиг|остался\s+на\s+уровне).{{0,40}}?{number}\s*тыс",
                rf"остался\s+вблизи\s*{number}\s*тыс",
            )
            for i, pattern in enumerate(patterns):
                match = re.search(pattern, fragment, re.I)
                if match:
                    avg = _num(match.group(1))
                    approximate = i == 2
                    break
            if avg is not None:
                break
        if avg is not None:
            break

    if avg is not None:
        row = _record("iis_average", year, quarter, avg, url,
                      f"Обзор ИИС, {quarter} кв. {year}, HTML"
                      + ("; приблизительно («вблизи»)" if approximate else ""))
        rows.append(row)

    # Совокупный результат: только если официальная формулировка прямо
    # относится ко ВСЕМ сегментам ИИС и к кварталу данного обзора.
    # Отрицательные цифры по брокерским ИИС и ДУ отдельно НЕ суммируются.
    net = None
    tag = rf"{quarter}\s*[кk]\s*{year % 100:02d}"
    match = re.search(
        rf"совокупные\s+нетто-взносы.{{0,260}}?в\s*{tag}\s*[-:]\s*"
        rf"{number}\s*млрд\s*руб", text, re.I,
    )
    if match:
        net = _num(match.group(1))

    # 2024: ЦБ прямо называет нетто-взносы по рынку в целом.
    # В обзоре за II квартал: «... по рынку в целом составили 6 млрд».
    if net is None:
        match = re.search(
            rf"Нетто-взносы\s+ИИС\s+по\s+рынку\s+в\s+целом\s+составили\s*"
            rf"{number}\s*млрд\s*руб", text, re.I,
        )
        if match:
            net = _num(match.group(1))

    # В обзоре за III квартал 2024: «рост числа ИИС в течение квартала ...
    # увеличением нетто-притока средств в этот инструмент — с 6 до 21 млрд».
    # Фраза явно о совокупном притоке на ИИС текущего квартала.
    if net is None:
        match = re.search(
            rf"Рост\s+числа\s+ИИС\s+в\s+течение\s+квартала"
            rf".{{0,130}}?увеличением\s+нетто-притока\s+средств\s+в\s+этот\s+инструмент"
            rf"\s*[-:]?\s*с\s*{number}\s+до\s*{number}\s*млрд\s*руб",
            text, re.I,
        )
        if match:
            net = _num(match.group(2))

    if net is not None:
        rows.append(_record(
            "iis_net_contributions", year, quarter, net, url,
            f"Обзор ИИС, {quarter} кв. {year}, HTML, совокупные нетто-взносы",
        ))
    return rows


def _iis():
    pat = re.compile(r"/analytics/rcb/(?:iis|rcbiis)_([1-4])q_(20\d{2})/?$", re.I)
    links = {}
    for url, m in _link_list(INDEX_IIS, pat):
        year, quarter = int(m.group(2)), int(m.group(1))
        if year >= 2024:
            links[(year, quarter)] = url
    if not links:
        raise ValueError("Обзоры ИИС не найдены")
    found = []
    for (year, quarter), url in sorted(links.items(), reverse=True)[:12]:
        try:
            page = _html(url)
            if "ИИС" not in page.get_text(" ", strip=True):
                raise ValueError("Обзор ИИС не опознан")
            found.extend(_parse_iis_text(page.get_text(" ", strip=True), year, quarter, url))
        except (requests.RequestException, ValueError) as exc:
            print(f"[RU PUBLICATIONS] WARNING IIS {year}Q{quarter}: {exc}")
    return found


def _parse_pif_text(text, url, issue):
    """Таблица 4.5.4: 10 колонок на квартал, допускаются переносы строк.

    Первое число — опубликованная выдача «всего», шестое — погашение
    «всего». Не суммируем компоненты и не склеиваем разные кварталы.
    """
    records = []
    current_year = None
    quarter_markers = {"I": 1, "II": 2, "III": 3, "IV": 4}
    pattern_num = re.compile(r"\d{1,3}(?:[\u00a0\u202f ]\d{3})*,\d+")
    period_pattern = re.compile(r"^(IV|III|II|I)\s+квартал(?:\s+(.*))?$", re.I)
    year_pattern = re.compile(r"^(20\d{2})\s+год\b", re.I)

    pending_quarter = None
    pending_values = []
    continuation_lines = 0

    def save_pending():
        nonlocal pending_quarter, pending_values, continuation_lines
        if pending_quarter is not None:
            if len(pending_values) == 10:
                issued = _num(pending_values[0])
                redeemed = _num(pending_values[5])
                records.extend([
                    _record("pif_issued", current_year, pending_quarter, issued, url,
                            f"Статистический бюллетень ЦБ {issue}, табл. 4.5.4"),
                    _record("pif_redeemed", current_year, pending_quarter, redeemed, url,
                            f"Статистический бюллетень ЦБ {issue}, табл. 4.5.4"),
                ])
            else:
                print(f"[RU PUBLICATIONS] WARNING PIF {current_year}Q{pending_quarter}: "
                      f"{len(pending_values)} колонок вместо 10")
        pending_quarter = None
        pending_values = []
        continuation_lines = 0

    for raw_line in text.splitlines():
        line = _normalized(raw_line).strip()
        year_match = year_pattern.match(line)
        if year_match:
            save_pending()
            current_year = int(year_match.group(1))
            continue

        period_match = period_pattern.match(line)
        if period_match:
            save_pending()
            if current_year is not None and current_year >= 2020:
                pending_quarter = quarter_markers[period_match.group(1).upper()]
                pending_values = pattern_num.findall(period_match.group(2) or "")
            continue

        if pending_quarter is None:
            continue

        # Принимаем продолжение только из самих чисел, а не примыкающих
        # заголовков/примечаний PDF. Не более 3 строк продолжения.
        if (0 < len(pending_values) < 10 and continuation_lines < 3
                and pattern_num.search(line)
                and pattern_num.sub("", line).strip() == ""):
            pending_values.extend(pattern_num.findall(line))
            continuation_lines += 1
        elif line:
            # Разрыв в структуре: нельзя присваивать чужие цифры кварталу.
            save_pending()

    save_pending()
    return records


def _pif():
    pat = re.compile(r"/Bbs(\d{2})(\d{2})r\.pdf", re.I)
    links = {}
    for url, match in _link_list(INDEX_BULLETINS, pat):
        yy, issue = int(match.group(1)), int(match.group(2))
        # Архив начинается в XX веке: Bbs9912r.pdf — декабрь 1999,
        # а Bbs2609r.pdf — сентябрь 2026. Не превращать 1999 в 2099.
        year = 2000 + yy if yy <= date.today().year % 100 else 1900 + yy
        if 2025 <= year <= date.today().year and 1 <= issue <= 12:
            links[(year, issue)] = url
    if not links:
        raise ValueError("Статистические бюллетени ЦБ не найдены")
    for (year, issue), url in sorted(links.items(), reverse=True)[:4]:
        try:
            with _pdf(url) as document:
                if len(document.pages) < 155:
                    raise ValueError("Изменена структура статистического бюллетеня")
                # Таблица 4.5.4 в известных выпусках расположена вблизи с. 154.
                # Проверяем заголовок таблицы, а не принимаем любую таблицу.
                texts = []
                for page in document.pages[145:min(len(document.pages), 175)]:
                    content = page.extract_text() or ""
                    if "окончание таблицы 4.5.4" in content.lower():
                        texts.append(content)
                if not texts:
                    raise ValueError("Страница 'окончание таблицы 4.5.4' не найдена")
                rows = _parse_pif_text("\n".join(texts), url, f"№ {issue}/{year}")
                if not rows:
                    raise ValueError("Строки выдачи/погашения не распознаны")
                return rows
        except (requests.RequestException, ValueError, OSError) as exc:
            print(f"[RU PUBLICATIONS] WARNING bulletin {year}/{issue}: {exc}")
    raise ValueError("Не удалось извлечь таблицу 4.5.4 ни из одного нового выпуска")


def fetch_official_publications():
    """Возвращает только извлечённые официальные наблюдения; сбои изолированы."""
    records = []
    for name, fetcher in (("brokers", _broker), ("IIS", _iis), ("PIF", _pif)):
        try:
            chunk = fetcher()
            records.extend(chunk)
            print(f"[RU PUBLICATIONS] {name}: {len(chunk)} наблюдений")
        except (requests.RequestException, ValueError, OSError) as exc:
            print(f"[RU PUBLICATIONS] WARNING {name}: {exc}")
    # История и последние хорошие данные сохраняются в cbr_reference.py.
    return records
