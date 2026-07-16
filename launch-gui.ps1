param(
    [string]$LogFile = ''
)

$ErrorActionPreference = 'Stop'
$WorkDir = (Get-Location).Path.TrimEnd('\')

function Write-Log([string]$Line) {
    if (-not $LogFile) { return }
    $dir = Split-Path -Parent $LogFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Add-Content -LiteralPath $LogFile -Value $Line -Encoding UTF8
}

function Set-LaunchEnv([string]$PyExe) {
    $pyDir = (Split-Path -Parent $PyExe).TrimEnd('\')
    $scripts = Join-Path $pyDir 'Scripts'
    $pathBits = @($pyDir)
    if (Test-Path -LiteralPath $scripts) { $pathBits += $scripts }
    $pathBits += $env:PATH -split ';' | Where-Object { $_ }
    $env:PATH = ($pathBits | Select-Object -Unique) -join ';'

    $site = Join-Path $pyDir 'Lib\site-packages'
    if (-not (Test-Path -LiteralPath $site)) {
        $parent = Split-Path -Parent $pyDir
        $site = Join-Path $parent 'Lib\site-packages'
    }
    $qtBin = Join-Path $site 'PyQt5\Qt5\bin'
    $qtPlugins = Join-Path $site 'PyQt5\Qt5\plugins'
    if (Test-Path -LiteralPath $qtBin) {
        $env:PATH = "$qtBin;$env:PATH"
    }
    if (Test-Path -LiteralPath $qtPlugins) {
        $env:QT_PLUGIN_PATH = $qtPlugins
    }
    $env:QT_QPA_PLATFORM = 'windows'
    $env:PYTHONHOME = $pyDir
}

function Get-MainPath {
    $pycOnly = Join-Path $WorkDir '.peecha-pyc-only'
    $pyc = Join-Path $WorkDir 'main.pyc'
    $py = Join-Path $WorkDir 'main.py'
    if ((Test-Path -LiteralPath $pycOnly) -and (Test-Path -LiteralPath $pyc)) {
        return (Resolve-Path -LiteralPath $pyc).Path
    }
    if (Test-Path -LiteralPath $py) { return (Resolve-Path -LiteralPath $py).Path }
    if (Test-Path -LiteralPath $pyc) { return (Resolve-Path -LiteralPath $pyc).Path }
    return ''
}

function Get-PythonExe {
    foreach ($rel in @('python\python.exe', '.venv\Scripts\python.exe')) {
        $path = Join-Path $WorkDir $rel
        if (Test-Path -LiteralPath $path) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    return ''
}

function Test-Launch([string]$Exe, [string]$MainPath) {
    if (-not (Test-Path -LiteralPath $Exe)) {
        Write-Log ('[{0}] missing exe: {1}' -f (Get-Date), $Exe)
        return $null
    }
    try {
        return Start-Process -FilePath $Exe `
            -ArgumentList @('-u', $MainPath) `
            -WorkingDirectory $WorkDir `
            -WindowStyle Hidden `
            -PassThru `
            -ErrorAction Stop
    } catch {
        Write-Log ('[{0}] Start-Process failed ({1}): {2}' -f (Get-Date), $Exe, $_)
        return $null
    }
}

function Capture-RunOutput([string]$Exe, [string]$MainPath) {
    Set-LaunchEnv $Exe
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = "-u `"$MainPath`""
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()
    [void][System.Threading.Tasks.Task]::WaitAll(@($outTask, $errTask))
    return @{ Code = $p.ExitCode; Out = $outTask.Result; Err = $errTask.Result }
}

if (-not (Test-Path -LiteralPath $WorkDir)) {
    Write-Log ('[{0}] missing workdir: {1}' -f (Get-Date), $WorkDir)
    exit 3
}

$mainPath = Get-MainPath
if (-not $mainPath) {
    Write-Log ('[{0}] missing main in {1}' -f (Get-Date), $WorkDir)
    exit 2
}

$pythonExe = Get-PythonExe
if (-not $pythonExe) {
    Write-Log ('[{0}] missing python in {1}' -f (Get-Date), $WorkDir)
    exit 4
}

Set-LaunchEnv $pythonExe
Write-Log ('[{0}] spawn try {1} -u {2}' -f (Get-Date), $pythonExe, $mainPath)

$proc = Test-Launch $pythonExe -MainPath $mainPath
if (-not $proc) {
    Write-Log ('[{0}] launch-gui: spawn failed' -f (Get-Date))
    exit 5
}

Write-Log ('[{0}] pid {1}' -f (Get-Date), $proc.Id)
Start-Sleep -Seconds 2
if (-not $proc.HasExited) { exit 0 }

Write-Log ('[{0}] process exited early code={1}' -f (Get-Date), $proc.ExitCode)
$cap = Capture-RunOutput $pythonExe -MainPath $mainPath
if ($cap.Out) {
    foreach ($line in ($cap.Out -split "`n")) {
        if ($line.Trim()) { Write-Log ('[python-out] {0}' -f $line.TrimEnd()) }
    }
}
if ($cap.Err) {
    foreach ($line in ($cap.Err -split "`n")) {
        if ($line.Trim()) { Write-Log ('[python-err] {0}' -f $line.TrimEnd()) }
    }
}
Write-Log ('[{0}] capture exit code={1}' -f (Get-Date), $cap.Code)
exit 5
