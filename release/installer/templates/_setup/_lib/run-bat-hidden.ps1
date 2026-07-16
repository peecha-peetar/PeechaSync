# PeechaSync hidden batch runner
param(
    [Parameter(Mandatory = $true)][string]$BatPath,
    [string]$WorkingDir = (Split-Path -Parent $BatPath),
    [string[]]$BatArgs = @()
)

if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-Error "Batch file not found: $BatPath"
    exit 1
}

$argLine = '/c "' + $BatPath + '"'
foreach ($a in $BatArgs) {
    $argLine += ' ' + $a
}

$p = Start-Process -FilePath $env:ComSpec `
    -ArgumentList $argLine `
    -WorkingDirectory $WorkingDir `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

exit $p.ExitCode
