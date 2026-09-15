# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for AksaraSight Local Portable Windows Distribution.

Builds a unified, zero-installer portable bundle containing:
1. AksaraSight.exe: Desktop Studio GUI (windowed mode, console=False).
2. ocr-llm.exe: Command Line Interface (console mode, console=True).
Both executables reside in dist/AksaraSight/ and share dist/AksaraSight/_internal/.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all non-Python data files and native C-extensions
all_datas = [
    ('gui/assets/icon.ico', 'gui/assets'),
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
    'core.formatter',
    'core.models',
    'core.constants',
    'gui.theme',
    'gui.app',
    'gui.settings_window',
]

# Explicitly collect packages with native DLLs, themes, fonts, or Tcl scripts
for pkg in ['customtkinter', 'tkinterdnd2', 'pypdfium2', 'pypdfium2_raw']:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    all_datas.extend(pkg_datas)
    all_binaries.extend(pkg_binaries)
    all_hiddenimports.extend(pkg_hiddenimports)

# ------------------------------------------------------------------------------
# 1. Target: Desktop Studio GUI (AksaraSight.exe, windowed, console=False)
# ------------------------------------------------------------------------------
a_gui = Analysis(
    ['gui/__main__.py'],
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

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='AksaraSight',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='gui/assets/icon.ico',
)

# ------------------------------------------------------------------------------
# 2. Target: Command Line Interface (ocr-llm.exe, console=True)
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
    name='ocr-llm',
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
    icon='gui/assets/icon.ico',
)

# ------------------------------------------------------------------------------
# 3. Unified Distribution Collector (dist/AksaraSight/)
# ------------------------------------------------------------------------------
coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AksaraSight',
)
