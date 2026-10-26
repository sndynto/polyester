@echo off
title Polyester Testnet Trading Client
cd /d "%~dp0"

if not exist ".env" (
    echo [INFO] File .env belum ditemukan. Membuat dari .env.example...
    copy .env.example .env
    echo [PENTING] Silakan buka file .env dengan Notepad dan masukkan API Key Anda!
    notepad .env
    pause
    exit /b
)

if not exist "venv\Scripts\python.exe" (
    echo [INFO] Membuat virtual environment Python...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo [INFO] Menjalankan Polyester Testnet Trading Client...
python bot.py
pause
