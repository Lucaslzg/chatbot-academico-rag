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
echo   Instalação do RAGAS, usado só na avaliação
echo   Precisa de internet e é feita uma única vez.
echo   Os pacotes do chatbot continuam nas versões atuais.
echo ================================================================
echo.
python instalar_avaliacao.py
echo.
pause
