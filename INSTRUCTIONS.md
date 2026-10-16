# INSTRUCTIONS — команды для работы с проектом

Шпаргалка по всем командам, которые нужно запускать вручную.
Все команды выполняются в PowerShell, если не указано иное.

Корень проекта: `C:\MyProjects\CB\Macro_dashboard`

---

## 1. Подготовка окружения (один раз)

### Активация виртуального окружения

```powershell
cd C:\MyProjects\CB\Macro_dashboard
.venv\Scripts\activate
```

После активации в начале строки появится `(.venv)`.

### Установка зависимостей

```powershell
pip install -r requirements.txt
```

### Проверка, что ключи на месте

```powershell
Get-Content .env
```

Должны быть `FRED_API_KEY`, `ESTAT_APP_ID`, `BEA_API_KEY`.

---

## 2. Обновление данных

### Обновить всё

```powershell
cd C:\MyProjects\CB\Macro_dashboard
.venv\Scripts\activate
python scheduler.py
```

Прогоняет все
группы: `rates`, `us`, `sg`, `br`, `gb`, `jp`, `kr`, `au`, `ca`, `ch`, `cn`, `in`, `tr`, `fred`, `imf`, `eurostat`, `extra`.
В конце — снимок сводной таблицы и очистка старых файлов.

### Обновить только одну группу

```powershell
python scheduler.py cn
python scheduler.py us
python scheduler.py rates
python scheduler.py fred
```

### Обновить несколько групп сразу

```powershell
python scheduler.py cn in tr
```

### Список доступных групп

```powershell
python scheduler.py --list
```

### Справка

```powershell
python scheduler.py --help
```

### Группы и что они обновляют

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

---

## 3. Запуск дашборда

```powershell
cd C:\MyProjects\CB\Macro_dashboard
.venv\Scripts\activate
streamlit run app.py
```

Откроется браузер на `http://localhost:8501`.

Остановить: `Ctrl+C` в терминале.

---

## 4. Bloomberg: перенос выгрузки

### Что делает скрипт

Перемещает файл `bbg_export.xlsx` из `Downloads` в `data\bloomberg\`,
переименовывая в `bbg_YYYY-MM-DD.xlsx` (вчерашняя дата).

### Запуск

```powershell
cd C:\MyProjects\CB\Macro_dashboard
powershell -ExecutionPolicy Bypass -File scripts\import_bbg.ps1
```

### Ручной вариант (если скрипт не сработал)

Выполняй **по одной строке**, Enter после каждой:

```powershell
$src = "C:\Users\Admin\Downloads\bbg_export.xlsx"
```

```powershell
$dstDir = "C:\MyProjects\CB\Macro_dashboard\data\bloomberg"
```

```powershell
$dstName = "bbg_" + (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") + ".xlsx"
```

```powershell
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
```

```powershell
Move-Item -Path $src -Destination (Join-Path $dstDir $dstName) -Force
```

### Проверка

```powershell
dir "C:\MyProjects\CB\Macro_dashboard\data\bloomberg"
```

### Если PowerShell ругается на execution policy

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

(действует только на текущее окно)

---

## 5. Диагностика

### Проверить, что таблица в БД есть

```powershell
cd C:\MyProjects\CB\Macro_dashboard
python -c "import sqlite3; con = sqlite3.connect('data/macro.db'); print([r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
```

### Посмотреть содержимое конкретной таблицы

```powershell
python -c "import sqlite3, pandas as pd; con = sqlite3.connect('data/macro.db'); print(pd.read_sql('SELECT * FROM china_gdp ORDER BY date DESC LIMIT 5', con))"
```

Замени `china_gdp` на нужную таблицу.

### Проверить размер БД

```powershell
Get-Item "C:\MyProjects\CB\Macro_dashboard\data\macro.db" | Select-Object Name, Length
```

### Список файлов Bloomberg-выгрузок

```powershell
dir "C:\MyProjects\CB\Macro_dashboard\data\bloomberg"
```

### Список PDF-отчётов NIFD

```powershell
dir "C:\MyProjects\CB\Macro_dashboard\data\nifd_reports"
```

### Проверить VPN (для Китая, Индии, Швейцарии)

```powershell
python -c "from curl_cffi import requests; print(requests.get('https://ipinfo.io/country').text)"
```

Должно вернуть код страны, **не RU**.

### Сравнить сводку до и после обновления

```powershell
python -c "from src.build_summary import build_summary; print(build_summary().to_string())"
```

---

## 6. Очистка

### Вручную запустить очистку

```powershell
python -c "from src.cleanup import cleanup_all; cleanup_all()"
```

### Что удаляется

| Папка                | Что      | Через сколько дней |
|----------------------|----------|--------------------|
| `data/bloomberg/`    | `*.xlsx` | 30                 |
| `data/nifd_reports/` | `*.pdf`  | 90                 |

Очистка также запускается автоматически в конце `python scheduler.py`.

### Полностью очистить БД (осторожно!)

```powershell
python -c "from src.storage import clear_all; clear_all()"
```

Удаляет **все** таблицы. Потом надо заново запускать `python scheduler.py`.

### Полный сброс (удалить БД и пересобрать)

```powershell
Remove-Item "C:\MyProjects\CB\Macro_dashboard\data\macro.db"
python scheduler.py
```

---

## 7. Git

### Проверить статус

```powershell
cd C:\MyProjects\CB\Macro_dashboard
git status
```

### Закоммитить изменения

```powershell
git add .
git commit -m "Update data"
git push
```

### Что НЕ должно попасть в git

- `data/` (папка целиком — включая `macro.db`, `bloomberg/`, `nifd_reports/`)
- `.env` (ключи)
- `.venv/`

Проверь `.gitignore`:

```powershell
Get-Content .gitignore
```

---

## 8. Частые проблемы

### `python` не найден

Активируй venv: `.venv\Scripts\activate`.

### `streamlit` не найден

То же — активируй venv.

### `ModuleNotFoundError: No module named 'src'`

Запускай из корня проекта, не из `src/`:

```powershell
cd C:\MyProjects\CB\Macro_dashboard
python scheduler.py
```

### Дашборд показывает устаревшие данные

1. Запусти `python scheduler.py`.
2. Обнови страницу в браузере (Ctrl+F5).

### Ошибка `database is locked`

Закрой все процессы, которые держат БД (Streamlit, Python-скрипты), и повтори.

---

## 9. Порядок еженедельного обновления

1. Зайти на удалённый ПК через RustDesk.
2. Открыть `bbg_export.xlsx` в Excel (с залогиненным Bloomberg).
3. Проверить, что все `BDP`-формулы вернули значения.
4. Сохранить и перекинуть файл на свой ПК (RustDesk File Transfer или облако).
5. Запустить импорт:

```powershell
cd C:\MyProjects\CB\Macro_dashboard
powershell -ExecutionPolicy Bypass -File scripts\import_bbg.ps1
```

6. Обновить остальные данные:

```powershell
python scheduler.py
```

7. Проверить дашборд:

```powershell
streamlit run app.py
```
