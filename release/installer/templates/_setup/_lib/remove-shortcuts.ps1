$ErrorActionPreference = 'SilentlyContinue'

$dirs = New-Object System.Collections.Generic.List[string]
foreach ($key in @('Desktop', 'CommonDesktop')) {
    try {
        $p = [Environment]::GetFolderPath($key)
        if ($p) { [void]$dirs.Add($p) }
    } catch {}
}
foreach ($p in @(
        "$env:USERPROFILE\Desktop",
        "$env:PUBLIC\Desktop",
        "$env:OneDrive\Desktop"
    )) {
    if ($p) { [void]$dirs.Add($p) }
}

$seen = @{}
foreach ($d in $dirs) {
    if (-not $d -or $seen.ContainsKey($d.ToLowerInvariant())) { continue }
    $seen[$d.ToLowerInvariant()] = $true
    $lnk = Join-Path $d 'PeechaSync.lnk'
    if (Test-Path -LiteralPath $lnk) {
        Remove-Item -LiteralPath $lnk -Force
    }
}
exit 0
