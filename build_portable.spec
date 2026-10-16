# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for AksaraSight Local Portable Windows Distribution.

Builds a unified, zero-installer portable bundle containing:
1. AksaraSight.exe: Web UI Desktop Server (console mode, console=True).
2. AksaraSight-CLI.exe: Command Line Interface (console mode, console=True).
Both executables reside in dist/AksaraSight/ and share dist/AksaraSight/_internal/.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all non-Python data files and native C-extensions
all_datas = [
    ('assets/icon.ico', 'assets'),
    ('assets/icon.png', 'assets'),
    ('web/static', 'web/static'),
]
all_binaries = []
all_hiddenimports = [
    'config.settings',
    'core.engine',
    'core.pipeline',
    'core.client',
    'core.hardware',
    'core.runtime_manager',
    'core.server_manager',
    'core.job_object',
    'core.formatter',
    'core.docx_export',
    'core.models',
    'core.constants',
    'core.model_manager',
    'core.diagnostics',
    'web.app',
    'web.orchestrator',
    'web.security',
]

# Explicitly collect packages with native DLLs, themes, fonts, data templates, or web dependencies
for pkg in ['pypdfium2', 'pypdfium2_raw', 'docx', 'markdown_it', 'mdurl', 'lxml', 'fastapi', 'starlette', 'uvicorn', 'python_multipart', 'multipart', 'anyio']:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    all_datas.extend(pkg_datas)
    all_binaries.extend(pkg_binaries)
    all_hiddenimports.extend(pkg_hiddenimports)

# ------------------------------------------------------------------------------
# 1. Target: Web UI Desktop Server (AksaraSight.exe, console mode, console=True)
# ------------------------------------------------------------------------------
a_web = Analysis(
    ['web/__main__.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_web = PYZ(a_web.pure, a_web.zipped_data, cipher=block_cipher)

exe_web = EXE(
    pyz_web,
    a_web.scripts,
    [],
    exclude_binaries=True,
    name='AksaraSight',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

# ------------------------------------------------------------------------------
# 2. Target: Command Line Interface (AksaraSight-CLI.exe, console=True)
# ------------------------------------------------------------------------------
a_cli = Analysis(
    ['cli/main.py'],
    pathex=['.'],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='AksaraSight-CLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

# ------------------------------------------------------------------------------
# 3. Unified Distribution Collector (dist/AksaraSight/)
# ------------------------------------------------------------------------------
coll = COLLECT(
    exe_web,
    a_web.binaries,
    a_web.zipfiles,
    a_web.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AksaraSight',
)
