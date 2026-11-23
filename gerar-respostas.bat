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
echo   Rodada de avaliação: respostas dos modelos
echo   Cada modelo responde às perguntas com os mesmos trechos, só no processador.
echo   O resultado fica numa pasta nova em avaliacao\rodadas.
echo ================================================================
echo.
python gerar_respostas.py %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --limite 3                      só as 3 primeiras perguntas, para medir o tempo
echo   --continuar                     continua a rodada mais recente de onde parou
echo   --modelos phi4-mini             só os modelos indicados
echo   --arquivo avaliacao\outro.csv   outro conjunto de perguntas
echo Depois, gere a tabela com avaliar-respostas.bat.
echo.
pause
