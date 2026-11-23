"""Instala as dependências da avaliação com o RAGAS sem estragar as do chatbot.

    python instalar_avaliacao.py        (ou dois cliques em instalar-avaliacao.bat)

Por que não basta "pip install -r requirements-avaliacao.txt": ao instalar um
pacote novo, o pip só olha o que os pacotes novos exigem, não o que os já
instalados exigem. Em 03/11/2026, num ambiente igual ao do chatbot
(transformers 5.12.1, que exige huggingface-hub abaixo de 2.0), o RAGAS puxou o
datasets 5.1.0, que pede huggingface-hub 1.31 ou mais; o pip instalou a 2.4.0,
avisou do conflito e o "import transformers" passou a falhar, o que para a
indexação e o chat (o sentence-transformers usa o transformers).

Por isso este programa:
1. grava a lista dos pacotes instalados agora em pacotes_antes_da_avaliacao.txt
   (só na primeira vez), para voltar atrás se for preciso;
2. instala o requirements-avaliacao.txt junto com as versões já instaladas dos
   pacotes do chatbot, fixadas; assim o pip leva em conta o que elas exigem e
   escolhe versões que sirvam aos dois (no exemplo, o huggingface-hub 1.33.0);
3. confere o ambiente (pip check) e se o chatbot e o RAGAS importam.

Se o pip não achar versões que sirvam aos dois, ele para antes de instalar e
nada muda.
"""

import importlib.metadata
import subprocess
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
REQUISITOS = PASTA / "requirements-avaliacao.txt"
ARQUIVO_ANTES = PASTA / "pacotes_antes_da_avaliacao.txt"

# Pacotes do chatbot que ficam na versão instalada. Os que eles exigem
# (huggingface-hub, numpy, fsspec...) ficam livres, para o pip achar uma versão
# que sirva também ao RAGAS.
FIXAR = ("chromadb", "sentence-transformers", "transformers", "tokenizers", "torch", "pymupdf", "ollama")

# O que precisa importar depois da instalação: o chatbot e o RAGAS.
MODULOS = ("chromadb", "fitz", "ollama", "transformers", "sentence_transformers", "ragas",
           "ragas.metrics.collections")

_CONFERIR_IMPORTACOES = r"""
import importlib, os, sys
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
falhas = 0
for nome in sys.argv[1:]:
    try:
        importlib.import_module(nome)
        print("  ok    " + nome)
    except Exception as erro:
        falhas += 1
        texto = str(erro).strip().splitlines()
        print("  ERRO  " + nome + ": " + (texto[0] if texto else type(erro).__name__))
sys.exit(1 if falhas else 0)
"""


def versoes_instaladas(nomes=FIXAR, versao=importlib.metadata.version) -> dict:
    """Versão instalada de cada pacote da lista; os que não estão instalados ficam de fora."""
    instaladas = {}
    for nome in nomes:
        try:
            instaladas[nome] = versao(nome)
        except importlib.metadata.PackageNotFoundError:
            continue
    return instaladas


def comando_instalacao(instaladas: dict, requisitos: Path = REQUISITOS, python: str = sys.executable) -> list:
    """O comando do pip: os requisitos da avaliação e os pacotes do chatbot fixados.

    Tudo vai como argumento separado (sem arquivo intermediário), porque o
    caminho da pasta tem espaços e barras invertidas no Windows.
    """
    return [python, "-m", "pip", "install", "-r", str(requisitos)] + [
        f"{nome}=={versao}" for nome, versao in instaladas.items()]


def guardar_lista_antes(destino: Path = ARQUIVO_ANTES, python: str = sys.executable, executar=None) -> bool:
    """Grava o "pip freeze" de agora, só se o arquivo ainda não existe. Devolve se gravou."""
    if destino.exists():
        return False
    resultado = (executar or subprocess.run)([python, "-m", "pip", "freeze"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise RuntimeError("o pip freeze falhou: " + (resultado.stderr or "").strip())
    destino.write_text(resultado.stdout, encoding="utf-8")
    return True


def conflitos(python: str = sys.executable, executar=None) -> list:
    """Linhas do "pip check" que apontam conflito (lista vazia: ambiente coerente)."""
    resultado = (executar or subprocess.run)([python, "-m", "pip", "check"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if resultado.returncode == 0:
        return []
    linhas = (resultado.stdout + "\n" + resultado.stderr).splitlines()
    return [linha.strip() for linha in linhas if linha.strip()]


def conferir_importacoes(modulos=MODULOS, python: str = sys.executable, executar=None) -> bool:
    """Importa cada módulo num Python novo e mostra o resultado. Devolve se todos importaram."""
    resultado = (executar or subprocess.run)([python, "-c", _CONFERIR_IMPORTACOES, *modulos])
    return resultado.returncode == 0


def main() -> int:
    if not REQUISITOS.exists():
        print(f"Não encontrei {REQUISITOS.name} na pasta {PASTA}.")
        return 1
    if sys.prefix == sys.base_prefix:
        print("Aviso: este Python não é o do ambiente virtual (.venv). Use o instalar-avaliacao.bat,")
        print("que ativa o ambiente antes de instalar.")
        return 1

    print("1. Lista dos pacotes instalados antes da avaliação")
    try:
        if guardar_lista_antes(ARQUIVO_ANTES):
            print(f"   gravada em {ARQUIVO_ANTES.name}")
        else:
            print(f"   {ARQUIVO_ANTES.name} já existe (é a lista de antes da primeira instalação); mantida")
    except (OSError, RuntimeError) as erro:
        print(f"   não consegui gravar ({erro}); a instalação continua")

    instaladas = versoes_instaladas()
    print("\n2. Instalação, com os pacotes do chatbot nas versões de agora:")
    for nome, versao in instaladas.items():
        print(f"   {nome} {versao}")
    faltam = [nome for nome in ("chromadb", "sentence-transformers", "pymupdf", "ollama") if nome not in instaladas]
    if faltam:
        print("   Aviso: não encontrei " + ", ".join(faltam) + ". Instale antes o requirements.txt do chatbot.")
    print()
    instalacao = subprocess.run(comando_instalacao(instaladas))
    if instalacao.returncode != 0:
        print("\nA instalação não terminou (veja a mensagem do pip acima).")
        print("Se o pip disse que não há versões compatíveis (ResolutionImpossible), nada foi alterado.")
        if ARQUIVO_ANTES.exists():
            print("Se o chatbot parar de funcionar, volte os pacotes com:")
            print(f"   python -m pip install -r {ARQUIVO_ANTES.name}")
        return 1

    print("\n3. Conferência do ambiente (pip check)")
    problemas = conflitos()
    if problemas:
        print("   O pip aponta conflitos entre pacotes:")
        for linha in problemas:
            print("   " + linha)
    else:
        print("   nenhum conflito entre os pacotes instalados")

    print("\n4. O chatbot e o RAGAS importam?")
    tudo_importa = conferir_importacoes()

    print()
    if tudo_importa and not problemas:
        versao_ragas = versoes_instaladas(("ragas",)).get("ragas", "?")
        print(f"RAGAS {versao_ragas} instalado, e o chatbot continua funcionando.")
        return 0
    if tudo_importa:
        print("Tudo importa, mas há conflitos acima. Rode testar.bat antes de usar.")
        return 1
    print("Algum módulo não importa (veja acima).")
    if ARQUIVO_ANTES.exists():
        print("Para voltar os pacotes como estavam antes da primeira instalação:")
        print(f"   python -m pip install -r {ARQUIVO_ANTES.name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
