@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo   JAPW desktop build  (PyInstaller one-folder)
echo   Output: dist\JAPW\JAPW.exe
echo ========================================
echo.

if not exist "JAPW.spec" (
    echo [ERROR] JAPW.spec not found in repo root.
    pause
    exit /b 1
)

set "PYTHON_CMD=python"
if exist "venv\Scripts\python.exe" set "PYTHON_CMD=venv\Scripts\python.exe"

"%PYTHON_CMD%" -c "import sys" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] No working Python. Use venv\Scripts\python.exe or put python on PATH.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%
echo.

echo [1/3] pip install -r requirements-dev.txt
"%PYTHON_CMD%" -m pip install -r requirements-dev.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

echo.
echo [2/3] Icon: logo.jpg -^> logo.ico ^(Pillow^)
if not exist "logo.jpg" (
    echo [ERROR] logo.jpg missing at repo root.
    pause
    exit /b 1
)
"%PYTHON_CMD%" tools\make_icon.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] tools\make_icon.py failed ^(install pillow^)
    pause
    exit /b 1
)

echo.
echo [3/3] PyInstaller  JAPW.spec  (one-folder, windowed)
"%PYTHON_CMD%" -m PyInstaller --noconfirm JAPW.spec
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller failed.
    pause
    exit /b 1
)

echo.
echo Done: dist\JAPW\JAPW.exe  (ship the whole dist\JAPW folder)
echo.
pause
