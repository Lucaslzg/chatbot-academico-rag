"""Engenharia de dados da fase de indexação (Fase 3 da metodologia, Seção 5.1).

Transforma um PDF em fragmentos prontos para vetorização, nesta ordem:

    PDF -> linhas com posição e fonte (PyMuPDF, modo "dict") + tabelas
        -> limpeza: cabeçalhos/rodapés (pela posição), caracteres invisíveis,
           texto riscado (redação revogada)
        -> unidades: título, capítulo, seção, artigo, parágrafo, inciso,
           alínea, item de lista, linha de tabela, parágrafo comum ou nota
           de rodapé (que não interrompe o parágrafo da página)
        -> descarte de redações alteradas anotadas "(Alterado pela...)"
        -> frases -> fragmentos (tamanho medido em tokens do modelo de embeddings)

Tudo é decidido por sinais GENÉRICOS do PDF (posição na página, tamanho e
peso da fonte, espaçamento, recuo, marcadores de norma), e não por
características de um documento específico: o mesmo código atende
resoluções, PPCs e editais com formatos diferentes.

O módulo não conhece o banco vetorial nem carrega o modelo de embeddings:
recebe uma função que conta tokens. Assim pode ser testado isoladamente.
"""
from __future__ import annotations

import bisect
import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

# O PyMuPDF 1.27 imprime, na primeira leitura de tabelas, uma recomendação do
# pacote opcional "pymupdf_layout". Ele não é usado aqui (a ordem de leitura e
# a estrutura são decididas pelas regras deste módulo), então a mensagem é
# desligada para não confundir quem roda a indexação.
if hasattr(fitz, "no_recommend_layout"):
    fitz.no_recommend_layout()

# Mude este número sempre que a lógica de processamento mudar: ele entra na
# "assinatura" da base, e a indexação seguinte reconstrói tudo sozinha.
VERSAO_PROCESSAMENTO = "6"

ContadorTokens = Callable[[str], int]

# Marca interna colocada no lugar de trechos riscados; é removida ao montar as
# unidades, junto com a anotação "(Alterado pela...)" que costuma segui-la.
RISCO = "\x00"


class ErroExtracao(Exception):
    """PDF que não pôde ser lido (corrompido, protegido por senha etc.)."""


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------
@dataclass
class OpcoesProcessamento:
    limite_tokens: int                 # máximo de tokens do texto vetorizado
    sobreposicao_tokens: int
    incluir_contexto: bool = True      # cabeçalho de contexto no embedding
    descartar_riscado: bool = True     # texto riscado = redação revogada
    descartar_alteradas: bool = True   # anotação "(Alterado pela...)" sem risco
    extrair_tabelas: bool = True
    prefixo: str = ""                  # prefixo exigido pelo modelo (e5: "passage: ")


@dataclass
class LinhaVisual:
    """Uma linha como aparece na página, com posição e estilo."""
    texto: str                 # trechos riscados substituídos por RISCO
    pagina: int
    bloco: int
    x0: float
    y0: float
    y1: float
    tamanho: float             # corpo de letra predominante (pt)
    negrito: bool
    x1: float = 0.0
    ocr: bool = False          # texto invisível de OCR (PDF digitalizado com camada de texto)

    @property
    def altura(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def visivel(self) -> str:
        """Texto sem os trechos riscados."""
        return _normalizar_espacos(self.texto.replace(RISCO, " "))


@dataclass
class Tabela:
    pagina: int
    y0: float
    y1: float
    cabecalho: list[str]
    linhas: list[str]          # uma string por linha da tabela, já "linearizada"
    celulas: list = field(default_factory=list)   # células das linhas de dados
    n_colunas: int = 0
    titulos: list = field(default_factory=list)   # títulos/legendas acima do cabeçalho
    grupo: str = ""            # último valor da coluna de grupo (continua na página seguinte)


@dataclass
class PaginaExtraida:
    numero: int
    altura: float
    elementos: list            # LinhaVisual e Tabela, na ordem de leitura
    riscados: list[str] = field(default_factory=list)
    caracteres: int = 0
    ilegiveis: int = 0         # caracteres sem mapeamento Unicode (U+FFFD)

    @property
    def linhas(self) -> list[LinhaVisual]:
        return [e for e in self.elementos if isinstance(e, LinhaVisual)]

    @property
    def tem_texto(self) -> bool:
        return any(l.visivel for l in self.linhas) or any(isinstance(e, Tabela) for e in self.elementos)


@dataclass
class Unidade:
    """Trecho estrutural do documento: um artigo, um parágrafo, um título...

    `marcas_pagina` guarda, para cada linha original, o deslocamento em que ela
    começa no texto da unidade e a página de onde veio. Isso permite saber a
    página exata de cada frase mesmo quando a unidade atravessa páginas.
    """
    tipo: str
    texto: str
    marcas_pagina: list[tuple[int, int]]
    rotulo: str = ""               # "48" (Art. 48), "2" (§2º), "único", "IV", "a"
    tamanho_marcador: int = 0      # nº de caracteres do marcador inicial ("Parágrafo único.")
    artigo: int | None = None      # artigo a que a unidade pertence
    localizacao: str = ""          # "TÍTULO III, CAPÍTULO IV"
    secao_nome: str = ""           # nome do título/capítulo/seção mais específico

    @property
    def pagina_inicio(self) -> int:
        return self.marcas_pagina[0][1]

    @property
    def pagina_fim(self) -> int:
        return self.marcas_pagina[-1][1]

    def pagina_em(self, deslocamento: int) -> int:
        """Página do caractere na posição `deslocamento` do texto da unidade."""
        inicios = [m[0] for m in self.marcas_pagina]
        i = max(0, bisect.bisect_right(inicios, deslocamento) - 1)
        return self.marcas_pagina[i][1]


@dataclass
class Fragmento:
    """Um fragmento (chunk) pronto para ser vetorizado e guardado na base."""
    texto: str                     # texto guardado e enviado ao LLM
    texto_embedding: str           # texto vetorizado (prefixo + cabeçalho de contexto + texto)
    pagina_inicio: int
    pagina_fim: int
    artigo_inicio: int | None
    artigo_fim: int | None
    localizacao: str
    secao_nome: str
    n_tokens: int                  # tokens de texto_embedding (sem tokens especiais)
    sobreposicao_chars: int        # início do texto que repete o fim do fragmento anterior
    separador_anterior: str        # separador entre este fragmento e o anterior


@dataclass
class DocumentoProcessado:
    nome: str
    titulo: str
    n_paginas: int
    paginas_sem_texto: list[int] = field(default_factory=list)
    paginas_ilegiveis: list[int] = field(default_factory=list)
    linhas_removidas: list[str] = field(default_factory=list)
    trechos_riscados: list[dict] = field(default_factory=list)
    redacoes_descartadas: list[dict] = field(default_factory=list)
    anotacoes_nao_resolvidas: list[dict] = field(default_factory=list)
    revogados_em_bloco: list[dict] = field(default_factory=list)
    linhas_sumario: int = 0
    paginas_ocr: list[int] = field(default_factory=list)   # páginas com texto de OCR (camada invisível)
    n_tabelas: int = 0
    hifenizacao_silabica: bool = False
    corpo_texto: float = 0.0
    unidades: list[Unidade] = field(default_factory=list)
    fragmentos: list[Fragmento] = field(default_factory=list)
    limite_tokens: int = 0


TIPOS_TITULOS = ("titulo", "capitulo", "secao", "subsecao", "cabecalho")
TIPOS_DISPOSITIVOS = ("artigo", "paragrafo", "inciso", "alinea")


# ---------------------------------------------------------------------------
# 1. Limpeza de caracteres
# ---------------------------------------------------------------------------
# Caracteres invisíveis que editores deixam no PDF (ex.: U+200F no meio de
# "matrícula" na Res. 29/2011). O hífen condicional (U+00AD) é tratado na
# junção das linhas, porque no fim de linha ele indica palavra partida.
_INVISIVEIS = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\ufeff"), None)
_SUBSTITUICOES = {
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\t": " ",
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    # marcadores de lista das fontes Symbol/Wingdings (área de uso privado)
    "\uf0b7": "•", "\uf0a7": "•", "\uf076": "•", "\uf0d8": "•", "\uf0fc": "•", "\uf0a8": "•",
    "\uf02d": "-",
    # ligaduras "ti" e "tt" da fonte Calibri que alguns PDFs exportados pelo Word
    # entregam com o código errado: "Norma\u019fva", "Polí\u019fca", "h\u01a9ps" (IN 05/2021)
    "\u019f": "ti", "\u01a9": "tt",
}


def limpar_linha(linha: str) -> str:
    """Normaliza Unicode (NFC), remove invisíveis e troca espaços especiais.

    NFC e não NFKC: o NFKC trocaria "º" por "o" ("Art. 1º" viraria "Art. 1o").
    """
    linha = unicodedata.normalize("NFC", linha).translate(_INVISIVEIS)
    for antigo, novo in _SUBSTITUICOES.items():
        linha = linha.replace(antigo, novo)
    return linha


def _normalizar_espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _letras_com_caixa(texto: str) -> list[str]:
    """Letras que têm maiúscula e minúscula. Exclui "º" e "ª", que o Python
    considera letras mas não têm caixa (sem isso, "RESOLUÇÃO Nº 29" não
    seria reconhecida como linha toda em maiúsculas)."""
    return [c for c in texto if c.isalpha() and c.lower() != c.upper()]


# ---------------------------------------------------------------------------
# 2. Extração (PyMuPDF, como na monografia, agora com posição e fonte)
# ---------------------------------------------------------------------------
_FLAGS_DICT = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES   # sem carregar imagens


def _tracos_finos(pagina) -> list[tuple[float, float, float]]:
    """Linhas horizontais finas desenhadas na página: (x0, x1, y)."""
    tracos = []
    try:
        desenhos = pagina.get_drawings()
    except Exception:
        return tracos
    for desenho in desenhos:
        for item in desenho.get("items", []):
            if item[0] == "re":
                r = item[1]
                if r.height <= 1.6 and r.width >= 3:
                    tracos.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
            elif item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) <= 0.6 and abs(b.x - a.x) >= 3:
                    tracos.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
    return tracos


def _riscado(bbox, tracos) -> bool:
    """O trecho está riscado? Critério: um traço fino passa pela faixa central
    da altura do texto (35% a 75%) e cobre pelo menos 60% da largura dele.
    Sublinhados ficam abaixo dessa faixa; marca-texto é alto demais para ser "fino"."""
    x0, y0, x1, y1 = bbox
    h, largura = y1 - y0, max(0.1, x1 - x0)
    coberto = 0.0
    for tx0, tx1, ty in tracos:
        if y0 + 0.35 * h <= ty <= y0 + 0.75 * h:
            coberto += max(0.0, min(x1, tx1) - max(x0, tx0))
    return coberto >= 0.6 * largura


def _trechos_riscados(brutos: list[dict], bbox, tracos: list) -> list[tuple[list, bool]]:
    """Divide um trecho de mesmo estilo em partes riscadas e não riscadas,
    caractere por caractere.

    Um mesmo trecho pode ter só uma parte riscada: na Res. 29/2011
    consolidada, a última linha de cada inciso do estágio traz o fim do texto
    revogado (riscado) e a anotação "(Revogado pela Resolução 329...)" (sem
    risco) no mesmo trecho; medido no trecho inteiro, o risco cobria menos de
    60% e nada era descartado. Espaços acompanham o caractere anterior.
    Devolve [(caracteres, riscado)], com caracteres = [(c, centro_x)].
    """
    chars = [(ch["c"], (ch["bbox"][0] + ch["bbox"][2]) / 2) for ch in brutos]
    x0, y0, x1, y1 = bbox
    h = y1 - y0
    no_meio = [t for t in tracos if y0 + 0.35 * h <= t[2] <= y0 + 0.75 * h and t[1] > x0 and t[0] < x1]
    if not no_meio:
        return [(chars, False)]
    # letras e algarismos são medidos; espaço e pontuação seguem o vizinho: o
    # traço costuma terminar antes do ";" final, e o "(" da anotação que vem
    # depois do texto riscado pertence à anotação (sem risco)
    medidas = [_riscado((ch["bbox"][0], y0, ch["bbox"][2], y1), no_meio) if ch["c"].isalnum() else None
               for ch in brutos]
    if all(m is None for m in medidas):          # só pontuação: vale o trecho inteiro
        return [(chars, bool("".join(c for c, _ in chars).strip()) and _riscado(bbox, no_meio))]
    marcas: list[bool] = []
    for i, ch in enumerate(brutos):
        if medidas[i] is not None:
            marcas.append(medidas[i])
            continue
        antes = next((m for m in reversed(medidas[:i]) if m is not None), None)
        depois = next((m for m in medidas[i + 1:] if m is not None), None)
        if ch["c"] in "([{\"\N{LEFT DOUBLE QUOTATION MARK}'":
            marcas.append(depois if depois is not None else bool(antes))
        else:
            marcas.append(antes if antes is not None else bool(depois))
    partes: list[list] = []
    for c, marca in zip(chars, marcas):
        if partes and partes[-1][1] == marca:
            partes[-1][0].append(c)
        else:
            partes.append([[c], marca])
    # Sobra curta sem risco (até 3 letras ou algarismos) no meio ou na ponta
    # de um trecho riscado conta como riscada: o traço às vezes termina um
    # pouco antes do texto (o "co." de "público.") ou falha numa letra de outra
    # fonte (o "í" de "política" na Res. 208/2018). A anotação que começa com
    # "(" nunca é absorvida.
    for i, (chars_parte, marca) in enumerate(partes):
        if marca or len(partes) == 1:
            continue
        texto = "".join(c for c, _ in chars_parte)
        vizinhas = [partes[j][1] for j in (i - 1, i + 1) if 0 <= j < len(partes)]
        if all(vizinhas) and sum(ch.isalnum() for ch in texto) <= 3 and not texto.lstrip().startswith("("):
            partes[i][1] = True
    juntas: list[tuple[list, bool]] = []
    for chars_parte, marca in partes:
        if juntas and juntas[-1][1] == marca:
            juntas[-1][0].extend(chars_parte)
        else:
            juntas.append((list(chars_parte), marca))
    return juntas


def _dentro(bbox, regiao, folga: float = 2.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return regiao[0] - folga <= cx <= regiao[2] + folga and regiao[1] - folga <= cy <= regiao[3] + folga


# Valores com cara de dado (e não de nome de coluna): datas "16/03",
# números, horas, percentuais e códigos como "BA000001".
_RE_DATA_CURTA = re.compile(r"\b\d{1,2}/\d{1,2}\b")
_RE_VALOR = re.compile(r"[\d\s.,%/:hH°ºª()+-]+|[A-Z]{1,5}\d{2,}\w*")


def _parece_valor(celula: str) -> bool:
    return bool(_RE_DATA_CURTA.search(celula) or _RE_VALOR.fullmatch(celula))


def _parece_rotulo(celula: str) -> bool:
    """Texto com cara de nome de coluna: curto, sem ponto final e sem ser dado."""
    return 0 < len(celula.split()) <= 8 and len(celula) <= 60 and not celula.endswith(".") \
        and not _parece_valor(celula)


def _fracao_negrito(pagina, bbox) -> float | None:
    """Fração dos caracteres em negrito dentro de um retângulo da página."""
    total = negrito = 0
    try:
        blocos = pagina.get_text("dict", clip=fitz.Rect(bbox), flags=_FLAGS_DICT)["blocks"]
    except Exception:
        return None
    for b in blocos:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                n = len(s.get("text", "").strip())
                total += n
                if s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower():
                    negrito += n
    return negrito / total if total else None


def _tem_cabecalho(pagina, t, celulas: list[list], i: int = 0) -> bool:
    """A linha `i` da tabela é o nome das colunas?

    Sinais: ela está em negrito e a seguinte não (o mais comum), ou todas as
    células dela têm cara de rótulo e, em alguma coluna, as de baixo têm cara
    de dado (número, data, código). Em qualquer caso, nenhuma célula dela
    pode ter cara de dado. Na dúvida, não há cabeçalho: tratar a primeira
    linha de dados como cabeçalho grudava o texto dela em todas as outras (no
    Calendário 2026, a data e o evento de "NOTAS PLE-I" apareciam em cada
    linha da tabela de março).
    """
    candidata = [c for c in celulas[i] if c]
    if len(candidata) < 2 or any(_parece_valor(c) for c in candidata):
        return False
    n1 = _fracao_negrito(pagina, t.rows[i].bbox) if i < len(t.rows) else None
    n2 = _fracao_negrito(pagina, t.rows[i + 1].bbox) if i + 1 < len(t.rows) else None
    if n1 is not None and n1 >= 0.6 and (n2 is None or n2 < 0.5) and all(len(c.split()) <= 12 for c in candidata):
        return True
    if not all(_parece_rotulo(c) for c in candidata):
        return False
    for j, rotulo in enumerate(celulas[i]):
        valores = [linha[j] for linha in celulas[i + 1:] if j < len(linha) and linha[j]]
        if rotulo and valores and sum(_parece_valor(v) for v in valores) >= 0.6 * len(valores):
            return True
    return False


def _nomes_das_colunas(t, celulas: list[list], i: int) -> list[str]:
    """Nomes das colunas na linha `i`. A parte de uma célula mesclada na
    horizontal repete o nome dela ("CH máxima" vale para as duas colunas que
    ela cobre)."""
    nomes, anterior = [], ""
    for j, c in enumerate(celulas[i]):
        mesclada = c is None and j > 0 and i < len(t.rows) and j < len(t.rows[i].cells) \
            and t.rows[i].cells[j] is None
        nome = c or (anterior if mesclada else "")
        nomes.append(nome)
        anterior = nome
    return nomes


def _cabecalho_em_dois_niveis(pagina, t, celulas: list[list], i: int) -> list[str] | None:
    """Cabeçalho em duas linhas: uma célula de cima mesclada na horizontal
    ("CH máxima") com os subtítulos embaixo ("por atividade" e "por tipo de
    atividade"), como nas tabelas de ACG dos PPCs 2019 e 2023. As duas linhas
    em negrito, sem nada com cara de dado, e a linha seguinte (se houver) sem
    negrito. Devolve os nomes combinados ("CH máxima por atividade") ou None.
    """
    if i + 1 >= len(celulas) or i + 1 >= len(t.rows):
        return None
    cima, baixo = celulas[i], celulas[i + 1]
    horizontais = [j for j in range(1, min(len(cima), len(baixo)))
                   if cima[j] is None and j < len(t.rows[i].cells) and t.rows[i].cells[j] is None and baixo[j]]
    textos = [c for c in cima + baixo if c]
    if not horizontais or sum(1 for c in cima if c) < 2 or any(_parece_valor(c) for c in textos):
        return None
    n1 = _fracao_negrito(pagina, t.rows[i].bbox)
    n2 = _fracao_negrito(pagina, t.rows[i + 1].bbox)
    n3 = _fracao_negrito(pagina, t.rows[i + 2].bbox) if i + 2 < len(t.rows) else None
    if n1 is None or n2 is None or n1 < 0.6 or n2 < 0.6 or (n3 is not None and n3 >= 0.5):
        return None
    nomes = []
    for pai, filho in zip(_nomes_das_colunas(t, celulas, i), baixo):
        nomes.append(f"{pai} {filho}".strip() if filho and filho != pai else pai)
    return nomes


def _linha_de_titulo(linha: list) -> bool:
    """Linha com uma só célula ocupando a largura toda (título ou legenda da
    tabela, título de grupo como "JANEIRO/2026")."""
    preenchidas = [c for c in linha if c]
    return len(preenchidas) == 1 and sum(c is None for c in linha) == len(linha) - 1


def _preencher_mescladas(t, celulas: list[list]) -> set:
    """Célula mesclada na vertical (o "3º" do semestre que vale para 4 linhas
    da matriz do PPC) só tem texto na primeira linha; o PyMuPDF devolve None
    nas outras. Cada linha precisa se ler sozinha, então o valor é repetido
    quando a célula de cima se estende até a linha. Célula mesclada na
    horizontal continua vazia (o valor já está na célula da esquerda).
    Devolve as colunas que tinham células mescladas."""
    colunas = set()
    for r in range(1, len(celulas)):
        for c in range(len(celulas[r])):
            if celulas[r][c] is not None or r >= len(t.rows):
                continue
            k = r - 1
            while k >= 0 and (c >= len(t.rows[k].cells) or t.rows[k].cells[c] is None):
                k -= 1
            if k >= 0 and celulas[k][c] and t.rows[k].cells[c][3] >= t.rows[r].bbox[1] + 2:
                celulas[r][c] = celulas[k][c]
                colunas.add(c)
    return colunas


def _preencher_coluna_de_grupo(celulas: list[list], anterior: str = "", mesclada: bool = False) -> str:
    """Primeira coluna usada para agrupar linhas (o semestre na matriz
    curricular): o valor aparece só na primeira linha do grupo.

    * Continuação: as primeiras linhas vazias de uma tabela que continua da
      página anterior pertencem ao grupo que vinha de lá (`anterior`).
    * Coluna esparsa (no máximo 40% das linhas preenchidas, valores curtos):
      cada linha vazia recebe o valor de cima, mesmo quando o PDF não mesclou
      as células.
    Só a primeira coluna: numa coluna como "Pré-requisito", vazio quer dizer
    "não tem", e repetir o valor de cima seria um erro. Devolve o último valor
    da coluna quando ela é de grupo (esparsa ou com células mescladas), para
    a continuação da tabela na página seguinte.
    """
    linhas = [l for l in celulas if l and not _linha_de_titulo(l)]
    if not linhas:
        return ""
    valores = [l[0] for l in linhas]
    preenchidos = [v for v in valores if v]
    esparsa = bool(preenchidos or anterior) and bool(valores[0] or anterior) \
        and len(preenchidos) <= max(1, 0.4 * len(valores)) and all(len(v) <= 25 for v in preenchidos)
    atual = anterior
    for l in linhas:
        if l[0]:
            if not esparsa and anterior:
                break                     # só as primeiras linhas herdam da página anterior
            atual = l[0]
        elif atual and any(l[1:]) and (esparsa or anterior):
            l[0] = atual
    finais = [l[0] for l in linhas if l[0]]
    return finais[-1] if finais and (esparsa or mesclada or anterior) else ""


# Marca de trecho omitido: "(...)", "[...]", "..." ou "…"
_RE_OMISSAO = re.compile(r"^[(\[]?\s*(?:\.{3}|\N{HORIZONTAL ELLIPSIS})\s*[)\]]?$")


def _linearizar(cabecalho: list[str], celulas: list[list]) -> list[str]:
    """Cada linha vira um texto que se lê sozinho: "Coluna: valor; Coluna:
    valor" com cabeçalho, "valor | valor" sem. Linha com uma só célula que
    ocupa a largura toda (título de grupo, como "JANEIRO/2026") vira só o
    texto dela. Linha só com "(...)" (as portarias que retificam o calendário
    omitem assim as linhas que não mudaram) não tem dado e sai."""
    textos = []
    for linha in celulas:
        preenchidas = [c for c in linha if c]
        if not preenchidas:
            continue
        omissoes = sum(1 for c in preenchidas if _RE_OMISSAO.match(c))
        if omissoes and len(preenchidas) - omissoes <= 1:
            continue
        if _linha_de_titulo(linha):
            textos.append(preenchidas[0])
        elif cabecalho:
            textos.append("; ".join(f"{h}: {c}" if h else c for h, c in zip(cabecalho, linha) if c))
        else:
            textos.append(" | ".join(preenchidas))
    return textos


def _tabelas_da_pagina(pagina, numero: int) -> tuple[list[Tabela], list[tuple]]:
    """Tabelas com bordas desenhadas, linearizadas linha a linha.

    Usa a estratégia "lines_strict" do PyMuPDF, que ignora retângulos só de
    preenchimento: com a estratégia padrão, o marca-texto amarelo do Art. 111
    da Res. 29/2011 virava uma "tabela" falsa. Também descarta grades quase
    vazias. Cada linha da tabela vira "Coluna: valor; Coluna: valor", que se
    lê sozinha (o fragmento não perde o significado das colunas).
    """
    try:
        encontradas = pagina.find_tables(strategy="lines_strict").tables
    except Exception:
        return [], []
    tabelas, regioes = [], []
    for t in encontradas:
        brutas = t.extract()
        # palavra com hífen quebrada dentro da célula ("quinta-" + "feira",
        # "Pró-" + "Reitoria") volta a ficar inteira
        celulas = [[None if c is None else _normalizar_espacos(limpar_linha(
            re.sub(r"(?<=[^\W\d_])-[ \t]*\n\s*(?=[^\W\d_])", "-", c))) for c in linha]
            for linha in brutas]
        cheias = sum(1 for l in celulas if sum(1 for c in l if c) >= 2)
        if sum(1 for l in celulas if any(l)) < 2 or max(len(l) for l in celulas) < 2 \
                or cheias < max(2, sum(1 for l in celulas if any(l)) / 2):
            continue   # grade vazia ou sombreamento: não é tabela de dados
        mescladas = _preencher_mescladas(t, celulas)
        # títulos e legendas no topo da tabela ("Legenda: S - Semestre; N - ...",
        # na matriz curricular do PPC) vêm antes do cabeçalho de verdade
        i = 0
        while i < len(celulas) - 1 and _linha_de_titulo(celulas[i]):
            i += 1
        if nomes := _cabecalho_em_dois_niveis(pagina, t, celulas, i):
            cabecalho, corpo = nomes, celulas[i + 2:]
        elif _tem_cabecalho(pagina, t, celulas, i):
            cabecalho, corpo = _nomes_das_colunas(t, celulas, i), celulas[i + 1:]
        else:
            cabecalho, corpo = [], celulas[i:]
        grupo = _preencher_coluna_de_grupo(corpo, mesclada=0 in mescladas)
        titulos = [c for linha in celulas[:i] for c in linha if c]
        linhas = titulos + _linearizar(cabecalho, corpo)
        if linhas:
            tabelas.append(Tabela(numero, t.bbox[1], t.bbox[3], cabecalho, linhas, corpo, len(celulas[0]),
                                  titulos, grupo))
            regioes.append(tuple(t.bbox))
    return tabelas, regioes


def _continuar_cabecalhos(paginas: list[PaginaExtraida], corpo: float) -> int:
    """Tabela que continua na página seguinte: primeira coisa da página, com o
    mesmo número de colunas de uma tabela que fechava a página anterior
    (nada de texto do corpo depois dela). Ela herda o cabeçalho, se não
    repetiu o seu (ou se repetiu só a primeira linha de um cabeçalho em dois
    níveis), e o valor da coluna de grupo (o semestre que começou na página
    anterior). Devolve quantas tabelas foram completadas."""
    completadas = 0
    anterior: Tabela | None = None
    for p in paginas:
        primeira = next((e for e in p.elementos if isinstance(e, Tabela) or e.visivel), None)
        if isinstance(primeira, Tabela) and anterior is not None and primeira.n_colunas == anterior.n_colunas:
            mudou = False
            if not primeira.cabecalho and anterior.cabecalho:
                primeira.cabecalho = anterior.cabecalho
                mudou = True
            elif primeira.cabecalho and len(primeira.cabecalho) == len(anterior.cabecalho) \
                    and primeira.cabecalho != anterior.cabecalho \
                    and all(b.startswith(a) for a, b in zip(primeira.cabecalho, anterior.cabecalho)):
                # a página seguinte repetiu só a 1ª linha de um cabeçalho em dois
                # níveis ("CH máxima" no lugar de "CH máxima por atividade")
                primeira.cabecalho = anterior.cabecalho
                mudou = True
            if anterior.grupo and primeira.celulas and not primeira.celulas[0][0]:
                primeira.grupo = _preencher_coluna_de_grupo(primeira.celulas, anterior.grupo) or primeira.grupo
                mudou = True
            if mudou:
                primeira.linhas = primeira.titulos + _linearizar(primeira.cabecalho, primeira.celulas)
                completadas += 1
        anterior = None
        for e in p.elementos:
            if isinstance(e, Tabela):
                anterior = e
            elif e.visivel and e.tamanho >= corpo - 0.5:
                anterior = None
    return completadas


def _ordem_de_leitura(linhas: list[LinhaVisual]) -> list[LinhaVisual]:
    """Coloca as linhas de uma página de coluna única de cima para baixo.

    A ordem interna do PDF nem sempre é a visual: na Res. 29/2011 o rodapé
    vem antes do corpo de cada página. Em página de coluna única, ordenar
    pela posição vertical resolve. Se a página tiver colunas (linhas longas
    lado a lado na mesma altura), a ordem do arquivo é mantida, porque nela
    cada coluna costuma vir inteira antes da seguinte.
    """
    longas = [l for l in linhas if len(l.visivel) > 20]
    lado_a_lado = 0
    for i, a in enumerate(longas):
        for b in longas[i + 1:]:
            sobrepoe_na_vertical = min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.altura, b.altura)
            separadas_na_horizontal = a.x1 <= b.x0 or b.x1 <= a.x0
            if sobrepoe_na_vertical and separadas_na_horizontal:
                lado_a_lado += 1
                break
    if longas and lado_a_lado >= max(2, 0.2 * len(longas)):
        return linhas
    return sorted(linhas, key=lambda l: (round(l.y0), l.x0))


@dataclass
class _Span:
    """Trecho com o mesmo estilo dentro de um pedaço de linha."""
    chars: list                # [(caractere, centro_x)]
    tamanho: float
    negrito: bool
    riscado: bool
    sobrescrito: bool
    invisivel: bool = False    # alpha 0: camada de texto de OCR sobre a imagem

    @property
    def texto(self) -> str:
        return "".join(c for c, _ in self.chars)


@dataclass
class _Peca:
    """Pedaço de linha como o PyMuPDF entrega. Uma mesma linha visual pode vir
    em vários pedaços: palavras de linha justificada, número de nota de rodapé
    separado do texto da nota ou, em alguns PDFs, a linha inteira gravada em
    faixas verticais (1ª página de resoluções de 2020 a 2024)."""
    ordem: int                 # posição no arquivo (preserva a ordem de colunas)
    bloco: int
    x0: float
    y0: float
    x1: float
    y1: float
    spans: list                # [_Span]
    horizontal: bool

    @property
    def centro(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def altura(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def tamanho(self) -> float:
        return max((s.tamanho for s in self.spans), default=10.0) or 10.0


def _pecas_da_pagina(dados: dict, regioes: list, tracos: list) -> list[_Peca]:
    """Lê as linhas do modo "rawdict" (com a posição de cada caractere)."""
    pecas: list[_Peca] = []
    for nb, bloco in enumerate(dados.get("blocks", [])):
        if bloco.get("type") != 0:
            continue
        for linha in bloco.get("lines", []):
            if any(_dentro(linha["bbox"], r) for r in regioes):
                continue          # texto de tabela: já foi lido pela tabela
            spans = []
            for s in linha.get("spans", []):
                brutos = s.get("chars", [])
                if not "".join(ch["c"] for ch in brutos):
                    continue
                negrito = bool(s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower())
                for chars, riscado in _trechos_riscados(brutos, s["bbox"], tracos):
                    spans.append(_Span(chars, round(s["size"], 1), negrito, riscado,
                                       bool(s.get("flags", 0) & 1), s.get("alpha", 255) == 0))
            if not spans:
                continue
            dx, dy = linha.get("dir", (1.0, 0.0))
            x0, y0, x1, y1 = linha["bbox"]
            pecas.append(_Peca(len(pecas), nb, x0, y0, x1, y1, spans, dx > 0 and abs(dy) < 0.1))
    return pecas


def _agrupar_linhas_visuais(pecas: list[_Peca]) -> list[list[_Peca]]:
    """Junta os pedaços que formam a mesma linha visual.

    Pedaços na mesma altura (centro a menos de 40% da altura da letra) são
    unidos, da esquerda para a direita, quando estão no mesmo bloco ou quando
    estão colados (distância menor que 60% do corpo de letra). Pedaços na mesma
    altura mas afastados (colunas, com um vão entre elas) continuam separados.
    As linhas voltam na ordem do arquivo, que `_ordem_de_leitura` usa em
    páginas com colunas.
    """
    horizontais = sorted((p for p in pecas if p.horizontal), key=lambda p: (p.centro, p.x0))
    grupos: list[list[_Peca]] = []
    for p in horizontais:
        if grupos and abs(p.centro - grupos[-1][0].centro) < 0.4 * min(p.altura, grupos[-1][0].altura):
            grupos[-1].append(p)
        else:
            grupos.append([p])
    linhas: list[list[_Peca]] = []
    for grupo in grupos:
        grupo.sort(key=lambda p: p.x0)
        atual = [grupo[0]]
        for p in grupo[1:]:
            direita = max(q.x1 for q in atual)
            if p.bloco == atual[-1].bloco or p.x0 - direita <= 0.6 * p.tamanho:
                atual.append(p)
            else:
                linhas.append(atual)
                atual = [p]
        linhas.append(atual)
    linhas += [[p] for p in pecas if not p.horizontal]   # texto girado: fica como está
    linhas.sort(key=lambda ps: min(p.ordem for p in ps))
    return linhas


def _texto_da_linha(pecas: list[_Peca]) -> tuple[str, list[str], Counter, bool]:
    """Texto de uma linha visual, com os trechos riscados trocados por RISCO.

    * Quando dois pedaços se sobrepõem (texto em faixas), o caractere da
      emenda aparece nos dois; a cópia do pedaço da direita é descartada pela
      posição (sem isso, "art. 10" + "0 da Resolução" viraria "art. 100").
    * "o" e "a" sobrescritos logo depois de letra ou número são ordinais
      ("n" + "o" = "nº", "1" + "a" = "1ª"), como o LaTeX costuma gravar.
    """
    partes: list[str] = []
    riscado_aqui: list[str] = []
    tamanhos: Counter = Counter()
    negrito = True
    direita: float | None = None
    for p in pecas:
        spans = p.spans
        if direita is not None:
            if p.x0 < direita - 0.5:                 # sobreposição: corta o início repetido
                cortados, cortando = [], True
                for s in spans:
                    chars = s.chars
                    if cortando:
                        i = 0
                        while i < len(chars) and chars[i][1] < direita:
                            i += 1
                        cortando = i == len(chars)
                        chars = chars[i:]
                    if chars:
                        cortados.append(_Span(chars, s.tamanho, s.negrito, s.riscado, s.sobrescrito, s.invisivel))
                spans = cortados
            elif p.x0 - direita > 0.15 * p.tamanho and partes and not partes[-1].endswith(" "):
                partes.append(" ")
        for s in spans:
            t = s.texto
            if not t:
                continue
            if t.strip():
                tamanhos[s.tamanho] += len(t.strip())
                if not s.negrito:
                    negrito = False
            if s.sobrescrito and t.strip() in ("o", "a") and "".join(partes)[-1:].isalnum():
                t = "\N{MASCULINE ORDINAL INDICATOR}" if t.strip() == "o" else "\N{FEMININE ORDINAL INDICATOR}"
            if s.riscado:
                partes.append(f" {RISCO} ")
                riscado_aqui.append(t.strip())
            else:
                partes.append(t)
        direita = p.x1 if direita is None else max(direita, p.x1)
    return limpar_linha("".join(partes)), riscado_aqui, tamanhos, negrito and bool(tamanhos)


def _extrair_pagina(pagina, numero: int, opcoes: OpcoesProcessamento) -> PaginaExtraida:
    tracos = _tracos_finos(pagina) if opcoes.descartar_riscado else []
    tabelas, regioes = _tabelas_da_pagina(pagina, numero) if opcoes.extrair_tabelas else ([], [])
    dados = pagina.get_text("rawdict", flags=_FLAGS_DICT)
    linhas: list[LinhaVisual] = []
    riscados: list[str] = []
    ultima_riscada = -10
    caracteres = ilegiveis = 0
    for grupo in _agrupar_linhas_visuais(_pecas_da_pagina(dados, regioes, tracos)):
        texto, riscado_aqui, tamanhos, negrito = _texto_da_linha(grupo)
        caracteres += sum(tamanhos.values())
        ilegiveis += texto.count("�")
        if riscado_aqui:
            # linhas riscadas seguidas formam um só trecho no relatório
            if riscados and ultima_riscada >= len(linhas) - 1:
                riscados[-1] += " " + " ".join(riscado_aqui)
            else:
                riscados.append(" ".join(riscado_aqui))
            ultima_riscada = len(linhas)
        tamanho = tamanhos.most_common(1)[0][0] if tamanhos else 0.0
        linhas.append(LinhaVisual(texto, numero, grupo[0].bloco,
                                  min(p.x0 for p in grupo), min(p.y0 for p in grupo),
                                  max(p.y1 for p in grupo), tamanho, negrito, max(p.x1 for p in grupo),
                                  all(s.invisivel for p in grupo for s in p.spans)))
    linhas = _ordem_de_leitura(linhas)
    # Cada tabela entra logo depois da última linha (na ordem de leitura) que
    # está acima dela: assim fica depois do título que a apresenta.
    elementos: list = list(linhas)
    for tabela in sorted(tabelas, key=lambda t: t.y0):
        acima = [i for i, e in enumerate(elementos) if isinstance(e, LinhaVisual) and e.y1 <= tabela.y0 + 2]
        elementos.insert(acima[-1] + 1 if acima else 0, tabela)
    return PaginaExtraida(numero, pagina.rect.height, elementos, riscados, caracteres, ilegiveis)


def extrair_paginas(caminho_pdf: str | Path, opcoes: OpcoesProcessamento | None = None) -> list[PaginaExtraida]:
    """Extrai linhas (com posição e fonte) e tabelas de cada página (RNF03:
    cada linha sabe de que página veio)."""
    opcoes = opcoes or OpcoesProcessamento(limite_tokens=10**6, sobreposicao_tokens=0)
    try:
        documento = fitz.open(caminho_pdf)
    except Exception as erro:  # arquivo corrompido ou que não é PDF
        raise ErroExtracao(f"não foi possível abrir o PDF ({erro})") from erro
    with documento:
        if documento.needs_pass:
            raise ErroExtracao("o PDF está protegido por senha")
        try:
            paginas = [_extrair_pagina(p, n, opcoes) for n, p in enumerate(documento, start=1)]
        except Exception as erro:
            raise ErroExtracao(f"falha ao ler o conteúdo do PDF ({erro})") from erro
    corrigir_ocr(paginas)
    return paginas


# Erros típicos do OCR (Tesseract) em normas, vistos nos 2 PDFs digitalizados do
# corpus: algarismos romanos lidos como "|", "l" ou "H" ("Il - docentes",
# "HI - discentes", "CAPÍTULO |"), "º" lido como "2" ("Art. 32" no lugar de
# "Art. 3º") ou como "o" ("Art. 1o", "nº" como "no"), "§" lido como "S", "$" ou
# "8" ("8 2o As ações...", 19 vezes na Res. 433/2025), "Art." lido como "Art," ou "Ar".
_RE_ROMANO_OCR = re.compile(r"^([|lIH]{1,4})(?=\s*[\-\N{EN DASH}\N{EM DASH}.)])")
_RE_TITULO_ROMANO_OCR = re.compile(r"^((?:T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\s+)([|lIH]{1,4})(?!\S)")
_MAIUSCULA_INICIAL = r"(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ\"“'(]|$)"
_RE_ARTIGO_OCR = re.compile(rf"^Art?(?:[.,]\s*|\s+)(\d+)\s*([º°o.])?\s*{_MAIUSCULA_INICIAL}")
# "§" lido como "S", "$" ou "8": "S 1o", "$ 2o", "8 3o" e "84o" (sem espaço) viram "§ Nº"
_RE_PARAGRAFO_OCR = re.compile(
    rf"^(?:S\s+|\$\s*|8\s+|8(?=\do\s))(\d{{1,2}})\s*[º°o]\s+{_MAIUSCULA_INICIAL}")


def _romano_ocr(token: str) -> str | None:
    """"|" -> "I", "Il" -> "II", "HI" -> "III"; None se não parece romano."""
    romano = token.replace("|", "I").replace("l", "I").replace("H", "II")
    return romano if romano in ("I", "II", "III", "IIII") and romano != token else None


def corrigir_ocr(paginas: list[PaginaExtraida]) -> int:
    """Corrige, só no texto de OCR (camada invisível), os erros típicos que
    quebram a estrutura das normas. Devolve quantas linhas mudaram.

    * algarismo romano no início da linha (inciso) ou depois de TÍTULO,
      CAPÍTULO e Seção; "S 1o", "$ 1o" e "8 1o" no início da linha viram "§ 1º";
    * "Art," e "Ar" viram "Art."; o número do artigo que quebra a sequência
      é corrigido quando termina em "2" e, sem ele, seria o esperado ("Art. 32"
      entre o 2º e o 4º vira "Art. 3º", porque o OCR lê o "º" como "2") ou
      quando está entre dois números certos ("Art. 4o" antes do "Art. 2o" vira
      "Art. 1º");
    * "no"/"No" antes de número vira "nº".
    Citação a artigo no começo da linha ("Art. 6o desta Instrução") não conta,
    como na regra dos artigos. A indexação e o relatório avisam quando o
    documento veio de OCR (`DocumentoProcessado.paginas_ocr`): nem todo erro
    tem conserto automático.
    """
    mudadas = 0
    artigos = []                              # (linha, número lido, fim do marcador, sufixo)
    for p in paginas:
        for l in p.linhas:
            if not l.ocr or not l.visivel:
                continue
            texto = l.texto.lstrip()
            novo = texto
            if (m := _RE_ROMANO_OCR.match(novo)) and (r := _romano_ocr(m.group(1))):
                novo = r + novo[m.end(1):]
            if (m := _RE_TITULO_ROMANO_OCR.match(novo)) and (r := _romano_ocr(m.group(2))):
                novo = m.group(1) + r + novo[m.end(2):]
            if m := _RE_PARAGRAFO_OCR.match(novo):
                novo = f"§ {m.group(1)}º " + novo[m.end():]
            novo = re.sub(r"\b[Nn]o\s+(?=\d)", "nº ", novo)
            if novo != texto:
                l.texto = novo
                mudadas += 1
            if m := _RE_ARTIGO_OCR.match(novo):
                artigos.append((l, int(m.group(1)), m.end(), m.group(2) or ""))
    numeros = [a[1] for a in artigos]
    anterior = 0
    for i, (linha, lido, fim, sufixo) in enumerate(artigos):
        numero, esperado = lido, anterior + 1
        proximo = numeros[i + 1] if i + 1 < len(numeros) else None
        if lido != esperado:
            digitos = str(lido)
            if len(digitos) >= 2 and digitos.endswith("2") and int(digitos[:-1]) == esperado:
                numero = esperado
            elif proximo == esperado + 1:
                numero = esperado
        marcador = f"Art. {numero}" + ("º" if numero <= 9 else sufixo.replace("o", "").replace("º", "")
                                       .replace("°", ""))
        novo = marcador + " " + linha.texto.lstrip()[fim:].lstrip()
        if novo.rstrip() != linha.texto.strip():
            linha.texto = novo.rstrip()
            mudadas += 1
        anterior = numero
    return mudadas


# ---------------------------------------------------------------------------
# 3. Cabeçalhos, rodapés, corpo do texto e hifenização
# ---------------------------------------------------------------------------
_RE_NUMERO_PAGINA = re.compile(
    r"^(?:p[áa]g(?:ina)?\.?\s*)?[\-\N{EN DASH}\N{EM DASH}]?\s*\d{1,4}\s*[\-\N{EN DASH}\N{EM DASH}]?"
    r"(?:\s*(?:de|/)\s*\d{1,4})?$", re.IGNORECASE)
# Marcas que o navegador acrescenta ao imprimir uma página web em PDF (caso
# dos documentos baixados do SEI): data e hora no topo e o endereço da página,
# encurtado com "…" ou seguido de "N/M", na base.
_RE_DATA_HORA = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\b")
_RE_ENDERECO_IMPRESSAO = re.compile(
    r"^(?:https?://|www\.)\S+(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)?(?:\s+\d{1,4}\s*/\s*\d{1,4})?$")


def _marca_de_impressao(texto: str) -> bool:
    return bool(_RE_DATA_HORA.match(texto)) or (
        bool(_RE_ENDERECO_IMPRESSAO.match(texto))
        and ("\N{HORIZONTAL ELLIPSIS}" in texto or "..." in texto or bool(re.search(r"\d\s*/\s*\d+$", texto))))


def remover_cabecalhos_rodapes(paginas: list[PaginaExtraida], zona: float = 0.12,
                               fracao: float = 0.4, minimo: int = 2) -> list[str]:
    """Remove cabeçalhos e rodapés repetidos e números de página (in loco).

    Critério geométrico, que vale para qualquer layout: uma linha na faixa de
    12% do topo ou da base da página, cujo texto (com os números trocados por
    "#") se repete em pelo menos 40% das páginas (e em no mínimo 2), é
    cabeçalho ou rodapé. Números de página sozinhos nessa faixa também saem.
    Na Res. 29/2011, o rodapé "Resolução nº 29, de 28 de abril de 2011"
    (corpo 7, na base da página) aparecia no meio de 25 dos 93 trechos da
    versão anterior. Devolve os textos removidos (para o relatório).

    Ajustes feitos com o corpus real:
    * Documento curto (até 4 páginas): a linha precisa aparecer em TODAS as
      páginas. Na Portaria 618/2026 (3 páginas), "Leia-se:" abre as páginas
      2 e 3 e era apagado como se fosse cabeçalho.
    * A comparação usa só os 40 primeiros caracteres: o rodapé do SEI traz um
      endereço que o navegador encurta de jeitos diferentes ("…&infra_… 1/24"
      e "…&infr… 10/24") e, sem isso, escapava nas páginas 1 a 9.
    * Marcas de impressão do navegador (data e hora no topo, endereço da
      página na base) saem mesmo em documento de 1 página, junto com o que
      estiver na mesma altura delas (o título que o navegador põe ao lado).
    """
    def na_zona(l: LinhaVisual, p: PaginaExtraida) -> bool:
        return l.y1 <= zona * p.altura or l.y0 >= (1 - zona) * p.altura

    def chave(texto: str) -> str:
        return re.sub(r"\d+", "#", texto).lower()[:40]

    com_texto = [p for p in paginas if p.tem_texto]
    contagem: Counter = Counter()
    for p in com_texto:
        contagem.update({chave(l.visivel) for l in p.linhas if l.visivel and na_zona(l, p)})
    n = len(com_texto)
    limite = n if n <= 4 else max(minimo, math.ceil(fracao * n))
    repetidas = {k for k, c in contagem.items() if n >= minimo and c >= limite}

    removidas: list[str] = []
    for p in paginas:
        marcas = [(l.y0 + l.y1) / 2 for l in p.linhas if l.visivel and na_zona(l, p) and _marca_de_impressao(l.visivel)]
        mantidos = []
        for e in p.elementos:
            if isinstance(e, LinhaVisual) and e.visivel and na_zona(e, p) and not _eh_marcador(e.visivel) \
                    and (chave(e.visivel) in repetidas or _RE_NUMERO_PAGINA.match(e.visivel)
                         or any(abs((e.y0 + e.y1) / 2 - m) < 3 for m in marcas)):
                if e.visivel not in removidas:
                    removidas.append(e.visivel)
                continue
            mantidos.append(e)
        p.elementos = mantidos
    return removidas


# Linha de sumário ou de lista de figuras/tabelas: pontilhado e número de página.
_RE_LINHA_SUMARIO = re.compile(r"(?:\.\s*){5,}\s*\d{1,4}$|(?:\N{HORIZONTAL ELLIPSIS}\s*){2,}\s*\d{1,4}$")
# Variações do PPC 2023: o número da página caiu na linha de baixo ("1.1
# Contextualização da UNIPAMPA ......" + "15") e as subseções não têm
# pontilhado ("1.3.1 Justificativa 25").
_RE_PONTILHADO_SEM_NUMERO = re.compile(r"(?:\.\s*){5,}$|(?:\N{HORIZONTAL ELLIPSIS}\s*){2,}$")
_RE_SO_NUMERO = re.compile(r"^\d{1,4}$")
_RE_ENTRADA_NUMERADA = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,4}\.?\s+\S.*\s\d{1,4}$")


def remover_sumarios(paginas: list[PaginaExtraida]) -> int:
    """Remove as linhas de sumário e de listas de figuras e tabelas (in loco).

    "4.1.2 Pessoa jurídica ........ 15" não tem conteúdo: repete um título
    que aparece no corpo do documento e aponta uma página. Mantidas, essas
    linhas viravam fragmentos só de títulos e pontilhados (449 linhas em 7
    documentos do corpus) e, no Regimento Geral, falsos TÍTULOS. Também sai o
    começo de uma entrada quebrada em duas linhas (linha sem pontuação final
    logo antes de uma linha de sumário, em página com pelo menos 3 delas).
    Devolve quantas linhas saíram.
    """
    removidas = 0
    for p in paginas:
        linhas = [e for e in p.elementos if isinstance(e, LinhaVisual) and e.visivel]
        marcadas = {id(l) for l in linhas if _RE_LINHA_SUMARIO.search(l.visivel)}
        for a, b in zip(linhas, linhas[1:]):
            if _RE_PONTILHADO_SEM_NUMERO.search(a.visivel) and _RE_SO_NUMERO.match(b.visivel):
                marcadas |= {id(a), id(b)}
        if not marcadas:
            continue
        if len(marcadas) >= 3:
            # página de sumário: entradas numeradas sem pontilhado também saem
            marcadas |= {id(l) for l in linhas if _RE_ENTRADA_NUMERADA.match(l.visivel)}
            for a, b in zip(linhas, linhas[1:]):
                if id(b) in marcadas and a.visivel[-1:] not in ".;:!?":
                    marcadas.add(id(a))
        antes = len(p.elementos)
        p.elementos = [e for e in p.elementos if id(e) not in marcadas]
        removidas += antes - len(p.elementos)
    return removidas


def tamanho_do_corpo(paginas: list[PaginaExtraida]) -> float:
    """Corpo de letra do texto principal: o tamanho com mais caracteres."""
    contagem: Counter = Counter()
    for p in paginas:
        for l in p.linhas:
            if l.visivel:
                contagem[l.tamanho] += len(l.visivel)
    return contagem.most_common(1)[0][0] if contagem else 0.0


def detectar_hifenizacao_silabica(paginas: list[PaginaExtraida]) -> bool:
    """O documento parte palavras em sílabas no fim da linha ("infor-" "mação")?

    Documentos do Word em geral não fazem isso (na Res. 29/2011 há só 2
    hífens de fim de linha, ambos de palavras compostas). Documentos feitos em
    LaTeX fazem com frequência. A decisão é por documento: com muitos hífens
    de fim de linha, eles são tratados como separação silábica.
    """
    n_linhas = n_hifens = 0
    for p in paginas:
        linhas = [l.visivel for l in p.linhas if l.visivel]
        n_linhas += len(linhas)
        for a, b in zip(linhas, linhas[1:]):
            if re.search(r"[a-záéíóúâêôãõàç]-$", a) and b[:1].islower():
                n_hifens += 1
    return n_hifens >= 8 and n_hifens >= 0.015 * max(1, n_linhas)


# ---------------------------------------------------------------------------
# 4. Estrutura: reconhecimento de títulos, dispositivos e listas
# ---------------------------------------------------------------------------
_ROMANO = r"[IVXL]{1,6}"
_INICIO_TEXTO = r"(?=$|[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ\"“'(])"
# hífen, meia-risca e travessão, escapados para uso DENTRO de colchetes
_TRACOS = r"\-\N{EN DASH}\N{EM DASH}"
RE_TITULO = re.compile(
    rf"^(T[ÍI]TULO|T[íi]tulo|CAP[ÍI]TULO|Cap[íi]tulo|SUBSE[ÇC][ÃA]O|Subse[çc][ãa]o|SE[ÇC][ÃA]O|Se[çc][ãa]o)"
    rf"\s+({_ROMANO}|[ÚU]NIC[OA]|[Úú]nic[oa])\s*(?:[{_TRACOS}.:]\s*(.*))?$")
RE_ARTIGO = re.compile(
    rf"^Art(?:igo)?\.?\s*(\d+)\s*(?:[º°o]|\.º)?\s*\.?\s*(?:[{_TRACOS}]\s*)?{_INICIO_TEXTO}(.*)$")
RE_PARAGRAFO = re.compile(
    rf"^§\s*(\d+)\s*(?:[º°o]|\.º)?\s*\.?\s*(?:[{_TRACOS}]\s*)?{_INICIO_TEXTO}(.*)$")
# "Parágrafo único.", "Parágrafo Único:", "PARÁGRAFO ÚNICO -" (as três grafias aparecem no corpus)
RE_PARAGRAFO_UNICO = re.compile(rf"^(?i:par[áa]grafo\s+[úu]nico)\s*[.:{_TRACOS}]?\s*(.*)$")
RE_INCISO = re.compile(rf"^({_ROMANO})\s*[.){_TRACOS}]\s*(.*)$")
RE_ALINEA = re.compile(r"^([a-z])\)\s*(.*)$")
RE_ITEM = re.compile(rf"^(?:(\d{{1,2}})[.)]|[•●▪■◦∙·{_TRACOS}])\s+(\S.*)$")
# Numeração em níveis ("2.1 Objetivos", "2.3.1 Integralização curricular"). É
# o único tipo de numeração que, sozinho, indica título: número simples
# ("5. Obter validação...", "1 Informação fornecida...") é item de lista ou
# nota de rodapé nos PPCs e manuais do corpus (50 de 50 casos).
RE_CABECALHO_MULTINIVEL = re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,4}\.?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]")
# Rótulo que abre um parágrafo em destaque, não uma seção ("Observação: Aluno
# eventualmente pode não conseguir vaga...", no guia de matrícula)
_RE_ROTULO_DE_PARAGRAFO = re.compile(
    r"^(?:Observa[çc](?:[ãa]o|[õo]es)|Obs\.?|Notas?|Aten[çc][ãa]o|Importante|Exemplos?|Dicas?|Lembretes?)\s*:",
    re.IGNORECASE)
# Enumeração no meio da linha: "1. Auxílio Moradia 2. Alojamento 3. Vaga..." (PPC 2019)
_RE_ENUMERACAO_INTERNA = re.compile(r"\s\d{1,2}[.)]\s+[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]")
# Numeração com parêntese ("2) Atentar para os prazos...") é de lista, não de seção
_RE_ITEM_COM_PARENTESE = re.compile(r"^\d{1,2}\)\s")
# Fim de frase no meio da linha: "...das etapas WEB. (Exemplos ao final",
# "...sequência de blocos. Os itens" (a palavra antes do ponto não pode ser
# abreviação: "Prof. Dr." não conta)
_RE_FRASE_NO_MEIO = re.compile(r"([^\W\d_]{3,})\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ(\[\"\u201c]")
# Título da lista de referências. Dentro dela o negrito marca o título da
# obra (ABNT), não uma seção nova.
_RE_TITULO_REFERENCIAS = re.compile(
    r"^(?:\d{1,2}\.?\s+)?(?:REFER[ÊE]NCIAS(?:\s+BIBLIOGR[ÁA]FICAS)?|BIBLIOGRAFIA)$", re.IGNORECASE)
# marcador no início do texto de um título já montado ("CAPÍTULO II DO PROCESSO...")
RE_MARCADOR_TITULO = re.compile(
    rf"^(?:T[ÍI]TULO|T[íi]tulo|CAP[ÍI]TULO|Cap[íi]tulo|SUBSE[ÇC][ÃA]O|Subse[çc][ãa]o|SE[ÇC][ÃA]O|Se[çc][ãa]o)"
    rf"\s+(?:{_ROMANO}|[ÚU]NIC[OA]|[Úú]nic[oa])\b[\s{_TRACOS}.:]*")

_TIPO_TITULO = {"T": "titulo", "C": "capitulo", "S": "secao"}


def _tipo_titulo(palavra: str) -> str:
    palavra = palavra.upper()
    if palavra.startswith("SUB"):
        return "subsecao"
    return _TIPO_TITULO[palavra[0]]


def _classificar(linha: str) -> tuple[str, str, str] | None:
    """Identifica se a linha abre uma unidade estrutural.

    Retorna (tipo, rótulo, resto_da_linha) ou None para linha comum. Os
    padrões exigem o marcador no início da linha e, quando há texto depois,
    que ele comece com maiúscula: assim "Art. 81, instruído..." (citação a
    outro artigo que caiu no começo de uma linha) não é tomado como artigo.
    """
    if m := RE_TITULO.match(linha):
        return _tipo_titulo(m.group(1)), m.group(2).upper(), (m.group(3) or "")
    if m := RE_ARTIGO.match(linha):
        return "artigo", str(int(m.group(1))), m.group(2)
    if m := RE_PARAGRAFO.match(linha):
        return "paragrafo", str(int(m.group(1))), m.group(2)
    if m := RE_PARAGRAFO_UNICO.match(linha):
        return "paragrafo", "único", m.group(1)
    if m := RE_INCISO.match(linha):
        return "inciso", m.group(1), m.group(2)
    if m := RE_ALINEA.match(linha):
        return "alinea", m.group(1), m.group(2)
    return None


def _eh_marcador(linha: str) -> bool:
    return _classificar(linha) is not None


def _eh_titulo_generico(linha: LinhaVisual, texto: str, corpo: float, em_referencias: bool = False) -> bool:
    """Título de documento sem artigos (PPCs, editais).

    Linha curta, sem pontuação final, que começa com maiúscula ou número e
    tem pelo menos um destes sinais: numeração em níveis ("2.1 Objetivos"),
    toda em maiúsculas, negrito ou letra maior que o corpo do texto.

    Não é título (versão 6, ver ERROS_CORRIGIDOS.md, erro 3.1): número
    simples sem outro destaque ("5. Obter validação..."), linha que parece
    frase ou lista (`_parece_frase_ou_lista`) e, dentro das referências,
    linha que só está em negrito (o título da obra, pela ABNT).
    """
    if not texto or len(texto) > 120 or texto[-1] in ".;," or _eh_marcador(texto):
        return False
    maior = bool(corpo and linha.tamanho >= corpo + 1.0)
    # dois-pontos no fim: "RESOLVE:", "Dicas:" apresentam o que vem a seguir.
    # Só é título com letra maior que o corpo e de 2 a 6 palavras
    # ("Exemplos de Solicitação:", 16 pt, no guia de matrícula)
    if texto[-1] == ":" and not (maior and 2 <= len(texto.split()) <= 6):
        return False
    if not (texto[:1].isupper() or texto[:1].isdigit()):
        return False
    letras = _letras_com_caixa(texto)
    if len(letras) < 3 or _parece_frase_ou_lista(texto):
        return False
    maiusculas = len(letras) >= 4 and all(c.isupper() for c in letras)
    em_niveis = bool(RE_CABECALHO_MULTINIVEL.match(texto))
    if em_referencias:
        return maiusculas or em_niveis or maior
    return em_niveis or maiusculas or linha.negrito or maior


def _parece_frase_ou_lista(texto: str) -> bool:
    """Sinais de que uma linha em destaque é parágrafo ou item, não título:
    rótulo ("Observação:"), numeração de lista ("2) ..."), enumeração no meio
    ("1. ... 2. ...") ou fim de frase no meio da linha."""
    if _RE_ROTULO_DE_PARAGRAFO.match(texto) or _RE_ITEM_COM_PARENTESE.match(texto) \
            or _RE_ENUMERACAO_INTERNA.search(texto):
        return True
    return any(m.group(1).lower() not in _ABREVIACOES for m in _RE_FRASE_NO_MEIO.finditer(texto))


def _titulo_montado_valido(texto: str) -> bool:
    """O título genérico já montado (uma ou mais linhas) ainda é título?

    Termina em ponto final ou ponto e vírgula: era frase (o item "5. Obter
    validação em 120 horas..., apresentada no Apêndice D.", cuja primeira
    linha terminava em "nos" e parecia um título que continuava). Títulos
    todos em maiúsculas podem terminar em ponto (ementa de resolução:
    "FIXAR O TEMPO MÁXIMO DE INTEGRALIZAÇÃO ... DO PAMPA.").
    """
    letras = _letras_com_caixa(texto)
    maiusculas = len(letras) >= 4 and all(c.isupper() for c in letras)
    if texto[-1:] in ".;" and not maiusculas:
        return False
    return not _parece_frase_ou_lista(texto)


def _nome_de_titulo(linha: str, primeira: bool) -> bool:
    """A linha pode ser (continuação do) nome de um TÍTULO/CAPÍTULO/Seção?

    A primeira linha do nome pode ter qualquer caixa ("Do Reingresso"); as
    seguintes só entram se estiverem em maiúsculas, como em
    "DA TRANSFERÊNCIA COMPULSÓRIA" + "(TRANSFERÊNCIA EX-OFFICIO)".
    """
    if len(linha) > 120 or _eh_marcador(linha):
        return False
    letras = _letras_com_caixa(linha)
    maiusculas = sum(c.isupper() for c in letras)
    return primeira or (bool(letras) and maiusculas >= 0.8 * len(letras))


# ---------------------------------------------------------------------------
# 5. Montagem das unidades
# ---------------------------------------------------------------------------
_CLITICOS = {"se", "lhe", "lhes", "lo", "la", "los", "las", "no", "na", "nos", "nas", "me", "te",
             "o", "a", "os", "as", "vos"}
_PREFIXOS_COM_HIFEN = {"pré", "pós", "pró", "ex", "vice", "sub", "super", "auto", "anti", "semi", "co",
                       "bem", "mal", "recém", "além", "sem", "contra", "extra", "infra", "intra", "ultra",
                       "neo", "pseudo", "sócio", "técnico", "médico", "político", "econômico", "didático",
                       "científico", "histórico", "jurídico", "ético"}
_RE_INICIO_ANOTACAO = re.compile(
    r"^\(\s*(?:Alterad[oa]|Revogad[oa]|Reda[çc][ãa]o\s+dada|Modificad[oa]|Inclu[íi]d[oa]|"
    r"Acrescid[oa]|Acrescentad[oa])\b", re.IGNORECASE)
# Trecho riscado e, logo depois, a anotação que explica o risco.
_RE_RISCO_E_ANOTACAO = re.compile(
    r"\x00(?:\s*\x00)*\s*(?:\(\s*(?:Alterad[oa]|Revogad[oa]|Reda[çc][ãa]o\s+dada|Modificad[oa]|"
    r"Inclu[íi]d[oa]|Acrescid[oa]|Acrescentad[oa])\b[^()]{0,200}\)\s*[.;]?)?", re.IGNORECASE)


def _juntar_linhas(linhas: list[tuple[str, int]], silabica: bool) -> tuple[str, list[tuple[int, int]]]:
    """Junta linhas de layout em texto corrido, guardando a página de cada uma.

    Hífen no fim da linha seguido de minúscula:
    * documento sem hifenização silábica (caso comum do Word): hífen mantido e
      palavras unidas ("transferir-" + "se" = "transferir-se");
    * documento com hifenização silábica (comum no LaTeX): hífen removido
      ("infor-" + "mação" = "informação"), exceto antes de pronome átono ou
      depois de prefixo que leva hífen ("encaminhá-lo", "pré-requisito").
    O hífen condicional (U+00AD) sempre indica palavra partida e é removido.
    """
    texto = ""
    marcas: list[tuple[int, int]] = []
    for linha, pagina in linhas:
        linha = _normalizar_espacos(linha)
        if not linha:
            continue
        if not texto:
            marcas.append((0, pagina))
            texto = linha
            continue
        if texto.endswith("\u00ad"):
            texto = texto[:-1]
            marcas.append((len(texto), pagina))
            texto += linha
        elif texto.endswith("-") and len(texto) > 1 and texto[-2].isalpha() and linha[0].islower():
            proxima = re.match(r"[^\W\d_]+", linha)
            anterior = re.search(r"([^\W\d_]+)-$", texto)
            manter = (not silabica
                      or (proxima and proxima.group(0).lower() in _CLITICOS)
                      or (anterior and anterior.group(1).lower() in _PREFIXOS_COM_HIFEN))
            if not manter:
                texto = texto[:-1]
            marcas.append((len(texto), pagina))
            texto += linha
        else:
            marcas.append((len(texto) + 1, pagina))
            texto += " " + linha
    return texto.replace("\u00ad", ""), marcas


def _substituir(texto: str, marcas: list[tuple[int, int]], padrao: re.Pattern, novo: str = " "):
    """Aplica `padrao.sub` e corrige os deslocamentos das marcas de página."""
    trechos = [(m.start(), m.end()) for m in padrao.finditer(texto)]
    if not trechos:
        return texto, marcas

    def nova_posicao(pos: int) -> int:
        ajuste = 0
        for ini, fim in trechos:
            if fim <= pos:
                ajuste += (fim - ini) - len(novo)
            elif ini < pos:          # a posição estava dentro do trecho removido
                return ini - ajuste
            else:
                break
        return pos - ajuste

    novo_texto = padrao.sub(novo, texto)
    return novo_texto, [(nova_posicao(p), pag) for p, pag in marcas]


def _limpar_unidade(texto: str, marcas: list[tuple[int, int]]):
    """Remove riscos (com a anotação que os acompanha) e espaços sobrando,
    mantendo as marcas de página coerentes."""
    if RISCO in texto:
        texto, marcas = _substituir(texto, marcas, _RE_RISCO_E_ANOTACAO, " ")
    texto, marcas = _substituir(texto, marcas, re.compile(r"\s{2,}"), " ")
    inicio = len(texto) - len(texto.lstrip())
    texto = texto.strip()
    # linhas cujo texto foi todo removido não contam para as páginas da unidade
    marcas = [(max(0, p - inicio), pag) for p, pag in marcas if p - inicio < len(texto)]
    if not marcas:
        return texto, [(0, 0)]
    if marcas[0][0] > 0:
        marcas.insert(0, (0, marcas[0][1]))
    return texto, marcas


class _Construtor:
    """Junta as linhas das páginas em unidades estruturais."""

    def __init__(self, silabica: bool) -> None:
        self.silabica = silabica
        self.unidades: list[Unidade] = []
        self.linhas: list[tuple[str, int]] = []   # (linha, página) da unidade aberta
        self.tipo = ""
        self.rotulo = ""
        self.tamanho_marcador = 0
        self.nome_titulo_linhas = 0               # linhas de nome já lidas (títulos)
        self.estilo_titulo: tuple | None = None   # (tamanho, negrito) de título genérico
        self.em_referencias = False               # dentro da lista de referências
        self.riscos_removidos = 0
        # Notas de rodapé adiadas: quando um parágrafo continua na página
        # seguinte, as notas da página ficam guardadas aqui e só viram unidades
        # depois que esse parágrafo termina (ver `montar_unidades`).
        self.notas_pendentes: list[LinhaVisual] = []

    @property
    def aberta(self) -> bool:
        return bool(self.linhas)

    def abrir(self, tipo: str, rotulo: str, linha: str, pagina: int,
              nome_na_linha: bool = False, resto: str = "", visivel: str = "") -> None:
        self.fechar()
        self.tipo, self.rotulo = tipo, rotulo
        self.linhas = [(linha, pagina)]
        # o marcador ("Art. 21.", "Parágrafo único.") nunca é separado do seu texto
        visivel = visivel or _normalizar_espacos(linha.replace(RISCO, " "))
        self.tamanho_marcador = len(visivel) - len(resto) if tipo in TIPOS_DISPOSITIVOS else 0
        # "CAPÍTULO I - DAS DISPOSIÇÕES" já traz o nome: só aceita continuação em maiúsculas
        self.nome_titulo_linhas = 1 if nome_na_linha else 0
        self.estilo_titulo = None

    def acrescentar(self, linha: str, pagina: int) -> None:
        self.linhas.append((linha, pagina))

    def fechar(self) -> None:
        if self.linhas:
            self._guardar(self.tipo, self.linhas, self.rotulo, self.tamanho_marcador)
            self.linhas = []
        if self.notas_pendentes:
            self._emitir_notas()

    def _guardar(self, tipo: str, linhas: list[tuple[str, int]], rotulo: str = "",
                 tamanho_marcador: int = 0) -> None:
        """Transforma linhas em uma unidade (sem riscos) e a acrescenta à lista."""
        texto, marcas = _juntar_linhas(linhas, self.silabica)
        if RISCO in texto:
            self.riscos_removidos += 1
        texto, marcas = _limpar_unidade(texto, marcas)
        # "título" que, montado, virou frase ou lista: é parágrafo ou item
        if tipo == "cabecalho" and texto and not _titulo_montado_valido(texto):
            tipo = "item" if RE_ITEM.match(texto) else "texto"
        # dispositivo que ficou só com o marcador ("III. ." quando o texto do
        # inciso foi riscado) não vira unidade
        marcador_sozinho = tipo in TIPOS_DISPOSITIVOS and not re.search(r"\w", texto[tamanho_marcador:])
        if texto and not marcador_sozinho:
            self.unidades.append(Unidade(tipo, texto, marcas, rotulo,
                                         tamanho_marcador=min(tamanho_marcador, len(texto))))

    def _emitir_notas(self) -> None:
        """Grava as notas de rodapé adiadas, logo depois do parágrafo que as
        interrompia. Uma nota nova começa com número ou símbolo ("1 ", "*")
        depois de frase terminada, ou numa página nova."""
        notas, self.notas_pendentes = self.notas_pendentes, []
        grupo: list[tuple[str, int]] = []
        for linha in notas:
            nova = grupo and (linha.pagina != grupo[-1][1]
                              or (_RE_INICIO_NOTA.match(linha.visivel)
                                  and _normalizar_espacos(grupo[-1][0])[-1:] in ".!?;)"))
            if nova:
                self._guardar("texto", grupo)
                grupo = []
            grupo.append((linha.texto, linha.pagina))
        if grupo:
            self._guardar("texto", grupo)

    def texto_atual(self) -> str:
        return _normalizar_espacos(" ".join(l for l, _ in self.linhas).replace(RISCO, " "))

    def tabela(self, tabela: Tabela) -> None:
        """Tabela: uma unidade de abertura (colunas) e uma por linha de dados."""
        self.fechar()
        if tabela.cabecalho:
            colunas = " | ".join(c for c in tabela.cabecalho if c)
            self.unidades.append(Unidade("tabela", f"Tabela (colunas: {colunas})", [(0, tabela.pagina)]))
        for i, linha in enumerate(tabela.linhas):
            tipo = "tabela" if (i == 0 and not tabela.cabecalho) else "linha_tabela"
            self.unidades.append(Unidade(tipo, linha, [(0, tabela.pagina)]))


def _espaco_tipico(linhas: list[LinhaVisual]) -> float:
    """Espaço vertical típico entre linhas seguidas de um mesmo parágrafo."""
    espacos = [b.y0 - a.y1 for a, b in zip(linhas, linhas[1:])
               if a.visivel and b.visivel and -5 < b.y0 - a.y1 < 40]
    return statistics.median(espacos) if espacos else 2.0


# Início de nota de rodapé: número ("1 ", "12."), asterisco, cruz ou número
# sobrescrito ("¹").
_RE_INICIO_NOTA = re.compile(
    r"^(?:\d{1,3}[.)]?|[*\N{DAGGER}\N{DOUBLE DAGGER}]+|[\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}"
    r"\N{SUPERSCRIPT THREE}\N{SUPERSCRIPT ZERO}-\N{SUPERSCRIPT NINE}]+)\s*\S")


def _notas_de_rodape(elementos: list, altura: float, corpo: float) -> int:
    """Quantos elementos do FIM da página são notas de rodapé.

    Sinais genéricos (Word, LaTeX e ABNT seguem o mesmo padrão): linhas
    depois de todo o texto da página, na metade de baixo dela, com letra pelo
    menos 1 ponto menor que o corpo do texto, e a primeira delas começando por
    número ou símbolo de nota ("1 ", "¹", "*"). A exigência do número evita
    confundir com uma citação longa em letra menor, que não começa assim.
    (Números de página e rodapés repetidos já saíram antes, em
    `remover_cabecalhos_rodapes`.) Uma página só com letra pequena não tem
    notas: tem texto.
    """
    n = 0
    for e in reversed(elementos):
        if not (isinstance(e, LinhaVisual) and e.visivel and corpo
                and e.tamanho <= corpo - 1.0 and e.y0 >= 0.5 * altura):
            break
        n += 1
    if n == 0 or n == len(elementos):
        return 0
    return n if _RE_INICIO_NOTA.match(elementos[len(elementos) - n].visivel) else 0


def _margem_direita(linhas: list[LinhaVisual]) -> float:
    """Onde terminam as linhas cheias da página (percentil 90 do fim das
    linhas com pelo menos 30 caracteres); 0 se não der para estimar."""
    fins = sorted(l.x1 for l in linhas if len(l.visivel) >= 30)
    return fins[int(0.9 * (len(fins) - 1))] if len(fins) >= 3 else 0.0


def _novo_paragrafo(anterior: LinhaVisual | None, linha: LinhaVisual, espaco: float,
                    margem_direita: float = 0.0) -> bool:
    """Sinais genéricos de início de parágrafo entre duas linhas da mesma página:
    espaço vertical maior que o normal, mudança de estilo (corpo de letra ou
    negrito, típica de títulos), troca de bloco depois de frase terminada ou
    recuo de primeira linha depois de frase terminada.

    Exceção ao espaço maior: se a linha anterior parou no meio da frase (sem
    pontuação final) e a seguinte começa com minúscula, ou a anterior vai até
    a margem direita, é a mesma frase. Acontece em páginas com espaçamentos
    misturados (ABNT: texto em 1,5 e exemplos ou referências em espaço
    simples), em que o espaço "normal" da página é o menor dos dois; nos
    Manuais de Normalização isso partia mais de 150 frases ao meio.
    """
    if anterior is None:
        return True
    fim_frase = anterior.visivel[-1:] in ".;:!?"
    if anterior.visivel and (abs(linha.tamanho - anterior.tamanho) >= 1.0 or linha.negrito != anterior.negrito):
        return True
    if linha.y0 - anterior.y1 > espaco + 0.4 * anterior.altura:
        continua = not fim_frase and (linha.visivel[:1].islower()
                                      or (margem_direita > 0 and anterior.x1 >= 0.97 * margem_direita))
        if not continua:
            return True
    if linha.bloco != anterior.bloco and fim_frase:
        return True
    return linha.x0 > anterior.x0 + 8 and fim_frase


# Palavras que não terminam um nome de título: se a linha acaba nelas, o nome
# continua na linha seguinte ("CAPÍTULO II DA MODALIDADE ... PARA" +
# "DISCENTE PROVÁVEL FORMANDO", na Res. 480/2026).
_CONECTORES = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os", "ao", "aos", "à", "às",
               "para", "por", "pelo", "pela", "pelos", "pelas", "com", "na", "no", "nas", "nos", "sobre",
               "entre", "sem", "ou"}


def _termina_com_conector(texto: str) -> bool:
    m = re.search(r"([^\W\d_]+)\W*$", texto)
    return bool(m) and m.group(1).lower() in _CONECTORES


def _abre_paragrafo_em_destaque(texto: str) -> bool:
    """O "título" parou numa preposição escrita em minúscula ("... Tecnológico
    e") ou com parêntese aberto: se a linha seguinte muda de estilo, era o
    começo em negrito de um parágrafo. "APÊNDICE A" e "ANEXO A" não contam:
    ali o "A" maiúsculo é o nome do apêndice, não a preposição."""
    m = re.search(r"([^\W\d_]+)\W*$", texto)
    return (bool(m) and m.group(1) in _CONECTORES) or texto.count("(") > texto.count(")")


def _titulo_incompleto(texto: str) -> bool:
    """Nome de título que claramente continua na linha seguinte: termina em
    preposição ou deixou um parêntese aberto ("(Redação dada pela Resolução
    nº 459, de" + "2025)", na Res. 29/2011 consolidada)."""
    return _termina_com_conector(texto) or texto.count("(") > texto.count(")")


# Legendas e fontes de figuras e tabelas, que podem cair no meio de um parágrafo
_RE_LEGENDA = re.compile(
    r"^(?:Fonte|Figura|Fig\.|Tabela|Quadro|Gr[áa]fico|Imagem|Ilustra[çc][ãa]o|Legenda)\b", re.IGNORECASE)


def _interrompe_paragrafo(u: Unidade) -> bool:
    """Elementos que podem aparecer no meio de uma frase sem fazer parte dela:
    tabelas e legendas ou fontes de figuras (o LaTeX e o Word posicionam
    figuras e tabelas no meio do texto)."""
    return u.tipo in ("tabela", "linha_tabela") or (u.tipo == "texto" and bool(_RE_LEGENDA.match(u.texto)))


def _juntar_unidades(a: Unidade, b: Unidade, silabica: bool) -> Unidade:
    """Emenda o texto de `b` ao fim de `a`, com o mesmo tratamento de hífen das
    linhas e as marcas de página de `b` deslocadas."""
    texto, marcas = _juntar_linhas([(a.texto, a.pagina_fim), (b.texto, b.pagina_inicio)], silabica)
    inicio_b = marcas[1][0] if len(marcas) > 1 else len(texto) - len(b.texto)
    novas = [m for m in a.marcas_pagina if m[0] < inicio_b] + [(inicio_b + d, p) for d, p in b.marcas_pagina]
    return Unidade(a.tipo, texto, novas, a.rotulo, a.tamanho_marcador)


def _religar_continuacoes(unidades: list[Unidade], silabica: bool) -> list[Unidade]:
    """Religa ao parágrafo interrompido o trecho que continua a mesma frase.

    Um parágrafo comum que começa com minúscula continua a frase de um
    parágrafo anterior que ficou sem pontuação final. Entre os dois podem
    existir só tabelas e legendas (figura ou tabela no meio do texto). Casos
    reais do corpus: frase partida por uma figura com "Fonte: NDE (2016)" no
    PPC de 2019 e linhas partidas por espaçamento misto nos Manuais. Os
    elementos do meio continuam no lugar, depois do parágrafo religado.
    """
    resultado: list[Unidade] = []
    for u in unidades:
        if u.tipo == "texto" and u.texto[:1].islower():
            j = len(resultado) - 1
            while j >= 0 and len(resultado) - 1 - j < 6 and _interrompe_paragrafo(resultado[j]):
                j -= 1
            if j >= 0 and resultado[j].tipo in ("texto", "item") and resultado[j].texto[-1:] not in ".!?:;" \
                    and u.pagina_inicio - resultado[j].pagina_fim <= 1:
                resultado[j] = _juntar_unidades(resultado[j], u, silabica)
                continue
        resultado.append(u)
    return resultado


def montar_unidades(paginas: list[PaginaExtraida], corpo: float, silabica: bool = False) -> tuple[list[Unidade], int]:
    """Transforma as linhas das páginas (já sem cabeçalhos) em unidades.

    * Uma linha que começa com marcador (Art., §, inciso, alínea, TÍTULO...)
      abre uma unidade nova; itens de lista ("•", "1.", "-") também.
    * Um parágrafo comum termina em linha em branco ou quando há sinal de
      parágrafo novo (espaço, recuo, bloco; ver `_novo_paragrafo`).
    * Títulos de documentos sem artigos são reconhecidos pelo estilo.
    * A quebra de página NÃO fecha a unidade quando o texto continua (o
      Art. 20 da Res. 29/2011 começa na p. 5 e termina na p. 6). Só fecha se
      a página anterior terminou em ponto final e a seguinte começa com
      maiúscula, marcador ou título, ou se a página seguinte começa com uma
      legenda de figura ou tabela.
    * Notas de rodapé (ver `_notas_de_rodape`) são separadas do fluxo da
      página e entram como unidades próprias (uma por nota) logo depois que a
      unidade aberta no fim da página termina. Se o parágrafo continua na
      página seguinte, as notas vêm depois dele inteiro; sem isso, a
      continuação seria colada na nota e o parágrafo ficaria cortado.
    Devolve as unidades e quantas tinham texto riscado removido.
    """
    c = _Construtor(silabica)
    for pagina in paginas:
        elementos = [e for e in pagina.elementos if isinstance(e, Tabela) or e.texto.strip()]
        if not elementos:
            continue
        espaco = _espaco_tipico(pagina.linhas)
        n_notas = _notas_de_rodape(elementos, pagina.altura, corpo)
        notas = elementos[len(elementos) - n_notas:] if n_notas else []
        elementos = elementos[:len(elementos) - n_notas]
        primeira = elementos[0]
        if c.aberta and isinstance(primeira, LinhaVisual) and primeira.visivel:
            texto = primeira.visivel
            termina_frase = c.texto_atual()[-1:] in ".!?"
            # legenda no alto da página ("Figura 3 - ..."): não é continuação; a
            # frase interrompida é religada depois, em `_religar_continuacoes`
            if _eh_marcador(texto) or _eh_titulo_generico(primeira, texto, corpo, c.em_referencias) \
                    or (termina_frase and texto[:1].isupper()) \
                    or (texto[:1].isupper() and _RE_LEGENDA.match(texto)):
                c.fechar()
        _ler_elementos(c, elementos, espaco, corpo, _margem_direita(pagina.linhas))
        # as notas esperam a unidade aberta terminar (talvez só na página seguinte)
        c.notas_pendentes.extend(notas)
    c.fechar()
    return _religar_continuacoes(c.unidades, silabica), c.riscos_removidos


def _ler_elementos(c: _Construtor, elementos: list, espaco: float, corpo: float,
                   margem_direita: float = 0.0) -> None:
    """Passa as linhas e tabelas de uma página (sem as notas de rodapé), na
    ordem, pelo construtor de unidades."""
    anterior: LinhaVisual | None = None
    for e in elementos:
        if isinstance(e, Tabela):
            c.tabela(e)
            anterior = None
            continue
        linha, texto = e, e.visivel
        if not texto:
            # linha inteiramente riscada: segue com a unidade aberta (ou abre
            # uma), para ser descartada junto com a anotação que vem depois
            if c.aberta:
                c.acrescentar(linha.texto, linha.pagina)
            else:
                c.abrir("texto", "", linha.texto, linha.pagina)
            anterior = linha
            continue
        if c.aberta and RISCO in c.linhas[-1][0] and _RE_INICIO_ANOTACAO.match(texto):
            # anotação "(Alterado pela...)" logo depois de texto riscado: pertence a ele
            c.acrescentar(linha.texto, linha.pagina)
            anterior = linha
            continue
        novo = (not c.aberta) or (anterior is not None and _novo_paragrafo(anterior, linha, espaco, margem_direita))
        anterior = linha
        # 1. marcador de norma (TÍTULO, Art., §, inciso, alínea)
        if classe := _classificar(texto):
            tipo, rotulo, resto = classe
            c.abrir(tipo, rotulo, linha.texto, linha.pagina,
                    nome_na_linha=(tipo in TIPOS_TITULOS and bool(resto.strip())),
                    resto=resto, visivel=texto)
            if tipo in TIPOS_TITULOS:
                c.em_referencias = False
            continue
        # 2. nome de TÍTULO/CAPÍTULO/Seção nas linhas seguintes ao marcador
        if c.aberta and c.tipo in ("titulo", "capitulo", "secao", "subsecao") and c.nome_titulo_linhas < 3 \
                and ((c.nome_titulo_linhas > 0 and _titulo_incompleto(c.texto_atual())
                      and len(texto) <= 120 and not _eh_marcador(texto))
                     or (not (novo and c.nome_titulo_linhas > 0)
                         and _nome_de_titulo(texto, c.nome_titulo_linhas == 0))):
            c.acrescentar(linha.texto, linha.pagina)
            c.nome_titulo_linhas += 1
            continue
        # 3. título genérico que continua na linha seguinte, com o mesmo estilo
        #    (se o título terminou em preposição, a linha seguinte é a continuação
        #    dele mesmo que termine com ponto: "... enfrentamento da" + "retenção e evasão.")
        if c.aberta and c.tipo == "cabecalho" and len(c.linhas) < 3 \
                and c.estilo_titulo == (linha.tamanho, linha.negrito) \
                and ((not novo and _eh_titulo_generico(linha, texto, corpo, c.em_referencias))
                     or (_titulo_incompleto(c.texto_atual()) and len(texto) <= 120 and not _eh_marcador(texto))):
            c.acrescentar(linha.texto, linha.pagina)
            continue
        # "título" em negrito que continua com minúscula na linha seguinte era, na
        # verdade, o começo de um parágrafo em negrito (ou um título longo que
        # quebrou no meio): a linha continua a mesma unidade
        if c.aberta and c.tipo == "cabecalho" and texto[:1].islower() \
                and c.texto_atual()[-1:] not in ".;:!?" and not _eh_marcador(texto):
            c.acrescentar(linha.texto, linha.pagina)
            if texto[-1:] in ".!?":
                c.tipo = "texto"          # título não termina com ponto: era parágrafo
            continue
        # "título" que parou numa preposição ou com parêntese aberto e cuja linha
        # seguinte muda de estilo era o começo em negrito de um parágrafo:
        # "Programa Institucional de Bolsas de Iniciação em Desenvolvimento
        # Tecnológico e" + "Inovação (PROBITI-FAPERGS/UNIPAMPA) oferece bolsas..."
        # (PPC 2019, p. 66). A linha continua a mesma unidade, agora parágrafo.
        if c.aberta and c.tipo == "cabecalho" and _abre_paragrafo_em_destaque(c.texto_atual()) \
                and not _eh_marcador(texto) and not RE_ITEM.match(texto) \
                and not _eh_titulo_generico(linha, texto, corpo, c.em_referencias):
            c.tipo = "texto"
            c.acrescentar(linha.texto, linha.pagina)
            continue
        # o que vem depois de um título nunca é continuação dele
        if c.aberta and c.tipo in TIPOS_TITULOS:
            novo = True
        # 4. item de lista ("•", "-", "1.", "1)")
        if (m := RE_ITEM.match(texto)) and not (m.group(1) and _eh_titulo_generico(linha, texto, corpo,
                                                                                   c.em_referencias)):
            c.abrir("item", "", linha.texto, linha.pagina)
            continue
        # 5. título genérico (PPCs, editais) no início de um parágrafo
        if novo and _eh_titulo_generico(linha, texto, corpo, c.em_referencias):
            c.abrir("cabecalho", "", linha.texto, linha.pagina)
            c.estilo_titulo = (linha.tamanho, linha.negrito)
            # "REFERÊNCIAS" abre a lista de referências; qualquer outro título
            # (que dentro dela só pode ser forte: maiúsculas, níveis, letra maior) a fecha
            c.em_referencias = bool(_RE_TITULO_REFERENCIAS.match(texto))
            continue
        # 6. continuação do parágrafo aberto, ou parágrafo novo
        if c.aberta and not novo:
            c.acrescentar(linha.texto, linha.pagina)
        else:
            c.abrir("texto", "", linha.texto, linha.pagina)


# ---------------------------------------------------------------------------
# 6. Redações alteradas anotadas (quando não há risco no PDF)
# ---------------------------------------------------------------------------
RE_ANOTACAO_ALTERACAO = re.compile(
    r"\(\s*Alterad[oa]\s+pel[oa]\s+[^()]{3,160}\)\s*[.;]?\s*$", re.IGNORECASE)
RE_ANOTACAO_QUALQUER = re.compile(r"\(\s*Alterad[oa]\s+pel[oa]\s+[^()]{3,160}\)", re.IGNORECASE)


def descartar_redacoes_alteradas(unidades: list[Unidade], janela: int = 80):
    """Remove a redação antiga de dispositivos alterados, pela anotação.

    Complementa o descarte de texto riscado para PDFs que marcam a alteração
    só com texto. Convenção das resoluções consolidadas da UNIPAMPA: a
    redação ANTIGA termina com "(Alterado pela Resolução X, de ...)" e a NOVA
    vem logo em seguida, começando pelo mesmo identificador:

        I. ...reingressar; (Alterado pela Resolução 225...)   <- antiga
        I. o Processo Seletivo Complementar é destinado...    <- nova

    Regra: se a unidade seguinte à anotação é um dispositivo (Art., §,
    inciso, alínea), volta-se até a unidade anterior com o MESMO
    identificador e descarta-se tudo desde ela até a anotação. A busca não
    atravessa títulos/capítulos nem, para §/inciso/alínea, o início do artigo.
    Casos fora do padrão ficam na base e são listados no relatório.
    """
    remover: set[int] = set()
    descartadas: list[dict] = []
    nao_resolvidas: list[dict] = []
    for j, unidade in enumerate(unidades):
        anotacao = RE_ANOTACAO_ALTERACAO.search(unidade.texto)
        if not anotacao:
            if meio := RE_ANOTACAO_QUALQUER.search(unidade.texto):
                nao_resolvidas.append({"pagina": unidade.pagina_inicio, "texto": unidade.texto[:160],
                                       "anotacao": meio.group(0).strip()})
            continue
        sucessora = unidades[j + 1] if j + 1 < len(unidades) else None
        alvo = None
        if sucessora is not None and sucessora.tipo in TIPOS_DISPOSITIVOS:
            chave = (sucessora.tipo, sucessora.rotulo)
            for i in range(j, max(-1, j - janela), -1):
                candidata = unidades[i]
                if (candidata.tipo, candidata.rotulo) == chave and i not in remover:
                    alvo = i
                    break
                if candidata.tipo in TIPOS_TITULOS:
                    break
                if i != j and candidata.tipo == "artigo" and sucessora.tipo != "artigo":
                    break
        if alvo is None:
            nao_resolvidas.append({"pagina": unidade.pagina_inicio, "texto": unidade.texto[:160],
                                   "anotacao": anotacao.group(0).strip()})
            continue
        remover.update(range(alvo, j + 1))
        descartadas.append({
            "pagina_inicio": unidades[alvo].pagina_inicio,
            "pagina_fim": unidade.pagina_fim,
            "anotacao": anotacao.group(0).strip(),
            "texto": " ".join(u.texto for u in unidades[alvo:j + 1]),
        })
    mantidas = [u for i, u in enumerate(unidades) if i not in remover]
    return mantidas, descartadas, nao_resolvidas


# Nota de revogação em bloco das normas consolidadas:
# "(Do Art. 40 ao Art. 48 - Revogados pela Resolução 480, de 20/08/2026)".
RE_REVOGADOS_EM_BLOCO = re.compile(
    r"\(\s*Dos?\s+Art(?:igo)?s?\.?\s*(\d+)\D{0,4}?\s+(?:ao|at[ée](?:\s+o)?)\s+(?:Art(?:igo)?\.?\s*)?(\d+)"
    r"[^()]*?\bRevogad[oa]s?\b[^()]*\)", re.IGNORECASE)


def descartar_revogados_em_bloco(unidades: list[Unidade]):
    """Remove restos de dispositivos que uma nota declara revogados em bloco.

    Na Res. 29/2011 consolidada até a Res. 480/2026, os Arts. 40 a 48 estão
    riscados e acompanhados da nota "(Do Art. 40 ao Art. 48 - Revogados pela
    Resolução 480...)". O PDF deixou sem risco o início do Art. 45 ("A
    prioridade de matrícula em componentes curriculares obedece: ..."), que
    sobrava na base como se valesse. Regra: dispositivo (Art., §, inciso,
    alínea) cujo artigo está dentro de uma faixa declarada revogada sai; a
    nota fica, porque informa a revogação. Exige `anotar_contexto` antes.
    """
    faixas = [(int(a), int(b)) for u in unidades for a, b in RE_REVOGADOS_EM_BLOCO.findall(u.texto)]
    if not faixas:
        return unidades, []
    mantidas, descartadas = [], []
    for u in unidades:
        if u.tipo in TIPOS_DISPOSITIVOS and u.artigo is not None \
                and any(a <= u.artigo <= b for a, b in faixas) and not RE_REVOGADOS_EM_BLOCO.search(u.texto):
            descartadas.append({"pagina": u.pagina_inicio, "texto": u.texto})
        else:
            mantidas.append(u)
    return mantidas, descartadas


# ---------------------------------------------------------------------------
# 7. Contexto estrutural (para citação e para o cabeçalho do embedding)
# ---------------------------------------------------------------------------
def _capitalizar_se_maiusculo(texto: str) -> str:
    """Texto todo em maiúsculas vira "Frase normal" (melhor para o embedding)."""
    letras = _letras_com_caixa(texto)
    if letras and sum(c.isupper() for c in letras) >= 0.8 * len(letras):
        return texto[:1].upper() + texto[1:].lower()
    return texto


def _nome_do_titulo(unidade: Unidade) -> str:
    """"CAPÍTULO IV DO TRANCAMENTO DE MATRÍCULA" -> "Do trancamento de matrícula"."""
    nome = RE_MARCADOR_TITULO.sub("", unidade.texto).strip()
    return _capitalizar_se_maiusculo(nome or unidade.texto)


# Tamanho máximo do nome de seção que vai no cabeçalho de contexto e na
# localização. Até a versão 5 o corte era em 80 caracteres, no meio da
# palavra ("..., nos t"); agora é no fim de uma palavra, com folga para
# "Normas para aproveitamento de atividades complementares de graduação no
# curso de Engenharia de Computação" (104 caracteres) caber inteiro.
LIMITE_NOME_SECAO = 110


def _encurtar(texto: str, limite: int) -> str:
    """Corta no fim de uma palavra e não deixa preposição solta no fim."""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite + 1].rsplit(" ", 1)[0].rstrip(" ,;:-\u2013")
    while " " in corte and _termina_com_conector(corte):
        corte = corte.rsplit(" ", 1)[0].rstrip(" ,;:-\u2013")
    return corte


def anotar_contexto(unidades: list[Unidade]) -> None:
    """Preenche artigo, localização e nome da seção de cada unidade.

    Parágrafos (§), incisos e alíneas pertencem ao último artigo aberto.
    Parágrafos comuns e itens de lista sem marcador de dispositivo (os
    critérios "• média ..." logo abaixo de "Art. 3 São considerados os
    seguintes critérios:") também pertencem a ele, mas só enquanto nenhum
    título ou tabela aparece no meio: depois do último artigo de uma norma
    costumam vir anexos e tabelas (o calendário acadêmico inteiro vem depois
    do último artigo da portaria), que não fazem parte do artigo.
    """
    ordem = ("titulo", "capitulo", "secao", "subsecao")
    rotulos = {"titulo": "TÍTULO", "capitulo": "CAPÍTULO", "secao": "Seção", "subsecao": "Subseção"}
    niveis = {k: "" for k in (*ordem, "cabecalho")}
    nomes = dict(niveis)
    artigo: int | None = None
    artigo_aberto: int | None = None   # artigo ainda não interrompido por título ou tabela
    for u in unidades:
        if u.tipo in ordem:
            # um TÍTULO novo zera capítulo e seção; um CAPÍTULO novo zera a seção...
            for nivel in ordem[ordem.index(u.tipo):]:
                niveis[nivel] = nomes[nivel] = ""
            niveis["cabecalho"] = nomes["cabecalho"] = ""
            niveis[u.tipo] = f"{rotulos[u.tipo]} {u.rotulo}"
            nomes[u.tipo] = _nome_do_titulo(u)
            artigo = artigo_aberto = None
        elif u.tipo == "cabecalho":
            titulo = u.texto.rstrip(" :")
            niveis["cabecalho"] = _encurtar(titulo, LIMITE_NOME_SECAO)
            # "2.1 OBJETIVOS DO CURSO" -> "Objetivos do curso" (a numeração não ajuda a busca)
            nome = re.sub(r"^\d{1,2}(?:\.\d{1,2}){0,4}\.?\s+", "", titulo)
            nomes["cabecalho"] = _capitalizar_se_maiusculo(_encurtar(nome, LIMITE_NOME_SECAO))
            artigo_aberto = None
        elif u.tipo == "artigo":
            artigo = artigo_aberto = int(u.rotulo)
        elif u.tipo in ("tabela", "linha_tabela"):
            artigo_aberto = None
        if u.tipo in TIPOS_DISPOSITIVOS:
            u.artigo = artigo
        elif u.tipo in ("texto", "item"):
            u.artigo = artigo_aberto
        else:
            u.artigo = None
        u.localizacao = ", ".join(v for v in niveis.values() if v)
        mais_especifico = [nomes[k] for k in ("cabecalho", "subsecao", "secao", "capitulo", "titulo") if nomes[k]]
        u.secao_nome = mais_especifico[0] if mais_especifico else ""


# ---------------------------------------------------------------------------
# 8. Frases (para fragmentos que não cortam no meio de uma frase)
# ---------------------------------------------------------------------------
# Abreviações comuns: o ponto delas não encerra a frase. Sem isso,
# "conforme o Art. 48" seria cortado depois de "Art." (24 fragmentos da
# versão anterior terminavam assim).
_ABREVIACOES = {
    "art", "arts", "inc", "incs", "al", "n", "nº", "no", "nos", "núm", "p", "pp", "pág",
    "págs", "fl", "fls", "res", "prof", "profa", "profª", "dr", "dra", "sr", "sra", "ex",
    "exa", "exmo", "exma", "ilmo", "ilma", "cf", "obs", "ref", "doc", "cap", "caps", "sec",
    "séc", "tel", "min", "máx", "mín", "aprox", "ltda", "cia", "av", "vol", "ed", "et",
    "vs", "e.g", "i.e", "lat", "esp", "coord", "dept", "depto",
}
_RE_FIM_FRASE = re.compile(r"[.!?]+[\"”')]*\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ§\"“(0-9•])")
_RE_FIM_ORACAO = re.compile(r"[;:]\s+")


def _dividir_por(regex: re.Pattern, texto: str, inicio: int, fim: int,
                 checar_abreviacao: bool, protegido: int = 0) -> list[tuple[int, int]]:
    """Corta o texto nos pontos casados por `regex`. Não corta dentro dos
    `protegido` primeiros caracteres (o marcador "Art. 21." ou
    "Parágrafo único." fica sempre junto do seu texto)."""
    trechos = []
    pos = inicio
    for m in regex.finditer(texto, inicio, fim):
        if m.start() < protegido:
            continue
        if checar_abreviacao:
            antes = texto[pos:m.start()].split()
            ultima = antes[-1].lower().rstrip(".") if antes else ""
            if ultima in _ABREVIACOES or (len(ultima) == 1 and ultima.isalpha()) \
                    or (re.fullmatch(r"[ivxl]+", ultima or "x") and texto[m.start()] == ".") \
                    or (len(antes) == 1 and re.fullmatch(r"\d{1,3}", ultima)):
                # a última condição: número de item de lista ("6. Lei nº 11.645...")
                continue
        trechos.append((pos, m.end()))
        pos = m.end()
    if pos < fim:
        trechos.append((pos, fim))
    return trechos


def _dividir_em_pedacos(texto: str, contar: ContadorTokens, limite: int,
                        protegido: int = 0) -> list[tuple[int, int]]:
    """Divide o texto em frases; frases grandes demais viram orações e, em
    último caso, blocos de palavras. Devolve intervalos (início, fim)."""
    resultado: list[tuple[int, int]] = []
    for ini, fim in _dividir_por(_RE_FIM_FRASE, texto, 0, len(texto), True, protegido):
        if contar(texto[ini:fim]) <= limite:
            resultado.append((ini, fim))
            continue
        for ini2, fim2 in _dividir_por(_RE_FIM_ORACAO, texto, ini, fim, False, protegido):
            if contar(texto[ini2:fim2]) <= limite:
                resultado.append((ini2, fim2))
                continue
            resultado.extend(_dividir_por_palavras(texto, ini2, fim2, contar, limite))
    return resultado


def _dividir_por_palavras(texto, inicio, fim, contar, limite) -> list[tuple[int, int]]:
    """Blocos de palavras de até `limite` tokens (último recurso, para frase
    sem pontuação maior que o limite). Os blocos saem equilibrados: uma frase
    de 146 tokens vira 73 + 73, e não 125 + 21 (sobra que viraria um
    fragmento pequeno demais)."""
    palavras = [(m.start(), m.end()) for m in re.finditer(r"\S+", texto[inicio:fim])]

    def gulosa(alvo: int) -> list[tuple[int, int]]:
        blocos, atual = [], []
        for p in palavras:
            candidato = atual + [p]
            if atual and contar(texto[inicio + candidato[0][0]: inicio + candidato[-1][1]]) > alvo:
                blocos.append((inicio + atual[0][0], inicio + atual[-1][1]))
                atual = [p]
            else:
                atual = candidato
        if atual:
            blocos.append((inicio + atual[0][0], inicio + atual[-1][1]))
        return blocos

    blocos = gulosa(limite)
    if len(blocos) > 1:
        total = contar(texto[inicio:fim])
        for folga in (1.0, 1.05, 1.1, 1.2):
            equilibrados = gulosa(min(limite, math.ceil(total / len(blocos) * folga)))
            if len(equilibrados) == len(blocos):
                return equilibrados
    return blocos


@dataclass
class _Pedaco:
    texto: str
    unidade: Unidade
    inicio_da_unidade: bool
    pagina_inicio: int
    pagina_fim: int
    n_tokens: int

    @property
    def abre_bloco(self) -> bool:
        """Início de título, artigo, parágrafo comum ou tabela: bom lugar para
        começar um fragmento. Parágrafos (§), incisos, alíneas, itens e linhas
        de tabela pertencem ao bloco anterior."""
        return self.inicio_da_unidade and (self.unidade.tipo in TIPOS_TITULOS
                                           or self.unidade.tipo in ("artigo", "texto", "tabela"))

    @property
    def eh_titulo(self) -> bool:
        return self.unidade.tipo in TIPOS_TITULOS


def _pedacos(unidades: list[Unidade], contar: ContadorTokens, limite: int) -> list[_Pedaco]:
    pedacos = []
    for u in unidades:
        for n, (ini, fim) in enumerate(_dividir_em_pedacos(u.texto, contar, limite,
                                                           u.tamanho_marcador + 1)):
            bruto = u.texto[ini:fim]
            recuo = len(bruto) - len(bruto.lstrip())
            texto = bruto.strip()
            if not texto:
                continue
            ini += recuo
            pedacos.append(_Pedaco(
                texto=texto, unidade=u, inicio_da_unidade=(n == 0),
                pagina_inicio=u.pagina_em(ini), pagina_fim=u.pagina_em(ini + len(texto) - 1),
                n_tokens=contar(texto)))
    return pedacos


# ---------------------------------------------------------------------------
# 9. Segmentação em fragmentos
# ---------------------------------------------------------------------------
def cabecalho_de_contexto(pedaco: _Pedaco) -> str:
    """Cabeçalho curto que vai na frente do texto vetorizado.

    Ex.: "Do trancamento de matrícula - Art. 48" para um fragmento que começa
    no meio do Art. 48. Se o fragmento já começa pelo título ou pelo "Art. N",
    o cabeçalho repete só o que falta.
    """
    u = pedaco.unidade
    if pedaco.eh_titulo and pedaco.inicio_da_unidade:
        return ""
    partes = []
    if u.secao_nome:
        partes.append(u.secao_nome)
    if u.artigo is not None and not (u.tipo == "artigo" and pedaco.inicio_da_unidade):
        partes.append(f"Art. {u.artigo}")
    return " - ".join(partes)


def segmentar(
    unidades: list[Unidade],
    contar: ContadorTokens,
    limite_tokens: int,
    sobreposicao_tokens: int,
    incluir_contexto: bool = True,
    prefixo: str = "",
    fracao_minima: float = 0.5,
    fracao_pequeno: float = 0.15,
) -> list[Fragmento]:
    """Agrupa frases consecutivas em fragmentos de até `limite_tokens` tokens.

    * O limite vale para o texto efetivamente vetorizado (prefixo do modelo +
      cabeçalho de contexto + texto): nenhum fragmento é truncado pelo modelo.
    * Antes de um TÍTULO/CAPÍTULO/Seção o fragmento sempre fecha (muda o
      assunto). Antes de um novo artigo, parágrafo comum ou tabela, fecha se
      já estiver pelo menos meio cheio (`fracao_minima`); blocos curtos
      vizinhos continuam juntos.
    * Nenhum fragmento termina com um título solto: o título passa para o
      fragmento seguinte, junto do texto a que se refere.
    * Sobreposição: quando um bloco (artigo, parágrafo) é cortado por
      tamanho, o fragmento seguinte repete as últimas frases (até
      `sobreposicao_tokens`) do mesmo bloco. Não há sobreposição entre blocos.
    * Nenhum fragmento fica pequeno demais (menos de `fracao_pequeno` do
      limite): "CAMPUS BAGÉ", "RESOLVE:" ou "Pré-requisitos: Não há." sozinhos
      não dizem nada e, por serem curtos, ficam parecidos com qualquer
      pergunta que tenha as mesmas palavras. O que abre o assunto seguinte
      (termina em ":" ou em preposição, ou é um título em maiúsculas) vai
      para o fragmento seguinte; o resto vai para o fragmento anterior, se
      couber nele.
    """
    pedacos = _pedacos(unidades, contar, limite_tokens)
    fragmentos: list[Fragmento] = []
    minimo = max(8, int(fracao_pequeno * limite_tokens))

    def texto_de(indices: list[int]) -> str:
        partes = []
        for n, k in enumerate(indices):
            if n:
                mesma = pedacos[k].unidade is pedacos[indices[n - 1]].unidade
                partes.append(" " if mesma else "\n")
            partes.append(pedacos[k].texto)
        return "".join(partes)

    def embutido(indices: list[int], com_contexto: bool) -> str:
        cab = cabecalho_de_contexto(pedacos[indices[0]]) if (incluir_contexto and com_contexto) else ""
        return prefixo + (cab + "\n" if cab else "") + texto_de(indices)

    def orcamento(indices: list[int]) -> int:
        """Tokens disponíveis para o texto, descontados prefixo e cabeçalho."""
        cab = cabecalho_de_contexto(pedacos[indices[0]]) if incluir_contexto else ""
        extra = contar(prefixo + cab + "\n") if (cab or prefixo) else 0
        return max(8, limite_tokens - extra)

    def soma(indices: list[int]) -> int:
        """Estimativa rápida (soma das frases + separadores); a contagem exata
        é conferida em `fechar` antes de emitir o fragmento."""
        return sum(pedacos[k].n_tokens for k in indices) + max(0, len(indices) - 1)

    def mesmo_bloco(a: _Pedaco, b: _Pedaco) -> bool:
        """a e b pertencem ao mesmo artigo (normas) ou à mesma unidade (demais)?"""
        if a.unidade.artigo is not None or b.unidade.artigo is not None:
            return a.unidade.artigo == b.unidade.artigo
        return a.unidade is b.unidade

    def emitir(indices: list[int], sobreposicao: list[int], texto_emb: str, n_tokens: int) -> None:
        texto = texto_de(indices)
        artigos = [pedacos[k].unidade.artigo for k in indices if pedacos[k].unidade.artigo is not None]
        primeiro = pedacos[indices[0]]
        if sobreposicao:
            separador = ""
            sobreposicao_chars = len(texto_de(sobreposicao))
        else:
            sobreposicao_chars = 0
            separador = "\n"
            if ultimo_emitido and pedacos[ultimo_emitido[-1]].unidade is primeiro.unidade:
                separador = " "   # o fragmento anterior terminou no meio da mesma unidade
        fragmentos.append(Fragmento(
            texto=texto, texto_embedding=texto_emb,
            pagina_inicio=min(pedacos[k].pagina_inicio for k in indices),
            pagina_fim=max(pedacos[k].pagina_fim for k in indices),
            artigo_inicio=min(artigos) if artigos else None,
            artigo_fim=max(artigos) if artigos else None,
            localizacao=primeiro.unidade.localizacao,
            secao_nome=primeiro.unidade.secao_nome,
            n_tokens=n_tokens, sobreposicao_chars=sobreposicao_chars,
            separador_anterior=separador if fragmentos else ""))
        ultimo_emitido[:] = indices

    def sem_titulos_no_fim(indices: list[int]) -> list[int]:
        conteudo = list(indices)
        while conteudo and pedacos[conteudo[-1]].eh_titulo:
            conteudo.pop()
        return conteudo

    def pequeno(indices: list[int], sobreposicao: list[int]) -> bool:
        """Pouco conteúdo (sem contar os títulos do fim, que vão para o
        fragmento seguinte). Fragmento só de títulos não conta."""
        conteudo = sem_titulos_no_fim(indices)
        return not sobreposicao and bool(conteudo) and soma(conteudo) < minimo

    def abre_o_seguinte(indices: list[int]) -> bool:
        """O fragmento pequeno introduz o que vem depois ("RESOLVE:",
        "Componentes Curriculares do", "CAMPUS BAGÉ")?"""
        final = pedacos[indices[-1]].texto
        letras = _letras_com_caixa(final)
        return final.endswith(":") or _titulo_incompleto(final) \
            or (final[-1:] not in ".;!?)" and bool(letras) and sum(c.isupper() for c in letras) >= 0.8 * len(letras))

    def juntar_ao_anterior(indices: list[int]) -> bool:
        """Estende o último fragmento emitido com `indices`, se couber (com o
        mesmo cabeçalho de contexto)."""
        if not fragmentos or not ultimo_emitido or ultimo_emitido[-1] + 1 != indices[0]:
            return False
        candidato = ultimo_emitido + indices
        tinha_cabecalho = fragmentos[-1].texto_embedding != prefixo + fragmentos[-1].texto
        texto_emb = embutido(candidato, tinha_cabecalho)
        n_tokens = contar(texto_emb)
        if n_tokens > limite_tokens:
            return False
        artigos = [pedacos[k].unidade.artigo for k in candidato if pedacos[k].unidade.artigo is not None]
        anterior = fragmentos[-1]
        anterior.texto, anterior.texto_embedding, anterior.n_tokens = texto_de(candidato), texto_emb, n_tokens
        anterior.pagina_inicio = min(pedacos[k].pagina_inicio for k in candidato)
        anterior.pagina_fim = max(pedacos[k].pagina_fim for k in candidato)
        anterior.artigo_inicio = min(artigos) if artigos else None
        anterior.artigo_fim = max(artigos) if artigos else None
        ultimo_emitido[:] = candidato
        return True

    def fechar(atual: list[int], sobreposicao: list[int]) -> list[int]:
        """Emite o fragmento e devolve os índices efetivamente emitidos.

        Antes de emitir: (1) devolve títulos soltos do fim para o próximo
        fragmento; (2) confere a contagem EXATA de tokens do texto vetorizado.
        Se passar do limite, tenta sem o cabeçalho de contexto, depois sem a
        sobreposição e, por fim, devolve a última frase ao próximo fragmento.
        """
        atual, sobreposicao = list(atual), list(sobreposicao)
        # Os títulos do fim passam para o próximo fragmento, a menos que o
        # fragmento seja só de títulos (devolver um a um deixava "UNIVERSIDADE
        # FEDERAL DO PAMPA", "CAMPUS BAGÉ"... sozinhos) ou que, sem eles, sobre
        # um fragmento pequeno demais.
        if not all(pedacos[k].eh_titulo for k in atual):
            conteudo = list(atual)
            while len(conteudo) - len(sobreposicao) > 1 and pedacos[conteudo[-1]].eh_titulo:
                conteudo.pop()
            if not pequeno(conteudo, sobreposicao):
                atual = conteudo
        while True:
            texto_emb = embutido(atual, True)
            n_tokens = contar(texto_emb)
            if n_tokens > limite_tokens:
                texto_emb = embutido(atual, False)
                n_tokens = contar(texto_emb)
            if n_tokens <= limite_tokens:
                break
            if sobreposicao:
                atual, sobreposicao = atual[len(sobreposicao):], []
            elif len(atual) > 1:
                atual.pop()
            else:
                break   # uma frase sozinha maior que o limite (não deve ocorrer)
        emitir(atual, sobreposicao, texto_emb, n_tokens)
        return atual

    ultimo_emitido: list[int] = []
    atual: list[int] = []
    sobreposicao_atual: list[int] = []
    i = 0
    while True:
        if i >= len(pedacos):
            if atual and len(atual) > len(sobreposicao_atual):
                if pequeno(atual, sobreposicao_atual) and juntar_ao_anterior(atual):
                    break
                emitidos = fechar(atual, sobreposicao_atual)
                if emitidos[-1] + 1 < len(pedacos):   # algo voltou: processa o resto
                    i, atual, sobreposicao_atual = emitidos[-1] + 1, [], []
                    continue
            break
        p = pedacos[i]
        if not atual:
            atual, sobreposicao_atual = [i], []
            i += 1
            continue
        cheio = soma(atual) + 1 + p.n_tokens > orcamento(atual)
        so_titulos = all(pedacos[k].eh_titulo for k in atual)
        quebra_estrutural = p.abre_bloco and not so_titulos and (
            p.eh_titulo or soma(atual) >= fracao_minima * orcamento(atual))
        if not (cheio or quebra_estrutural):
            atual.append(i)
            i += 1
            continue
        if pequeno(atual, sobreposicao_atual):
            if not cheio and abre_o_seguinte(atual):
                atual.append(i)          # segue junto com o assunto seguinte
                i += 1
                continue
            conteudo = sem_titulos_no_fim(atual)
            if juntar_ao_anterior(conteudo):
                # os títulos do fim (se houver) começam o próximo fragmento
                atual, sobreposicao_atual = atual[len(conteudo):], []
                continue
            if not cheio:
                atual.append(i)
                i += 1
                continue
        emitidos = fechar(atual, sobreposicao_atual)
        i = emitidos[-1] + 1
        # sobreposição: últimas frases do mesmo bloco, se o corte foi por tamanho
        proximo = pedacos[i]
        sobreposicao_atual = []
        if not proximo.abre_bloco and sobreposicao_tokens > 0:
            for k in reversed(emitidos[1:]):
                pk = pedacos[k]
                if pk.eh_titulo or not mesmo_bloco(pk, proximo):
                    break
                candidato = [k] + sobreposicao_atual
                if soma(candidato) > sobreposicao_tokens \
                        or soma(candidato) + 1 + proximo.n_tokens > orcamento(candidato):
                    break
                sobreposicao_atual = candidato
        atual = list(sobreposicao_atual)
    return fragmentos


def juntar_fragmentos_consecutivos(textos: list[str], sobreposicoes: list[int],
                                   separadores: list[str]) -> str:
    """Reconstrói o texto contínuo de fragmentos consecutivos sem repetir a
    sobreposição. Usado na montagem do contexto (consulta.py)."""
    resultado = textos[0]
    for texto, sobre, sep in zip(textos[1:], sobreposicoes[1:], separadores[1:]):
        resultado += texto[sobre:] if sobre else (sep or "\n") + texto
    return resultado


# ---------------------------------------------------------------------------
# 10. Pipeline completo de um PDF
# ---------------------------------------------------------------------------
_GENERICAS = ("UNIVERSIDADE FEDERAL", "MINISTÉRIO DA EDUCAÇÃO", "SERVIÇO PÚBLICO FEDERAL",
              "REPÚBLICA FEDERATIVA", "FUNDAÇÃO UNIVERSIDADE")


# Linha de identificação de um ato normativo, quase sempre em maiúsculas:
# "RESOLUÇÃO CONSUNI/UNIPAMPA Nº 300, DE 10 DE DEZEMBRO DE 2020".
_RE_IDENTIFICACAO_ATO = re.compile(
    r"^(?:RESOLU[ÇC][ÃA]O|PORTARIA|INSTRU[ÇC][ÃA]O\s+NORMATIVA|ORIENTA[ÇC][ÃA]O\s+NORMATIVA|EDITAL|DECRETO|"
    r"LEI|PARECER|NOTA\s+T[ÉE]CNICA|TERMO\s+DE\s+APOSTILAMENTO)\b.{0,80}?\bN(?:[º°o.]|[ÚU]MERO)?\s*\d+",
    re.IGNORECASE)
_RE_DATA_POR_EXTENSO = re.compile(r"(?:\bDE\s+)?\b\d{1,2}[º°]?\s+DE\s+[A-ZÇÃÉÍÓÚÂÊÔ]+\s+DE\s+\d{4}", re.IGNORECASE)
_SIGLAS = {"UNIPAMPA", "CONSUNI", "PROGRAD", "PROPPI", "PROEXT", "PRAEC", "GR", "MEC", "CNE", "CES", "CP",
           "SEI", "UAB", "EAD", "PPC", "TCC", "NDE", "ABNT", "PET", "PDA", "CIFOR", "NUDE", "SISU", "ENEM",
           "ENADE", "PIBID", "CAPES", "CNPQ", "UFSM", "UFPEL"}


def _formatar_ato(texto: str) -> str:
    """"RESOLUÇÃO CONSUNI/UNIPAMPA Nº 300, DE 10 DE DEZEMBRO DE 2020" ->
    "Resolução CONSUNI/UNIPAMPA nº 300, de 10 de dezembro de 2020"."""
    palavras = []
    for p in texto.split():
        nucleo = p.strip(",.;:()")
        palavras.append(p if ("/" in nucleo or nucleo.upper() in _SIGLAS) else p.lower())
    frase = " ".join(palavras)
    return frase[:1].upper() + frase[1:]


def _identificacao_do_ato(paginas: list[PaginaExtraida]) -> str:
    """Procura a linha que identifica o ato (Resolução, Portaria, Instrução
    Normativa...) nas primeiras linhas das duas primeiras páginas com texto.
    Só vale linha em maiúsculas: uma frase do preâmbulo que começa com
    "Resolução nº 5..." não é o título."""
    vistas = 0
    for pagina in paginas:
        linhas = [l.visivel for l in pagina.linhas if l.visivel]
        if not linhas:
            continue
        for i, texto in enumerate(linhas[:30]):
            letras = _letras_com_caixa(texto)
            if _RE_IDENTIFICACAO_ATO.match(texto) and letras and sum(c.isupper() for c in letras) >= 0.8 * len(letras):
                if m := _RE_DATA_POR_EXTENSO.search(texto):
                    texto = texto[:m.end()]
                else:
                    # sem a data na linha: corta o que sobra depois do último trecho
                    # com algarismos (carimbo ou rubrica lidos pelo OCR) e procura a
                    # data na linha seguinte ("de 20 de novembro de 2018")
                    palavras = texto.split()
                    ultimo = max(k for k, w in enumerate(palavras) if re.search(r"\d", w))
                    texto = " ".join(palavras[:ultimo + 1])
                    if i + 1 < len(linhas) and (m := _RE_DATA_POR_EXTENSO.search(linhas[i + 1])):
                        data = m.group(0)
                        texto += (" " if data[:2].lower() == "de" else ", ") + data
                return _formatar_ato(texto)[:150]
        vistas += 1
        if vistas == 2:
            break
    return ""


def titulo_do_documento(nome_arquivo: str, paginas: list[PaginaExtraida], corpo: float) -> str:
    """Título legível do documento, para o prompt e os relatórios.

    1. Linha de identificação do ato ("Resolução CONSUNI/UNIPAMPA nº 300, de
       10 de dezembro de 2020"), quando existe: em muitas resoluções ela tem
       o mesmo corpo de letra do texto e a regra 2 não a encontrava.
    2. Na primeira página com texto, a linha de letra MAIOR que o corpo do
       texto (título de capa), pulando linhas institucionais genéricas
       ("UNIVERSIDADE FEDERAL DO PAMPA"...); linhas seguidas do mesmo tamanho
       são unidas (título em duas linhas). Título curto demais ("Unipampa •
       2026", na capa de um guia) não vale.
    3. Sem nada disso, o nome do arquivo, que costuma ser o identificador
       mais confiável.
    """
    if ato := _identificacao_do_ato(paginas):
        return ato
    for pagina in paginas:
        linhas = [l for l in pagina.linhas if l.visivel]
        if not linhas:
            continue
        candidatas = [l for l in linhas
                      if 8 <= len(l.visivel) <= 150 and len(_letras_com_caixa(l.visivel)) >= 5
                      and l.tamanho > corpo + 0.5
                      and not any(g in l.visivel.upper() for g in _GENERICAS)]
        if candidatas:
            maior = max(l.tamanho for l in candidatas)
            inicio = linhas.index(next(l for l in candidatas if l.tamanho == maior))
            partes = []
            for l in linhas[inicio:inicio + 3]:
                if l.tamanho != maior or any(g in l.visivel.upper() for g in _GENERICAS):
                    break
                partes.append(l.visivel)
            titulo = _capitalizar_se_maiusculo(" ".join(partes))[:150]
            if len(titulo.split()) >= 2 and len(_letras_com_caixa(titulo)) >= 12:
                return titulo
        break
    return re.sub(r"[-_]+", " ", Path(nome_arquivo).stem).strip()


def processar_pdf(caminho_pdf: str | Path, contar: ContadorTokens,
                  opcoes: OpcoesProcessamento) -> DocumentoProcessado:
    """Executa todas as etapas para um PDF e devolve fragmentos e diagnóstico."""
    caminho_pdf = Path(caminho_pdf)
    paginas = extrair_paginas(caminho_pdf, opcoes)
    doc = DocumentoProcessado(nome=caminho_pdf.name, titulo="", n_paginas=len(paginas),
                              limite_tokens=opcoes.limite_tokens)
    doc.paginas_sem_texto = [p.numero for p in paginas if not p.tem_texto]
    doc.paginas_ilegiveis = [p.numero for p in paginas if p.caracteres and p.ilegiveis > 0.05 * p.caracteres]
    doc.paginas_ocr = [p.numero for p in paginas if any(l.ocr and l.visivel for l in p.linhas)]
    doc.trechos_riscados = [{"pagina": p.numero, "texto": t} for p in paginas for t in p.riscados]
    doc.n_tabelas = sum(isinstance(e, Tabela) for p in paginas for e in p.elementos)
    doc.linhas_removidas = remover_cabecalhos_rodapes(paginas)
    doc.linhas_sumario = remover_sumarios(paginas)
    doc.corpo_texto = tamanho_do_corpo(paginas)
    _continuar_cabecalhos(paginas, doc.corpo_texto)
    doc.titulo = titulo_do_documento(caminho_pdf.name, paginas, doc.corpo_texto)
    doc.hifenizacao_silabica = detectar_hifenizacao_silabica(paginas)
    unidades, _ = montar_unidades(paginas, doc.corpo_texto, doc.hifenizacao_silabica)
    if opcoes.descartar_alteradas:
        anotar_contexto(unidades)          # a revogação em bloco usa o número do artigo
        unidades, doc.revogados_em_bloco = descartar_revogados_em_bloco(unidades)
        unidades, doc.redacoes_descartadas, doc.anotacoes_nao_resolvidas = \
            descartar_redacoes_alteradas(unidades)
    anotar_contexto(unidades)
    doc.unidades = unidades
    doc.fragmentos = segmentar(unidades, contar, opcoes.limite_tokens, opcoes.sobreposicao_tokens,
                               incluir_contexto=opcoes.incluir_contexto, prefixo=opcoes.prefixo)
    return doc
