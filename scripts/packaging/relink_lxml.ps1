[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Workbench,
    [string]$AppSourceRoot,
    [string]$Python,
    [string]$WindowsSdkVersion = '10.0.26100.0',
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Workbench).Path
$receipt = Get-Content -LiteralPath (Join-Path $root 'materials-receipt.json') -Raw | ConvertFrom-Json
if ($receipt.status -ne 'PINNED_MATERIALS_PRESENT_RELINK_NOT_RUN') { throw 'Incomplete material receipt.' }
foreach ($material in $receipt.materials) {
    $path = Join-Path $root ('archives/' + $material.file)
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $material.sha256) { throw 'Material digest differs.' }
}
if (-not $Build) {
    [ordered]@{ status='PLAN_ONLY'; material_count=$receipt.materials.Count; relink='NOT_RUN';
        compiler_required='MSVC v143 14.44.x x64'; sdk=$WindowsSdkVersion;
        distribution_clearance=$false } | ConvertTo-Json
    return
}
# Build is opt-in, only on a host whose policy permits native tool/test execution.
# Never run it as an output-path workaround on a policy-blocked host.
if ($env:VCToolsVersion -notmatch '^14\.44\.') { throw 'Activate the reviewed MSVC v143 14.44.x x64 environment; do not silently use v145.' }
foreach ($tool in @('msbuild','nmake','cscript.exe','git','uv')) { Get-Command $tool -ErrorAction Stop | Out-Null }
$app = (Resolve-Path -LiteralPath $AppSourceRoot).Path
if (Test-Path -LiteralPath (Join-Path $app '.git')) { throw 'Use a fresh archived source copy, never a live checkout.' }
if (Test-Path -LiteralPath (Join-Path $app '.venv')) { throw 'Use a fresh source copy without a pre-existing environment.' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Explicit Python 3.12.16 executable required.' }
function Invoke-Checked([string]$Tool,[string[]]$ToolArgs) {
    & $Tool @ToolArgs
    if ($LASTEXITCODE -ne 0) { throw "Recipient command failed: $Tool" }
}
$native = Join-Path $root 'trees/native'
$iconv = Join-Path $native 'libiconv'
$zlib = Join-Path $native 'zlib'
$xml = Join-Path $native 'libxml2'
$xslt = Join-Path $native 'libxslt'
$lxml = Join-Path $root 'trees/lxml'
$savedEnvironment = @{}
foreach ($key in @('STATICBUILD','LXML_STATIC_INCLUDE_DIRS','LXML_STATIC_LIBRARY_DIRS','CAFE_FIN_TEST_SIDECAR')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key,'Process')
}
try {
    $before = @(Get-ChildItem -LiteralPath (Join-Path $app 'backend') -Recurse -File | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | Select-Object -ExpandProperty Hash)
    Invoke-Checked 'git' @('-C',$iconv,'apply','--check',(Join-Path $native 'libiconv.patch'))
    Invoke-Checked 'git' @('-C',$iconv,'apply',(Join-Path $native 'libiconv.patch'))
    # A harmless exported constant-returning function makes modified native code
    # observable in BOTH linked PYDs; parsing/conversion semantics stay unchanged.
    $probe = "`n#ifdef _WIN32`n__declspec(dllexport) int cafe_fin_relink_probe(void) { return 20261108; }`n#endif`n"
    Add-Content -LiteralPath (Join-Path $iconv 'source/lib/iconv.c') -Value $probe -Encoding ascii
    Invoke-Checked 'msbuild' @((Join-Path $iconv 'MSVC17/libiconv_static/libiconv_static.vcxproj'),
        '/p:Configuration=Release','/p:Platform=x64','/p:PlatformToolset=v143',
        "/p:VCToolsVersion=$env:VCToolsVersion","/p:WindowsTargetPlatformVersion=$WindowsSdkVersion")
    $iconvLib = Join-Path $iconv 'MSVC17/x64/lib'
    Copy-Item -LiteralPath (Join-Path $iconvLib 'libiconv_a.lib') -Destination (Join-Path $iconvLib 'iconv_a.lib')
    Push-Location -LiteralPath $zlib
    try { Invoke-Checked 'nmake' @('-f','win32/Makefile.msc','zlib_a.lib') } finally { Pop-Location }
    Copy-Item -LiteralPath (Join-Path $zlib 'zlib_a.lib') -Destination (Join-Path $zlib 'zlib.lib')
    $iconvInclude = Join-Path $iconv 'source/include'
    $xmlInclude = Join-Path $xml 'include'
    $xmlLib = Join-Path $xml 'win32/bin.msvc'
    $xsltLib = Join-Path $xslt 'win32/bin.msvc'
    Push-Location -LiteralPath (Join-Path $xml 'win32')
    try {
        Invoke-Checked 'cscript.exe' @('//nologo','configure.js',"lib=$zlib;$iconvLib","include=$zlib;$iconvInclude",'vcmanifest=yes','zlib=yes')
        Invoke-Checked 'nmake' @('libxmla')
    } finally { Pop-Location }
    Push-Location -LiteralPath (Join-Path $xslt 'win32')
    try {
        Invoke-Checked 'cscript.exe' @('//nologo','configure.js',"lib=$zlib;$iconvLib;$xmlLib","include=$zlib;$iconvInclude;$xmlInclude",'vcmanifest=yes','zlib=yes')
        Invoke-Checked 'nmake' @('libxslta','libexslta')
    } finally { Pop-Location }
    Invoke-Checked 'uv' @('sync','--frozen','--project',$app,'--python',$Python)
    $venvPython = Join-Path $app '.venv/Scripts/python.exe'
    $env:STATICBUILD = '' # --static uses supplied libraries; --static-deps would download mutable inputs.
    $env:LXML_STATIC_INCLUDE_DIRS = "$zlib;$iconvInclude;$xmlInclude;$xslt"
    $env:LXML_STATIC_LIBRARY_DIRS = "$iconvLib;$zlib;$xmlLib;$xsltLib"
    Push-Location -LiteralPath $lxml
    try { Invoke-Checked $venvPython @('setup.py','bdist_wheel','--static','--without-cython') } finally { Pop-Location }
    $wheel = @(Get-ChildItem -LiteralPath (Join-Path $lxml 'dist') -Filter '*cp312*win_amd64.whl' -File)
    if ($wheel.Count -ne 1) { throw 'Exactly one modified x64 wheel is required.' }
    Invoke-Checked 'uv' @('pip','install','--python',$venvPython,'--reinstall','--no-deps',$wheel[0].FullName)
    Invoke-Checked $venvPython @((Join-Path $PSScriptRoot 'verify_relinked_lxml.py'),'--output',(Join-Path $root 'relink-probe.json'))
    & (Join-Path $app 'desktop/scripts/build-sidecar.ps1') -Python $venvPython
    if ($LASTEXITCODE -ne 0) { throw 'Modified sidecar packaging failed.' }
    $env:CAFE_FIN_TEST_SIDECAR = Join-Path $app 'desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe'
    Push-Location -LiteralPath $app
    try { Invoke-Checked $venvPython @('-m','pytest','tests/core/test_api_sidecar.py::test_sidecar_real_loopback_unicode_second_instance_and_restart','-q') } finally { Pop-Location }
    $after = @(Get-ChildItem -LiteralPath (Join-Path $app 'backend') -Recurse -File | Where-Object { $_.Extension -ne '.pyc' } | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | Select-Object -ExpandProperty Hash)
    if (($before -join '') -ne ($after -join '')) { throw 'Business source changed during recipient procedure.' }
    [ordered]@{ status='RECIPIENT_RELINK_AND_FROZEN_SMOKE_PASS';
        modified_wheel_sha256=(Get-FileHash -LiteralPath $wheel[0].FullName -Algorithm SHA256).Hash;
        modified_sidecar_sha256=(Get-FileHash -LiteralPath $env:CAFE_FIN_TEST_SIDECAR -Algorithm SHA256).Hash;
        compiler=$env:VCToolsVersion; sdk=$WindowsSdkVersion; business_source_unchanged=$true;
        legal_clearance=$false; installed_gui='NOT_RUN' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'recipient-build-receipt.json') -Encoding utf8
} finally {
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key,$savedEnvironment[$key],'Process') }
}
