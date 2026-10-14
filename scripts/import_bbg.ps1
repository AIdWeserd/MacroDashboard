# Импорт свежей выгрузки Bloomberg в папку проекта
# Имя формируется автоматически: bbg_<вчерашняя дата>.xlsx

$src = "C:\Users\Admin\Downloads\bbg_export.xlsx"
$dstDir = "C:\MyProjects\CB\Macro_dashboard\data\bloomberg"
$dstName = "bbg_" + (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") + ".xlsx"
$dstFull = Join-Path $dstDir $dstName

if (-not (Test-Path $src)) {
    Write-Host "[ERROR] Файл не найден: $src" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Move-Item -Path $src -Destination $dstFull -Force

Write-Host "[OK] Перемещено: $dstFull" -ForegroundColor Green
