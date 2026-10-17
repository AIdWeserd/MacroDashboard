# ============================================================
# Импорт свежей выгрузки Bloomberg в папку проекта.
# Имя формируется автоматически: bbg_<вчерашняя дата>.xlsx
# Старые файлы (старше 6 месяцев) удаляются.
# ============================================================

$src     = "C:\Users\Admin\Downloads\bbg_export.xlsx"
$dstDir  = "C:\MyProjects\CB\Macro_dashboard\data\bloomberg"
$dstName = "bbg_" + (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") + ".xlsx"
$dstFull = Join-Path $dstDir $dstName

# Сколько дней хранить старые выгрузки
$keepDays = 180

# 1. Проверка исходного файла
if (-not (Test-Path $src)) {
    Write-Host "[ERROR] Файл не найден: $src" -ForegroundColor Red
    Write-Host "        Убедись, что bbg_export.xlsx лежит в Downloads." -ForegroundColor Yellow
    exit 1
}

# 2. Проверка расширения
if ([System.IO.Path]::GetExtension($src) -ne ".xlsx") {
    Write-Host "[ERROR] Ожидался .xlsx, получено: $src" -ForegroundColor Red
    exit 1
}

# 3. Создание папки назначения
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null

# 4. Проверка, что файла с таким именем ещё нет
if (Test-Path $dstFull) {
    Write-Host "[WARN] Файл с таким именем уже существует: $dstFull" -ForegroundColor Yellow
    $answer = Read-Host "Перезаписать? (y/n)"
    if ($answer -ne "y") {
        Write-Host "[CANCEL] Отменено пользователем." -ForegroundColor Yellow
        exit 0
    }
}

# 5. Перемещение
Move-Item -Path $src -Destination $dstFull -Force

Write-Host "[OK] Перемещено:" -ForegroundColor Green
Write-Host "     $dstFull" -ForegroundColor Green

# 6. Удаление старых файлов (старше $keepDays)
$cutoff = (Get-Date).AddDays(-$keepDays)
$oldFiles = Get-ChildItem -Path $dstDir -Filter "bbg_*.xlsx" |
            Where-Object { $_.LastWriteTime -lt $cutoff }

if ($oldFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "[CLEANUP] Удаляю файлы старше $keepDays дней:" -ForegroundColor Yellow
    foreach ($f in $oldFiles) {
        Remove-Item -Path $f.FullName -Force
        Write-Host "          Удалён: $($f.Name) (mtime=$($f.LastWriteTime.ToString('yyyy-MM-dd')))" -ForegroundColor Gray
    }
    Write-Host "[CLEANUP] Удалено файлов: $($oldFiles.Count)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "[CLEANUP] Старых файлов (старше $keepDays дней) нет." -ForegroundColor Gray
}

Write-Host ""
Write-Host "Теперь запусти: python scheduler.py" -ForegroundColor Cyan