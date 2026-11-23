"""Avaliação da busca (recuperação) com um conjunto de perguntas de teste.

    python avaliar_recuperacao.py                    # avalia a base indexada (busca do config.py)
    python avaliar_recuperacao.py --modo hibrida     # avalia a base com outra busca
    python avaliar_recuperacao.py --comparar-buscas  # compara as buscas densa, BM25 e híbrida
    python avaliar_recuperacao.py --comparar         # compara a segmentação anterior com a atual
    python avaliar_recuperacao.py --k 6              # outro número de fragmentos por pergunta
    python avaliar_recuperacao.py --arquivo avaliacao/outro.csv   # outro conjunto de perguntas

As perguntas vêm do arquivo de config.ARQUIVO_PERGUNTAS (ou de --arquivo),
lido e conferido pelo perguntas.py; um arquivo com erros não é avaliado.
Entram na avaliação da busca as perguntas sem resposta (para o limiar) e as
respondíveis que dizem onde está a resposta; as respondíveis sem esse local
(o normal nas perguntas reais) ficam de fora e são listadas. A busca delas é
medida na avaliação das respostas, pela cobertura dos trechos (o RAGAS confere
se os trechos contêm o que diz a resposta correta).

Não usa o LLM: mede só se a busca encontra o trecho certo (a "precisão do
contexto" da Seção 2.2.2 da monografia). Usa só o recuperacao.py, o mesmo
módulo de busca do chat, e não importa a parte de geração. Cada pergunta respondível do arquivo
avaliacao/perguntas_recuperacao.json diz onde está a resposta, com um ou mais
destes critérios (todos os que aparecem precisam valer; na planilha das
perguntas reais, as colunas fonte, artigos e paginas, todas opcionais):

* "fonte": nome do PDF em data/documentos;
* "artigos": o fragmento cobre algum destes artigos (normas);
* "paginas": [primeira, última], o fragmento toca este intervalo de páginas
  (PPCs, manuais e outros documentos sem artigos);
* "trecho": o texto do fragmento contém este trecho (sem diferenciar
  maiúsculas, acentos e espaços; útil em tabelas, como o calendário).

Quando a resposta pode estar em mais de um lugar (a Res. 29/2011 e a Res.
480/2026 tratam da frequência mínima, por exemplo), a pergunta traz uma lista
"alternativas" com um conjunto de critérios em cada item; basta atender a um.
Um fragmento recuperado conta como relevante quando atende aos critérios.
Métricas:

* acerto@1: o 1º fragmento recuperado é relevante;
* acerto@k: algum dos TOP_K fragmentos recuperados é relevante;
* contexto@k: o texto que chega ao LLM (os TOP_K fragmentos mais os vizinhos
  que os acompanham) contém o artigo esperado. É a métrica que decide a
  comparação entre segmentações de tamanhos diferentes, e corresponde à
  abrangência do contexto (context recall) do RAGAS, Seção 2.2.2. Na base
  indexada, o contexto é exatamente o do chat: já com o limiar
  (SIMILARIDADE_MINIMA) e o corte por trecho;
* MRR: média de 1/posição do primeiro fragmento relevante (1,0 = sempre em 1º);
* perdidas pelo corte: perguntas em que o trecho certo estava entre os TOP_K
  primeiros da busca, mas ficou fora do contexto por ter similaridade abaixo
  do limiar. É o custo do corte, que existe para evitar respostas com base
  fraca.

acerto@1, acerto@k e MRR olham a ordem da busca (na híbrida, a da fusão);
contexto@k olha o que o LLM recebe.

Para as perguntas sem resposta no documento, mostra a similaridade do
fragmento mais próximo e sugere um valor para SIMILARIDADE_MINIMA que não
bloqueie nenhuma pergunta respondível. A similaridade é sempre a da busca
densa, que decide a abstenção em qualquer modo.

O modo --comparar-buscas avalia a mesma base com as três buscas (densa, BM25
e híbrida) e aplica o teste de McNemar exato ao contexto@k: considera só as
perguntas em que as duas buscas discordam (uma põe o trecho certo no
contexto e a outra não) e diz se essa diferença pode ser acaso.

Os resultados vão para avaliacao/resultados/ (JSON), com a data, a hora e o
nome do conjunto de perguntas no nome do arquivo; dentro, a versão do código e
o arquivo e a assinatura das perguntas usadas. Cada pergunta leva a
lista "recuperados": os 10 primeiros fragmentos, com documento, páginas,
artigos, similaridade, se atende ao critério e o começo do texto. É ela que
mostra o que a busca trouxe no lugar do trecho esperado; no detalhe impresso,
cada FALHA mostra o fragmento que veio em 1º.

O modo --comparar monta em memória (sem mexer na base) três versões do índice
com o mesmo modelo de embeddings e as mesmas perguntas, com todos os PDFs de
data/documentos (como na base real; --so-fontes usa só os documentos citados
nas perguntas, mais rápido e menos realista):
  1. anterior: segmentação da versão anterior (página a página, janelas de
     1.000 caracteres com 200 de sobreposição, sem limpeza);
  2. atual: segmentação atual (config.py);
  3. atual sem o cabeçalho de contexto no embedding.
É a forma de medir, na sua máquina e com o modelo real, o efeito das mudanças.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

import config
import processamento
from estatistica import mcnemar_exato  # noqa: F401  (usado aqui e pelos testes como av.mcnemar_exato)
from perguntas import ConjuntoPerguntas, ErroPerguntas, carregar_perguntas, para_busca
# PROFUNDIDADE: posições examinadas para o MRR (as mesmas guardadas pelo chat)
from recuperacao import MODOS_BUSCA, PROFUNDIDADE, ErroBusca, Recuperador
from vetorial import ModeloEmbeddings, opcoes_processamento, parametros_indice

NOMES_BUSCA = {"densa": "densa (por sentido)", "bm25": "BM25 (por palavras)", "hibrida": "híbrida"}


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
_CAMPOS_CRITERIO = ("fonte", "artigos", "paginas", "trecho")


def criterios(item: dict) -> list[dict]:
    """Os conjuntos de critérios da pergunta: a lista "alternativas" ou os
    campos da própria pergunta."""
    if item.get("alternativas"):
        return item["alternativas"]
    return [{k: item[k] for k in _CAMPOS_CRITERIO if k in item}]


def _normalizar(texto: str) -> str:
    """Sem acentos, em minúsculas e com espaços simples (para o "trecho")."""
    sem_acento = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def atende(meta: dict, criterio: dict) -> bool:
    if criterio.get("fonte") and meta.get("fonte") != criterio["fonte"]:
        return False
    if "artigos" in criterio:
        ini, fim = meta.get("artigo_inicio"), meta.get("artigo_fim")
        if ini is None or not any(ini <= a <= fim for a in criterio["artigos"]):
            return False
    if "paginas" in criterio:
        primeira, ultima = criterio["paginas"]
        ini = meta.get("pagina")
        fim = meta.get("pagina_fim", ini)
        if ini is None or fim < primeira or ini > ultima:
            return False
    if "trecho" in criterio and _normalizar(criterio["trecho"]) not in _normalizar(meta.get("texto", "")):
        return False
    return any(k in criterio for k in _CAMPOS_CRITERIO)


def relevante(meta: dict, item: dict) -> bool:
    """O fragmento (ou passagem) descrito por `meta` responde à pergunta?"""
    return any(atende(meta, c) for c in criterios(item))


def descrever_esperado(item: dict) -> str:
    """"Res_480...pdf, Art. 37 | PPC...pdf, p. 406-410" (para os resultados)."""
    partes = []
    for c in criterios(item):
        desc = [c["fonte"]] if c.get("fonte") else []
        if "artigos" in c:
            desc.append("Art. " + ", ".join(str(a) for a in c["artigos"]))
        if "paginas" in c:
            a, b = c["paginas"]
            desc.append(f"p. {a}" if a == b else f"p. {a}-{b}")
        if "trecho" in c:
            desc.append(f'"{c["trecho"]}"')
        partes.append(", ".join(desc))
    return " | ".join(partes)


def fontes_citadas(itens: list[dict]) -> set[str]:
    return {c["fonte"] for i in itens for c in criterios(i) if c.get("fonte")}


def resumo_recuperado(meta: dict, similaridade: float, item: dict) -> dict:
    """Um fragmento da lista de recuperados gravada no JSON de resultados.

    Com ela dá para ver, pergunta a pergunta, o que a busca trouxe no lugar
    do trecho esperado (antes o JSON guardava só a posição do primeiro
    trecho aceito, e o diagnóstico das falhas ficava no escuro).
    """
    ini = meta.get("pagina")
    fim = meta.get("pagina_fim", ini)
    paginas = "" if ini is None else (f"p. {ini}" if ini == fim else f"p. {ini}-{fim}")
    a, b = meta.get("artigo_inicio"), meta.get("artigo_fim")
    artigos = "" if a is None else (f"Art. {a}" if a == b else f"Arts. {a} a {b}")
    resumo = {"fonte": meta.get("fonte"), "paginas": paginas, "artigos": artigos,
              "similaridade": round(float(similaridade), 4), "relevante": relevante(meta, item),
              "inicio": " ".join(str(meta.get("texto", "")).split())[:120]}
    if meta.get("id"):
        resumo["id"] = meta["id"]
    # posições em cada busca e nota do modo (quando a busca as informa)
    for chave in ("posicao_densa", "posicao_bm25"):
        if chave in meta:
            resumo[chave] = meta[chave]
    if meta.get("nota") is not None:
        resumo["nota"] = round(float(meta["nota"]), 5)
    return resumo


def avaliar_resultados(itens: list[dict], recuperados: list[list[tuple[dict, float]]], k: int,
                       contextos: list[list[dict]] | None = None, maiores: list[float] | None = None,
                       limiar: float | None = None, abstencoes: list[bool] | None = None) -> dict:
    """`recuperados[i]` = lista (metadados, similaridade) na ordem da busca.

    `contextos[i]` = metadados do que efetivamente chega ao LLM na pergunta i
    (os k fragmentos e, no sistema atual, os vizinhos que os acompanham). É a
    base da métrica contexto@k, a comparação justa entre segmentações de
    tamanhos diferentes: importa se o LLM recebe o artigo certo.

    `maiores[i]` = maior similaridade da busca densa na pergunta i, a que
    decide a abstenção (na busca híbrida, o 1º da lista pode não ser o mais
    parecido). Sem ela, vale a similaridade do 1º da lista.

    `limiar`: com ele, cada pergunta registra se o sistema se abstém antes do
    LLM, e o resultado conta as perguntas em que o corte por trecho tirou do
    contexto um trecho certo que estava entre os k primeiros da busca.

    `abstencoes[i]`: se o sistema se absteve antes do LLM na pergunta i, como o
    Recuperador decidiu. Sem ela, vale "maior similaridade abaixo do limiar"
    (no modo BM25 o sistema também se abstém quando nenhum candidato das
    palavras passa no corte).
    """
    linhas, sims_resp, sims_sem, perdidas = [], [], [], []
    acertos1 = acertosk = acertos_contexto = 0
    soma_rr = 0.0
    n_resp = 0
    for i, (item, lista) in enumerate(zip(itens, recuperados)):
        top1 = maiores[i] if maiores is not None else (lista[0][1] if lista else 0.0)
        lista_json = [resumo_recuperado(m, s, item) for m, s in lista[:PROFUNDIDADE]]
        if item.get("sem_resposta"):
            sims_sem.append(top1)
            linha = {"id": item["id"], "pergunta": item["pergunta"], "sem_resposta": True,
                     "similaridade_top1": round(top1, 4), "recuperados": lista_json}
            if limiar is not None:
                linha["abstencao_previa"] = abstencoes[i] if abstencoes is not None else top1 < limiar
            linhas.append(linha)
            continue
        n_resp += 1
        sims_resp.append(top1)
        posicao = next((n for n, (m, _) in enumerate(lista[:PROFUNDIDADE], 1) if relevante(m, item)), None)
        contexto = contextos[i] if contextos is not None else [m for m, _ in lista[:k]]
        no_contexto = any(relevante(m, item) for m in contexto)
        acertos1 += posicao == 1
        acertosk += posicao is not None and posicao <= k
        acertos_contexto += no_contexto
        soma_rr += 1 / posicao if posicao else 0.0
        linha = {"id": item["id"], "pergunta": item["pergunta"], "esperado": descrever_esperado(item),
                 "posicao": posicao, "no_contexto": no_contexto, "similaridade_top1": round(top1, 4),
                 "recuperados": lista_json}
        if limiar is not None:
            linha["abstencao_previa"] = abstencoes[i] if abstencoes is not None else top1 < limiar
            if not no_contexto and any(relevante(m, item) and s < limiar for m, s in lista[:k]):
                linha["perdida_pelo_corte"] = True
                perdidas.append(item["id"])
        linhas.append(linha)
    return {
        "n_respondiveis": n_resp, "n_sem_resposta": len(sims_sem),
        "acerto_1": acertos1 / n_resp if n_resp else 0.0,
        "acerto_k": acertosk / n_resp if n_resp else 0.0,
        "contexto_k": acertos_contexto / n_resp if n_resp else 0.0,
        "mrr": soma_rr / n_resp if n_resp else 0.0,
        "k": k, "linhas": linhas, "sims_respondiveis": sims_resp, "sims_sem_resposta": sims_sem,
        "limiar": limiar, "perdidas_pelo_corte": perdidas,
    }


def sugerir_limiar(sims_resp: list[float], sims_sem: list[float]) -> tuple[float | None, int]:
    """Maior limiar (múltiplo de 0,05) que não bloqueia nenhuma pergunta respondível."""
    if not sims_resp:
        return None, 0
    candidatos = [round(x * 0.05, 2) for x in range(1, 20) if x * 0.05 <= min(sims_resp)]
    if not candidatos:
        return None, 0
    limiar = max(candidatos)
    return limiar, sum(s < limiar for s in sims_sem)


def comparar_pares(base: dict, outra: dict) -> dict:
    """Perguntas respondíveis em que só uma das duas buscas põe o trecho certo
    no contexto, e o p do McNemar exato."""
    def acertos(resultado: dict) -> dict[str, bool]:
        return {l["id"]: l["no_contexto"] for l in resultado["linhas"] if not l.get("sem_resposta")}
    a, b = acertos(base), acertos(outra)
    so_base = sorted(i for i in a if a[i] and not b.get(i, False))
    so_outra = sorted(i for i in b if b[i] and not a.get(i, False))
    return {"so_base": so_base, "so_outra": so_outra, "p": mcnemar_exato(len(so_base), len(so_outra))}


# ---------------------------------------------------------------------------
# Impressão
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _dec(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def imprimir_detalhe(res: dict) -> None:
    for l in res["linhas"]:
        if l.get("sem_resposta"):
            print(f"  [sem resposta] {l['id']}  maior similaridade {_dec(l['similaridade_top1'])}  {l['pergunta']}")
        else:
            situacao = "OK   " if l["no_contexto"] else "FALHA"
            posicao = f"{l['posicao']}º" if l["posicao"] else f"fora dos {PROFUNDIDADE}"
            print(f"  {situacao} {l['id']}  1º relevante: {posicao:<11} sim. {_dec(l['similaridade_top1'])}  "
                  f"{l['pergunta']}")
            if not l["no_contexto"] and l.get("recuperados"):
                r = l["recuperados"][0]
                local = ", ".join(x for x in (r["paginas"], r["artigos"]) if x)
                print(f"             veio em 1º: {r['fonte']}, {local}: \"{r['inicio'][:70]}...\"")


def imprimir_resumo(res: dict, titulo: str) -> None:
    print(f"\n{titulo}")
    print(f"  perguntas respondíveis: {res['n_respondiveis']} | sem resposta: {res['n_sem_resposta']}")
    print(f"  acerto@1: {_pct(res['acerto_1'])} | acerto@{res['k']}: {_pct(res['acerto_k'])} | "
          f"contexto@{res['k']}: {_pct(res['contexto_k'])} | MRR: {_dec(res['mrr'])}")
    print("  (OK/FALHA no detalhe = o contexto entregue ao LLM contém ou não o artigo esperado)")
    if res.get("limiar") is not None:
        perdidas = res.get("perdidas_pelo_corte", [])
        print(f"  perdidas pelo corte de {_dec(res['limiar'])}: {len(perdidas)}"
              + (f" ({', '.join(perdidas)})" if perdidas else ""))
    imprimir_limiar(res)


def imprimir_limiar(res: dict) -> None:
    """Faixas da maior similaridade por pergunta e o limiar sugerido."""
    if res["sims_respondiveis"] and res["sims_sem_resposta"]:
        sr, ss = res["sims_respondiveis"], res["sims_sem_resposta"]
        print(f"  maior similaridade por pergunta: respondíveis {_dec(min(sr))} a {_dec(max(sr))} "
              f"(média {_dec(float(np.mean(sr)))}); sem resposta {_dec(min(ss))} a {_dec(max(ss))} "
              f"(média {_dec(float(np.mean(ss)))})")
        limiar, bloqueadas = sugerir_limiar(sr, ss)
        if limiar is not None:
            print(f"  SIMILARIDADE_MINIMA sugerida: {_dec(limiar)} (não bloqueia nenhuma respondível; "
                  f"bloqueia {bloqueadas} de {len(ss)} sem resposta antes do LLM). "
                  f"Atual: {_dec(config.SIMILARIDADE_MINIMA)}")


# ---------------------------------------------------------------------------
# Modo 1: avaliação da base indexada (caminho real do chatbot) e comparação das buscas
# ---------------------------------------------------------------------------
def _meta_do_trecho(t) -> dict:
    return dict(t.metadados, texto=t.texto, id=t.id, posicao_densa=t.posicao_densa,
                posicao_bm25=t.posicao_bm25, nota=t.nota)


def avaliar_base(itens: list[dict], k: int, modo: str | None = None,
                 recuperador: Recuperador | None = None) -> dict:
    """Mede a busca pelo mesmo caminho do chat (Recuperador.recuperar).

    O contexto avaliado é exatamente o que o LLM receberia: os k primeiros que
    passam no limiar, ampliados com os vizinhos.
    """
    recuperador = recuperador or Recuperador()
    modo = recuperador.modo_valido(modo)
    recuperador.preparar(modo)
    recuperados, contextos, maiores, abstencoes = [], [], [], []
    for item in itens:
        contexto = recuperador.recuperar(item["pergunta"], k=k, modo=modo)
        recuperados.append([(_meta_do_trecho(t), t.similaridade) for t in contexto.recuperados])
        contextos.append([{"fonte": p.fonte, "artigo_inicio": p.artigo_inicio, "artigo_fim": p.artigo_fim,
                           "pagina": p.pagina_inicio, "pagina_fim": p.pagina_fim, "texto": p.texto}
                          for p in contexto.passagens])
        maiores.append(contexto.maior_similaridade)
        abstencoes.append(contexto.abstencao_previa)
    resultado = avaliar_resultados(itens, recuperados, k, contextos, maiores=maiores,
                                   limiar=config.SIMILARIDADE_MINIMA, abstencoes=abstencoes)
    resultado.update(modo=modo, configuracao=recuperador.configuracao(modo, k))
    return resultado


def comparar_buscas(itens: list[dict], k: int, recuperador: Recuperador | None = None) -> dict:
    """Avalia a mesma base com as três buscas e compara cada uma com a densa.

    O modelo de embeddings e o índice do BM25 são carregados uma vez só.
    """
    recuperador = recuperador or Recuperador()
    resultados = {}
    for modo in MODOS_BUSCA:
        inicio = time.perf_counter()
        resultados[modo] = avaliar_base(itens, k, modo, recuperador)
        resultados[modo]["segundos"] = round(time.perf_counter() - inicio, 1)
    comparacoes = {modo: comparar_pares(resultados["densa"], resultados[modo])
                   for modo in MODOS_BUSCA if modo != "densa"}
    return {"k": k, "resultados": resultados, "comparacoes_com_densa": comparacoes}


def _contagem(fracao: float, n: int) -> str:
    return f"{round(fracao * n)} ({_pct(fracao)})"


def imprimir_comparacao_buscas(comparacao: dict) -> None:
    k = comparacao["k"]
    resultados = comparacao["resultados"]
    densa = resultados["densa"]
    n = densa["n_respondiveis"]
    print(f"\nComparação das buscas na base indexada: {n} perguntas respondíveis e "
          f"{densa['n_sem_resposta']} sem resposta, k = {k}, limiar {_dec(config.SIMILARIDADE_MINIMA)}")
    print(f"{'Busca':<22} {'acerto@1':>9} {'acerto@' + str(k):>9} {'contexto@' + str(k):>11} "
          f"{'MRR':>5} {'perdidas pelo corte':>20}")
    for modo, res in resultados.items():
        print(f"{NOMES_BUSCA[modo]:<22} {_contagem(res['acerto_1'], n):>9} {_contagem(res['acerto_k'], n):>9} "
              f"{_contagem(res['contexto_k'], n):>11} {_dec(res['mrr']):>5} "
              f"{len(res['perdidas_pelo_corte']):>20}")
    print(f"contexto@{k} = o texto que chega ao LLM, já com o limiar e o corte, contém o trecho certo.")
    print(f"perdidas pelo corte = o trecho certo estava entre os {k} primeiros da busca, mas tinha "
          f"similaridade abaixo de {_dec(config.SIMILARIDADE_MINIMA)} e ficou fora do contexto.")
    print(f"\nMcNemar exato sobre o contexto@{k} (perguntas em que as duas buscas discordam):")
    for modo, c in comparacao["comparacoes_com_densa"].items():
        print(f"  {NOMES_BUSCA[modo]} x densa: só a {modo} acerta {len(c['so_outra'])}"
              + (f" ({', '.join(c['so_outra'])})" if c["so_outra"] else "")
              + f"; só a densa acerta {len(c['so_base'])}"
              + (f" ({', '.join(c['so_base'])})" if c["so_base"] else "")
              + f"; p = {_dec(c['p'])}")
    print("\nFalhas de cada busca (o trecho certo não chega ao LLM):")
    for modo, res in resultados.items():
        falhas = [l["id"] for l in res["linhas"] if not l.get("sem_resposta") and not l["no_contexto"]]
        print(f"  {NOMES_BUSCA[modo]}: {', '.join(falhas) or 'nenhuma'}")
    paradas = [l["id"] for l in densa["linhas"] if l.get("sem_resposta") and l.get("abstencao_previa")]
    print("\nLimiar (sempre pela busca densa, então igual nas três buscas):")
    print(f"  perguntas sem resposta que param antes do LLM: {', '.join(paradas) or 'nenhuma'}")
    imprimir_limiar(densa)


# ---------------------------------------------------------------------------
# Modo 2: comparação de segmentações em memória
# ---------------------------------------------------------------------------
_RE_INICIO_ARTIGO = re.compile(r"(?:^|(?<=\s))Art\.?\s*(\d+)\s*[º°o]?\.?\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ])")


def _janelas_versao_anterior(texto: str, tamanho: int = 1000, sobreposicao: int = 200) -> list[str]:
    """Cópia fiel do `dividir_em_chunks` da versão anterior (para comparação)."""
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return []
    chunks, inicio, n = [], 0, len(texto)
    while inicio < n:
        fim = min(inicio + tamanho, n)
        if fim < n:
            janela = texto[inicio:fim]
            corte = max(janela.rfind(". "), janela.rfind("? "), janela.rfind("! "))
            if corte > tamanho * 0.5:
                fim = inicio + corte + 1
        chunks.append(texto[inicio:fim].strip())
        if fim >= n:
            break
        inicio = max(fim - sobreposicao, inicio + 1)
    return [c for c in chunks if c]


def fragmentos_versao_anterior(pdf: Path) -> list[tuple[str, dict]]:
    """Fragmentos como a versão anterior os criava, com os artigos cobertos
    estimados (artigo aberto no início do fragmento + artigos que começam nele)."""
    resultado, artigo_aberto = [], None
    with fitz.open(pdf) as documento:   # extração da versão anterior: texto simples por página
        paginas = [(n, p.get_text("text")) for n, p in enumerate(documento, start=1)]
    for numero, texto in paginas:
        if not texto.strip():
            continue
        for chunk in _janelas_versao_anterior(texto):
            inicios = [int(m.group(1)) for m in _RE_INICIO_ARTIGO.finditer(chunk)]
            cobertos = inicios[:]
            if artigo_aberto is not None and not chunk.startswith("Art"):
                cobertos.insert(0, artigo_aberto)
            if inicios:
                artigo_aberto = inicios[-1]
            meta = {"fonte": pdf.name, "pagina": numero, "texto": chunk}
            if cobertos:
                meta["artigo_inicio"], meta["artigo_fim"] = min(cobertos), max(cobertos)
            resultado.append((chunk, meta))
    return resultado


def fragmentos_atuais(pdf: Path, modelo: ModeloEmbeddings, incluir_contexto: bool) -> list[tuple[str, dict]]:
    opcoes = opcoes_processamento(parametros_indice(modelo))
    opcoes.incluir_contexto = incluir_contexto
    doc = processamento.processar_pdf(pdf, modelo.contar_tokens, opcoes)
    saida = []
    for f in doc.fragmentos:
        meta = {"fonte": pdf.name, "pagina": f.pagina_inicio, "pagina_fim": f.pagina_fim, "texto": f.texto}
        if f.artigo_inicio is not None:
            meta["artigo_inicio"], meta["artigo_fim"] = f.artigo_inicio, f.artigo_fim
        saida.append((f.texto_embedding, meta))
    return saida


def comparar(itens: list[dict], k: int, modelo: ModeloEmbeddings, so_fontes: bool = False) -> list[dict]:
    if so_fontes:
        pdfs = [config.DOCS_DIR / f for f in sorted(fontes_citadas(itens)) if (config.DOCS_DIR / f).exists()]
    else:
        pdfs = sorted(config.DOCS_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"Nenhum documento das perguntas está em {config.DOCS_DIR}.")
    print(f"{len(pdfs)} documento(s) em cada variante.")
    # (nome, gerador de fragmentos, vizinhos que acompanham cada fragmento no contexto)
    variantes = [
        ("anterior: página a página, 1.000/200 caracteres",
         lambda pdf: fragmentos_versao_anterior(pdf), 0),
        ("atual: estrutural, limitada à janela do modelo",
         lambda pdf: fragmentos_atuais(pdf, modelo, config.CONTEXTO_NO_EMBEDDING), config.JANELA_VIZINHOS),
        ("atual sem cabeçalho de contexto no embedding",
         lambda pdf: fragmentos_atuais(pdf, modelo, False), config.JANELA_VIZINHOS),
    ]
    perguntas = np.array(modelo.codificar_consultas([i["pergunta"] for i in itens]))
    resultados = []
    for nome, gerar, janela in variantes:
        inicio = time.perf_counter()
        print(f"\nVariante: {nome}")
        fragmentos = []
        for pdf in pdfs:
            try:
                fragmentos += gerar(pdf)
            except processamento.ErroExtracao as erro:
                print(f"  {pdf.name}: ignorado ({erro})")
        textos = [t for t, _ in fragmentos]
        tokens = [modelo.contar_tokens(t) for t in textos]
        vetores = np.array(modelo.codificar_documentos(textos, mostrar_progresso=True))
        similaridades = perguntas @ vetores.T            # cosseno (vetores normalizados)
        recuperados, contextos = [], []
        for linha in similaridades:
            ordem = np.argsort(-linha)[:max(k, PROFUNDIDADE)]
            recuperados.append([(fragmentos[j][1], float(linha[j])) for j in ordem])
            vizinhos = {v for j in ordem[:k] for v in range(j - janela, j + janela + 1)
                        if 0 <= v < len(fragmentos) and fragmentos[v][1]["fonte"] == fragmentos[j][1]["fonte"]}
            contextos.append([fragmentos[v][1] for v in sorted(vizinhos)])
        res = avaliar_resultados(itens, recuperados, k, contextos)
        res.update(variante=nome, n_fragmentos=len(textos),
                   truncados=sum(t > modelo.limite_conteudo for t in tokens),
                   segundos=round(time.perf_counter() - inicio, 1))
        resultados.append(res)
    return resultados


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from vetorial import ErroEmbeddings
    try:
        return _executar(argv)
    except (ErroBusca, ErroEmbeddings) as erro:
        print(f"\nERRO: {erro}")
        return 1


def _carregar_conjunto(arquivo: Path | None) -> ConjuntoPerguntas | None:
    """Lê e confere as perguntas; None (com a explicação impressa) se não der para usar."""
    try:
        conjunto = carregar_perguntas(arquivo)
    except ErroPerguntas as erro:
        print(f"ERRO: {erro}")
        return None
    print(f"Perguntas: {conjunto.arquivo.name} ({len(conjunto.perguntas)} perguntas, "
          f"assinatura {conjunto.assinatura})")
    if conjunto.erros:
        print(f"ERRO: o arquivo de perguntas tem {len(conjunto.erros)} erro(s); rode validar-perguntas.bat "
              "para ver todos e corrigir. Os primeiros:")
        for problema in conjunto.erros[:5]:
            print(f"  {problema}")
        return None
    _, fora = para_busca(conjunto.perguntas)
    if fora:
        print(f"  {len(fora)} pergunta(s) respondível(is) sem o local da resposta ficam fora da avaliação "
              f"da busca: {', '.join(fora[:15])}{' ...' if len(fora) > 15 else ''}")
    return conjunto


def _executar(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="Avalia a busca do chatbot com perguntas de teste.")
    parser.add_argument("--arquivo", "--perguntas", dest="arquivo", type=Path, default=None,
                        help="arquivo de perguntas (padrão: ARQUIVO_PERGUNTAS do config.py)")
    parser.add_argument("--k", type=int, default=config.TOP_K, help="fragmentos entregues ao LLM (TOP_K)")
    parser.add_argument("--modo", choices=MODOS_BUSCA, default=None,
                        help="busca avaliada na base indexada (padrão: MODO_BUSCA do config.py)")
    parser.add_argument("--comparar-buscas", action="store_true",
                        help="compara as buscas densa, BM25 e híbrida na base indexada")
    parser.add_argument("--comparar", action="store_true",
                        help="compara a segmentação anterior com a atual, em memória")
    parser.add_argument("--so-fontes", action="store_true",
                        help="no --comparar, usa só os documentos citados nas perguntas (mais rápido)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    conjunto = _carregar_conjunto(args.arquivo)
    if conjunto is None:
        return 1
    itens, fora = para_busca(conjunto.perguntas)
    if not any(not i["sem_resposta"] for i in itens):
        print("Nenhuma pergunta respondível deste arquivo diz onde está a resposta, então a avaliação "
              "da busca não se aplica a ele. A busca destas perguntas é medida na avaliação das "
              "respostas, pela cobertura dos trechos.")
        return 0
    faltando = sorted(f for f in fontes_citadas(itens) if not (config.DOCS_DIR / f).exists())
    if faltando:
        print(f"Aviso: {len(faltando)} documento(s) citado(s) nas perguntas não está(ão) em {config.DOCS_DIR} "
              f"(as perguntas que dependem só deles vão aparecer como FALHA):")
        for f in faltando:
            print(f"  - {f}")
    pasta = config.AVALIACAO_DIR / "resultados"
    pasta.mkdir(parents=True, exist_ok=True)
    # data e hora com segundos, o k e o conjunto: duas avaliações seguidas nunca gravam no mesmo arquivo
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_k{args.k}_" + conjunto.nome
    sobre = {"versao_chatbot": config.VERSAO_CHATBOT,
             "perguntas": dict(conjunto.identificacao(), avaliadas=len(itens), fora_sem_local=fora)}

    if args.comparar:
        modelo = ModeloEmbeddings()
        print(f"Comparando segmentações com o modelo {modelo.nome} "
              f"(janela de {modelo.janela_tokens} tokens), k = {args.k}...")
        resultados = comparar(itens, args.k, modelo, so_fontes=args.so_fontes)
        print(f"\n{'Variante':<50} {'frag.':>6} {'trunc.':>7} {'acerto@1':>9} "
              f"{'acerto@' + str(args.k):>9} {'contexto@' + str(args.k):>10} {'MRR':>6}")
        for r in resultados:
            print(f"{r['variante']:<50} {r['n_fragmentos']:>6} {r['truncados']:>7} "
                  f"{_pct(r['acerto_1']):>9} {_pct(r['acerto_k']):>9} {_pct(r['contexto_k']):>10} "
                  f"{_dec(r['mrr']):>6}")
        print("frag. = fragmentos na base; trunc. = fragmentos maiores que a janela do modelo "
              "(parte do texto fica fora do vetor);\ncontexto@k = o texto entregue ao LLM contém o "
              "artigo esperado (fragmentos recuperados + vizinhos, quando houver).")
        for r in resultados:
            imprimir_resumo(r, f"Detalhe: {r['variante']}")
            imprimir_detalhe(r)
        for r in resultados:
            r.update(sobre)
        destino = pasta / f"comparacao_{carimbo}.json"
        destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.comparar_buscas:
        print(f"Comparando as buscas densa, BM25 e híbrida na base indexada "
              f"(modelo {config.EMBEDDING_MODEL}, k = {args.k})...")
        comparacao = comparar_buscas(itens, args.k)
        comparacao.update(sobre)
        imprimir_comparacao_buscas(comparacao)
        destino = pasta / f"buscas_{carimbo}.json"
        destino.write_text(json.dumps(comparacao, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        modo = Recuperador.modo_valido(args.modo)
        print(f"Avaliando a base indexada (modelo {config.EMBEDDING_MODEL}, busca {NOMES_BUSCA[modo]}, "
              f"k = {args.k})...")
        resultado = avaliar_base(itens, args.k, modo)
        resultado.update(sobre)
        imprimir_detalhe(resultado)
        imprimir_resumo(resultado, "Resumo")
        destino = pasta / f"recuperacao_{modo}_{carimbo}.json"
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultados gravados em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
