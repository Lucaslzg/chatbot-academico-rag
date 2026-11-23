@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Ambiente virtual .venv nao encontrado nesta pasta.
    echo Crie com:  python -m venv .venv   e depois:  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo ============================================
echo   Instalacao do RAGAS (so para a avaliacao)
echo   Uma vez so; precisa de internet.
echo   Os pacotes do chatbot ficam nas versoes de agora.
echo ============================================
echo.
python instalar_avaliacao.py
echo.
pause
