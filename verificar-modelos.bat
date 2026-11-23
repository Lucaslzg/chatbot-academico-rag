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
echo   Conferência dos modelos no Ollama
echo   Confere se os modelos estão instalados, onde cada um roda
echo   e se o raciocínio dos modelos que pensam está desligado.
echo ================================================================
echo.
python verificar_modelos.py %*
echo.
pause
