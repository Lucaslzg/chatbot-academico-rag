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
echo   Indexando os PDFs de data\documentos
echo   (so o que mudou; para refazer tudo use:
echo    python ingestao.py --completo)
echo ============================================
echo.
python ingestao.py %*
echo.
pause
