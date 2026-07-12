#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'

function Write-Log([string]$msg) {
    if (-not $LogPath) { return }
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Write-ApplyFailed([string]$install, [string]$reason) {
    $stateDir = Join-Path $env:LOCALAPPDATA 'PeechaSync'
    if (-not (Test-Path -LiteralPath $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }
    $payload = @{
        at      = (Get-Date).ToString('o')
        reason  = $reason
        install = $install
    } | ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $stateDir 'update-apply-failed.json') -Value $payload -Encoding UTF8
}

function Clear-ApplyFailed {
    $path = Join-Path $env:LOCALAPPDATA 'PeechaSync\update-apply-failed.json'
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-InstallRoot([string]$fallback) {
    $locFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\install.loc'
    if (Test-Path -LiteralPath $locFile) {
        $fromLoc = (Get-Content -LiteralPath $locFile -Raw -Encoding UTF8).Trim()
        if ($fromLoc -and (Test-Path -LiteralPath $fromLoc)) {
            return $fromLoc.TrimEnd('\', '/')
        }
    }
    return $fallback.TrimEnd('\', '/')
}

function Wait-PeechaExit([int]$maxSec = 60) {
    for ($i = 0; $i -lt $maxSec; $i++) {
        $alive = Get-Process pythonw, python -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ($_.Path -like '*PeechaSync*')
        }
        if (-not $alive) { return }
        Start-Sleep -Seconds 1
    }
    Get-Process pythonw, python -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ($_.Path -like '*PeechaSync*')
    } | ForEach-Object {
        Write-Log "force kill pid $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
}

function Invoke-RobocopyMirror([string]$src, [string]$dst) {
    if (-not (Test-Path -LiteralPath $src)) { return }
    if (-not (Test-Path -LiteralPath $dst)) {
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
    }
    & robocopy $src $dst /MIR /R:3 /W:2 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed ($src -> $dst) exit=$LASTEXITCODE"
    }
}

function Test-SourcePackageReady([string]$source) {
    if (-not (Test-Path -LiteralPath (Join-Path $source 'sync_app\core'))) {
        throw 'Update package incomplete (sync_app missing)'
    }
    $ver = Read-ExpectedVersion $source
    if (-not $ver) {
        throw 'Update package incomplete (VERSION missing)'
    }
    $hasPython = Test-Path -LiteralPath (Join-Path $source 'python\python.exe')
    $hasMain = (Test-Path -LiteralPath (Join-Path $source 'main.pyc')) -or
        (Test-Path -LiteralPath (Join-Path $source 'main.py'))
    if (-not $hasPython -and -not $hasMain) {
        throw 'Update package incomplete (python or main missing)'
    }
    return $ver
}

function Invoke-ForceCleanInstall([string]$install, [string]$source, [string]$logPath) {
    $forceClean = Join-Path $source 'Force-CleanProgramFiles.ps1'
    if (-not (Test-Path -LiteralPath $forceClean)) {
        $forceClean = Join-Path $install 'Force-CleanProgramFiles.ps1'
    }
    if (-not (Test-Path -LiteralPath $forceClean)) {
        throw 'Force-CleanProgramFiles.ps1 missing — cannot replace install safely'
    }
    Write-Log 'force clean old program (keep license, settings, maps)'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $forceClean -InstallRoot $install -LogPath $logPath
    if (-not (Test-Path -LiteralPath $install)) {
        New-Item -ItemType Directory -Path $install -Force | Out-Null
    }
    Write-Log 'force clean done'
}

function Read-ExpectedVersion([string]$root) {
    $verFile = Join-Path $root 'VERSION.txt'
    if (Test-Path -LiteralPath $verFile) {
        return (Get-Content -LiteralPath $verFile -Raw -Encoding UTF8).Trim()
    }
    $verPy = Join-Path $root 'sync_app\core\app_version.py'
    if (Test-Path -LiteralPath $verPy) {
        foreach ($line in Get-Content -LiteralPath $verPy -Encoding UTF8) {
            if ($line -match '_BUILTIN_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
            if ($line -match 'APP_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
        }
    }
    return ''
}

$install = Resolve-InstallRoot $InstallRoot
$source = $SourceRoot.TrimEnd('\', '/')

try {
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Update source not found: $source"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'sync_app'))) {
        throw 'Invalid update package (sync_app missing)'
    }

    $expectedVer = Test-SourcePackageReady $source

    Write-Log "apply start install=$install target=$expectedVer (full replace)"
    Wait-PeechaExit

    Invoke-ForceCleanInstall $install $source $LogPath

    foreach ($dir in @('sync_app', 'python', '_packages')) {
        $srcDir = Join-Path $source $dir
        if (Test-Path -LiteralPath $srcDir) {
            Write-Log "mirror $dir"
            Invoke-RobocopyMirror $srcDir (Join-Path $install $dir)
        }
    }

    foreach ($name in @(
            'main.py', 'main.pyc', 'requirements.txt', 'PeechaSync.ico', 'VERSION.txt',
            'Run-PeechaSync.bat', 'Launch-PeechaSync.vbs', 'launch-gui.cmd', 'launch-gui.ps1',
            'patch-launch-env.cmd', 'repair-launch-env.cmd', 'set-python-env.bat',
            'test-import.ps1', 'test-bootstrap.ps1', 'verify-main-pyc.ps1',
            'show-startup-error.bat', 'show-user-message.ps1', 'check-internet.bat',
            'peecha-version-refresh.ps1', 'Apply-ClientUpdate.ps1', 'Force-CleanProgramFiles.ps1',
            'Assert-InstalledVersion.ps1', 'peecha-apply-cached-update.ps1', 'Apply-CachedUpdate.bat',
            '.peecha-pyc-only', '.peecha-release'
        )) {
        $srcFile = Join-Path $source $name
        if (Test-Path -LiteralPath $srcFile) {
            Copy-Item -LiteralPath $srcFile -Destination (Join-Path $install $name) -Force
        }
    }

    Get-ChildItem -LiteralPath $install -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $install -Recurse -Filter '*.pyc' -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    $mainPyc = Join-Path $install 'main.pyc'
    if (Test-Path -LiteralPath $mainPyc) { Remove-Item -LiteralPath $mainPyc -Force }

    $py = Join-Path $install 'python\python.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        $py = Join-Path $install '.venv\Scripts\python.exe'
    }

    $packages = Join-Path $install '_packages'
    $reqFile = Join-Path $install 'requirements.txt'
    if ((Test-Path -LiteralPath $py) -and (Test-Path -LiteralPath $reqFile)) {
        $findLinks = $packages
        if (-not (Get-ChildItem -LiteralPath $packages -Filter '*.whl' -File -ErrorAction SilentlyContinue)) {
            $alt = Join-Path $source '_packages'
            if (Test-Path -LiteralPath $alt) { $findLinks = $alt }
        }
        if (Get-ChildItem -LiteralPath $findLinks -Filter '*.whl' -File -ErrorAction SilentlyContinue) {
            Write-Log 'pip offline install'
            & $py -m pip install --no-index --find-links $findLinks -r $reqFile 2>&1 | Out-Null
        }
    }

    if (Test-Path -LiteralPath $py) {
        & $py -m compileall -b -q $install 2>&1 | Out-Null
        Write-Log 'compileall done'
        if (Test-Path -LiteralPath (Join-Path $install '.peecha-pyc-only')) {
            Get-ChildItem -LiteralPath $install -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }

    Copy-Item -LiteralPath (Join-Path $source 'VERSION.txt') -Destination (Join-Path $install 'VERSION.txt') -Force
    $stamp = Join-Path $install '.peecha-installed-version'
    if (Test-Path -LiteralPath $stamp) { Remove-Item -LiteralPath $stamp -Force }

    $refresh = Join-Path $install 'peecha-version-refresh.ps1'
    if (Test-Path -LiteralPath $refresh) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $refresh -InstallRoot $install
    }

    $assert = Join-Path $install 'Assert-InstalledVersion.ps1'
    if (-not (Test-Path -LiteralPath $assert)) {
        $assert = Join-Path $source 'Assert-InstalledVersion.ps1'
    }
    if (Test-Path -LiteralPath $assert) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $assert -InstallRoot $install -ExpectedVersion $expectedVer
            Write-Log "version assert ok $expectedVer"
        } catch {
            Write-Log "version assert warn: $($_.Exception.Message)"
        }
    }

    $locDir = Join-Path $env:LOCALAPPDATA 'PeechaSync'
    if (-not (Test-Path -LiteralPath $locDir)) {
        New-Item -ItemType Directory -Path $locDir -Force | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $locDir 'install.loc') -Value $install -Encoding UTF8 -NoNewline
    Clear-ApplyFailed
    Write-Log 'apply end ok'
    exit 0
} catch {
    Write-Log "apply FAILED: $($_.Exception.Message)"
    Write-ApplyFailed $install $_.Exception.Message
    exit 1
}
