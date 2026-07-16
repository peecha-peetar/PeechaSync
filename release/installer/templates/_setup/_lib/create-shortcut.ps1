$ErrorActionPreference = 'Stop'

& "$PSScriptRoot\remove-shortcuts.ps1" | Out-Null

$ShortcutPath = $env:SC_SHORTCUT
$TargetBat = $env:SC_TARGET_BAT
$WorkingDir = $env:SC_WORKING_DIR
$IconFile = $env:SC_ICON_FILE

if (-not $ShortcutPath -or -not $TargetBat -or -not $WorkingDir) {
    Write-Error 'SC_SHORTCUT, SC_TARGET_BAT, SC_WORKING_DIR required'
    exit 1
}

if (-not (Test-Path -LiteralPath $TargetBat)) {
    Write-Error "Target not found: $TargetBat"
    exit 1
}
if (-not (Test-Path -LiteralPath $WorkingDir)) {
    Write-Error "Working dir not found: $WorkingDir"
    exit 1
}

$shortcutDir = Split-Path -Parent $ShortcutPath
if ($shortcutDir -and -not (Test-Path -LiteralPath $shortcutDir)) {
    New-Item -ItemType Directory -Path $shortcutDir -Force | Out-Null
}

$vbs = Join-Path $WorkingDir 'Launch-PeechaSync.vbs'
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $wscript)) {
    Write-Error 'wscript.exe not found'
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$s = $wsh.CreateShortcut($ShortcutPath)
if (Test-Path -LiteralPath $vbs) {
    $s.TargetPath = $wscript
    $s.Arguments = "`"$vbs`""
} else {
    $cmd = $env:ComSpec
    if (-not $cmd) { $cmd = "$env:SystemRoot\System32\cmd.exe" }
    $s.TargetPath = $cmd
    $s.Arguments = '/c "' + $TargetBat + '"'
}
$s.WorkingDirectory = $WorkingDir
$s.WindowStyle = 7
$s.Description = 'PeechaSync (via Launch-PeechaSync.vbs)'
if ($IconFile -and (Test-Path -LiteralPath $IconFile)) {
    $s.IconLocation = "$IconFile,0"
}
$s.Save()
exit 0
