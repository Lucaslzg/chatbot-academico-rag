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
echo   Conferencia dos modelos de linguagem
echo   (instalados? rodam so no processador? e o juiz,
echo   na placa de video? raciocinio desligado?)
echo ============================================
echo.
python verificar_modelos.py %*
echo.
pause
