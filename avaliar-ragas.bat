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
echo   Notas dos LLMs avaliadores (RAGAS) na rodada mais recente
echo   Os avaliadores rodam na placa de vídeo, com os prompts em português.
echo   Pode levar algumas horas.
echo ================================================================
echo.
python avaliar_ragas.py %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --limite 3                        só as 3 primeiras perguntas, para medir o tempo
echo   --rodada avaliacao\rodadas\NOME   outra rodada
echo   --modelos phi4-mini               só as respostas dos modelos indicados
echo   --juiz ministral-3:8b             só o avaliador indicado
echo   --ingles                          prompts originais do RAGAS, em inglês
echo Depois, atualize a tabela com avaliar-respostas.bat.
echo.
pause
