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
echo   Rodada de avaliacao: respostas de cada modelo
echo   (os mesmos trechos para todos; so no processador)
echo ============================================
echo.
python gerar_respostas.py %*
echo.
echo Opcoes (depois do nome deste arquivo):
echo   --limite 3                        so as 3 primeiras perguntas (para medir o tempo)
echo   --continuar                       continua a rodada mais recente, de onde parou
echo   --modelos llama3.2:3b             so os modelos indicados
echo   --arquivo avaliacao\outro.csv     outro conjunto de perguntas
echo.
pause
