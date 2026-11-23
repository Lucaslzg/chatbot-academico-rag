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
echo   Avaliação da busca
echo   Compara as buscas densa, lexical (BM25) e híbrida.
echo   Não usa os modelos de linguagem.
echo ================================================================
echo.
python avaliar_recuperacao.py --comparar-buscas %*
echo.
echo Opções, escritas depois do nome do arquivo no terminal:
echo   --k 6                           fragmentos por pergunta (padrão: TOP_K do config.py)
echo   --arquivo avaliacao\outro.csv   outro conjunto de perguntas
echo Comparação das segmentações, mais demorada:  python avaliar_recuperacao.py --comparar
echo.
pause
