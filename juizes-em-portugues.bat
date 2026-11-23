@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Ambiente virtual .venv não encontrado nesta pasta.
    echo Para criá-lo, siga a seção Instalação do README.md.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo ================================================================
echo   Estudo piloto, passo 2: LLMs avaliadores com prompts em português
echo   Avaliam só as respostas sorteadas, na placa de vídeo.
echo   Pode levar mais de uma hora.
echo ================================================================
echo.
python avaliar_ragas.py --portugues --so-piloto %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --rodada avaliacao\rodadas\NOME   outra rodada
echo   --juiz ministral-3:8b             só o avaliador indicado
echo Depois de preencher a planilha do piloto, rode avaliar-piloto.bat.
echo.
pause
