# Macro Dashboard — реестр используемых источников данных

**Срез: 26.10.2026.** Это карта источников **рабочей реализации** (`scheduler.py`, загрузчики в `src/`, наблюдения сводной таблицы). Она описывает происхождение и методологию, **но не гарантирует**, что каждый внешний сервер доступен в момент запуска. Конкретную версию официального релиза, если она важна для анализа, проверяй отдельно.

## 1. Правила приоритета

1. При наличии подходящего ряда — национальная статистическая служба, центральный банк, министерство или иной официальный издатель.
2. Затем международные институциональные источники (`Eurostat`, `FRED` как канал передачи оригинального ряда, `IMF WEO`).
3. Допускаются согласованные труднодоступные источники и агрегаторы для конкретных стран: `NIFD`, `Tonghuashun`, `chinadata.live`, а также **ручные** Bloomberg Excel; их нельзя маскировать как официальную прямую выгрузку.
4. Сохранять **период и тип величины**: месячное/квартальное/годовое; `Central`, `Federal`, `General Government`; `SA`/`NSA`; `YoY`/`MoM`; `Current Account`/торговля товарами и т.д. Одно название колонки не означает полную международную сопоставимость.
5. Для текущего и будущих годов годовой IMF WEO как резерв явно помечать **«прогноз»**; для завершённых лет — годовые опубликованные исторические значения без автоматически навешиваемой пометки «прогноз». Не приравнивать годовой WEO к квартальному факту.
6. В действующей сводке принята сезонная логика выбора периода: для ряда долга/бюджета/трейда в декабре использовать согласованную годовую методологию, в остальные месяцы — квартальную; исключения показывать пользователю. Это **правило текущего приложения, а не универсальное свойство каждого источника**.
7. Утверждённые расчёты относительных показателей к ВВП **не переписывать по умолчанию**. Они разработаны и проверены отдельно. Технический аудит не является основанием для замены методологии.

## 2. Матрица источников по странам

| Экономика | Ставка / CPI / рынок труда / GDP | Долг, бюджет и внешняя позиция |
|---|---|---|
| **США (US)** | FRED (BLS и другие исходные издатели), BEA; US rate — FRED | Treasury Fiscal Data (Debt to the Penny, MTS), BEA API (NIPA, ITA), годовые ряды BEA/FRED |
| **Еврозона (EU)** | ECB через FRED, Eurostat HICP/безработица/GDP | Eurostat: квартальные долг, бюджет, BOP и годовые госфинансы |
| **Германия, Франция, Италия, Испания** | ECB/FRED, Eurostat HICP/GDP/безработица | Eurostat квартальные и годовые госфинансы, баланс внешнего сектора |
| **Великобритания (GB)** | BoE, ONS CPI, FRED/OECD безработица и GDP | ONS: долг, сальдо госуправления, current account |
| **Япония (JP)** | BoJ, e-Stat CPI, FRED GDP/безработица | MOF (Central Gov), e-Stat; для отсутствующих сопоставимых годовых величин — IMF WEO, ограниченно Bloomberg |
| **Китай (CN)** | ChinaMoney LPR, NBS Core CPI и официальные публикации, Tonghuashun CPI/GDP, chinadata.live безработица | NIFD (квартальный долг и принятая методология), Минфин КНР (бюджет), SAFE (current account), IMF/FRED годовой резерв |
| **Индия (IN)** | FRED/OECD ставка, MoSPI MCP CPI/GDP/безработица | IMF WEO годовой резерв; отдельные квартальные Bloomberg с явной меткой BBG |
| **Бразилия (BR)** | BCB SGS (ставка), IBGE SIDRA CPI/GDP/безработица | BCB SGS (долг и внешние счета), согласованный Bloomberg fallback для отдельных метрик |
| **Канада (CA)** | Bank of Canada Valet, Statistics Canada CPI/WDS, FRED GDP/безработица | StatCan WDS квартальные финансовые показатели и внешняя позиция |
| **Южная Корея (KR)** | FRED/OECD ставка и GDP/безработица, ECOS CPI | IMF DSBB Central Gov; IMF WEO годовой бюджет; Bloomberg для отдельных квартальных показателей |
| **Австралия (AU)** | RBA через `rba-mcp`, ABS CPI/внешние счета, FRED GDP/безработица | ABS квартальный current account, IMF WEO годовые бюджет и долг |
| **Турция (TR)** | FRED ставка и GDP/безработица, TCMB CPI | IMF WEO годовой долг; отдельные квартальные Bloomberg |
| **Швейцария (CH)** | SNB ставка, FSO/SECO CPI/ВВП/рынок труда (в реализации есть посредник `dataseries.org`) | SNB + SECO квартальный current account; IMF WEO годовые долг и бюджет |
| **Сингапур (SG)** | SingStat / data.gov.sg CPI, GDP, безработица | SingStat долг, бюджет, current account; для части бюджета — IMF WEO годовой резерв |
| **Россия (RU)** | Банк России CPI, ключевая ставка, кредитные/депозитные ставки, денежные и кредитные ряды | ЦБ РФ, Росстат и Казначейство: ВВП, бюджет, долг, текущий счёт и торговля; MOEX инвесторы, ЦБ РФ брокеры/ИИС/ПИФ/RUONIA |

Сводка реально охватывает **18** экономик, включая еврозону. Для отдельных метрик видимые периоды и методологии различаются. Таблица — ориентир: точные названия колонок и выбор источников внутри ячейки определяет `src/build_summary.py`.

## 3. Конкретные датасеты и модули

| Данные | Серии / идентификаторы, используемые в проекте | Модули |
|---|---|---|
| CPI, ставки, другие макро | FRED `CPIAUCSL`, `CPILFESL`, `PPIACO`, `FEDFUNDS`, `ECBDFR`, `DFEDTARU` и страновые ряды | `src/fetch_fred.py`, `src/fetch_fred_cpi.py`, `src/fetch_policy_rates.py` |
| GDP US/JP/GB/CA/AU/KR/TR | FRED `GDPC1`, `JPNRGDPEXP`, `NGDPRSAXDC*` | `src/fetch_fred_gdp.py` |
| Безработица стран вне ЕС | FRED `UNRATE`, `LRHUTTTT*`, `LRUNTTT*` | `src/fetch_fred_unemployment.py` |
| ЕС: HICP, GDP, долг/бюджет/внешняя позиция | Eurostat `PRC_HICP_MINR`, `namq_10_gdp`, `gov_10q_ggdebt`, `gov_10q_ggnfa`, `bop_gdp6_q` | `src/fetch_eurostat*.py` |
| США долг/дефицит | Treasury Fiscal Data Debt to the Penny, MTS Table 1 | `src/fetch_us_treasury.py`, `src/fetch_us.py` |
| США General Gov и current account | BEA NIPA, ITA (`BalCurrAcct`) | `src/fetch_us_bea.py`, `src/fetch_us.py` |
| Китай CPI/GDP | NBS и Tonghuashun; Core CPI NBS HTML | `src/fetch_china_core_cpi.py`, `src/fetch_china_cpi.py`, `src/fetch_china_gdp.py` |
| Китай бюджет и current account | Минфин КНР и SAFE (публикации) | `src/fetch_china_fiscal.py` |
| Китай долг | NIFD и FRED/IMF годовой резерв | `src/fetch_nifd_report.py`, `src/fetch_china_debt_fred.py` |
| Канада | Statistics Canada WDS и CPI | `src/fetch_canada_quarterly.py`, `src/fetch_canada_cpi.py` |
| Корея долг | IMF DSBB | `src/fetch_korea_quarterly.py` |
| Россия CPI/квартальные финансы | ЦБ РФ PDF, Казначейство GFS XLSX, Росстат, ЦБ РФ | `src/fetch_russia.py` |
| Россия детальные показатели | ЦБ РФ HTML/XLSX/PDF; MOEX пресс-релизы | `src/Russia/*.py` |
| Ручные Bloomberg значения | Excel `data/bloomberg/bbg_YYYY-MM-DD.xlsx`, период через `last_update` | `src/fetch_bloomberg.py` |
| IMF WEO | Опубликованные страновые ежегодные оценки, факты/прогнозы по периоду | `src/fetch_imf.py` |
| Новости/календарь | RSS (Reuters/BBC/Investing), ForexFactory | `src/fetch_rss.py`, `src/fetch_forexfactory.py` |

## 4. Особые методологии, которые нужно сохранять

- **Япония:** квартальный Central Gov (MOF) и годовой General Gov (IMF) — не одно и то же. Не считать разницу ошибкой.
- **США:** квартальные Federal/Treasury показатели и годовые General Gov/BEA различаются уровнем сектора. В сводке ставятся подписи.
- **Великобритания:** отдаётся предпочтение согласованному ONS General Government вместо методологически иного неконсолидированного показателя.
- **Китай:** NIFD, Tonghuashun и HTML NBS используются в связи с ограничениями публикаций/API. Не называй NIFD национальным госорганом или данные Tonghuashun прямым API NBS. Исправлен поиск Core CPI по нескольким страницам архива.
- **Канада:** бюджетные величины StatCan могут быть NSA; это должно быть явно отмечено. API подвержены тайм-аутам.
- **Сингапур, Австралия, Корея:** отдельные бюджетные/долговые метрики берутся из годового IMF fallback, если сопоставимого квартального официального ряда нет.
- **Bloomberg:** используется ограниченно и вручную, квартал определяется по `last_update`; ячейки помечаются `BBG`, в интерфейсе могут выделяться красным.
- **Россия:** оперативные оценки торговли не должны автоматически заменять исторические проверенные ряды; RUONIA содержит только опубликованные дни, прочерк не равен нулю.

## 5. Проверочные адреса издателей

- FRED: https://fred.stlouisfed.org/
- Eurostat: https://ec.europa.eu/eurostat/
- BEA: https://apps.bea.gov/api/
- US Treasury: https://fiscaldata.treasury.gov/
- IMF WEO: https://www.imf.org/en/Publications/WEO
- ONS: https://www.ons.gov.uk/
- Bank of Canada: https://www.bankofcanada.ca/valet/
- Statistics Canada: https://www.statcan.gc.ca/
- NBS China: https://www.stats.gov.cn/
- MOF China: http://gks.mof.gov.cn/
- SAFE: https://www.safe.gov.cn/
- NIFD: http://www.nifd.cn/
- BCB Brazil: https://www.bcb.gov.br/
- IBGE SIDRA: https://sidra.ibge.gov.br/
- MoSPI India: https://www.mospi.gov.in/
- ABS: https://www.abs.gov.au/
- SingStat: https://www.singstat.gov.sg/
- SNB: https://data.snb.ch/
- ЦБ РФ: https://www.cbr.ru/
- Росстат: https://rosstat.gov.ru/
- Казначейство РФ: https://roskazna.gov.ru/
- Московская биржа: https://www.moex.com/

Ссылки — официальные сайты издателей или используемых посредников, **не обещание**, что прямой путь к нужному Excel/API доступен сейчас.

## 6. Доступность на дату аудита

Полный запуск 26.10.2026 выявил отдельные проблемы: StatCan SSL/timeout, ChinaMoney LPR SSL, FRED JP timeout, Turkey TCMB timeout, ForexFactory HTTP 403. При этом остальные 53 этапа завершились успешно. ЦБ РФ доверенный TLS, но Росстат и Казначейство требовали ограниченного исключения проверки сертификата (`verify=False`) в рабочем загрузчике: это открытый риск информационной безопасности; см. [`AUDIT.md`](AUDIT.md).

Для конкретного числа важнее **источник, дата и подпись в ячейке**, чем одна общая таблица, которая может устареть.
