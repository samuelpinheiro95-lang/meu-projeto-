@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    echo Primeira execucao: instalando dependencias, aguarde...
    python -m venv .venv || (echo Instale o Python 3.10+ em https://python.org e marque "Add to PATH". & pause & exit /b 1)
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)
if not exist .env copy .env.example .env >nul
.venv\Scripts\python iniciar.py
pause
