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
echo   Tabela de confiabilidade da rodada mais recente
echo   Classifica as respostas e grava a tabela na pasta da rodada.
echo ================================================================
echo.
python avaliar_respostas.py %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --rodada avaliacao\rodadas\NOME   outra rodada
echo.
pause
