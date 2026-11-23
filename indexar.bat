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
echo   Indexação dos documentos
echo   Lê os PDFs de data\documentos e atualiza a base de busca.
echo   Só os arquivos novos ou alterados são processados.
echo ================================================================
echo.
python ingestao.py %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --completo   refaz a base inteira
echo.
pause
