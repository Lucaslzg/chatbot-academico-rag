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
echo   Piloto dos juizes: suas notas x as dos juizes
echo   (outra rodada:  avaliar-piloto.bat --rodada avaliacao\rodadas\NOME)
echo ============================================
echo.
python piloto.py comparar %*
echo.
pause
