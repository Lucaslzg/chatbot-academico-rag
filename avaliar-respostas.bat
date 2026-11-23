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
echo   Tabela de confiabilidade da rodada mais recente
echo   (outra rodada:  avaliar-respostas.bat --rodada avaliacao\rodadas\NOME)
echo ============================================
echo.
python avaliar_respostas.py %*
echo.
pause
