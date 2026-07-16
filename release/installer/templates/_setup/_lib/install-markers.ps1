#Requires -Version 5.1
function Test-PeechaProgramInstalled {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $root = $InstallRoot.TrimEnd('\', '/')
    if (-not (Test-Path -LiteralPath $root)) { return $false }
    foreach ($rel in @(
            'main.pyc',
            'Run-PeechaSync.bat',
            'python\python.exe',
            'sync_app\core\peecha_launcher.pyc'
        )) {
        if (Test-Path -LiteralPath (Join-Path $root $rel)) { return $true }
    }
    return $false
}
