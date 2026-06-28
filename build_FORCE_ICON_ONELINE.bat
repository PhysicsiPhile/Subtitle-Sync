@echo off
setlocal
cd /d "%~dp0"

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

if not exist ".buildenv\Scripts\python.exe" py -m venv .buildenv
call ".buildenv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install pyinstaller tkinterdnd2

pyinstaller --noconfirm --clean --onefile --windowed --name "SRT-Sync" --icon "%CD%\srtsync_logo.ico" --add-data "srtsync_logo.ico;." --add-data "srtsync_logo.png;." "gui.py"

if errorlevel 1 (
  echo.
  echo Build failed. Read the error above.
  pause
  exit /b 1
)

echo.
echo Build complete:
echo dist\SRT-Sync.exe
pause
