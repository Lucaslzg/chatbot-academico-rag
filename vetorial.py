"""Acesso ao modelo de embeddings e à base vetorial (ChromaDB).

Duas responsabilidades, ambas executadas só na máquina local (RNF01):

1. ModeloEmbeddings: carrega o modelo sentence-transformers a partir do cache
   local, conta tokens com o tokenizador do próprio modelo (para a
   segmentação respeitar a janela dele) e gera vetores normalizados.
2. Base vetorial: abre o ChromaDB persistente em data/chroma_db com a
   telemetria desligada e cria a coleção com similaridade de cosseno
   (Seção 3.6 da monografia).

Os vetores são calculados aqui e entregues prontos ao ChromaDB (em vez de
deixar o ChromaDB chamar o modelo). Assim o mesmo código serve a modelos que
exigem prefixos diferentes para pergunta e documento (e5) e a contagem de
tokens usa exatamente o texto que é vetorizado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

# Telemetria das bibliotecas desligada antes de importá-las (RNF01: nada de
# envio de dados de uso a terceiros).
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

import config  # noqa: E402
import processamento  # noqa: E402

try:  # ChromaDB 1.x
    from chromadb.errors import NotFoundError
except ImportError:  # versões antigas lançavam ValueError
    NotFoundError = ValueError

# Coleção criada pela versão anterior do protótipo (antes desta revisão).
COLECAO_LEGADA = "documentos_institucionais"


class ErroEmbeddings(RuntimeError):
    """Falha ao carregar ou usar o modelo de embeddings."""


# ---------------------------------------------------------------------------
# Modelo de embeddings
# ---------------------------------------------------------------------------
class ModeloEmbeddings:
    """Envolve o SentenceTransformer com carregamento tardio e contagem de tokens."""

    def __init__(self, nome: str | None = None, max_tokens: int | None = None,
                 dispositivo: str | None = None) -> None:
        # valores lidos do config.py no momento da criação (não da importação)
        self.nome = nome or config.EMBEDDING_MODEL
        self.max_tokens = max_tokens if max_tokens is not None else config.EMBEDDING_MAX_TOKENS
        self.dispositivo = dispositivo or config.EMBEDDING_DISPOSITIVO
        self.prefixo_consulta, self.prefixo_documento = config.PREFIXOS_EMBEDDINGS.get(self.nome, ("", ""))
        self._modelo = None

    @property
    def modelo(self):
        if self._modelo is None:
            self._modelo = self._carregar()
        return self._modelo

    @property
    def carregado(self) -> bool:
        return self._modelo is not None

    def _carregar(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as erro:
            raise ErroEmbeddings("A biblioteca sentence-transformers não está instalada. "
                                 "Rode: pip install -r requirements.txt") from erro
        try:
            # Primeiro tenta o cache local: não faz nenhum acesso à internet.
            modelo = SentenceTransformer(self.nome, device=self.dispositivo, local_files_only=True)
        except Exception:
            # Não está no cache: baixa do HuggingFace uma única vez.
            print(f"Baixando o modelo de embeddings '{self.nome}' (só na primeira vez)...")
            try:
                modelo = SentenceTransformer(self.nome, device=self.dispositivo)
            except Exception as erro:
                raise ErroEmbeddings(
                    f"Não foi possível carregar o modelo de embeddings '{self.nome}'. "
                    f"Verifique a conexão na primeira execução. Detalhe: {erro}") from erro
        if self.max_tokens:
            modelo.max_seq_length = int(self.max_tokens)
        return modelo

    # --- janela de leitura do modelo -------------------------------------
    @property
    def janela_tokens(self) -> int:
        """Máximo de tokens que o modelo lê por texto (128 no mpnet multilíngue)."""
        return int(self.modelo.max_seq_length)

    @property
    def limite_conteudo(self) -> int:
        """Tokens disponíveis para o texto, descontados os tokens especiais (<s>, </s>)."""
        return self.janela_tokens - self.modelo.tokenizer.num_special_tokens_to_add(pair=False)

    def contar_tokens(self, texto: str) -> int:
        return len(self.modelo.tokenizer(texto, add_special_tokens=False, verbose=False)["input_ids"])

    @property
    def dimensao(self) -> int:
        return int(self.modelo.get_embedding_dimension())

    # --- vetorização --------------------------------------------------------
    def codificar_documentos(self, textos: list[str], mostrar_progresso: bool = False) -> list[list[float]]:
        """Vetoriza fragmentos. O prefixo de documento, quando o modelo exige,
        já vem no texto (a segmentação o inclui para contar os tokens certos)."""
        vetores = self.modelo.encode(list(textos), batch_size=32, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=mostrar_progresso)
        return vetores.tolist()

    def codificar_consultas(self, perguntas: list[str]) -> list[list[float]]:
        vetores = self.modelo.encode([self.prefixo_consulta + p for p in perguntas], batch_size=32,
                                     normalize_embeddings=True, convert_to_numpy=True,
                                     show_progress_bar=False)
        return vetores.tolist()

    def codificar_consulta(self, pergunta: str) -> list[float]:
        return self.codificar_consultas([pergunta])[0]


# ---------------------------------------------------------------------------
# Parâmetros que definem a base (a "assinatura" do índice)
# ---------------------------------------------------------------------------
def parametros_indice(modelo: ModeloEmbeddings) -> dict:
    """Parâmetros que, se mudarem, exigem reconstruir a base.

    O tamanho efetivo do fragmento é o menor entre o alvo (CHUNK_MAX_TOKENS) e
    o que o modelo consegue ler: no mpnet, 126 tokens de conteúdo.
    """
    limite = min(config.CHUNK_MAX_TOKENS, modelo.limite_conteudo)
    return {
        "modelo_embeddings": modelo.nome,
        "janela_modelo": modelo.janela_tokens,
        "limite_fragmento_tokens": limite,
        "sobreposicao_tokens": round(config.CHUNK_SOBREPOSICAO * limite),
        "contexto_no_embedding": bool(config.CONTEXTO_NO_EMBEDDING),
        "descartar_texto_riscado": bool(config.DESCARTAR_TEXTO_RISCADO),
        "descartar_redacao_alterada": bool(config.DESCARTAR_REDACAO_ALTERADA),
        "extrair_tabelas": bool(config.EXTRAIR_TABELAS),
        "prefixo_documento": modelo.prefixo_documento,
        "versao_processamento": processamento.VERSAO_PROCESSAMENTO,
    }


def opcoes_processamento(parametros: dict) -> processamento.OpcoesProcessamento:
    """Converte os parâmetros do índice nas opções do módulo de processamento."""
    return processamento.OpcoesProcessamento(
        limite_tokens=parametros["limite_fragmento_tokens"],
        sobreposicao_tokens=parametros["sobreposicao_tokens"],
        incluir_contexto=parametros["contexto_no_embedding"],
        descartar_riscado=parametros["descartar_texto_riscado"],
        descartar_alteradas=parametros["descartar_redacao_alterada"],
        extrair_tabelas=parametros["extrair_tabelas"],
        prefixo=parametros["prefixo_documento"])


def assinatura(parametros: dict) -> str:
    return hashlib.sha1(json.dumps(parametros, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------
def abrir_cliente(caminho: Path | None = None):
    """Cliente persistente, com a telemetria do ChromaDB desligada (RNF01)."""
    caminho = Path(caminho or config.CHROMA_DIR)
    caminho.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(caminho), settings=Settings(anonymized_telemetry=False))


def nome_colecao(modelo_nome: str | None = None) -> str:
    """Uma coleção por modelo: vetores de modelos diferentes não se comparam.

    Ex.: "documentos_paraphrase-multilingual-mpnet-base-v2".
    """
    modelo_nome = modelo_nome or config.EMBEDDING_MODEL
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", modelo_nome.replace("\\", "/").rstrip("/").split("/")[-1]).strip("-_")
    nome = f"{config.COLLECTION_NAME}_{base}"
    if len(nome) > 60:
        nome = nome[:51] + "_" + hashlib.sha1(modelo_nome.encode()).hexdigest()[:8]
    return nome


def obter_colecao(cliente, nome: str):
    """Devolve a coleção ou None se ela não existir.

    `embedding_function=None`: os vetores vêm sempre prontos deste módulo, então o
    ChromaDB não precisa (nem deve) carregar modelo nenhum por conta própria.
    """
    try:
        return cliente.get_collection(nome, embedding_function=None)
    except (NotFoundError, ValueError):
        return None


def criar_colecao(cliente, nome: str, metadados: dict):
    return cliente.create_collection(
        nome, embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},   # similaridade de cosseno
        metadata=metadados)


def remover_colecao(cliente, nome: str) -> bool:
    try:
        cliente.delete_collection(nome)
        return True
    except (NotFoundError, ValueError):
        return False


def id_fragmento(fonte: str, indice: int) -> str:
    """Identificador estável: nome do arquivo + posição do fragmento no documento.

    Permite buscar os vizinhos de um fragmento (índice - 1 e + 1) na consulta.
    """
    return f"{fonte}#{indice:05d}"


# ===========================================================================
# Títulos dos documentos (usados na busca e no relatório de indexação)
# ===========================================================================
def carregar_titulos(caminho=None) -> dict[str, str]:
    """Títulos de exibição por nome de arquivo (config.ARQUIVO_TITULOS).

    Arquivo ausente ou ilegível: dicionário vazio, e o chat usa o título
    extraído do próprio PDF (nunca impede o atendimento).
    """
    caminho = Path(config.ARQUIVO_TITULOS if caminho is None else caminho)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as erro:
        print(f"Aviso: não consegui ler {caminho} ({erro}); o chat vai usar os títulos extraídos dos PDFs.")
        return {}
    titulos = dados.get("titulos", {}) if isinstance(dados, dict) else {}
    return {str(k): str(v).strip() for k, v in titulos.items() if str(v).strip()}
