# PeechaSync diagnostic
$ErrorActionPreference = 'Continue'

$outDir = $env:PEECHA_CHECK_DIR
if (-not $outDir) { $outDir = (Get-Location).Path }
$outDir = $outDir.TrimEnd('\')
$reportFile = Join-Path $outDir 'PeechaSync-diagnostic-report.txt'

$appDir = Join-Path $env:LOCALAPPDATA 'PeechaSync'
if (-not (Test-Path -LiteralPath $appDir)) {
    New-Item -ItemType Directory -Path $appDir -Force | Out-Null
}

$lines = New-Object System.Collections.Generic.List[string]
function Add-Line { param([string]$Text) [void]$lines.Add($Text) }
function Save-Report {
    $text = $lines -join [Environment]::NewLine
    [System.IO.File]::WriteAllText($reportFile, $text, [System.Text.UTF8Encoding]::new($false))
}

Add-Line '========================================'
Add-Line 'PeechaSync diagnostic report'
Add-Line '========================================'
Add-Line ('Time: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Line ('PC: ' + $env:COMPUTERNAME)
Add-Line ('User: ' + $env:USERNAME)
Add-Line ('Check file folder: ' + $outDir)
Add-Line ('Windows: ' + [Environment]::OSVersion.VersionString)
Save-Report

Add-Line ''
Add-Line '--- Python ---'
$pyOk = $false
foreach ($cmd in @('py -3.12', 'py -3.11', 'python')) {
    $parts = $cmd.Split(' ', 2)
    $exe = $parts[0]
    $args = @()
    if ($parts.Length -gt 1) { $args = $parts[1] }
    $args += @('-c', 'import sys; print(sys.version); print(sys.executable)')
    try {
        $out = & $exe @args 2>&1
        if ($LASTEXITCODE -eq 0) {
            Add-Line ("OK $cmd")
            foreach ($line in @($out)) { Add-Line ('  ' + $line) }
            $pyOk = $true
            break
        }
    } catch {
        Add-Line ("FAIL $cmd")
    }
}
if (-not $pyOk) { Add-Line 'FAIL: Python 3.11+ not found' }
Save-Report

Add-Line ''
Add-Line '--- Install folder ---'
$installDir = 'C:\PeechaSync'
$locFile = Join-Path $appDir 'install.loc'
if (Test-Path -LiteralPath $locFile) {
    $installDir = (Get-Content -LiteralPath $locFile -Raw).Trim()
}
Add-Line ('Path: ' + $installDir)
if (Test-Path -LiteralPath $installDir) {
    Add-Line 'OK folder exists'
    foreach ($name in @('main.pyc', 'main.py', 'Run-PeechaSync.bat', '.venv\Scripts\python.exe', '.venv\Scripts\pythonw.exe')) {
        $p = Join-Path $installDir $name
        if (Test-Path -LiteralPath $p) { Add-Line ("OK $name") }
        else { Add-Line ("MISSING $name") }
    }
} else {
    Add-Line 'FAIL install folder not found'
}
Save-Report

Add-Line ''
Add-Line '--- Desktop shortcut ---'
try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    Add-Line ('Desktop: ' + $desktop)
    $lnk = Join-Path $desktop 'PeechaSync.lnk'
    if (Test-Path -LiteralPath $lnk) {
        Add-Line 'OK PeechaSync.lnk'
        $wsh = New-Object -ComObject WScript.Shell
        $sc = $wsh.CreateShortcut($lnk)
        Add-Line ('  Target: ' + $sc.TargetPath)
        Add-Line ('  Args: ' + $sc.Arguments)
        Add-Line ('  WorkDir: ' + $sc.WorkingDirectory)
    } else {
        Add-Line 'MISSING PeechaSync.lnk'
    }
} catch {
    Add-Line ('Desktop error: ' + $_)
}
Save-Report

Add-Line ''
Add-Line '--- Package imports ---'
$vpy = Join-Path $installDir '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $vpy) {
    foreach ($mod in @('PyQt5', 'pyodbc', 'requests', 'woocommerce', 'cryptography', 'psutil')) {
        & $vpy -c "import $mod" 2>$null
        if ($LASTEXITCODE -eq 0) { Add-Line ("OK import $mod") }
        else { Add-Line ("FAIL import $mod") }
    }
} else {
    Add-Line 'SKIP no venv python'
}
Save-Report

Add-Line ''
Add-Line '--- startup-errors.log ---'
$startupLog = Join-Path $appDir 'startup-errors.log'
if (Test-Path -LiteralPath $startupLog) {
    $content = Get-Content -LiteralPath $startupLog -ErrorAction SilentlyContinue
    if ($content) {
        foreach ($line in $content | Select-Object -Last 40) { Add-Line $line }
    } else { Add-Line '(empty)' }
} else {
    Add-Line '(not found)'
}

Add-Line ''
Add-Line '========================================'
Add-Line ('Report: ' + $reportFile)
Add-Line 'Send this file to Peecha support.'
Add-Line '========================================'
Save-Report

Start-Process -FilePath 'notepad.exe' -ArgumentList $reportFile | Out-Null
exit 0
