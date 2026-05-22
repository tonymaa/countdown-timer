@echo off
chcp 65001 >nul
echo Building...

pip install pyinstaller >nul 2>&1

pyinstaller --noconfirm --onefile --windowed --icon=icon.ico --add-data "icon.png;." --add-data "icon.ico;." --name "CountdownTimer" main.py

echo.
if exist "dist\CountdownTimer.exe" (
    echo Build OK: dist\CountdownTimer.exe
) else (
    echo Build failed
)
pause
