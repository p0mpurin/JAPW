# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for JAPW (one-file, Playwright + Flask + pywebview).
# Run: build.bat  or  pyinstaller --noconfirm JAPW.spec

from PyInstaller.utils.hooks import collect_all

block_cipher = None

pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=pw_binaries,
    datas=[
        ("frontend", "frontend"),
    ] + pw_datas,
    hiddenimports=[
        "japw",
        "japw.config",
        "japw.api",
        "japw.pinterest",
        "japw.x",
        "pinscrape",
        "browser_cookie3",
        "flask",
        "requests",
        "webview",
    ] + pw_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="JAPW",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="logo.ico",
)
