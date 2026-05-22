@echo off
chcp 65001 >nul
echo 正在打包...

pip install pyinstaller >nul 2>&1

pyinstaller --noconfirm --onefile --windowed ^
  --icon=icon.ico ^
  --add-data "icon.png;." ^
  --add-data "icon.ico;." ^
  --name "倒计时" ^
  main.py

echo.
if exist "dist\倒计时.exe" (
    echo 打包成功: dist\倒计时.exe
) else (
    echo 打包失败，请检查错误信息
)
pause
