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
echo   Juizes em portugues: so as respostas do piloto
echo   (os dois juizes na placa de video; cerca de 1 hora e meia para 30 respostas)
echo ============================================
echo.
python avaliar_ragas.py --portugues --so-piloto %*
echo.
echo Opcoes (depois do nome deste arquivo):
echo   --rodada avaliacao\rodadas\NOME             outra rodada
echo   --juiz ministral-3:8b                       so o juiz indicado
echo Depois de preencher a planilha do piloto: avaliar-piloto.bat (ingles e portugues lado a lado)
echo.
pause
