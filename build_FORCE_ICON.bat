@echo off
setlocal
cd /d "%~dp0"

echo Cleaning old output...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

if not exist ".buildenv\Scripts\python.exe" (
    py -m venv .buildenv
    if errorlevel 1 goto fail
)

call ".buildenv\Scripts\activate.bat"
if errorlevel 1 goto fail

python -m pip install --upgrade pip
if errorlevel 1 goto fail

pip install pyinstaller tkinterdnd2
if errorlevel 1 goto fail

pyinstaller --noconfirm --clean "SRT-Sync.spec"
if errorlevel 1 goto fail

echo.
echo Build complete:
echo dist\SRT-Sync.exe
pause
exit /b 0

:fail
echo.
echo Build failed. Read the error above.
pause
exit /b 1
