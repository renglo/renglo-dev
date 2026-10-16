# Install and start a local Renglo workspace. The workspace is the parent of this repo.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $Root

if (Get-Command python3.12 -ErrorAction SilentlyContinue) {
    & python3.12 -m renglo_dev @args
    exit $LASTEXITCODE
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -m renglo_dev @args
    exit $LASTEXITCODE
}

Write-Error "python3.12 or the py launcher (py -3.12) is required and was not found on PATH."
exit 1
