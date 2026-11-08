[CmdletBinding()]
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $Python) { $Python = Join-Path $repo '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath (Join-Path $repo 'frontend/node_modules/.package-lock.json'))) {
    throw 'Install the locked frontend environment before building the desktop candidate.'
}
Push-Location -LiteralPath $repo
try {
    & node 'frontend/scripts/third-party-notices.mjs'
    if ($LASTEXITCODE -ne 0) { throw 'Frontend notice generation failed.' }
    & node 'desktop/scripts/third-party-notices.mjs'
    if ($LASTEXITCODE -ne 0) { throw 'Rust notice generation failed.' }
    & $Python 'scripts/packaging/notice_provenance.py' --repo $repo
    if ($LASTEXITCODE -ne 0) { throw 'Notice provenance generation failed.' }
} finally { Pop-Location }
