# Macro Dashboard

Внутренний макроэкономический дашборд: сводная таблица по 17 странам, экономический календарь, ставки ЦБ, исторические
графики и новости.

Проект собирает данные из официальных первоисточников (национальные статистические службы, центральные банки, минфины,
международные организации) и показывает их в Streamlit-интерфейсе. Все данные хранятся в локальной SQLite.

## Ключевая идея

Не «ещё один агрегатор». Наоборот — прозрачный инструмент, где у каждой цифры видно:

- источник (ONS, Eurostat, FRED, BEA, IMF, BBG, ...),
- период (Q2 2026, сен 2026, 2025 (IMF, год)),
- методологию (Central Gov / General Gov, SA / NSA, факт или прогноз).

Главный приоритет — достоверность и сопоставимость данных, а не количество метрик.

## Принципы выбора источников

1. Актуальность. Свежесть данных — приоритет. Если источник отстаёт на квартал, а есть альтернатива с задержкой в
   недели — берём альтернативу.
2. Официальность + надёжность. Только структурированные источники с публичным API или официальными релизами. Не парсим
   журналистские сайты (Reuters, Investing.com). Агрегаторы (Trading Economics, CEIC) — не используем.
3. Бесплатность. Платные API не применяются. Bloomberg — только ручные выгрузки там, где официального источника нет.
4. Фактичность. Где возможно — подтверждённые данные, не прогнозы. IMF WEO — только как fallback.
5. Проверяемость. У каждого источника — открытая ссылка и публичные релизы.

## Приоритеты источников

Для каждой метрики/страны/периода:

1. Официальный национальный источник (Eurostat, ONS, BEA, IBGE, NBS, ...)
2. Bloomberg — если официального нет
3. IMF WEO — fallback, годовое значение
4. Прочерк — если ничего нет

Правило для декабря: за декабрь (год закрыт) для долга / бюджета / трейда берём годовое значение (IMF или официальное).
За остальные месяцы — квартальное.

## Что внутри

### Основная таблица

17 стран × 11 колонок:

| Колонка      | Что показывает | Источник                                                                                            |
|--------------|----------------|-----------------------------------------------------------------------------------------------------|
| Ставка ЦБ    | %, ключевая    | FRED / BoE / BoJ / BoC / SNB / RBA / BCB / chinamoney / OECD                                        |
| Инфляция YoY | %              | FRED / Eurostat / ONS / e-Stat / ECOS / SingStat / NBS / SIDRA / MoSPI / TCMB / FSO / ABS / StatCan |
| Инфляция MoM | %              | то же                                                                                               |
| Core CPI YoY | %              | FRED / Eurostat / ONS / e-Stat / SingStat / FSO / StatCan / NBS                                     |
| Рост ВВП     | % YoY          | Eurostat / FRED / Tonghuashun / SECO / SingStat / SIDRA / MoSPI                                     |
| Безработица  | %, SA          | Eurostat / FRED / data.gov.sg / SIDRA / chinadata.live / MoSPI / FSO                                |
| Долг/ВВП     | %              | Treasury / Eurostat / ONS / MOF / BCB / NIFD / SingStat / StatCan / IMF DSBB / IMF / BBG            |
| Бюджет/ВВП   | %              | MTS / BEA / Eurostat / ONS / Минфин КНР / SingStat / StatCan / IMF / BBG                            |
| Трейд/ВВП    | %              | BEA / Eurostat / ONS / SAFE / BCB / SingStat / StatCan / ABS / SNB / IMF / BBG                      |

### Дашборд Streamlit

- Две таблицы: с датами и без.
- Фильтры: год, месяц, регион (Америка / Европа / Азия и Океания), метрики.
- Подсветка:
    - красным — данные из Bloomberg,
    - жёлтым — изменения за неделю.
- Экспорт: CSV, Excel, HTML, PDF.
- Сноска про сезонность: большинство показателей — SA; явно помеченные — NSA.

### Expander'ы

1. Месячные метрики (детально) — свежие HICP и безработица по странам ЕС.
2. Ставки ЦБ (исторические) — таблица «Страна × Месяц».
3. Экономический календарь — события на неделю (ForexFactory).
4. FRED (исторические ряды) — CPI, PPI, ставки, GDP.
5. Новости — RSS-ленты.

## Архитектура

src/fetch_*.py → scheduler.py → src/storage.py → data/macro.db → src/build_summary.py → app.py (Streamlit)

| Файл                   | Ответственность                                                 |
|------------------------|-----------------------------------------------------------------|
| app.py                 | Streamlit-интерфейс, фильтры, экспорты, подсветка               |
| scheduler.py           | Ручной CLI: группы источников, вызов fetch/save                 |
| config.py              | Пути, .env, ключи API, списки стран, RSS, календарь             |
| src/storage.py         | SQLite: сохранение / чтение / очистка                           |
| src/build_summary.py   | Сводка по 17 странам, приоритеты источников                     |
| src/snapshot.py        | Недельные снимки, сравнение для подсветки                       |
| src/charts.py          | Графики Plotly                                                  |
| src/cleanup.py         | Очистка файлов Bloomberg (180 дней) и NIFD (90 дней)            |
| src/fetch_bloomberg.py | Парсер xlsx-выгрузок с автоопределением квартала по last_update |
| src/fetch_*.py         | Получение и нормализация данных                                 |

## Текущий статус по странам

Легенда: ✅ — фактические квартальные, 🟡 — годовое (IMF / Eurostat annual), 🔴 — Bloomberg (нет официального), ❌ — нет
данных.

| Страна | Инфляция | Core  | Безработица | Рост ВВП | Долг/ВВП            | Бюджет/ВВП      | Трейд/ВВП       |
|--------|----------|-------|-------------|----------|---------------------|-----------------|-----------------|
| US     | ✅        | ✅     | ✅           | ✅        | ✅ Treasury (Fed)    | ✅ BEA           | ✅ BEA           |
| CN     | ✅        | ✅ NBS | ✅           | ✅        | ✅ NIFD + 🟡 IMF     | ✅ MOF + 🟡 IMF  | ✅ SAFE          |
| EU     | ✅        | ✅     | ✅           | ✅        | ✅ Eurostat          | ✅ Eurostat      | ✅ Eurostat      |
| DE     | ✅        | ✅     | ✅           | ✅        | ✅ Eurostat          | ✅ Eurostat      | ✅ Eurostat      |
| JP     | ✅        | ✅     | ✅           | ✅        | ✅ MOF + 🟡 IMF      | 🟡 IMF          | 🔴 BBG + 🟡 IMF |
| IN     | ✅        | ❌     | ✅           | ✅        | 🟡 IMF              | 🔴 BBG + 🟡 IMF | 🔴 BBG + 🟡 IMF |
| GB     | ✅        | ✅     | ✅           | ✅        | ✅ ONS               | ✅ ONS           | ✅ ONS           |
| FR     | ✅        | ✅     | ✅           | ✅        | ✅ Eurostat          | ✅ Eurostat      | ✅ Eurostat      |
| IT     | ✅        | ✅     | ✅           | ✅        | ✅ Eurostat          | ✅ Eurostat      | ✅ Eurostat      |
| BR     | ✅        | ❌     | ✅           | ✅        | ✅ BCB               | 🔴 BBG + 🟡 IMF | ✅ BCB           |
| CA     | ✅        | ✅     | ✅           | ✅        | ✅ StatCan (NSA)     | ✅ StatCan (NSA) | ✅ StatCan       |
| KR     | ✅        | ❌     | ✅           | ✅        | ✅ IMF DSBB + 🟡 IMF | 🟡 IMF          | 🔴 BBG + 🟡 IMF |
| AU     | ✅        | ❌     | ✅           | ✅        | 🟡 IMF              | 🟡 IMF          | ✅ ABS           |
| ES     | ✅        | ✅     | ✅           | ✅        | ✅ Eurostat          | ✅ Eurostat      | ✅ Eurostat      |
| TR     | ✅        | ❌     | ✅           | ✅        | 🟡 IMF              | 🔴 BBG + 🟡 IMF | 🔴 BBG + 🟡 IMF |
| CH     | ✅        | ✅     | ✅           | ✅        | 🟡 IMF              | 🟡 IMF          | ✅ SNB           |
| SG     | ✅        | ✅     | ✅           | ✅        | ✅ SingStat          | 🟡 IMF          | ✅ SingStat      |

Итого:

- Инфляция — 17/17 фактических.
- Безработица — 17/17.
- Рост ВВП — 17/17.
- Ставка — 16/17 (кроме Сингапура, у MAS нет policy rate).
- Долг/ВВП — 12/17 квартальных, 5 IMF годовых.
- Бюджет/ВВП — 10/17 квартальных, 3 через Bloomberg, 4 IMF годовых.
- Трейд/ВВП — 12/17 квартальных, 4 через Bloomberg, 3 IMF годовых.
- Core CPI — 11/17 официальных, 6 прочерков.

## Bloomberg: ручные выгрузки

Используется только там, где нет официального источника.

### Формат xlsx

| country | metric     | ticker       | field   | last_update            | value       | date      | frequency |
|---------|------------|--------------|---------|------------------------|-------------|-----------|-----------|
| IN      | budget_gdp | EHBBIN Index | PX_LAST | =BDP(C2,"LAST_UPDATE") | =BDP(C2,D2) | =BTODAY() | Q         |
| IN      | trade_gdp  | EHCAIN Index | PX_LAST | =BDP(C3,"LAST_UPDATE") | =BDP(C3,D3) | =BTODAY() | Q         |
| TR      | budget_gdp | EHBBTR Index | PX_LAST | =BDP(C4,"LAST_UPDATE") | =BDP(C4,D4) | =BTODAY() | Q         |
| TR      | trade_gdp  | EHCATR Index | PX_LAST | =BDP(C5,"LAST_UPDATE") | =BDP(C5,D5) | =BTODAY() | Q         |
| BR      | budget_gdp | EHBBBR Index | PX_LAST | =BDP(C6,"LAST_UPDATE") | =BDP(C6,D6) | =BTODAY() | Q         |
| JP      | trade_gdp  | EHCAJP Index | PX_LAST | =BDP(C7,"LAST_UPDATE") | =BDP(C7,D7) | =BTODAY() | Q         |
| KR      | trade_gdp  | EHCAKR Index | PX_LAST | =BDP(C8,"LAST_UPDATE") | =BDP(C8,D8) | =BTODAY() | Q         |

### Как работает парсер

1. Файл bbg_export.xlsx кладётся на удалённом ПК.
2. Скрипт scripts/import_bbg.ps1 переносит его в data/bloomberg/bbg_YYYY-MM-DD.xlsx.
3. fetch_bloomberg.py читает файл, конвертирует last_update в квартал (30.06.2026 → Q2 2026), сохраняет в таблицу
   bloomberg.
4. В build_summary.py — приоритет выше IMF, ниже официальных.
5. В дашборде — красная подсветка для всех BBG-ячеек.

### Лимиты Bloomberg Excel Add-in

- ≤ 2500–3000 уникальных тикеров в месяц.
- ≤ 200 000 датапоинтов в день.
- Не использовать TODAY() — только BTODAY().
- Осторожно с F9 / Shift+F9 / Ctrl+Shift+Enter.

У нас ~7 тикеров + одна выгрузка в неделю — лимиты не превышаются.

## Структура проекта

macro_dashboard/
├── data/
│ ├── macro.db
│ ├── bloomberg/
│ └── nifd_reports/
├── scripts/
│ └── import_bbg.ps1
├── src/
│ ├── storage.py
│ ├── snapshot.py
│ ├── charts.py
│ ├── build_summary.py
│ ├── cleanup.py
│ ├── fetch_bloomberg.py
│ ├── fetch_us.py
│ ├── fetch_us_treasury.py
│ ├── fetch_us_bea.py
│ ├── fetch_us_fred_annual.py
│ ├── fetch_eurostat.py
│ ├── fetch_eurostat_quarterly.py
│ ├── fetch_eurostat_annual.py
│ ├── fetch_eurostat_unemployment.py
│ ├── fetch_china_cpi.py
│ ├── fetch_china_core_cpi.py
│ ├── fetch_china_debt_fred.py
│ ├── fetch_china_fiscal.py
│ ├── fetch_china_gdp.py
│ ├── fetch_china_trade.py
│ ├── fetch_china_unemployment.py
│ ├── fetch_nifd_report.py
│ ├── fetch_japan_cpi.py
│ ├── fetch_japan_quarterly.py
│ ├── fetch_korea_cpi.py
│ ├── fetch_korea_quarterly.py
│ ├── fetch_india_cpi.py
│ ├── fetch_india_gdp.py
│ ├── fetch_india_unemployment.py
│ ├── fetch_uk_ons.py
│ ├── fetch_uk_quarterly.py
│ ├── fetch_brazil_cpi.py
│ ├── fetch_brazil_gdp.py
│ ├── fetch_brazil_ibge.py
│ ├── fetch_brazil_quarterly.py
│ ├── fetch_canada_cpi.py
│ ├── fetch_canada_quarterly.py
│ ├── fetch_australia_cpi.py
│ ├── fetch_australia_quarterly.py
│ ├── fetch_turkey_cpi.py
│ ├── fetch_switzerland_cpi.py
│ ├── fetch_switzerland_gdp.py
│ ├── fetch_switzerland_quarterly.py
│ ├── fetch_switzerland_unemployment.py
│ ├── fetch_singapore_cpi.py
│ ├── fetch_singapore_gdp.py
│ ├── fetch_singapore_mom.py
│ ├── fetch_singapore_quarterly.py
│ ├── fetch_fred.py
│ ├── fetch_fred_cpi.py
│ ├── fetch_fred_gdp.py
│ ├── fetch_fred_unemployment.py
│ ├── fetch_imf.py
│ ├── fetch_policy_rates.py
│ ├── fetch_forexfactory.py
│ └── fetch_rss.py
├── app.py
├── config.py
├── scheduler.py
├── requirements.txt
├── .env
├── .gitignore
├── README.md
├── INSTRUCTIONS.md
├── SOURCES.md
├── ADVANTAGES.md
└── AGENTS_HACKATHON.md

## Запуск

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

Скопировать .env.example в .env и заполнить ключи.
python scheduler.py # обновить всё
python scheduler.py us # только США
python scheduler.py cn in tr # Китай, Индия, Турция
python scheduler.py --list # список групп
streamlit run app.py

### Группы в scheduler

| Группа   | Что обновляет                                     |
|----------|---------------------------------------------------|
| rates    | Ставки ЦБ                                         |
| us       | США: Treasury + BEA + годовой General Gov         |
| cn       | Китай: NIFD, MOF, SAFE, NBS Core CPI, FRED        |
| gb       | Великобритания: ONS, CPI                          |
| jp       | Япония: MOF, e-Stat, CPI                          |
| kr       | Южная Корея: IMF DSBB, ECOS                       |
| au       | Австралия: ABS, CPI                               |
| ca       | Канада: StatCan, CPI                              |
| ch       | Швейцария: SNB + SECO, CPI                        |
| br       | Бразилия: BCB SGS, IBGE SIDRA, CPI                |
| in       | Индия: MoSPI MCP                                  |
| tr       | Турция: TCMB                                      |
| fred     | FRED: макро, GDP, безработица, CPI                |
| imf      | IMF WEO                                           |
| eurostat | Eurostat: HICP, безработица, квартальные, годовые |
| bbg      | Bloomberg: ручные выгрузки                        |
| extra    | ForexFactory, RSS                                 |

## Документация

- README.md (этот файл) — контекст, архитектура, статус, запуск.
- INSTRUCTIONS.md — все команды для работы с проектом.
- SOURCES.md — все источники по метрикам и странам.
- ADVANTAGES.md — чем проект отличается от агрегаторов.
- AGENTS_HACKATHON.md — контекст для хакатон-команды.

## Известные ограничения

1. Япония: бюджет и трейд — IMF. У MOF нет квартального Overall Balance.
2. Индия: бюджет и трейд — Bloomberg. CGA/RBI — HTML, парсинг хрупкий.
3. Турция: бюджет и трейд — Bloomberg. Минфин — React SPA.
4. Бразилия: бюджет — Bloomberg. BCB не публикует квартальный Overall Balance.
5. Австралия: долг и бюджет — IMF. Dataflow GFS в ABS Data API не существует.
6. Сингапур: ставка — прочерк. У MAS нет классической policy rate.
7. Core CPI: недоступен для CN (NBS даёт только YoY через пресс-релизы), KR (ECOS sample-ключ), BR, IN, AU, TR.
8. Индия: ставка — с задержкой 2 месяца (FRED / OECD).
9. SAFE (Китай): задержка ~3 месяца.
10. ForexFactory: 403 Forbidden с 2026. Календарь не работает.

## Архитектурные решения

### Почему build_summary собирается на лету

Сводная таблица не хранится в БД — собирается в build_summary.py при каждом рендере app.py. Логика приоритетов
источников сложная, её проще вычислить на лету.

### Почему у некоторых стран годовые метки

Если у страны нет официального квартального источника — ставим годовое значение из IMF с пометкой «(IMF, год)».

### Почему у Японии долг = 48–205% (разные периоды)

- Квартально — MOF Central Government Debt (~48–50%).
- Декабрь — IMF General Government Gross Debt (~205%).

Разница — в 4 раза, потому что MOF публикует только центральное правительство, а General Gov включает местные власти и
соцфонды. Пометки честно указывают разницу.

### Почему у Сингапура долг = 153%

Central Gov Gross Debt Сингапура ~150% GDP, потому что правительство выпускает много SGS (гособлигаций) для создания
рынка. При этом у Сингапура большие активы (GIC, Temasek, MAS) — net debt отрицательный. Показываем gross debt, помечаем
Central Gov.

### Почему у Сингапура budget_gdp = IMF, а не SingStat

SingStat даёт deficit_sgd_mn в месячном NSA-виде, значения скачут от −5346 до +13678. Знак неоднозначен. Используем IMF
годовое — стабильно +3.7% за 2025.

### Почему у Великобритании долг = 100%, а не 148%

Bloomberg / World Bank показывают 148% — это неконсолидированный долг с госкомпаниями. ONS a3pw даёт ~100% —
Maastricht-методология, консолидированная, сопоставимая с Германией (63%) и Францией (115%). Используем ONS —
сопоставимо с ЕС.

## Задачи на неделю

### Приоритет — сверка Bloomberg vs наши источники

Задача 1. Найти расхождения. Для США, Германии, Франции, Китая сравнить значения из Bloomberg с нашими источниками.
Выписать расхождения и причины.

Задача 2. Экспорт из Bloomberg в Excel по BDP. Ваня — прислать скриншот или пример файла. Убедиться, что не нарушаем
лимиты.

Задача 3. Core CPI Китая. Ваня — прислать ссылку или кор, где взять Core Inflation по Китаю.

Задача 4. Фильтры в шапку таблицы. Уже есть (год, месяц, регион, метрики). Проверить, доработать при необходимости.

Задача 5. Жёлтая подсветка обновившихся ячеек. Уже работает через snapshot.py. Проверить.

Задача 6. Автоматизация отчёта. Ваня — написать, что хочет автоматизировать:

- графики в конце отчёта,
- автозаполнение текстом,
- применение формата ко всему отчёту.

### Дополнительно из записки

- Лёша — добавить в чат «Недельный».
- Ваня — прислать скриншот таблицы, дать обратную связь.
- Ссылки на первоисточники — для каждого показателя добавить ссылку на официальный релиз.
- По Японии — посмотреть, есть ли Core-Core и Tokyo CPI (предиктор национальной инфляции). Не приоритет.
- По Китаю — YTD и YoY, объединение jan-feb, таможенные данные.

## Контекст для LLM-ассистента

Если ты — ChatGPT Plus или другой LLM-ассистент, помогающий команде, прочитай этот раздел.

### Что понимать

1. Проект — макроэкономический дашборд на Python + Streamlit + SQLite.
2. 17 стран собраны из официальных источников.
3. Приоритеты: официальный → Bloomberg → IMF.
4. Декабрь = годовое значение (IMF или официальное), остальные месяцы — квартальные.
5. Bloomberg используется только там, где нет официального источника. Каждое значение BBG подсвечено красным.
6. Числа в ячейках имеют формат: значение · период (источник, методология).

### Правила работы с командой

- Всегда проси показать релевантный код целиком, прежде чем писать правки. Без контекста получится галлюцинация.
- Формулировка задачи — узкая. «Напиши функцию X для API Y по такому образцу ответа» — хорошо. «Улучши весь проект» —
  плохо.
- Не выдумывай API. Если не знаешь эндпоинт — попроси команду проверить руками (curl / браузер) и принести ответ.
- Никогда не запрашивай и не принимай API-ключи в промптах. Они живут в .env.
- Предупреждай о рисках парсинга: смена вёрстки, блокировки, лимиты.
- Проверяй вместе с командой: запрос → ответ → парсер → DataFrame → ячейка в дашборде.
- Если задача большая — разбей на шаги, предложи порядок.
- Если что-то неясно — спроси, не строй догадок.

### Что не делать

- Автотесты, Docker, CI — не приоритет.
- Платные API — только бесплатные (MOEX, ЦБ, ЕМИСС).
- LLM для парсинга — только регулярки и BeautifulSoup.
- Агрегаторы без первоисточника — данные теряют достоверность.
- Заменять отсутствующие данные нулями — ставим прочерк.
- Смешивать Central Gov / General Gov, SA / NSA, YoY / MoM — только с пометкой.

## Передача проекта

Что передавать: всю папку проекта, кроме .venv/, data/ и .env.

Что получатель делает:

1. Создаёт окружение: python -m venv .venv.
2. Ставит зависимости: pip install -r requirements.txt.
3. Получает ключи: FRED, e-Stat, BEA.
4. Создаёт .env.
5. Убеждается, что VPN включён (для Китая).
6. Запускает python scheduler.py.

## Лицензия

Внутренний проект. Внешнее распространение — по согласованию.
