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
echo   Conferencia do arquivo de perguntas
echo   (sem nada depois: o ARQUIVO_PERGUNTAS do config.py)
echo ============================================
echo.
python perguntas.py %*
echo.
echo Para conferir outro arquivo:  validar-perguntas.bat avaliacao\perguntas_reais.csv
echo (ou arraste o arquivo para cima deste .bat)
echo.
pause
