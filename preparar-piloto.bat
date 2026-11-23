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
echo   Piloto dos juizes: sorteio das respostas
echo   (grava o caderno e a planilha na pasta piloto da rodada)
echo ============================================
echo.
python piloto.py preparar %*
echo.
echo Opcoes (depois do nome deste arquivo):
echo   --rodada avaliacao\rodadas\NOME             outra rodada
echo   --refazer                                   sorteia de novo, guardando o piloto atual
echo Depois de preencher a planilha: avaliar-piloto.bat
echo.
pause
