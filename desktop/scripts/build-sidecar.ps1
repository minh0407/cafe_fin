[CmdletBinding()]
param(
    [string]$Python = '',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$foundationRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$desktopRoot = Join-Path $foundationRoot 'desktop'
if (-not $Python) { $Python = Join-Path $foundationRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Python build environment is missing. Run the locked uv sync first; this is a developer command.'
}
$entrypoint = Join-Path $foundationRoot 'backend\cafe_fin\__main__.py'
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw 'Backend entrypoint is not implemented yet. A placeholder sidecar will not be built.'
}

& $Python -c "import platform, sqlite3, sys; import PyInstaller; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'; assert platform.machine().upper() in ('AMD64','X86_64'), 'Windows x64 required'; assert sqlite3.sqlite_version_info >= (3,51,3) and sqlite3.sqlite_version_info != (3,52,0), 'SQLite WAL-reset fix required'; assert PyInstaller.__version__ == '6.22.3', 'Use the locked PyInstaller version'; print('Build runtime:', sys.version.split()[0], 'SQLite', sqlite3.sqlite_version, 'PyInstaller', PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Sidecar build-runtime verification failed.' }

# All generated artifacts stay inside this verified worktree. The standard
# Tauri notices/* resource pattern distributes this human-readable file.
$noticesRoot = Join-Path $desktopRoot 'notices'
$binaryRoot = Join-Path $desktopRoot 'binaries'
$workRoot = Join-Path $foundationRoot 'build\sidecar'
New-Item -ItemType Directory -Force -Path $noticesRoot,$binaryRoot,$workRoot | Out-Null
$env:CAFE_FIN_BUILD_ROOT = $foundationRoot
$noticeBuilder = @'
import importlib.metadata as metadata
import hashlib
import io
import json
import os
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from packaging.requirements import Requirement
from lxml import etree

root = Path(os.environ['CAFE_FIN_BUILD_ROOT'])
visited, sections = set(), ['Cafe Fin Windows sidecar third-party notices\nGenerated from the locked build environment.\n']
def visit(name):
    dist = metadata.distribution(name)
    normalized = dist.metadata['Name'].lower().replace('_', '-')
    if normalized in visited:
        return
    visited.add(normalized)
    sections.append('\n' + '=' * 72 + '\n' + dist.metadata['Name'] + ' ' + dist.version + '\n')
    sections.append('License: ' + (dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See notices below') + '\n')
    for file in dist.files or ():
        lower = str(file).lower()
        if '.dist-info/' in lower and any(term in lower for term in ('license', 'notice', 'copying', 'copyright')):
            sections.append('\n--- ' + str(file) + ' ---\n' + dist.locate_file(file).read_text(encoding='utf-8', errors='replace') + '\n')
    for specifier in dist.requires or ():
        requirement = Requirement(specifier)
        if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
            visit(requirement.name)

visit('cafe-fin')
# The frozen binary includes the PyInstaller bootloader under its documented
# distribution exception; the builder itself is not a runtime dependency.
visit('pyinstaller')
for file in sorted((root / 'backend/cafe_fin/core/assets').rglob('*')):
    if file.is_file() and file.suffix.lower() not in ('.ttf', '.otf'):
        sections.append('\n--- ' + file.relative_to(root).as_posix() + ' ---\n' + file.read_text(encoding='utf-8', errors='replace') + '\n')
python_license = Path(__import__('sys').base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    sections.append('\n--- Python runtime LICENSE.txt ---\n' + python_license.read_text(encoding='utf-8', errors='replace'))

# Native license texts are pinned independently of the package's main license.
# The build runtime is the PBS 20261026 Windows x64 release. A runtime upgrade
# must update this inventory intentionally rather than retain stale notices.
assert sys.version_info[:3] == (3, 12, 16), 'Native notices currently pin Python 3.12.16'
assert (Path(sys.base_prefix) / 'BUILD').read_text().strip() == '20261026', 'Native notices pin PBS build 20261026'
assert ssl.OPENSSL_VERSION.startswith('OpenSSL 3.5.9 '), 'Update OpenSSL native notices'
assert etree.LIBXML_COMPILED_VERSION == (2,11,9) and etree.LIBXSLT_COMPILED_VERSION == (1,1,45), 'Update lxml native notices'
pbs = 'https://raw.githubusercontent.com/astral-sh/python-build-standalone/20261026/'
sources = [
    ('bzip2 1.0.8',pbs+'LICENSE.bzip2.txt','1f38bbc7caacafd65169276d759c0d88c991b753b643ce35d0e45ea1971dd441'),
    ('libffi 3.8.0',pbs+'LICENSE.libffi.txt','deaf3a42effb551a5b140fa9afefed183a27f1341c6d1bf430d106a5e6931fc0'),
    ('OpenSSL 3.5.9',pbs+'LICENSE.openssl-3.txt','7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a'),
    ('SQLite 3.53.1',pbs+'LICENSE.sqlite.txt','38bef3d28b24f145ea293bd3b6eb4b20396982abc8303128fb493986ea5bc719'),
    ('liblzma 5.8.4',pbs+'LICENSE.liblzma.txt','9a4062de0a2c388a98cf35a35d348b62fa97c838a71c3c28ee1a2d7d0a565b02'),
    ('zlib 1.3.2',pbs+'LICENSE.zlib.txt','818922b2620f12801a12bf78e399644a30990e66824abd8ca8ec24d451d6f92c'),
    ('zlib-ng 2.2.4 Windows build dependency',pbs+'LICENSE.zlib-ng.txt','6c9f0d975b41afaa34d22f55bb8986ce69e5cb7ad327cb2b28820cd425edf5ee'),
    ('libxml2 2.11.9','https://raw.githubusercontent.com/GNOME/libxml2/v2.11.9/Copyright','c5c63674f8a83c4d2e385d96d1c670a03cb871ba2927755467017317878574bd'),
    ('libxslt/libexslt 1.1.45','https://raw.githubusercontent.com/GNOME/libxslt/v1.1.45/Copyright','7e48e290b6bfccc2ec1b297023a1d77f2fd87417f71fbb9f50aabef40a851819'),
    ('Microsoft Visual C++ Runtime 2015-2022, DLL version 14.44.35211.0','https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx','f1e3d56ceb2ad68aae0711b910375009e651ac5530fa0760f0dea6e81e54fae1'),
]
cache = root / 'build/native-notices'
cache.mkdir(parents=True, exist_ok=True)
for component, url, expected in sources:
    cached = cache / expected
    if not cached.is_file():
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read(2*1024*1024+1)
        assert len(payload) <= 2*1024*1024, 'Native license response exceeds limit'
        assert hashlib.sha256(payload).hexdigest() == expected, 'Native license source hash changed: '+component
        cached.write_bytes(payload)
    payload = cached.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected, 'Native license cache corrupted: '+component
    if url.endswith('.docx'):
        with zipfile.ZipFile(io.BytesIO(payload)) as document:
            xml = ET.fromstring(document.read('word/document.xml'))
        text = '\n'.join(''.join(p.itertext()) for p in xml.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    else:
        text = payload.decode('utf-8')
    sections.append('\n--- '+component+' ---\nSource: '+url+'\nSHA256: '+expected+'\n'+text+'\n')
sections.append('\nNative version provenance: '+pbs+'pythonbuild/downloads.json\n')
sections.append('Microsoft redistribution list: https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution\n')
sections.append('Windows 11 uses its OS UCRT; UCRT/API-set DLLs are not bundled: https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment\n')
sections.append('OPEN DISTRIBUTION GATE: lxml wheel enables iconv; exact static iconv build version/source/relink compliance has not yet been established. Do not describe this notice file as release clearance.\n')
destination = root / 'desktop/notices/backend.txt'
destination.write_text(''.join(sections), encoding='utf-8')
(root / 'desktop/notices/native-license-sources.json').write_text(json.dumps([{'component':n,'url':u,'sha256':h} for n,u,h in sources],indent=2),encoding='utf-8')
print('Generated runtime notices for', len(visited), 'distributions')
'@
try {
    $noticeBuilder | & $Python -
    if ($LASTEXITCODE -ne 0) { throw 'Sidecar notices generation failed.' }
    if (-not $SkipBuild) {
        Push-Location -LiteralPath $foundationRoot
        try {
            & $Python -m PyInstaller --noconfirm --distpath $binaryRoot --workpath $workRoot (Join-Path $desktopRoot 'sidecar.spec')
            if ($LASTEXITCODE -ne 0) { throw 'PyInstaller sidecar build failed.' }
        } finally {
            Pop-Location
        }
        $sidecar = Join-Path $binaryRoot 'cafe-fin-sidecar-x86_64-pc-windows-msvc.exe'
        if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) { throw 'Expected Windows sidecar executable is missing.' }
        $inventoryBuilder = @'
import hashlib, json, os
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
root=Path(os.environ['CAFE_FIN_BUILD_ROOT'])
exe=root/'desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe'
archive=CArchiveReader(str(exe))
assert not any('darkgarden' in name.lower() for name in archive.toc), 'Unneeded GPL font asset found'
assert not any(name.lower()=='ucrtbase.dll' or name.lower().startswith(('api-ms-win-','ext-ms-win-')) for name in archive.toc), 'Host OS CRT should not be redistributed'
assert any(name.replace(chr(92),'/')=='docx/templates/default.docx' for name in archive.toc), 'DOCX template missing'
inventory={'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'exe_bytes':exe.stat().st_size,'native_files':[{'key':name,'sha256':hashlib.sha256(archive.extract(name)).hexdigest()} for name in sorted(archive.toc) if name.lower().endswith(('.dll','.pyd'))]}
(root/'desktop/notices/sidecar-native-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
print('Packaged native-file inventory:',len(inventory['native_files']),'files')
'@
        $inventoryBuilder | & $Python -
        if ($LASTEXITCODE -ne 0) { throw 'Packaged sidecar inventory verification failed.' }
        Get-FileHash -LiteralPath $sidecar -Algorithm SHA256
        Write-Output 'Sidecar build complete. Native/clean-Windows smoke tests remain required.'
    }
} finally {
    Remove-Item Env:\CAFE_FIN_BUILD_ROOT -ErrorAction SilentlyContinue
}
