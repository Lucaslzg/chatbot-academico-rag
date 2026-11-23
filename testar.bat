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
echo   Testes automatizados
echo   Não precisam do Ollama nem do modelo de embeddings.
echo ================================================================
echo.
python -m unittest discover -s testes -v
echo.
pause
