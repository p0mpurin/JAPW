# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for JAPW (one-folder, Flask + pywebview).
# One-folder starts much faster than one-file: nothing is unpacked to %TEMP% on each launch.
# Run: build.bat  or  pyinstaller --noconfirm JAPW.spec

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("frontend", "frontend"),
    ],
    hiddenimports=collect_submodules("japw") + [
        "PIL",
        "pinscrape",
        "browser_cookie3",
        "flask",
        "requests",
        "webview",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "pytest", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JAPW",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed DLLs must be unpacked on every start (and trip antivirus)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="JAPW",
)
