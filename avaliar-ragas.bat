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
echo   Avaliacao com o RAGAS da rodada mais recente
echo   (os juizes rodam na placa de video, com os prompts em portugues; pode levar horas)
echo ============================================
echo.
python avaliar_ragas.py %*
echo.
echo Opcoes (depois do nome deste arquivo):
echo   --limite 3                                  so as 3 primeiras perguntas (para medir o tempo do juiz)
echo   --rodada avaliacao\rodadas\NOME             outra rodada
echo   --modelos llama3.2:3b                       so os modelos indicados
echo   --ingles                                    os juizes com os prompts do RAGAS como vem, em ingles
echo Depois: avaliar-respostas.bat (a tabela final, com as medias do juiz)
echo.
pause
