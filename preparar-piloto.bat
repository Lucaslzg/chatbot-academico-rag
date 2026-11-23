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
echo   Estudo piloto, passo 1: sorteio das respostas
echo   Grava o caderno de leitura e a planilha para as suas notas
echo   na pasta piloto da rodada.
echo ================================================================
echo.
python piloto.py preparar %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --rodada avaliacao\rodadas\NOME   outra rodada
echo   --refazer                         sorteia de novo e guarda o sorteio anterior
echo Depois de preencher a planilha, rode avaliar-piloto.bat.
echo.
pause
