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
echo   Comparacao das buscas na base indexada
echo   (densa, BM25 e hibrida; nao usa o LLM)
echo ============================================
echo.
python avaliar_recuperacao.py --comparar-buscas %*
echo.
echo Opcoes (depois do nome deste arquivo):
echo   --k 6                               fragmentos por pergunta (padrao: TOP_K do config.py)
echo   --arquivo avaliacao\outro.csv       outro conjunto de perguntas
echo Para comparar as segmentacoes (cerca de 16 min):
echo   python avaliar_recuperacao.py --comparar
echo.
pause
