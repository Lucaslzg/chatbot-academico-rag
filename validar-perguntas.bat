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
echo   Conferência do arquivo de perguntas
echo   Sem indicar um arquivo, confere o definido no config.py.
echo ================================================================
echo.
python perguntas.py %*
echo.
echo Para conferir outro arquivo, arraste-o sobre este .bat ou use:
echo   validar-perguntas.bat avaliacao\perguntas_reais.csv
echo.
pause
