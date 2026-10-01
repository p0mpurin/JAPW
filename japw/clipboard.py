"""Native Windows clipboard (images + text) via ctypes — works regardless of WebView permissions."""

from __future__ import annotations

import ctypes
import io
import sys
import time

CF_UNICODETEXT = 13
CF_DIB = 8
GMEM_MOVEABLE = 0x0002


class ClipboardUnavailable(RuntimeError):
    pass


def _win():
    if sys.platform != "win32":
        raise ClipboardUnavailable("Native clipboard is only available on Windows")
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return user32, kernel32


def _open(user32) -> None:
    # Another app may hold the clipboard for a moment.
    for _ in range(20):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ClipboardUnavailable("The clipboard is busy")


def _put(user32, kernel32, fmt: int, data: bytes) -> None:
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ClipboardUnavailable("Out of memory")
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(fmt, handle):
        raise ClipboardUnavailable("Could not set clipboard data")


def copy_image(png_bytes: bytes) -> None:
    """Put an image on the clipboard as both DIB (universal) and PNG (keeps transparency)."""
    from PIL import Image

    user32, kernel32 = _win()
    im = Image.open(io.BytesIO(png_bytes))
    bmp = io.BytesIO()
    im.convert("RGB").save(bmp, "BMP")
    dib = bmp.getvalue()[14:]  # strip the 14-byte BITMAPFILEHEADER
    png_format = user32.RegisterClipboardFormatW("PNG")
    _open(user32)
    try:
        user32.EmptyClipboard()
        _put(user32, kernel32, CF_DIB, dib)
        if png_format:
            _put(user32, kernel32, png_format, png_bytes)
    finally:
        user32.CloseClipboard()


def copy_text(text: str) -> None:
    user32, kernel32 = _win()
    data = (text + "\0").encode("utf-16-le")
    _open(user32)
    try:
        user32.EmptyClipboard()
        _put(user32, kernel32, CF_UNICODETEXT, data)
    finally:
        user32.CloseClipboard()
