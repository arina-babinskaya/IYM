@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    echo Создаю виртуальное окружение...
    python -m venv .venv || (echo Не найден Python. Установи его с python.org и поставь галочку "Add python.exe to PATH". & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo Устанавливаю зависимости, первый раз это занимает пару минут...
python -m pip install -q -r requirements.txt
python run_local.py %*
pause
