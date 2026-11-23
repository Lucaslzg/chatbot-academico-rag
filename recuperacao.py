"""Recuperação: busca dos trechos e montagem do contexto (Seções 3.5, 3.6 e 5.6).

Este módulo não conhece o LLM. Ele entrega um Contexto (pergunta, trechos
numerados, decisão do limiar e configuração da busca) e não sabe quem vai
lê-lo: o chat (consulta.py) ou a rodada de testes com vários modelos. Como os
dois usam o mesmo código, o que os testes medem é o que o chat faz.

Modos de busca (config.MODO_BUSCA):

* "densa": por sentido. A pergunta vira um vetor com o mesmo modelo de
  embeddings da indexação, e o ChromaDB devolve os fragmentos mais próximos
  (similaridade de cosseno). É a busca original do protótipo.
* "bm25": por palavras (Robertson; Zaragoza, 2009). Soma as palavras da
  pergunta que aparecem no fragmento, com mais peso para as raras e desconto
  para os fragmentos longos. Serve de referência na avaliação.
* "hibrida": as duas buscas, juntas pela posição de cada fragmento em cada
  lista (Reciprocal Rank Fusion; Cormack; Clarke; Büttcher, 2009).

O índice do BM25 é montado em memória, na primeira busca, a partir dos
fragmentos que já estão no ChromaDB: não há segundo banco para sincronizar, e
as duas buscas sempre leem os mesmos fragmentos. Depois de reindexar, reinicie
o chat para o índice ser montado de novo.

O limiar (config.SIMILARIDADE_MINIMA) vale igual nos três modos, sempre pela
similaridade da busca densa:

1. abstenção antes do LLM (RF06): se nem o fragmento mais parecido chega ao
   limiar, o contexto sai vazio e o sistema se abstém;
2. corte por trecho: só entram no contexto fragmentos com similaridade de pelo
   menos o limiar; entre eles, os TOP_K mais bem colocados na ordem da busca.
   Na busca densa, é exatamente o que o chat já fazia. Na híbrida, as palavras
   podem mudar a escolha entre os trechos que passam no corte, mas nunca põem
   no contexto um trecho que a busca densa considera fraco (requisito do
   trabalho: melhor não responder do que responder com base fraca).
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field

import numpy as np

import config
from processamento import juntar_fragmentos_consecutivos
from vetorial import (ModeloEmbeddings, abrir_cliente, assinatura, carregar_titulos, id_fragmento,
                      nome_colecao, obter_colecao, parametros_indice)

MODOS_BUSCA = ("densa", "bm25", "hibrida")

# Quantas posições do ranking ficam guardadas no Contexto. O registro do chat
# e a avaliação da busca (acerto@1, acerto@k e MRR) olham até a 10ª posição.
PROFUNDIDADE = 10

# Resultados a mais pedidos ao ChromaDB além dos necessários, para desfazer
# empates na fronteira (ver Recuperador._busca_densa).
MARGEM_EMPATES = 10


# ===========================================================================
# Erros com mensagem para o usuário final
# ===========================================================================
class ErroChatbot(Exception):
    """Erro com mensagem pronta para mostrar ao usuário (base dos erros do chatbot)."""


class ErroBusca(ErroChatbot):
    """Erro da busca."""


class ErroBaseVazia(ErroBusca):
    pass


# ===========================================================================
# Estruturas de dados
# ===========================================================================
@dataclass
class Trecho:
    """Fragmento devolvido pela busca."""
    id: str
    texto: str
    metadados: dict
    similaridade: float                 # cosseno com a pergunta (busca densa), em qualquer modo
    nota: float | None = None           # o que ordena o modo: cosseno, nota do BM25 ou da fusão
    posicao_densa: int | None = None    # 1 = 1º da busca densa; None = fora dos candidatos dela
    posicao_bm25: int | None = None     # 1 = 1º do BM25; None = fora dos candidatos dele
    nota_bm25: float | None = None

    @property
    def fonte(self) -> str:
        return self.metadados.get("fonte", "?")

    @property
    def indice(self) -> int:
        return int(self.metadados.get("indice", 0))

    @property
    def ordem(self) -> float:
        """Critério de ordenação: a nota do modo ou, sem ela, a similaridade."""
        return self.similaridade if self.nota is None else self.nota


@dataclass
class Passagem:
    """Texto contínuo entregue ao LLM: um ou mais fragmentos vizinhos unidos."""
    numero: int
    fonte: str
    documento: str
    texto: str
    pagina_inicio: int
    pagina_fim: int
    artigo_inicio: int | None
    artigo_fim: int | None
    localizacao: str
    secao: str
    similaridade: float           # maior similaridade entre os fragmentos que a originaram
    ids: list[str] = field(default_factory=list)

    @property
    def paginas(self) -> str:
        if self.pagina_inicio == self.pagina_fim:
            return f"p. {self.pagina_inicio}"
        return f"p. {self.pagina_inicio}-{self.pagina_fim}"

    @property
    def artigos(self) -> str:
        if self.artigo_inicio is None:
            return ""
        if self.artigo_inicio == self.artigo_fim:
            return f"Art. {self.artigo_inicio}"
        return f"Arts. {self.artigo_inicio} a {self.artigo_fim}"

    def referencia(self) -> str:
        """Ex.: "res-29_2011-...pdf, p. 10-11, Arts. 47 a 48"."""
        return ", ".join(p for p in (self.fonte, self.paginas, self.artigos) if p)


@dataclass
class Contexto:
    """O que a busca entrega à geração: a pergunta, os trechos numerados e a decisão do limiar."""
    pergunta: str
    passagens: list[Passagem]
    recuperados: list[Trecho]           # os primeiros do ranking (até PROFUNDIDADE), com as posições
    maior_similaridade: float           # melhor similaridade da busca densa (decide a abstenção)
    abstencao_previa: bool              # nada passou no limiar: o LLM não é chamado
    configuracao: dict = field(default_factory=dict)
    tempo_s: float = 0.0

    def para_dict(self) -> dict:
        """Tudo o que o modelo de linguagem recebe e a decisão do limiar, para
        gravar em arquivo. As rodadas de avaliação congelam assim o contexto de
        cada pergunta: todos os modelos recebem exatamente os mesmos trechos."""
        return asdict(self)

    @classmethod
    def de_dict(cls, dados: dict) -> "Contexto":
        """O inverso de para_dict (lê um contexto congelado)."""
        return cls(pergunta=dados["pergunta"],
                   passagens=[Passagem(**p) for p in dados.get("passagens", [])],
                   recuperados=[Trecho(**t) for t in dados.get("recuperados", [])],
                   maior_similaridade=float(dados.get("maior_similaridade", 0.0)),
                   abstencao_previa=bool(dados.get("abstencao_previa", False)),
                   configuracao=dict(dados.get("configuracao", {})),
                   tempo_s=float(dados.get("tempo_s", 0.0)))


# ===========================================================================
# Busca por palavras (BM25)
# ===========================================================================
def _sem_acento(texto: str) -> str:
    """Minúsculas e sem acentos ("Ação" -> "acao"). Os demais caracteres fora
    de a-z e 0-9 (travessões, "§", "º", símbolos) ficam e, na tokenização,
    separam palavras: "2019–2023" vira "2019" e "2023", e não "20192023"."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


# Palavras sem conteúdo próprio (artigos, preposições, conjunções, pronomes,
# interrogativos e alguns verbos muito frequentes), comparadas sem acentos.
# Lista curta, fixada antes de medir. Números e algarismos romanos ficam:
# "Cálculo I" e "Cálculo II" continuam diferentes.
PALAVRAS_VAZIAS = frozenset(_sem_acento(p) for p in (
    "a o as os um uma uns umas de da do das dos em na no nas nos ao aos à às "
    "para pra por pelo pela pelos pelas com sem sob sobre entre e ou que se como qual quais "
    "quando onde quem cujo cuja é ser são foi há ter tem têm meu minha seu sua seus suas "
    "eu ele ela eles elas isso isto esse essa este esta posso pode podem").split())

_RE_PALAVRA = re.compile(r"[a-z0-9]+")


def tokenizar(texto: str) -> list[str]:
    """Palavras do texto, sem acentos, em minúsculas e sem as palavras vazias.

    Ex.: "Qual o período do trancamento total em 2026/1?" ->
    ["periodo", "trancamento", "total", "2026", "1"].
    """
    return [p for p in _RE_PALAVRA.findall(_sem_acento(texto)) if p not in PALAVRAS_VAZIAS]


def texto_para_bm25(texto: str, metadados: dict, incluir_cabecalho: bool = True) -> str:
    """Texto que o BM25 lê: o do fragmento, mais o nome da seção e o "Art. N".

    São as mesmas informações do cabeçalho de contexto que vai na frente do
    texto vetorizado (CONTEXTO_NO_EMBEDDING), lidas dos metadados: o texto
    guardado no ChromaDB não tem o cabeçalho.
    """
    if not incluir_cabecalho:
        return texto
    artigo = metadados.get("artigo_inicio")
    cabecalho = " ".join(p for p in (metadados.get("secao", ""),
                                     f"Art. {artigo}" if artigo is not None else "") if p)
    return cabecalho + "\n" + texto


class IndiceBM25:
    """Índice invertido com a nota BM25 (Robertson; Zaragoza, 2009).

    nota(fragmento) = soma, para cada palavra da pergunta presente nele, de
        idf * f * (k1 + 1) / (f + k1 * (1 - b + b * comprimento / comprimento_medio))
    com f = vezes que a palavra aparece no fragmento e
        idf = ln(1 + (N - n + 0,5) / (n + 0,5)),
    em que N é o total de fragmentos e n, os que têm a palavra. Palavras raras
    pesam mais; repetir a palavra ajuda cada vez menos (k1); fragmentos longos
    recebem desconto (b).
    """

    def __init__(self, ids: list[str], textos: list[str], k1: float | None = None,
                 b: float | None = None) -> None:
        self.k1 = config.BM25_K1 if k1 is None else k1
        self.b = config.BM25_B if b is None else b
        self.ids = list(ids)
        self._ocorrencias: dict[str, list[tuple[int, int]]] = {}
        self._comprimentos: list[int] = []
        for j, texto in enumerate(textos):
            palavras = tokenizar(texto)
            self._comprimentos.append(len(palavras))
            for palavra, frequencia in Counter(palavras).items():
                self._ocorrencias.setdefault(palavra, []).append((j, frequencia))
        n = len(self.ids)
        self.comprimento_medio = sum(self._comprimentos) / n if n else 0.0
        self._idf = {p: math.log(1 + (n - len(o) + 0.5) / (len(o) + 0.5)) for p, o in self._ocorrencias.items()}

    def __len__(self) -> int:
        return len(self.ids)

    def buscar(self, pergunta: str, n: int) -> list[tuple[str, float]]:
        """Os n fragmentos de maior nota, como (id, nota). Fragmento sem nenhuma
        palavra da pergunta não entra. Empates: id em ordem alfabética."""
        notas: dict[int, float] = {}
        # ordem fixa das palavras: a soma em ponto flutuante sai sempre igual
        for palavra in sorted(set(tokenizar(pergunta))):
            ocorrencias = self._ocorrencias.get(palavra)
            if not ocorrencias:
                continue
            idf = self._idf[palavra]
            for j, frequencia in ocorrencias:
                relativo = self._comprimentos[j] / self.comprimento_medio if self.comprimento_medio else 1.0
                denominador = frequencia + self.k1 * (1 - self.b + self.b * relativo)
                notas[j] = notas.get(j, 0.0) + idf * frequencia * (self.k1 + 1) / denominador
        ordem = sorted(notas.items(), key=lambda par: (-par[1], self.ids[par[0]]))
        return [(self.ids[j], nota) for j, nota in ordem[:n]]


# ===========================================================================
# Fusão das duas listas
# ===========================================================================
def fundir_rrf(listas: list[list[str]], k: int | None = None) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (Cormack; Clarke; Büttcher, 2009).

    Cada fragmento soma 1/(k + posição) em cada lista em que aparece (posição 1
    = primeiro). As notas das buscas não entram: cosseno e BM25 têm escalas
    diferentes, e a posição é comparável. O que as duas buscas acham bom sobe.
    Empates: melhor posição em qualquer lista, depois o id.
    """
    k = config.RRF_K if k is None else k
    notas: dict[str, float] = {}
    melhor: dict[str, int] = {}
    for lista in listas:
        for posicao, ident in enumerate(lista, start=1):
            notas[ident] = notas.get(ident, 0.0) + 1.0 / (k + posicao)
            melhor[ident] = min(melhor.get(ident, posicao), posicao)
    return sorted(notas.items(), key=lambda par: (-par[1], melhor[par[0]], par[0]))


# ===========================================================================
# Recuperador
# ===========================================================================
class Recuperador:
    """Busca (densa, BM25 ou híbrida), limiar, vizinhos e limite de texto.

    Recursos pesados (modelo de embeddings, base, índice do BM25) são
    carregados sob demanda.
    """

    def __init__(self, modelo: ModeloEmbeddings | None = None, colecao=None,
                 titulos: dict[str, str] | None = None) -> None:
        self.modelo = modelo or ModeloEmbeddings()
        self._colecao = colecao
        # título de cada documento no prompt (data/titulos_documentos.json)
        self.titulos = carregar_titulos() if titulos is None else titulos
        self._bm25: IndiceBM25 | None = None
        self._dados: dict[str, tuple[str, dict]] = {}

    # Recursos
    @property
    def colecao(self):
        if self._colecao is None:
            colecao = obter_colecao(abrir_cliente(), nome_colecao(self.modelo.nome))
            if colecao is None or colecao.count() == 0:
                raise ErroBaseVazia(
                    f"A base vetorial do modelo '{self.modelo.nome}' está vazia ou ainda não existe. "
                    "Rode antes a indexação: indexar.bat (ou python ingestao.py).")
            self._colecao = colecao
        return self._colecao

    def verificar_base(self) -> list[str]:
        """Confere se a base foi indexada com os parâmetros atuais."""
        avisos = []
        atual = assinatura(parametros_indice(self.modelo))
        if (self.colecao.metadata or {}).get("assinatura") != atual:
            avisos.append("A configuração de indexação mudou desde a última indexação (config.py). "
                          "Rode indexar.bat para atualizar a base; até lá, as respostas usam a base antiga.")
        return avisos

    @staticmethod
    def modo_valido(modo: str | None = None) -> str:
        modo = modo or config.MODO_BUSCA
        if modo not in MODOS_BUSCA:
            raise ErroBusca(f"Modo de busca inválido: '{modo}'. Use um destes no config.py "
                            "(MODO_BUSCA): 'densa', 'bm25' ou 'hibrida'.")
        return modo

    def aquecer(self) -> None:
        """Carrega o modelo de embeddings antes da primeira busca (o tempo de carga
        não entra no tempo da primeira pergunta)."""
        self.modelo.codificar_consultas(["aquecimento"])

    def preparar(self, modo: str | None = None) -> None:
        """Monta o índice do BM25 antes da primeira pergunta, quando o modo usa."""
        if self.modo_valido(modo) != "densa":
            _ = self.indice_bm25

    @property
    def indice_bm25(self) -> IndiceBM25:
        """Índice do BM25 sobre todos os fragmentos da base (montado uma vez)."""
        if self._bm25 is None:
            dados = self.colecao.get(include=["documents", "metadatas"])
            ids, textos, metadados = dados["ids"], dados["documents"], dados["metadatas"]
            self._dados = {i: (t, m) for i, t, m in zip(ids, textos, metadados)}
            incluir = bool(config.CONTEXTO_NO_EMBEDDING)
            self._bm25 = IndiceBM25(ids, [texto_para_bm25(t, m, incluir) for t, m in zip(textos, metadados)])
        return self._bm25

    # Buscas
    def _busca_densa(self, vetor: list[float], n: int) -> list[Trecho]:
        """Os n fragmentos mais próximos da pergunta, por cosseno.

        Fragmentos com o mesmo texto (um parágrafo igual nos dois PPCs, por
        exemplo) têm o mesmo vetor e empatam. O ChromaDB devolve os empatados
        numa ordem que pode mudar de uma execução para outra, então a busca
        pede alguns resultados a mais, ordena por similaridade e, no empate,
        pelo id, e só corta onde não há empate com quem ficou de fora. Assim os
        empates saem sempre na mesma ordem, no chat e na avaliação.
        """
        total = self.colecao.count()
        n = min(n, total)
        pedir = min(total, n + MARGEM_EMPATES)
        while True:
            resultado = self.colecao.query(query_embeddings=[vetor], n_results=pedir,
                                           include=["documents", "metadatas", "distances"])
            trechos = [Trecho(id=i, texto=d, metadados=m, similaridade=1.0 - float(dist),
                              nota=1.0 - float(dist))
                       for i, d, m, dist in zip(resultado["ids"][0], resultado["documents"][0],
                                                resultado["metadatas"][0], resultado["distances"][0])]
            trechos.sort(key=lambda t: (-t.similaridade, t.id))
            # o n-ésimo não pode empatar com o último devolvido: senão, pode haver
            # outro empatado fora da consulta, e a escolha entre eles seria do acaso
            if pedir >= total or len(trechos) <= n or trechos[n - 1].similaridade > trechos[-1].similaridade:
                break
            pedir = min(total, 2 * pedir)
        trechos = trechos[:n]
        for posicao, trecho in enumerate(trechos, 1):
            trecho.posicao_densa = posicao
        return trechos

    def _similaridades(self, vetor: list[float], ids: list[str]) -> dict[str, float]:
        """Cosseno da pergunta com fragmentos que a busca densa não trouxe.

        Os vetores guardados e o da pergunta são normalizados: o cosseno é o
        produto escalar (o mesmo valor que a busca densa daria).
        """
        if not ids:
            return {}
        dados = self.colecao.get(ids=list(ids), include=["embeddings"])
        pergunta = np.asarray(vetor, dtype=float)
        return {i: float(np.dot(pergunta, np.asarray(e, dtype=float)))
                for i, e in zip(dados["ids"], dados["embeddings"])}

    @staticmethod
    def _profundidade(k: int, modo: str) -> int:
        if modo == "densa":
            return max(k, PROFUNDIDADE)
        return max(k, PROFUNDIDADE, config.CANDIDATOS_FUSAO)

    def _candidatos(self, pergunta: str, modo: str, profundidade: int) -> tuple[list[Trecho], float]:
        """Ranking completo do modo e a melhor similaridade da busca densa.

        A busca densa roda em qualquer modo: é ela que decide a abstenção e dá a
        similaridade de cada candidato para o corte.
        """
        vetor = self.modelo.codificar_consulta(pergunta)
        densos = self._busca_densa(vetor, profundidade)
        maior = densos[0].similaridade if densos else 0.0
        if modo == "densa":
            return densos, maior

        palavras = self.indice_bm25.buscar(pergunta, profundidade)
        posicao_bm25 = {ident: p for p, (ident, _) in enumerate(palavras, 1)}
        nota_bm25 = dict(palavras)
        if modo == "bm25":
            ordem = palavras
        else:
            ordem = fundir_rrf([[t.id for t in densos], [ident for ident, _ in palavras]], config.RRF_K)

        similaridades = {t.id: t.similaridade for t in densos}
        similaridades.update(self._similaridades(vetor, [i for i, _ in ordem if i not in similaridades]))
        dados = {t.id: (t.texto, t.metadados) for t in densos}
        posicao_densa = {t.id: t.posicao_densa for t in densos}
        candidatos = []
        for ident, nota in ordem:
            texto, metadados = dados.get(ident) or self._dados[ident]
            candidatos.append(Trecho(id=ident, texto=texto, metadados=metadados,
                                     similaridade=similaridades.get(ident, 0.0), nota=nota,
                                     posicao_densa=posicao_densa.get(ident),
                                     posicao_bm25=posicao_bm25.get(ident), nota_bm25=nota_bm25.get(ident)))
        return candidatos, maior

    def buscar(self, pergunta: str, n: int | None = None, modo: str | None = None) -> list[Trecho]:
        """Os n primeiros do ranking do modo, sem limiar (para a avaliação da busca)."""
        modo = self.modo_valido(modo)
        n = n or config.TOP_K
        candidatos, _ = self._candidatos(pergunta, modo, self._profundidade(n, modo))
        return candidatos[:n]

    def recuperar(self, pergunta: str, k: int | None = None, modo: str | None = None) -> Contexto:
        """Busca, limiar, corte, vizinhos e limite de texto: o contexto do LLM."""
        inicio = time.perf_counter()
        modo = self.modo_valido(modo)
        k = k or config.TOP_K
        candidatos, maior = self._candidatos(pergunta, modo, self._profundidade(k, modo))
        limiar = config.SIMILARIDADE_MINIMA
        passagens: list[Passagem] = []
        if maior >= limiar:
            selecionados = [t for t in candidatos if t.similaridade >= limiar][:k]
            if selecionados:
                passagens = self.montar_passagens(selecionados)
        return Contexto(pergunta=pergunta, passagens=passagens,
                        recuperados=candidatos[:max(k, PROFUNDIDADE)], maior_similaridade=maior,
                        abstencao_previa=not passagens, configuracao=self.configuracao(modo, k),
                        tempo_s=round(time.perf_counter() - inicio, 3))

    def configuracao(self, modo: str, k: int) -> dict:
        """Parâmetros da busca, gravados com cada contexto (reprodutibilidade)."""
        dados = {"modo_busca": modo, "modelo_embeddings": self.modelo.nome,
                 "assinatura_base": (self.colecao.metadata or {}).get("assinatura"), "top_k": k,
                 "similaridade_minima": config.SIMILARIDADE_MINIMA, "janela_vizinhos": config.JANELA_VIZINHOS,
                 "contexto_max_caracteres": config.CONTEXTO_MAX_CARACTERES}
        if modo != "densa":
            dados.update(candidatos_fusao=config.CANDIDATOS_FUSAO, rrf_k=config.RRF_K, bm25_k1=config.BM25_K1,
                         bm25_b=config.BM25_B, bm25_cabecalho=bool(config.CONTEXTO_NO_EMBEDDING))
        return dados

    # Montagem do contexto
    def montar_passagens(self, trechos: list[Trecho], janela: int | None = None) -> list[Passagem]:
        """Amplia cada fragmento com seus vizinhos e une o que se sobrepõe.

        Fragmentos do mesmo documento cujas janelas se tocam viram uma única
        passagem contínua (sem repetir texto). As passagens saem na ordem da
        busca: primeiro a do trecho de maior nota; no empate de notas, a do
        trecho que veio antes na lista recebida (a ordem do ranking).
        """
        janela = config.JANELA_VIZINHOS if janela is None else janela
        intervalos: dict[str, list[list]] = {}
        for posicao, t in enumerate(trechos):
            ultimo = int(t.metadados.get("n_fragmentos", t.indice + 1)) - 1
            intervalos.setdefault(t.fonte, []).append(
                [max(0, t.indice - janela), min(ultimo, t.indice + janela), t.ordem, t.similaridade, posicao])
        unidos: list[tuple[str, int, int, float, float, int]] = []
        for fonte, lista in intervalos.items():
            lista.sort()
            atual = lista[0]
            for ini, fim, ordem, sim, posicao in lista[1:]:
                if ini <= atual[1] + 1:
                    atual[1], atual[2] = max(atual[1], fim), max(atual[2], ordem)
                    atual[3], atual[4] = max(atual[3], sim), min(atual[4], posicao)
                else:
                    unidos.append((fonte, *atual))
                    atual = [ini, fim, ordem, sim, posicao]
            unidos.append((fonte, *atual))

        ids = [id_fragmento(f, i) for f, ini, fim, *_ in unidos for i in range(ini, fim + 1)]
        dados = self.colecao.get(ids=ids, include=["documents", "metadatas"])
        mapa = {i: (d, m) for i, d, m in zip(dados["ids"], dados["documents"], dados["metadatas"])}

        passagens: list[Passagem] = []
        for fonte, ini, fim, _, sim, _ in sorted(unidos, key=lambda u: (-u[3], u[5])):
            partes = [(id_fragmento(fonte, i), *mapa[id_fragmento(fonte, i)])
                      for i in range(ini, fim + 1) if id_fragmento(fonte, i) in mapa]
            if not partes:
                continue
            metas = [m for _, _, m in partes]
            texto = juntar_fragmentos_consecutivos(
                [d for _, d, _ in partes],
                [0] + [int(m.get("sobreposicao_chars", 0)) for m in metas[1:]],
                [""] + [m.get("separador_anterior", "\n") for m in metas[1:]])
            artigos = [a for m in metas for a in (m.get("artigo_inicio"), m.get("artigo_fim")) if a is not None]
            passagens.append(Passagem(
                numero=len(passagens) + 1, fonte=fonte,
                documento=self.titulos.get(fonte) or metas[0].get("documento", fonte),
                texto=texto, pagina_inicio=min(int(m.get("pagina", 0)) for m in metas),
                pagina_fim=max(int(m.get("pagina_fim", m.get("pagina", 0))) for m in metas),
                artigo_inicio=min(artigos) if artigos else None,
                artigo_fim=max(artigos) if artigos else None,
                localizacao=metas[0].get("localizacao", ""), secao=metas[0].get("secao", ""),
                similaridade=sim, ids=[i for i, _, _ in partes]))
        return self._limitar_contexto(passagens)

    @staticmethod
    def _limitar_contexto(passagens: list[Passagem]) -> list[Passagem]:
        """Limita o texto entregue ao LLM a CONTEXTO_MAX_CARACTERES.

        O limite é fixo, e não calculado da janela do LLM: qualquer modelo
        recebe exatamente os mesmos trechos. Passagens que excedem o limite (as
        menos relevantes, que vêm por último) ficam de fora; a primeira sempre
        entra.
        """
        selecionadas, total = [], 0
        for p in passagens:
            if selecionadas and total + len(p.texto) > config.CONTEXTO_MAX_CARACTERES:
                break
            selecionadas.append(p)
            total += len(p.texto)
        for n, p in enumerate(selecionadas, 1):
            p.numero = n
        return selecionadas
