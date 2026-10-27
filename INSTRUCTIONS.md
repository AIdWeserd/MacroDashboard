# Macro Dashboard — использование и обновление данных

**Состояние: 26.10.2026.** Команды для Windows PowerShell из корня рабочего проекта. Первичная установка описана только в [`README.md`](README.md).

## 1. Ежедневный запуск

```powershell
cd C:\MyProjects\CB\Macro_dashboard
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

Открыть `http://localhost:8501`. Остановить приложение — `Ctrl+C`. Сводная таблица читает **уже сохранённые данные**, поэтому для простого просмотра полный `scheduler.py` не нужен.

## 2. Работа в интерфейсе

1. **Сводная таблица:** выбери год и месяц, просмотри значения по 18 странам/экономикам. В ячейке важны не только число, но и период, источник, методология и отметка прогноза.
2. **Таблица без дат:** отдельный вид числовых значений, если нужна компактная выборка.
3. **Экспорт:** выбери формат и вид таблицы, выгрузи Excel/CSV/HTML/PDF (набор доступных форматов может зависеть от локальных библиотек). Экспорт не изменяет SQLite.
4. **Детальные метрики:** раскрываемые секции для месячных показателей, исторических ставок и рядов FRED, графики и история.
5. **Данные по странам:** в нижнем разделе выбери страну и открой детальную страницу; наиболее полно реализована Россия — ставки, кредиты, ипотека, денежная масса, торговля, инвесторы, справочная статистика и RUONIA.
6. **Календарь / RSS:** это внешние информационные источники. ForexFactory может возвращать `403`; отказ календаря не означает ошибку макроэкономических таблиц. Календарь загружается по отдельному действию в актуально исправленной версии интерфейса.
7. **Подсветка:** жёлтым могут выделяться изменения относительно недельного снимка, красным — значения Bloomberg. Если предыдущий снимок старый, подсветка сравнивает именно с ним, а не обязательно с предыдущей календарной неделей.

## 3. Команды планировщика

```powershell
python scheduler.py --help
python scheduler.py --list
python scheduler.py --dry-run
python scheduler.py --dry-run ru
python scheduler.py fred
python scheduler.py ru
python scheduler.py ca
python scheduler.py cn in tr
python scheduler.py
```

`--list` выводит подробный состав групп. `--dry-run` только показывает план: без сети и записей. Несколько групп можно указать в одной команде. Если этап повторился через пересекающиеся группы, планировщик устраняет дубликаты по функции загрузки и сохранения.

### Основные группы: 59 этапов

| Группа | Шагов | Назначение |
|---|---:|---|
| `bbg` | 1 | Ручной Bloomberg Excel |
| `rates` | 1 | Ставки ЦБ нескольких стран |
| `us` | 2 | США — квартальные и годовые финансы |
| `sg` | 4 | Сингапур |
| `br` | 4 | Бразилия |
| `gb` | 2 | Великобритания |
| `jp` | 2 | Япония |
| `kr` | 2 | Южная Корея |
| `au` | 2 | Австралия |
| `ca` | 2 | Канада |
| `ch` | 4 | Швейцария |
| `cn` | 7 | Китай |
| `in` | 3 | Индия |
| `tr` | 1 | Турция |
| `ru` | 11 | Россия — сводка и детальные ряды |
| `fred` | 4 | FRED: макро, GDP, безработица, CPI |
| `imf` | 1 | IMF WEO |
| `eurostat` | 4 | HICP, безработица, квартальные и годовые данные |
| `extra` | 2 | ForexFactory и RSS |

**Дополнительные выборочные группы:** `ru_reference` — только брокеры/ИИС/ПИФ ЦБ РФ (1 шаг), `ru_ruonia` — только дневной RUONIA (1 шаг). Они уже включены в полную группу `ru` и **не добавляются повторно** при запуске без аргументов.

Примеры узких запусков:

```powershell
python scheduler.py ru_reference
python scheduler.py ru_ruonia
python scheduler.py us fred
python scheduler.py eurostat
python scheduler.py extra
```

### Коды завершения

- `0` — все выбранные этапы успешны.
- `1` — хотя бы один этап вернул пустые или частичные данные и **не было ошибок**.
- `2` — как минимум один этап завершился ошибкой; остальные этапы могли сохранить данные.

В PowerShell сразу после запуска: `Write-Host $LASTEXITCODE`. Смотри `[SUMMARY]` и `[FINISH]`: **статус всей операции не равен состоянию каждого ряда**. При неполном полном запуске недельный снимок и очистка по расписанию не выполняются. `scheduler.py` не оборачивает все 59 шагов одной общей транзакцией.

## 4. Bloomberg — ручная загрузка

Подготовить файл `bbg_export.xlsx` с вычисленными значениями ячеек Add-in. Импортер `scripts/import_bbg.ps1` рассчитан на **конкретные локальные пути автора** (`C:\Users\Admin\Downloads`, `C:\MyProjects\CB\Macro_dashboard`): **на другом компьютере сначала исправить переменные `$src`, `$dstDir` внутри скрипта**.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\import_bbg.ps1
python scheduler.py bbg
```

После импорта проверяй `data/bloomberg/bbg_YYYY-MM-DD.xlsx`, колонки `country`, `metric`, `ticker`, `value`, `date`, `last_update`. `last_update` определяет период наблюдения. Не подменять пустые формулы Excel нулями.

## 5. Безопасный журнал и диагностика

Для корректного русского текста в текущей сессии PowerShell:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = 'utf-8'
```

Лог лучше сохранять неинтерактивно, чтобы избежать искажённой кодировки при передаче через `Tee-Object`:

```powershell
New-Item -ItemType Directory -Force .\data\audit_logs | Out-Null
python -u scheduler.py fred *> .\data\audit_logs\fred_latest.log
Write-Host 'EXIT CODE:' $LASTEXITCODE
```

Сохраняй журналы локально; перед отправкой проверяй, что они не содержат ключи или токены. Для просмотра SQLite без записи:

```powershell
@'
from config import DB_PATH
from pathlib import Path
import sqlite3
p = Path(DB_PATH)
if not p.is_file(): raise SystemExit(f'Нет базы: {p}')
con = sqlite3.connect(p.resolve().as_uri()+'?mode=ro', uri=True)
try:
    print('quick_check:', con.execute('PRAGMA quick_check').fetchone()[0])
finally:
    con.close()
'@ | python -
```

`test.py` используется **только как временный одноразовый диагностический файл**: перед каждой новой диагностикой полностью заменяй его содержимое. Не считай его постоянным тестовым набором.

## 6. Резервные копии и действия при ошибках

Перед заменой файлов и особенно перед миграцией SQLite — согласованная резервная копия. Источник истины для пути БД — `config.DB_PATH`.

```powershell
@'
import sqlite3
from datetime import datetime
from pathlib import Path
from config import DB_PATH
p = Path(DB_PATH)
if not p.is_file(): raise SystemExit(f'База не найдена: {p}')
b = p.parent / 'audit_backups' / (p.stem + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + p.suffix)
b.parent.mkdir(parents=True, exist_ok=True)
src = sqlite3.connect(p)
dst = sqlite3.connect(b)
try:
    src.backup(dst)
    print('BACKUP:', b, 'quick_check:', dst.execute('PRAGMA quick_check').fetchone()[0])
finally:
    dst.close(); src.close()
'@ | python -
```

При `timeout`, `SSL`, `403` **не очищай** таблицу. Сначала проверь, осталась ли последняя история, и повтори позже **только нужную группу**. Время публикации разных источников неодинаково; опубликованное Q2 при начавшемся Q4 не всегда означает сбой. Исключения по доступности перечислены в `AUDIT.md`.
