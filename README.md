# Macro Dashboard

Дашборд макроэкономических метрик, экономического календаря и мировых новостей.

Проект автоматизирует сбор данных из официальных источников (национальные статслужбы, центральные банки, минфины,
международные организации). Все данные сохраняются в локальную SQLite и отображаются в Streamlit-интерфейсе.

## Принципы выбора источников

1. Актуальность. Свежесть данных — приоритет. Если источник отстаёт на квартал, а есть альтернатива с задержкой в
   недели — берём альтернативу.
2. Официальность + надёжность. Только структурированные источники с публичным API или официальными релизами. Не парсим
   журналистские сайты (Reuters, Investing.com). Агрегаторы (Trading Economics, CEIC) — не используем.
3. Бесплатность. Платные API не применяются.
4. Фактичность. Где возможно — подтверждённые данные, не прогнозы. Прогнозы IMF — только как fallback.
5. Проверяемость. У каждого источника — открытая ссылка и публичные релизы.

## Что внутри

Одна главная вкладка со сводной таблицей + пять expander'ов с деталями.

### Основная таблица

17 стран × 11 колонок:

| Колонка      | Что показывает | Источник                                                                                          |
|--------------|----------------|---------------------------------------------------------------------------------------------------|
| Инфляция     | YoY, %         | FRED / Eurostat / ONS / e-Stat / ECOS / SingStat / Tonghuashun / SIDRA / MoSPI / TCMB / FSO / ABS |
| Инфляция MoM | MoM, %         | то же                                                                                             |
| Core         | Core YoY, %    | FRED / Eurostat / ONS / StatCan / e-Stat / SingStat / FSO                                         |
| Безработица  | %, SA          | Eurostat / FRED / data.gov.sg / SIDRA / chinadata.live / MoSPI / FSO                              |
| Долг/ВВП     | %              | Treasury / Eurostat / ONS / MOF / BCB / NIFD / SingStat / StatCan / IMF DSBB / IMF                |
| Бюджет/ВВП   | %              | MTS / Eurostat / ONS / Минфин КНР / SingStat / StatCan / IMF                                      |
| Трейд/ВВП    | %              | BEA / Eurostat / ONS / SAFE / BCB / SingStat / StatCan / ABS / SNB / IMF                          |
| Рост ВВП     | %, YoY         | Eurostat / FRED / Tonghuashun / SECO / SingStat / SIDRA / MoSPI                                   |
| Ставка       | %, ключевая    | FRED / BoE / BoJ / BoC / SNB / rba-mcp / BCB / chinamoney / OECD                                  |

### Expander'ы

1. Месячные метрики (детально) — свежие HICP и безработица по странам ЕС.
2. Ставки ЦБ (исторические) — таблица «Страна × Месяц» по 12 странам.
3. Экономический календарь — события на неделю (ForexFactory).
4. FRED (исторические ряды) — исторические CPI, PPI, ставки, GDP.
5. Новости — Reuters, BBC, Investing.com.

## Текущий статус по странам

Легенда: ✅ — фактические квартальные, ⏳ — IMF (годовые), ❌ — нет данных.

| Страна | Инфляция | Безработица | Долг/ВВП   | Бюджет/ВВП | Трейд/ВВП  | Рост ВВП | Ставка   |
|--------|----------|-------------|------------|------------|------------|----------|----------|
| US     | ✅        | ✅           | ✅ Treasury | ✅ MTS      | ✅ BEA      | ✅        | ✅ 4.00%  |
| CN     | ✅        | ✅           | ✅ NIFD     | ✅ Минфин   | ✅ SAFE     | ✅        | ✅ 3.00%  |
| EU     | ✅        | ✅           | ✅ Eurostat | ✅ Eurostat | ✅ Eurostat | ✅        | ✅ 2.50%  |
| JP     | ✅        | ✅           | ✅ MOF      | ⏳ IMF      | ⏳ IMF      | ✅        | ✅ 1.50%  |
| DE     | ✅        | ✅           | ✅ Eurostat | ✅ Eurostat | ✅ Eurostat | ✅        | ✅ 2.50%  |
| GB     | ✅        | ✅           | ✅ ONS      | ✅ ONS      | ✅ ONS      | ✅        | ✅ 3.75%  |
| FR     | ✅        | ✅           | ✅ Eurostat | ✅ Eurostat | ✅ Eurostat | ✅        | ✅ 2.50%  |
| IT     | ✅        | ✅           | ✅ Eurostat | ✅ Eurostat | ✅ Eurostat | ✅        | ✅ 2.50%  |
| ES     | ✅        | ✅           | ✅ Eurostat | ✅ Eurostat | ✅ Eurostat | ✅        | ✅ 2.50%  |
| CA     | ✅        | ✅           | ✅ StatCan  | ✅ StatCan  | ✅ StatCan  | ✅        | ✅ 2.25%  |
| AU     | ✅        | ✅           | ⏳ IMF      | ⏳ IMF      | ✅ ABS      | ✅        | ✅ 4.36%  |
| KR     | ✅        | ✅           | ✅ DSBB     | ⏳ IMF      | ⏳ IMF      | ✅        | ✅ 2.97%  |
| SG     | ✅        | ✅           | ✅ SingStat | ✅ SingStat | ✅ SingStat | ✅        | ❌        |
| BR     | ✅        | ✅           | ✅ BCB      | ❌          | ✅ BCB      | ✅        | ✅ 13.75% |
| IN     | ✅        | ✅           | ⏳ IMF      | ⏳ IMF      | ⏳ IMF      | ✅        | ✅ 5.32%  |
| TR     | ✅        | ✅           | ⏳ IMF      | ⏳ IMF      | ⏳ IMF      | ✅        | ✅ 38.75% |
| CH     | ✅        | ✅           | ⏳ IMF      | ⏳ IMF      | ✅ SNB      | ✅        | ✅ 0.00%  |

Итого:

- Инфляция — 17 из 17 фактических.
- Безработица — 17 из 17 фактических.
- Рост ВВП — 17 из 17 фактических.
- Ставка — 12 из 13 (кроме Сингапура).
- Долг/ВВП — 11 из 17 квартальных.
- Бюджет/ВВП — 9 из 17 квартальных, 1 прочерк (BR), 7 IMF годовых.
- Трейд/ВВП — 10 из 17 квартальных, 7 IMF годовых.

## Отложенные задачи

### 1. Бюджет и трейд для Японии

Официального квартального Overall Fiscal Balance не существует. MOF публикует только кассовое исполнение. Трейд Японии
можно сделать через MOF BoP (PDF) — сложно, отложено.

### 2. Долг, бюджет, трейд для Индии

CGA и RBI публикуют данные в HTML/Excel, парсинг хрупкий (структура меняется). Оставляем IMF.

### 3. Долг, бюджет, трейд для Турции

Минфин Турции — React SPA, контент через JavaScript. requests не работает, curl_cffi тоже. Оставляем IMF.

### 4. Бюджет для Бразилии

BCB не публикует квартальный Overall Fiscal Balance. Только 12-месячный накопленный (SGS 5785) или месячный. Оставляем
прочерк.

### 5. Долг и бюджет для Австралии

Dataflow GFS в ABS Data API не существует. GFS публикуется отдельно. Оставляем IMF.

### 6. Ставка для Сингапура

MAS не устанавливает классическую ставку — использует курсовую политику (S$NEER). SORA — это бенчмарк, а не ключевая
ставка. Бесплатного API нет. Оставляем прочерк.

### 7. Core CPI для CN, KR, BR, IN, AU, TR

- CN — NBS не публикует Core CPI.
- KR — ECOS sample-ключ не даёт Core.
- BR — только MoM в BCB.
- IN — MoSPI не публикует.
- AU — Trimmed mean недоступен.
- TR — только в PDF.

### 8. Инфраструктура

- Фильтры в основной таблице (пользователь выбирает метрики).
- Кнопка «Печать».
- Экспорт в Excel.
- Мониторинг свежести данных.

## Установка

1. Клонировать проект:
   cd C:\MyProjects\CB\Macro_dashboard

2. Создать виртуальное окружение:
   python -m venv .venv

3. Активировать:
   .venv\Scripts\activate

4. Установить зависимости:
   pip install -r requirements.txt

5. Получить API-ключи:
    - FRED: https://fred.stlouisfed.org/docs/api/api_key.html
    - e-Stat: https://www.e-stat.go.jp/api/
    - BEA: https://apps.bea.gov/api/signup/

6. Создать .env:
   FRED_API_KEY=...
   ESTAT_APP_ID=...
   BEA_API_KEY=...

## Запуск

Обновить все данные:
python scheduler.py

Обновить только Китай:
python scheduler.py cn

Только ставки:
python scheduler.py rates

Список групп:
python scheduler.py --list

Справка:
python scheduler.py --help

Открыть дашборд:
streamlit run app.py

## Группы в scheduler

| Группа   | Что обновляет                                      |
|----------|----------------------------------------------------|
| rates    | Ставки ЦБ (12 стран)                               |
| us       | США: Treasury + BEA                                |
| sg       | Сингапур: CPI, безработица, ВВП, долг/бюджет/трейд |
| br       | Бразилия: CPI, безработица, ВВП, долг/трейд        |
| gb       | Великобритания: ONS, CPI                           |
| jp       | Япония: MOF, CPI                                   |
| kr       | Южная Корея: IMF DSBB, CPI                         |
| au       | Австралия: ABS, CPI                                |
| ca       | Канада: StatCan, CPI                               |
| ch       | Швейцария: SNB + SECO, CPI, безработица, ВВП       |
| cn       | Китай: безработица, NIFD, Минфин, ВВП, CPI         |
| in       | Индия: безработица, CPI, ВВП                       |
| tr       | Турция: CPI                                        |
| fred     | FRED: макро, GDP, безработица, CPI                 |
| imf      | IMF WEO                                            |
| eurostat | Eurostat: HICP, безработица, квартальные           |
| extra    | ForexFactory, RSS                                  |

## VPN-требования

Проверка, что VPN работает для Python:
python -c "from curl_cffi import requests; print(requests.get('https://ipinfo.io/country').text)"

| Источник                                      | Требуется VPN | Какой                                          |
|-----------------------------------------------|---------------|------------------------------------------------|
| Tonghuashun (Китай)                           | Да            | Азиатский (Гонконг, Сингапур, Тайвань, Япония) |
| Минфин КНР, SAFE                              | Да            | Европейский (Бельгия, Швейцария)               |
| NIFD (Китай)                                  | Нет           | Работает без VPN                               |
| MoSPI (Индия)                                 | Да            | Любой не-российский                            |
| ABS (Австралия)                               | Нет           | Работает                                       |
| dataseries.org (Швейцария)                    | Да            | Любой не-российский                            |
| FRED, Eurostat, ONS, BEA, Treasury            | Нет           | Работают без VPN                               |
| e-Stat, BoJ, BoE, BoC, SNB, StatCan, SingStat | Нет           | Работают                                       |
| chinamoney (Китай)                            | Нет           | Работает                                       |
| BCB (Бразилия)                                | Нет           | Работает                                       |
| rba-mcp (Австралия)                           | Нет           | Работает                                       |

## Риски парсинга и устойчивость

Retry-логика:

- FRED — 3 попытки.
- SIDRA (Бразилия) — 3 попытки.
- NIFD — 3 попытки.
- SingStat — 3 попытки при 502.
- Минфин КНР — 5 попыток, timeout=90.
- SAFE — 3 попытки.
- MoSPI — 3 попытки.
- BCB SGS — 3 попытки.

Кеширование:

- PDF NIFD кешируются в data/nifd_reports/.

Накопление:

- save_china_fiscal — merge по дате, NaN дозаполняются.
- _save_df пропускает пустые DataFrame.

## Архитектурные решения

### Почему build_summary собирается на лету

Сводная таблица не хранится в БД — собирается в build_summary.py при каждом рендере app.py. Логика приоритетов
источников сложная, её проще вычислить на лету.

### Приоритеты источников

1. Национальный официальный источник (квартальный) — если есть.
2. FRED — если национальный недоступен или отстаёт.
3. IMF WEO — последний fallback, годовые прогнозы.

### Почему у некоторых стран годовые метки

Если у страны нет официального квартального источника — ставим годовое значение из IMF с пометкой «(IMF, год)».

### Почему у Бразилии бюджет = прочерк

BCB публикует только 12-месячный накопленный NFSP (% PIB) или месячные абсолютные значения. Квартального официального
Overall Fiscal Balance не существует.

### Почему у Японии долг = 48,85% (Central Government)

MOF публикует Central Government Debt (только центральное правительство). CEIC и IMF дают General Government Gross
Debt (~204%). Разница — в 4 раза. Показываем официальный квартальный MOF (48,85%), помечаем «(Central Gov)».

### Почему ставка — отдельная вкладка

Ключевая ставка — не ежемесячная метрика, а событийная. Меняется на заседаниях ЦБ. В основной таблице показываем текущее
значение, в отдельном expander'е — полную историю по месяцам.

### Почему Индия — с задержкой

RBI блокирует ботов (403 Cloudflare). Официального API нет. Используем FRED INDIR3TIB01STM (OECD на основе данных RBI) —
3-month interbank rate с задержкой ~2 месяца. Альтернатива — хардкод официальных изменений RBI, но это против принципа
автоматизации.

### Почему Сингапур — с прочерком

MAS не устанавливает классическую ставку. Вместо этого — курсовая политика (S$NEER). SORA — это бенчмарк (overnight
rate), а не ключевая ставка. Бесплатного API нет.

## Структура проекта

macro_dashboard/
data/
macro.db
nifd_reports/
src/
storage.py
snapshot.py
charts.py
build_summary.py
fetch_us.py
fetch_us_treasury.py
fetch_us_bea.py
fetch_singapore_cpi.py
fetch_singapore_gdp.py
fetch_singapore_mom.py
fetch_singapore_quarterly.py
fetch_brazil_cpi.py
fetch_brazil_gdp.py
fetch_brazil_ibge.py
fetch_brazil_quarterly.py
fetch_uk_ons.py
fetch_uk_quarterly.py
fetch_japan_cpi.py
fetch_japan_quarterly.py
fetch_china_cpi.py
fetch_china_fiscal.py
fetch_china_gdp.py
fetch_china_trade.py
fetch_china_unemployment.py
fetch_nifd_report.py
fetch_india_cpi.py
fetch_india_gdp.py
fetch_india_unemployment.py
fetch_canada_cpi.py
fetch_canada_quarterly.py
fetch_australia_cpi.py
fetch_australia_quarterly.py
fetch_turkey_cpi.py
fetch_switzerland_cpi.py
fetch_switzerland_unemployment.py
fetch_switzerland_gdp.py
fetch_switzerland_quarterly.py
fetch_korea_cpi.py
fetch_korea_quarterly.py
fetch_fred.py
fetch_fred_cpi.py
fetch_fred_gdp.py
fetch_fred_unemployment.py
fetch_eurostat.py
fetch_eurostat_quarterly.py
fetch_eurostat_unemployment.py
fetch_imf.py
fetch_policy_rates.py
fetch_forexfactory.py
fetch_rss.py
app.py
config.py
scheduler.py
requirements.txt
.env
.gitignore
README.md
SOURCES.md

## Известные ограничения

1. Япония: бюджет и трейд — IMF.
2. Бразилия: бюджет — прочерк.
3. Индия, Турция: долг, бюджет, трейд — IMF.
4. Австралия: долг и бюджет — IMF.
5. Core CPI: недоступен для CN, KR, BR, IN, AU, TR.
6. Сингапур: ставка — прочерк.
7. Индия: ставка — с задержкой 2 месяца (FRED OECD).
8. SAFE (Китай): задержка ~3 месяца.
9. Минфин КНР, SAFE: периодически 502.
10. Tonghuashun: требует азиатского VPN.
11. NIFD: исследовательский институт, не госорган.
12. MoSPI, dataseries.org: блокируют РФ.
13. FRED: периодически 502.
14. ECOS: sample-ключ (лимит 10 строк).

## Передача проекта

Что передавать: всю папку проекта, кроме .venv/, data/ и .env.

Что получатель делает:

1. Создаёт окружение: python -m venv .venv
2. Ставит зависимости: pip install -r requirements.txt
3. Получает ключи FRED, e-Stat, BEA.
4. Создаёт .env.
5. Убеждается, что VPN включён (для Китая).
6. Запускает python scheduler.py.

## Лицензия

Внутренний проект. Внешнее распространение — по согласованию.
