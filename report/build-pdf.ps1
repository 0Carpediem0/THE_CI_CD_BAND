# Печатает report.html в report.pdf через Chrome или Edge.
# Запуск из папки report:  powershell -ExecutionPolicy Bypass -File .\build-pdf.ps1
# Или двойной щелчок по build-pdf.cmd

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$html = Join-Path $here "report.html"
$pdf = Join-Path $here "report.pdf"

if (-not (Test-Path $html)) {
    throw "Нет файла $html"
}

$browsers = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$browser = $browsers | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) {
    throw "Не найден Chrome или Edge."
}

$uri = ([Uri]$html).AbsoluteUri
if (Test-Path $pdf) {
    Remove-Item $pdf -Force
}

# chrome.exe — GUI-процесс: вызов через & возвращается сразу, не дожидаясь PDF.
$arg = "--headless --disable-gpu --no-pdf-header-footer --print-to-pdf=`"$pdf`" `"$uri`""
$proc = Start-Process -FilePath $browser -ArgumentList $arg -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) {
    throw "Браузер завершился с кодом $($proc.ExitCode)."
}

$ready = $false
foreach ($i in 1..20) {
    if (Test-Path $pdf) { $ready = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    throw "PDF не создан."
}

$item = Get-Item $pdf
Write-Host ("Готово: {0} ({1} байт)" -f $item.FullName, $item.Length)
