# Источники данных Macro Dashboard

Документ описывает все источники, из которых проект собирает макроэкономические данные. Составлен для презентации.

## Принципы выбора источников

1. Актуальность. Свежесть данных — приоритет.
2. Официальность. Национальные статистические службы, центральные банки, минфины, международные организации.
3. Бесплатность. Платные сервисы не используются.
4. Фактичность. Где возможно — подтверждённые данные, не прогнозы.
5. Проверяемость. Открытые ссылки, публичные релизы, даты публикации.

## Сводная таблица источников по метрикам

### Инфляция (YoY, MoM, Core)

| Страна | Источник                      | Формат | Свежесть |
|--------|-------------------------------|--------|----------|
| US     | FRED (BLS) CPIAUCSL, CPILFESL | API    | Месячная |
| EU     | Eurostat PRC_HICP_MINR        | API    | Месячная |
| GB     | ONS d7g7, d7oe, dko8          | API    | Месячная |
| CA     | StatCan v41690973, v108785715 | API    | Месячная |
| JP     | e-Stat 0004052037             | API    | Месячная |
| KR     | ECOS 901Y009                  | API    | Месячная |
| SG     | SingStat M213751, M213891     | API    | Месячная |
| CN     | Tonghuashun (агрегатор NBS)   | HTML   | Месячная |
| BR     | IBGE SIDRA 1737               | API    | Месячная |
| IN     | MoSPI MCP                     | API    | Месячная |
| TR     | TCMB                          | HTML   | Месячная |
| CH     | FSO via dataseries.org        | API    | Месячная |
| AU     | ABS 3.10001.10.50.M           | API    | Месячная |

### Безработица

| Страна                     | Источник               | Формат | Свежесть    |
|----------------------------|------------------------|--------|-------------|
| EU                         | Eurostat               | API    | Месячная    |
| US, JP, GB, CA, AU, KR, TR | FRED                   | API    | Месячная    |
| SG                         | data.gov.sg            | API    | Квартальная |
| BR                         | IBGE SIDRA             | API    | Квартальная |
| CN                         | chinadata.live         | API    | Месячная    |
| IN                         | MoSPI MCP              | API    | Месячная    |
| CH                         | FSO via dataseries.org | API    | Месячная    |

### Рост ВВП (все 17 стран, квартальный, фактический)

| Страна                     | Источник                            | Модуль                      |
|----------------------------|-------------------------------------|-----------------------------|
| EU, DE, FR, IT, ES         | Eurostat namq_10_gdp                | fetch_eurostat_quarterly.py |
| US, JP, GB, CA, AU, KR, TR | FRED GDPC1, JPNRGDPEXP, NGDPRSAXDC* | fetch_fred_gdp.py           |
| CN                         | Tonghuashun                         | fetch_china_gdp.py          |
| CH                         | SECO via dataseries.org             | fetch_switzerland_gdp.py    |
| SG                         | SingStat M015631                    | fetch_singapore_gdp.py      |
| BR                         | IBGE SIDRA 5932                     | fetch_brazil_gdp.py         |
| IN                         | MoSPI MCP NAS, indicator_code=5     | fetch_india_gdp.py          |

### Долг/ВВП

| Страна             | Источник                                 | Формат | Тип                       |
|--------------------|------------------------------------------|--------|---------------------------|
| US                 | Treasury Fiscal Data (Debt to the Penny) | API    | Квартальный               |
| EU, DE, FR, IT, ES | Eurostat gov_10q_ggdebt                  | API    | Квартальный               |
| GB                 | ONS Beta API HF6X                        | API    | Квартальный               |
| JP                 | MOF Central Government Debt              | HTML   | Квартальный (Central Gov) |
| CN                 | NIFD                                     | PDF    | Квартальный (Central Gov) |
| SG                 | SingStat M130181 (seriesNo=1)            | API    | Квартальный (Central Gov) |
| BR                 | BCB SGS 13762                            | API    | Месячный → квартальный    |
| KR                 | IMF DSBB (EIDN001)                       | HTML   | Квартальный (Central Gov) |
| CA                 | StatCan WDS 36100467                     | API    | Квартальный               |
| AU, IN, TR, CH     | IMF WEO                                  | API    | Годовой (прогноз)         |

### Бюджет/ВВП

| Страна             | Источник                           | Формат | Тип                       |
|--------------------|------------------------------------|--------|---------------------------|
| US                 | Treasury Fiscal Data (MTS Table 1) | API    | Квартальный               |
| EU, DE, FR, IT, ES | Eurostat gov_10q_ggnfa             | API    | Квартальный               |
| GB                 | ONS Beta API A3PT                  | API    | Квартальный               |
| CN                 | Минфин КНР                         | HTML   | Квартальный (Central Gov) |
| SG                 | SingStat M130621 (seriesNo=1)      | API    | Месячный → квартальный    |
| CA                 | StatCan WDS 36100118               | API    | Квартальный               |
| BR                 | —                                  | —      | Прочерк                   |
| JP, AU, IN, TR, CH | IMF WEO                            | API    | Годовой                   |

### Трейд/ВВП (Current Account)

| Страна             | Источник                        | Формат | Тип         |
|--------------------|---------------------------------|--------|-------------|
| US                 | BEA API (ITA BalCurrAcct)       | API    | Квартальный |
| EU, DE, FR, IT, ES | Eurostat bop_gdp6_q             | API    | Квартальный |
| GB                 | ONS Beta API AA6H               | API    | Квартальный |
| CN                 | SAFE                            | HTML   | Квартальный |
| SG                 | SingStat M060171 (seriesNo=1.1) | API    | Квартальный |
| BR                 | BCB SGS 23081 + 4385            | API    | Квартальный |
| CA                 | StatCan WDS 36100018            | API    | Квартальный |
| AU                 | ABS Data API (BOP + ANA_AGG)    | API    | Квартальный |
| CH                 | SNB (ch_snb_bopcurrq) + SECO    | API    | Квартальный |
| JP, IN, TR         | IMF WEO                         | API    | Годовой     |

### Ставки ЦБ

| Страна | Источник             | Формат      | Последняя         |
|--------|----------------------|-------------|-------------------|
| US     | FRED DFEDTARU        | API         | 4.00% (окт 2026)  |
| EU     | FRED ECBDFR          | API         | 2.50% (окт 2026)  |
| GB     | BoE CSV IUDBEDR      | CSV         | 3.75% (окт 2026)  |
| JP     | BoJ API MADR1M       | JSON        | 1.50% (сен 2026)  |
| CA     | BoC Valet V39079     | JSON        | 2.25% (окт 2026)  |
| CH     | SNB snboffzisa       | JSON        | 0.00% (авг 2026)  |
| KR     | FRED IR3TIB01KRM156N | API         | 2.97% (авг 2026)  |
| TR     | FRED INTDSRTRM193N   | API         | 38.75% (авг 2026) |
| AU     | rba-mcp (F1.1)       | MCP (stdio) | 4.36% (сен 2026)  |
| BR     | BCB SGS 432          | API         | 13.75% (окт 2026) |
| CN     | chinamoney LPR       | JSON        | 3.00% (сен 2026)  |
| IN     | FRED INDIR3TIB01STM  | API         | 5.32% (июл 2026)  |
| SG     | —                    | —           | нет источника     |

## Детали по источникам

### FRED (Federal Reserve Economic Data)

- Владелец: Федеральный резервный банк Сент-Луиса (США).
- URL: https://fred.stlouisfed.org
- Что берём: CPI США, безработица, квартальный Real GDP, ставки (US, EU, KR, TR, IN).
- Формат: REST API с бесплатным ключом.
- Retry: 3 попытки.

### Eurostat

- Владелец: Статистическая служба ЕС.
- URL: https://ec.europa.eu/eurostat
- Что берём: HICP, безработица, квартальные ВВП/долг/бюджет/трейд для EU, DE, FR, IT, ES.
- Датасеты: PRC_HICP_MINR, namq_10_gdp, gov_10q_ggdebt, gov_10q_ggnfa, bop_gdp6_q.
- Формат: SDMX API, без ключа.

### ONS (Office for National Statistics, UK)

- Владелец: Статистическая служба Великобритании.
- API: https://api.beta.ons.gov.uk/v1
- Что берём: CPI, долг/ВВП (HF6X), бюджет/ВВП (A3PT), трейд/ВВП (AA6H).
- Формат: REST API, без ключа.

### BoE (Bank of England)

- Владелец: Банк Англии.
- Что берём: Bank Rate (IUDBEDR).
- Формат: CSV.

### BEA (Bureau of Economic Analysis, US)

- Владелец: Бюро экономического анализа США.
- URL: https://apps.bea.gov/api/
- Что берём: ВВП (NIPA T10105), Current Account (ITA BalCurrAcct).
- Формат: REST API с ключом.

### Treasury Fiscal Data (US)

- Владелец: Министерство финансов США.
- URL: https://fiscaldata.treasury.gov
- Что берём: Долг (Debt to the Penny), бюджет (MTS Table 1).
- Формат: REST API, без ключа.

### e-Stat (Япония)

- Владелец: Статистическое бюро Японии.
- URL: https://www.e-stat.go.jp
- Что берём: CPI (statsDataId=0004052037), номинальный ВВП (statsDataId=0003109785).
- Формат: REST API с ключом.

### BoJ (Bank of Japan)

- Владелец: Банк Японии.
- URL: https://www.stat-search.boj.or.jp/api/v1/
- Что берём: Policy Rate (db=IR01, code=MADR1M).
- Формат: JSON API, без ключа.

### MOF (Ministry of Finance, Japan)

- Владелец: Министерство финансов Японии.
- URL: https://www.mof.go.jp
- Что берём: Central Government Debt.
- Формат: HTML.

### BoC (Bank of Canada)

- Владелец: Банк Канады.
- URL: https://www.bankofcanada.ca/valet/
- Что берём: Central Bank Rate (V39079).
- Формат: JSON API.

### SNB (Swiss National Bank)

- Владелец: Швейцарский национальный банк.
- URL: https://data.snb.ch
- Что берём: Policy Rate (snboffzisa), Current Account (ch_snb_bopcurrq).
- Формат: JSON.

### RBA (Reserve Bank of Australia)

- Владелец: Резервный банк Австралии.
- Что берём: Cash Rate Target (F1.1).
- Формат: MCP-сервер rba-mcp (stdio).

### BCB (Banco Central do Brasil)

- Владелец: Центральный банк Бразилии.
- URL: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
- Что берём: Selic (SGS 432), долг/ВВП (13762), трейд (23081 + 4385).
- Формат: REST API, без ключа.

### chinamoney (Китай)

- Владелец: Национальный межбанковский центр финансирования (под управлением PBOC).
- URL: https://www.chinamoney.com.cn
- Что берём: LPR 1Y (LprHis endpoint).
- Формат: JSON, без ключа. История — 12 месяцев.

### IBGE SIDRA (Бразилия)

- Владелец: Бразильский институт географии и статистики.
- URL: https://apisidra.ibge.gov.br
- Что берём: IPCA (1737), GDP (5932).
- Формат: REST API, без ключа.

### Tonghuashun (Китай)

- Владелец: Tonghuashun — китайский финансовый портал.
- URL: https://data.10jqka.com.cn
- Что берём: CPI, GDP.
- Формат: HTML-парсинг.
- VPN: азиатский.

### NIFD (Китай)

- Владелец: Исследовательский институт при Китайской академии общественных наук.
- URL: http://www.nifd.cn
- Что берём: Консолидированный долг правительства (% ВВП).
- Формат: PDF-парсинг.
- Официальность: не госорган, но использует официальные данные.

### Минфин КНР

- Владелец: Министерство финансов КНР.
- URL: http://gks.mof.gov.cn
- Что берём: Доходы и расходы бюджета.
- Формат: HTML-парсинг. Retry 5 попыток.
- VPN: европейский.

### SAFE (Китай)

- Владелец: Государственное управление валютного контроля КНР.
- URL: http://www.safe.gov.cn/en/SAFENews/
- Что берём: Current Account.
- Формат: HTML-парсинг.
- VPN: европейский.

### chinadata.live (Китай)

- Владелец: независимый агрегатор данных NBS.
- URL: https://chinadata.live
- Что берём: Безработица Китая.
- Формат: REST API, без ключа.

### MoSPI (Индия)

- Владелец: Министерство статистики Индии.
- URL: https://mcp.mospi.gov.in/mcp
- Что берём: CPI, GDP.
- Формат: JSON-RPC (MCP), без ключа.
- VPN: любой не-российский.

### TCMB (Турция)

- Владелец: Центральный банк Турции.
- URL: https://www.tcmb.gov.tr
- Что берём: CPI YoY, MoM.
- Формат: HTML-парсинг.

### FSO / SECO (Швейцария)

- Владелец: Федеральное статистическое управление и Государственный секретариат по экономике.
- URL: через dataseries.org
- Что берём: CPI (ch_fso_cpi), GDP (ch_seco_gdp).
- Формат: REST API.
- VPN: любой не-российский.

### ABS (Австралия)

- Владелец: Статистическая служба Австралии.
- URL: https://data.api.abs.gov.au
- Что берём: CPI, квартальный трейд (BOP + ANA_AGG).
- Формат: REST API (SDMX).
- VPN: не требуется.

### StatCan (Канада)

- Владелец: Статистическая служба Канады.
- URL: https://www150.statcan.gc.ca
- Что берём: CPI, квартальные долг/бюджет/трейд (WDS API).
- Формат: WDS REST API, без ключа.

### IMF WEO (International Monetary Fund)

- Владелец: МВФ.
- URL: https://www.imf.org/en/Publications/WEO
- Что берём: годовые метрики (долг/ВВП, бюджет/ВВП, трейд/ВВП, рост ВВП, инфляция) для 17 стран.
- Роль: fallback.
- Формат: библиотека imf-reader.

### IMF DSBB (Корея)

- Владелец: МВФ + корейский минфин.
- URL: https://mods.go.kr/imfDsbbArcPage.es
- Что берём: Central Government Debt (Q2/26).
- Формат: HTML-парсинг.

### ForexFactory

- URL: https://www.forexfactory.com
- Что берём: экономический календарь.
- Формат: библиотека market-calendar-tool.

### RSS

- Reuters Business, BBC Business, Investing.com.
- Формат: feedparser.

## VPN-требования

| Источник                                           | VPN | Какой                 |
|----------------------------------------------------|-----|-----------------------|
| Tonghuashun                                        | Да  | Азиатский             |
| Минфин КНР, SAFE                                   | Да  | Европейский (Бельгия) |
| NIFD                                               | Нет | Работает              |
| MoSPI                                              | Да  | Не-российский         |
| dataseries.org                                     | Да  | Не-российский         |
| FRED, Eurostat, ONS, BEA, Treasury                 | Нет | Работают              |
| e-Stat, BoJ, BoE, BoC, SNB, ABS, StatCan, SingStat | Нет | Работают              |
| chinamoney, BCB, rba-mcp                           | Нет | Работают              |

## Технические решения для устойчивости

- Retry-логика для всех источников (3–5 попыток).
- Fallback на IMF — если источник недоступен.
- Накопление данных в save_china_fiscal.
- Кеширование PDF NIFD.
- rba-mcp для RBA — обходит блокировку.

## Проверка достоверности

1. Открыть источник напрямую.
2. Сверить значение в дашборде с источником.
3. Проверить дату публикации.
