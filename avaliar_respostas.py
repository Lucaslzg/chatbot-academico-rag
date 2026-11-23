"""Tabela de confiabilidade de uma rodada: o que cada modelo fez com cada pergunta.

    python avaliar_respostas.py                      # a rodada mais recente
    python avaliar_respostas.py --rodada avaliacao/rodadas/2026-11-20_0900_perguntas_reais

Não precisa de juiz: olha só o comportamento, que já diz muito sobre o
requisito do trabalho (melhor não responder do que responder sem base). Cada
resposta tem uma categoria (consulta.classificar_resposta): resposta,
abstenção, abstenção com acréscimo (diz que não encontrou, mas acrescenta
algo sem citar), mista (cita trechos e diz que não encontrou) ou vazia.

A categoria é refeita sobre o texto gravado, com as regras desta versão
(categoria_automatica()), e não lida do arquivo: assim uma regra corrigida vale também
para as rodadas já geradas. A da versão 10: a recusa com outras palavras e
uma citação solta ("Não foi encontrada na informação fornecida... [1]") é
abstenção, e não resposta. As respostas que mudaram de categoria aparecem na
tabela; o arquivo de respostas continua como foi gravado.

* perguntas que os documentos respondem: o modelo respondeu ou se absteve? A
  abstenção pode vir do limiar, antes do modelo (nenhum trecho passou nele;
  é igual para todos, porque os trechos estão congelados), ou do modelo;
* perguntas que os documentos não respondem: o sistema se absteve, pelo
  limiar ou pelo modelo, como devia, ou respondeu mesmo assim? Responder (ou
  se abster acrescentando algo) é o caso perigoso: uma resposta sem base;
* as taxas são calculadas sobre as perguntas que chegaram ao modelo, porque
  as paradas no limiar não dependem dele;
* respostas mistas, sem citação, cortadas no limite de tokens, raciocínio que
  não desligou; tempo por resposta e velocidade de escrita.

Quando os juízes já avaliaram a rodada (avaliar_ragas.py), a tabela ganha as
médias de correção (F1), de completude (versão 10) e de fidelidade: a média
dos juízes, desde a versão 09, ou a do juiz único, numa rodada avaliada pelas
versões 06 a 08.

Grava confiabilidade.md, .csv e .json na pasta da rodada, mais revisar.csv:
as respostas que a classificação automática pode ter errado ou que contam
como sem base, com o texto, para conferência à mão. Tudo é calculado das
respostas, que nunca mudam: rodar de novo só refaz as tabelas. Compara cada
par de modelos com o teste de McNemar exato.

Conferência à mão (versão 14): a decisão escrita na coluna "sua conferência"
do revisar.csv ("manter" ou "corrigir para <categoria>") passa a valer na
próxima vez que a tabela é gerada, e também na escolha do que os juízes
avaliam (avaliar_ragas.py). Ela só vale para o mesmo texto de resposta que
estava na planilha; se a resposta mudou, a decisão é marcada para conferir de
novo e não vale. Ao gerar o revisar.csv de novo, as decisões são guardadas,
inclusive as de respostas que saíram da lista. As respostas que mudaram de
categoria à mão aparecem na tabela; o arquivo de respostas não muda.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from itertools import combinations
from pathlib import Path

import config
from estatistica import mcnemar_exato
from gerar_respostas import (ErroRodada, abrir_rodada, arquivo_respostas, ler_respostas, pasta_das_rodadas,
                             rodada_mais_recente)
from modelos import info_modelo

COLUNAS = [
    ("rotulo", "Modelo", 0),
    ("respondidas", "Perguntas respondidas pelo modelo", 0),
    ("respondiveis", "Com resposta nos documentos", 0),
    ("respondeu", "Respondeu", 0),
    ("absteve_antes", "Abstenção pelo limiar", 0),
    ("absteve_modelo", "Abstenção do modelo", 0),
    ("acrescimo_respondivel", "Abstenção com acréscimo", 0),
    ("taxa_resposta", "Respondeu, das que chegaram ao modelo", "pct"),
    ("sem_resposta", "Sem resposta nos documentos", 0),
    ("absteve_limiar_certo", "Absteve-se pelo limiar", 0),
    ("absteve_modelo_certo", "Absteve-se o modelo", 0),
    ("respondeu_sem_base", "Respondeu sem base (perigoso)", 0),
    ("taxa_abstencao_certa", "Absteve-se, das que chegaram ao modelo", "pct"),
    ("vazias", "Respostas vazias", 0),
    ("mistas", "Respostas mistas", 0),
    ("sem_citacao", "Respostas sem citação", 0),
    ("cortadas", "Cortadas no limite de tokens", 0),
    ("raciocinou", "Raciocinou mesmo desligado", 0),
    ("tempo_medio_s", "Tempo médio (s)", 1),
    ("tempo_mediano_s", "Tempo mediano (s)", 1),
    ("tokens_por_s", "Escrita (tokens/s)", 1),
]
# Colunas que entram quando os juízes já avaliaram a rodada (avaliar_ragas.py)
COLUNAS_JUIZ = [("correcao_media", "Correção (F1) média (juízes)", 2),
                ("completude_media", "Completude média (juízes)", 2),
                ("fidelidade_media", "Fidelidade média (juízes)", 2)]
NOMES_CATEGORIAS = {"resposta": "resposta", "abstencao": "abstenção", "abstencao_com_acrescimo":
                    "abstenção com acréscimo", "mista": "mista", "vazia": "vazia"}


def categoria_gravada(linha: dict) -> str:
    """A categoria gravada na geração (respostas de versões sem ela: pela abstenção)."""
    return linha.get("categoria") or ("abstencao" if linha.get("abstencao") else "resposta")


ARQUIVO_REVISAR = "revisar.csv"
PASTA_REVISAR_ANTERIORES = "revisar_anteriores"       # cópia do revisar.csv de antes, quando ele muda (versão 14)
COLUNA_CONFERENCIA = "sua conferência"
CAMPOS_REVISAR = ["modelo", "id", "pergunta", "sem_resposta", "categoria", "motivo", "resposta", "resposta_correta"]
MARCA_DESATUALIZADA = "[confira de novo e apague esta marca]"
_CATEGORIAS_POR_NOME = {"resposta": "resposta", "abstencao": "abstencao",
                        "abstencao com acrescimo": "abstencao_com_acrescimo", "mista": "mista", "vazia": "vazia"}
_MANTER = ("manter", "mantem", "mantida", "mantido", "ok", "certo", "certa", "correto", "correta")
_SEM_NOTA_DO_JUIZ = ("abstencao", "vazia")
_UM_BYTE = ("cp1252", "cp850", "mac_roman")   # codificações do Excel em que o caractere que falta vira "?"
_ARQUIVO_CHAVE_DO_PILOTO = Path("piloto") / "piloto_chave.json"   # piloto.ARQUIVO_CHAVE (o piloto importa este módulo)


def tratamento_do_juiz(cat: str | None) -> str:
    """Como o juiz trata uma categoria (avaliar_ragas.avaliar_modelo): sem nota (abstenção e vazia) ou julgada."""
    return "sem_nota" if cat in _SEM_NOTA_DO_JUIZ else "julgada"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").lower().strip()


def _mesmo_texto(atual, da_planilha, codificacao: str | None = None) -> bool:
    """Se o texto da planilha é o texto atual, sem contar espaços e quebras de linha (o Excel pode trocar o fim
    de linha). Numa planilha salva em ANSI, o caractere que a codificação não tem vira "?" nos dois lados."""
    atual = str(atual or "")
    if codificacao in _UM_BYTE:
        atual = atual.encode(codificacao, "replace").decode(codificacao)
    return " ".join(atual.split()) == " ".join(str(da_planilha or "").split())


def interpretar_decisao(texto: str) -> tuple[str, str | None]:
    """A decisão da coluna "sua conferência": ("vazia", None), ("manter", None), ("corrigir", categoria),
    ("desatualizada", None) ou ("invalida", None).

    Aceita "manter" (ou "ok"), "manter como <categoria>", "corrigir para
    <categoria>" (também com dois pontos) e só o nome da categoria, com ou
    sem acento e maiúsculas, e com um comentário entre parênteses no fim,
    mesmo com quebra de linha. A decisão com a marca de conferir de novo, que
    o programa põe quando a resposta ou a classificação mudou, não vale até a
    marca ser apagada.
    """
    bruto = (texto or "").strip()
    if not bruto:
        return "vazia", None
    if bruto.startswith(MARCA_DESATUALIZADA):
        return "desatualizada", None
    t = re.sub(r"\s*\(.*\)\s*$", "", _sem_acento(bruto), flags=re.S)
    t = " ".join(t.split()).rstrip(" .;:!")
    if t.startswith("manter") or t in _MANTER:
        resto = re.sub(r"^[\s,:;-]*(como |na categoria |em )?", "", t[len("manter"):] if t.startswith("manter") else "")
        categoria_escrita = _CATEGORIAS_POR_NOME.get(" ".join(resto.replace("_", " ").split()).strip(" .;:!"))
        return ("corrigir", categoria_escrita) if categoria_escrita else ("manter", None)
    for prefixo in ("corrigir para", "corrigir"):
        if t.startswith(prefixo):
            t = t[len(prefixo):].lstrip(" :;,-")
            break
    categoria_escrita = _CATEGORIAS_POR_NOME.get(" ".join(t.replace("_", " ").split()))
    return ("corrigir", categoria_escrita) if categoria_escrita else ("invalida", None)


def _leituras(dados: bytes) -> list[tuple[str, str]]:
    """As leituras possíveis da planilha, da mais provável para a menos: (texto, codificação). O Excel grava em
    UTF-8 (com ou sem a marca do começo), em ANSI, em UTF-16 ("Texto Unicode", às vezes sem a marca), em MS-DOS
    (cp850) e em Macintosh."""
    if dados.startswith(b"\xef\xbb\xbf"):
        return [(dados.decode("utf-8-sig", errors="replace"), "utf-8")]
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return [(dados.decode("utf-16", errors="replace"), "utf-16")]
    if b"\x00" in dados[:400]:                     # UTF-16 sem a marca do começo (como piloto._ler_texto)
        return [(dados.decode("utf-16-le" if dados[1:2] == b"\x00" else "utf-16-be", errors="replace"), "utf-16")]
    leituras = []
    try:
        leituras.append((dados.decode("utf-8"), "utf-8"))
    except UnicodeDecodeError:
        pass
    return leituras + [(dados.decode(c, errors="replace"), c) for c in _UM_BYTE]


_LETRAS_DO_PORTUGUES = set("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ")
_OUTROS_DOS_DOCUMENTOS = set("ºª°§–“”‘’…•€«»²³½\u2014\u00a0")


def _pontos_de_portugues(texto: str) -> int:
    """Quanto o texto parece português bem lido: as letras acentuadas contam a favor, e os caracteres que não
    aparecem em português (os de outra página de código lida errado) contam contra. Escolhe, entre as
    codificações de um byte (ANSI, MS-DOS e Macintosh), a que o Excel usou."""
    estranhos = sum(1 for c in texto if c == "\ufffd" or (ord(c) > 127 and c not in _LETRAS_DO_PORTUGUES
                                                          and c not in _OUTROS_DOS_DOCUMENTOS))
    return sum(c in _LETRAS_DO_PORTUGUES for c in texto) - 5 * estranhos


def _ler_csv(texto: str) -> tuple[dict | None, str]:
    """As linhas da planilha, se o cabeçalho tiver as colunas modelo, id, resposta e a da conferência; senão,
    None e o motivo. A da conferência é a "sua conferência" ou, sem ela, a única coluna com "conferência" no
    nome. Guarda também as colunas a mais da pessoa: as com nome e as sem nome que têm algo escrito."""
    partes = re.split(r"\r\n|\r|\n", texto, maxsplit=1)
    separador = None
    if partes[0].strip().strip('"').lower().startswith("sep=") and len(partes[0].strip().strip('"')) >= 5:
        separador = partes[0].strip().strip('"')[4]          # a linha "sep=;" que o Excel aceita no começo
        texto = partes[1] if len(partes) > 1 else ""
    if separador is None:
        cabecalho = next((l for l in texto.splitlines() if l.strip()), "")
        separador = max((";", ",", "\t"), key=cabecalho.count)
    try:
        linhas = [l for l in csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
                  if any(c.strip() for c in l)]
    except csv.Error as erro:
        return None, f"o arquivo não pôde ser lido como CSV ({erro})"
    if not linhas:
        return None, "o arquivo não tem nenhuma linha"
    cabecalho = [c.strip() for c in linhas[0]]
    nomes = [_sem_acento(c) for c in cabecalho]
    posicao: dict[str, int] = {}
    for n, nome in enumerate(nomes):
        posicao.setdefault(nome, n)
    faltam = [c for c in ("modelo", "id", "resposta") if c not in posicao]
    candidatas = [n for n, nome in enumerate(nomes) if "conferencia" in nome]
    coluna_conferencia = posicao.get(_sem_acento(COLUNA_CONFERENCIA))
    if coluna_conferencia is None and len(candidatas) == 1:
        coluna_conferencia = candidatas[0]
    if coluna_conferencia is None:
        faltam.append(f"\"{COLUNA_CONFERENCIA}\"" if not candidatas else
                      f"\"{COLUNA_CONFERENCIA}\" (há {len(candidatas)} colunas com \"conferência\" no nome)")
    if faltam:
        return None, "falta a coluna " + ", ".join(faltam) if len(faltam) == 1 else "faltam as colunas " + ", ".join(faltam)

    def celula(linha: list[str], n: int | None) -> str:
        return linha[n] if n is not None and n < len(linha) else ""

    conhecidas = {posicao[c] for c in CAMPOS_REVISAR if c in posicao} | {coluna_conferencia}
    largura = max(len(l) for l in linhas)
    extras = [n for n in range(largura) if n not in conhecidas
              and ((n < len(cabecalho) and cabecalho[n]) or any(celula(l, n).strip() for l in linhas[1:]))]

    registros = []
    for linha in linhas[1:]:
        reg = {c: celula(linha, posicao.get(c)) for c in CAMPOS_REVISAR}
        reg["modelo"], reg["id"] = reg["modelo"].strip(), reg["id"].strip()
        reg["decisao"] = celula(linha, coluna_conferencia).strip()
        reg["extras"] = [celula(linha, n) for n in extras]
        registros.append(reg)
    return {"linhas": registros, "extras": [cabecalho[n] if n < len(cabecalho) else "" for n in extras]}, ""


def ler_planilha_revisar(pasta: Path) -> dict | None:
    """O revisar.csv da rodada como a pessoa deixou: as linhas, com a decisão e as colunas a mais dela, e a
    codificação em que foi lido. None sem o arquivo ou com ele vazio.

    Um arquivo com conteúdo em que as colunas modelo, id, resposta e a da
    conferência não são reconhecidas para a tabela com ErroRodada, sem gravar
    nada: gravar por cima apagaria as decisões.
    """
    caminho = pasta / ARQUIVO_REVISAR
    if not caminho.exists():
        return None
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ErroRodada(f"não consegui ler o {ARQUIVO_REVISAR} da rodada ({erro}); feche-o (no Excel?) e rode de "
                         "novo. Ele não foi apagado.")
    if not dados.strip():
        return None
    validas, motivos = [], []
    for texto, codificacao in _leituras(dados):
        planilha, motivo = _ler_csv(texto)
        if planilha is not None:
            validas.append((texto, codificacao, planilha))
        motivos.append(motivo)
    if validas:
        texto, codificacao, planilha = (validas[0] if validas[0][1] in ("utf-8", "utf-16")
                                        else max(validas, key=lambda v: _pontos_de_portugues(v[0])))
        return {**planilha, "codificacao": codificacao}
    raise ErroRodada(f"não reconheci as colunas do {ARQUIVO_REVISAR} da rodada ({motivos[0]}); salve de novo como "
                     "CSV, com o cabeçalho que o programa gravou. Ele não foi apagado.")


def _categoria_vista(registro: dict) -> str | None:
    """A categoria que estava na coluna "categoria" da planilha quando a decisão foi escrita (None se não der para ler)."""
    return _CATEGORIAS_POR_NOME.get(" ".join(_sem_acento(registro.get("categoria", "")).replace("_", " ").split()))


def _amostra_do_piloto(pasta: Path) -> dict[tuple[str, str], str]:
    """As respostas sorteadas para o piloto, {(modelo, id): código}; vazio sem piloto ou com a chave ilegível."""
    try:
        chave = json.loads((pasta / _ARQUIVO_CHAVE_DO_PILOTO).read_text(encoding="utf-8"))
        return {(a["modelo"], a["id"]): a["codigo"] for a in chave.get("amostra", [])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _mesma_forma(decisao: tuple[str, str | None], linha: dict | None) -> tuple[str, str | None]:
    """"corrigir para" a categoria que o programa já deu é o mesmo que "manter" (para comparar linhas repetidas)."""
    if linha is not None and decisao[0] == "corrigir" and decisao[1] == categoria_automatica(linha):
        return "manter", None
    return decisao


def aplicar_conferencia(pasta: Path, por_modelo: dict[str, dict[str, dict]], so_estes_modelos: bool = False,
                        perguntas: dict[str, dict] | None = None) -> dict:
    """Aplica as decisões do revisar.csv às respostas da rodada (versão 14).

    A decisão vale para a resposta daquele modelo e daquela pergunta só se o
    texto da resposta e o da pergunta forem os que estavam na planilha; o
    "manter" vale também só se a classificação automática ainda for a da
    coluna "categoria" da planilha, que foi a confirmada. Se algo mudou, a
    decisão não vale e ganha a marca de conferir de novo no revisar.csv
    seguinte. Linhas repetidas da mesma resposta com decisões diferentes não
    valem. A resposta recebe a categoria conferida em "categoria_conferida"
    (só na memória: o arquivo de respostas não muda), e categoria() passa a
    devolvê-la. Devolve as respostas que mudaram de categoria, quantas
    ficaram como o programa classificou, a situação de cada decisão, os
    avisos e a planilha lida (para o revisar.csv novo guardar tudo).
    so_estes_modelos: as decisões de modelos fora de por_modelo são deixadas
    de lado, sem aviso (o avaliar_ragas.py lê um modelo de cada vez).
    """
    planilha = ler_planilha_revisar(pasta)
    resultado = {"alteradas": [], "mantidas": 0, "decisoes": [], "avisos": [], "planilha": planilha}
    if planilha is None:
        return resultado
    codificacao = planilha["codificacao"]
    piloto = _amostra_do_piloto(pasta)
    grupos: dict[tuple[str, str], list[dict]] = {}
    for reg in planilha["linhas"]:
        if not (reg["modelo"] and reg["id"]):
            if reg["decisao"] and not so_estes_modelos:
                resultado["avisos"].append(f"uma linha com a decisão \"{reg['decisao']}\" não tem o modelo ou o id; "
                                           "ela fica na planilha e não vale")
            continue
        if so_estes_modelos and reg["modelo"] not in por_modelo:
            continue
        respostas = por_modelo.get(reg["modelo"], {})
        i = next((k for k in respostas if k.upper() == reg["id"].upper()), reg["id"])    # o id como está na rodada
        reg["chave"] = (reg["modelo"], i)
        grupos.setdefault(reg["chave"], []).append(reg)
    for (modelo, i), regs in sorted(grupos.items()):
        com_decisao = [r for r in regs if r["decisao"]]
        if not com_decisao:
            continue
        nome = f"{info_modelo(modelo)['rotulo']} {i}"
        linha = por_modelo.get(modelo, {}).get(i)
        lidas = {_mesma_forma(interpretar_decisao(r["decisao"]), linha) for r in com_decisao}
        d = com_decisao[0]
        tipo, conferida = next(iter(lidas))
        aviso = None
        if len(lidas) > 1:
            situacao, aviso = "conflito", (f"{len(com_decisao)} linhas com decisões diferentes; deixe uma só "
                                           "(nenhuma vale)")
        elif linha is None:
            situacao, aviso = "fora_da_rodada", "a resposta não está na rodada"
        elif tipo == "desatualizada":
            situacao, aviso = "desatualizada", ("a decisão está marcada para conferir de novo: confira a resposta e "
                                                "a categoria e apague a marca do começo da célula")
        elif (perguntas and i in perguntas and d.get("pergunta", "").strip()
              and not _mesmo_texto(perguntas[i]["pergunta"], d["pergunta"], codificacao)):
            situacao, aviso = "desatualizada", ("a pergunta da planilha não é a desta rodada; confira de novo e "
                                                "apague a marca")
        elif not _mesmo_texto(linha.get("resposta"), d.get("resposta"), codificacao):
            situacao, aviso = "desatualizada", "a resposta mudou depois da conferência; confira de novo e apague a marca"
        elif tipo == "invalida":
            situacao, aviso = "invalida", (f"decisão não reconhecida (\"{d['decisao']}\"); escreva \"manter\" ou "
                                           "\"corrigir para\" e a categoria")
        elif not linha.get("gerada_pelo_llm", True):
            situacao, aviso = "invalida", "parou no limiar, antes do modelo, e não tem o que conferir"
        elif tipo == "manter" and _categoria_vista(d) not in (None, categoria_automatica(linha)):
            situacao = "desatualizada"          # "manter" confirmou a categoria que estava na planilha, não esta
            aviso = (f"a classificação automática mudou depois da conferência (de "
                     f"{NOMES_CATEGORIAS[_categoria_vista(d)]} para "
                     f"{NOMES_CATEGORIAS.get(categoria_automatica(linha), categoria_automatica(linha))}); confira de "
                     "novo e apague a marca")
        elif tipo == "manter" or conferida == categoria_automatica(linha):
            situacao = "mantida"
            resultado["mantidas"] += 1
        else:
            situacao = "aplicada"
            resultado["alteradas"].append({"modelo": modelo, "id": i, "automatica": categoria_automatica(linha),
                                           "conferida": conferida})
            linha["categoria_conferida"] = conferida
            if ((modelo, i) in piloto and tratamento_do_juiz(conferida) != tratamento_do_juiz(
                    categoria_automatica(linha))):
                resultado["avisos"].append(f"{nome}: está no piloto ({piloto[(modelo, i)]}), e com a decisão "
                                           "deixa de ter nota dos juízes; o piloto passa a ter uma resposta a menos")
        if aviso:
            resultado["avisos"].append(f"{nome}: {aviso}")
        resultado["decisoes"].append({"modelo": modelo, "id": i, "decisao": d["decisao"], "situacao": situacao})
    return resultado


def categoria(linha: dict) -> str:
    """A categoria da resposta: a conferida à mão no revisar.csv (versão 14), quando há, ou a automática."""
    return linha.get("categoria_conferida") or categoria_automatica(linha)


def categoria_automatica(linha: dict) -> str:
    """A categoria pelas regras de classificação desta versão, refeita sobre o texto gravado.

    As abstenções pelo limiar (o modelo nem foi chamado) ficam como foram
    gravadas. As citações gravadas foram contadas com o número de trechos
    da pergunta; para a classificação, basta saber se houve alguma.
    """
    texto = linha.get("resposta")
    if not linha.get("gerada_pelo_llm", True) or not isinstance(texto, str):
        return categoria_gravada(linha)
    from consulta import classificar_resposta        # aqui dentro: o consulta carrega a busca inteira
    citadas = linha.get("citadas")
    n_passagens = max(citadas, default=0) if isinstance(citadas, list) else 99
    return classificar_resposta(texto, n_passagens)


def reclassificadas(por_modelo: dict[str, dict[str, dict]]) -> list[dict]:
    """As respostas cuja categoria pelas regras desta versão é outra que a gravada na geração."""
    saida = []
    for modelo, respostas in por_modelo.items():
        for i, linha in respostas.items():
            if linha.get("categoria") and categoria_automatica(linha) != linha["categoria"]:
                saida.append({"modelo": modelo, "id": i, "gravada": linha["categoria"],
                              "atual": categoria_automatica(linha)})
    return saida


def _texto_reclassificadas(lista: list[dict], de: str = "gravada", para: str = "atual") -> str:
    return "; ".join(f"{info_modelo(r['modelo'])['rotulo']} {r['id']}, de "
                     f"{NOMES_CATEGORIAS.get(r[de], r[de])} para "
                     f"{NOMES_CATEGORIAS.get(r[para], r[para])}" for r in lista)


def ultimas_por_id(linhas: list[dict]) -> tuple[dict[str, dict], int]:
    """Uma linha por pergunta (a última) e quantas linhas repetidas havia."""
    saida: dict[str, dict] = {}
    for linha in linhas:
        saida[linha["id"]] = linha
    return saida, len(linhas) - len(saida)


def resumo_modelo(respostas: dict[str, dict], perguntas: dict[str, dict]) -> dict:
    """Contagens de um modelo (só as perguntas que ele já respondeu)."""
    r = {chave: 0 for chave, _, _ in COLUNAS if chave != "rotulo"}
    tempos, gerados, segundos = [], 0, 0.0
    for linha in respostas.values():
        item = perguntas.get(linha["id"])
        if item is None:
            continue
        cat = categoria(linha)
        pelo_limiar = not linha.get("gerada_pelo_llm", True)
        r["respondidas"] += 1
        if item["sem_resposta"]:
            r["sem_resposta"] += 1
            if pelo_limiar:
                r["absteve_limiar_certo"] += 1
            elif cat == "abstencao":
                r["absteve_modelo_certo"] += 1
            elif cat != "vazia":
                r["respondeu_sem_base"] += 1          # resposta, mista ou abstenção com acréscimo
        else:
            r["respondiveis"] += 1
            if pelo_limiar:
                r["absteve_antes"] += 1
            elif cat == "abstencao":
                r["absteve_modelo"] += 1
            elif cat == "abstencao_com_acrescimo":
                r["acrescimo_respondivel"] += 1
            elif cat in ("resposta", "mista"):
                r["respondeu"] += 1
        r["vazias"] += cat == "vazia"
        r["mistas"] += cat == "mista"
        r["sem_citacao"] += cat in ("resposta", "abstencao_com_acrescimo") and not linha.get("citacao_explicita")
        estatisticas = linha.get("estatisticas_llm") or {}
        r["cortadas"] += estatisticas.get("motivo_fim") == "length"
        r["raciocinou"] += bool(estatisticas.get("raciocinio_caracteres"))
        if linha.get("gerada_pelo_llm"):
            tempos.append(float(linha.get("tempos", {}).get("total_s") or 0.0))
            gerados += int(estatisticas.get("eval_count") or 0)
            segundos += float(estatisticas.get("eval_s") or 0.0)
    chegaram_r = r["respondiveis"] - r["absteve_antes"]
    chegaram_s = r["sem_resposta"] - r["absteve_limiar_certo"]
    r["taxa_resposta"] = r["respondeu"] / chegaram_r if chegaram_r else None
    r["taxa_abstencao_certa"] = r["absteve_modelo_certo"] / chegaram_s if chegaram_s else None
    r["tempo_medio_s"] = round(statistics.mean(tempos), 1) if tempos else None
    r["tempo_mediano_s"] = round(statistics.median(tempos), 1) if tempos else None
    r["tokens_por_s"] = round(gerados / segundos, 1) if segundos else None
    return r


def comparacoes(por_modelo: dict[str, dict[str, dict]], perguntas: dict[str, dict]) -> list[dict]:
    """McNemar exato para cada par de modelos, nas perguntas que os dois responderam:

    * nas perguntas sem resposta: quem se absteve, como devia (as paradas no
      limiar valem para os dois e não pesam no teste);
    * nas perguntas com resposta: quem respondeu (em vez de se abster).
    """
    def comportamento(respostas, sem_resposta: bool) -> dict[str, bool]:
        saida = {}
        for i, l in respostas.items():
            if i in perguntas and perguntas[i]["sem_resposta"] == sem_resposta:
                cat = categoria(l)
                saida[i] = (cat == "abstencao") if sem_resposta else (cat in ("resposta", "mista"))
        return saida
    saida = []
    for a, b in combinations(por_modelo, 2):
        for sem_resposta, criterio in ((True, "absteve-se nas perguntas sem resposta"),
                                       (False, "respondeu as perguntas com resposta")):
            ca, cb = comportamento(por_modelo[a], sem_resposta), comportamento(por_modelo[b], sem_resposta)
            comuns = sorted(set(ca) & set(cb))
            so_a = [i for i in comuns if ca[i] and not cb[i]]
            so_b = [i for i in comuns if cb[i] and not ca[i]]
            saida.append({"modelo_a": a, "modelo_b": b, "criterio": criterio, "perguntas": len(comuns),
                          "so_a": so_a, "so_b": so_b, "p": mcnemar_exato(len(so_a), len(so_b))})
    return saida


def para_revisar(por_modelo: dict[str, dict[str, dict]], perguntas: dict[str, dict]) -> list[dict]:
    """Respostas a conferir à mão: as sem base, as mistas, as com acréscimo, as
    vazias e as abstenções do modelo escritas com outras palavras."""
    linhas = []
    for modelo, respostas in por_modelo.items():
        for i, l in respostas.items():
            item = perguntas.get(i)
            if item is None or not l.get("gerada_pelo_llm", True):
                continue
            cat = categoria_automatica(l)          # a lista não muda com a conferência: a decisão fica na coluna dela
            motivo = None
            if item["sem_resposta"] and cat != "abstencao":
                motivo = "respondeu a uma pergunta que os documentos não respondem"
            elif cat in ("mista", "abstencao_com_acrescimo", "vazia"):
                motivo = {"mista": "cita trechos e diz que não encontrou",
                          "abstencao_com_acrescimo": "diz que não encontrou e acrescenta algo sem citar",
                          "vazia": "resposta vazia"}[cat]
            elif cat == "abstencao" and l.get("resposta", "").strip() != config.MENSAGEM_ABSTENCAO:
                motivo = "abstenção com outras palavras (conferir se é mesmo abstenção)"
            if motivo:
                linhas.append(_linha_revisar(modelo, i, l, item, motivo))
    return linhas


def _linha_revisar(modelo: str, i: str, linha: dict, item: dict, motivo: str) -> dict:
    """Uma linha do revisar.csv, com o texto e a classificação automática atuais da resposta."""
    return {"modelo": modelo, "id": i, "pergunta": item["pergunta"], "sem_resposta": "sim" if item["sem_resposta"]
            else "não", "categoria": categoria_automatica(linha), "motivo": motivo,
            "resposta": linha.get("resposta", ""), "resposta_correta": item.get("resposta_correta", "")}


def _medias_do_juiz(pasta: Path, modelo: str, resumo_juizes: dict | None = None) -> dict | None:
    """Médias do RAGAS de um modelo: a média dos juízes (versão 09) ou, numa rodada avaliada pelas
    versões 06 a 08 (um juiz só, notas soltas na pasta da rodada), as daquele juiz."""
    try:
        from avaliar_ragas import arquivo_ragas, medias_dos_juizes, medias_ragas
    except ImportError:
        return None
    if resumo_juizes:
        return medias_dos_juizes(pasta, modelo, resumo_juizes)
    return medias_ragas(pasta, modelo) if arquivo_ragas(pasta, modelo).exists() else None


_NOME_DA_LINGUA = {"portugues": "em português", "ingles": "em inglês"}


def _resumo_dos_juizes(pasta: Path) -> dict | None:
    """O resumo dos juízes da tabela (versão 15): os da língua de config.JUIZES_LINGUA, se todos eles avaliaram
    a rodada inteira (nenhuma nota faltando, nem a cobertura dos trechos); senão, os da outra língua, se eles
    avaliaram a rodada inteira, com o aviso do que falta na língua do config; e, se nenhuma das duas está
    completa, a que tem menos notas faltando, com as médias parciais avisadas. Os juízes em português só do
    piloto, por exemplo, não entram enquanto os em inglês tiverem a rodada inteira ou menos notas faltando."""
    try:
        from avaliar_ragas import comando_dos_juizes, faltam_notas, resumir_juizes
    except ImportError:
        return None
    preferida = config.JUIZES_LINGUA
    outra = "ingles" if preferida != "ingles" else "portugues"
    faltam = {lingua: faltam_notas(pasta, lingua) for lingua in (preferida, outra)}
    completa = {lingua: bool(f) and not any(f.values()) for lingua, f in faltam.items()}
    total = {lingua: sum(f.values()) for lingua, f in faltam.items()}
    if completa[preferida]:
        escolhida = preferida
    elif completa[outra]:
        escolhida = outra
    elif faltam[preferida] and faltam[outra]:           # as duas incompletas: a que tem menos notas faltando
        escolhida = preferida if total[preferida] <= total[outra] else outra
    elif faltam[preferida] or faltam[outra]:
        escolhida = preferida if faltam[preferida] else outra
    else:
        return None
    resumo = resumir_juizes(pasta, escolhida)
    if not resumo:
        return None
    avisos = []
    nao_usada = outra if escolhida == preferida else preferida
    if total[escolhida]:
        avisos.append(f"a avaliação dos juízes {_NOME_DA_LINGUA[escolhida]} não está completa (faltam "
                      f"{total[escolhida]} nota(s)): as médias saem só das respostas que todos avaliaram. Rode "
                      f"{comando_dos_juizes(escolhida)} para completar")
    if faltam[nao_usada] and total[nao_usada]:
        avisos.append(f"os juízes {_NOME_DA_LINGUA[nao_usada]} também não avaliaram a rodada inteira (faltam "
                      f"{total[nao_usada]} nota(s)); a tabela usa os juízes {_NOME_DA_LINGUA[escolhida]}"
                      + (f". Rode {comando_dos_juizes(nao_usada)} para completar" if nao_usada == preferida else "")
                      if total[escolhida] else
                      f"os juízes {_NOME_DA_LINGUA[nao_usada]} ainda não avaliaram a rodada inteira (faltam "
                      f"{total[nao_usada]} nota(s)); a tabela usa os juízes {_NOME_DA_LINGUA[escolhida]}"
                      + (f". Rode {comando_dos_juizes(nao_usada)} para completar" if nao_usada == preferida else ""))
    return {**resumo, "lingua": escolhida, "avisos_da_lingua": avisos}


def _notas_em_categoria_mudada(pasta: Path, por_modelo: dict[str, dict[str, dict]], lingua: str = "ingles") -> int:
    """Quantas notas dos juízes (do método atual) foram dadas numa categoria que o juiz trata de outro jeito que
    a categoria de agora (julgada contra sem nota): ainda contam como antes nas médias até o avaliar-ragas.bat
    refazê-las (versão 14)."""
    try:
        from avaliar_ragas import arquivo_ragas, ler_notas, pastas_dos_juizes
        pastas = pastas_dos_juizes(pasta, lingua)
    except (ImportError, ErroRodada):
        return 0
    n = 0
    for _, pasta_juiz in pastas:
        for modelo, respostas in por_modelo.items():
            notas, _ = ler_notas(arquivo_ragas(pasta_juiz, modelo))
            n += sum(1 for i, nota in notas.items() if i in respostas and nota.get("categoria")
                     and tratamento_do_juiz(nota["categoria"]) != tratamento_do_juiz(categoria(respostas[i])))
    return n


def avaliar_rodada(pasta: Path) -> dict:
    configuracao, lista = abrir_rodada(pasta)
    perguntas = {p["id"]: p for p in lista}
    modelos = [m["modelo"] for m in configuracao.get("modelos", [])]
    por_modelo, repetidas = {}, {}
    for modelo in modelos:
        respostas, n = ultimas_por_id(ler_respostas(arquivo_respostas(pasta, modelo)))
        if respostas:
            por_modelo[modelo] = respostas
        if n:
            repetidas[modelo] = n
    if not por_modelo:
        raise ErroRodada(f"a rodada {pasta.name} ainda não tem respostas; rode gerar-respostas.bat --continuar")
    conferencia = aplicar_conferencia(pasta, por_modelo, perguntas=perguntas)   # antes de contar: vale a conferida
    tabela = []
    resumo_juizes = _resumo_dos_juizes(pasta)
    for modelo, respostas in por_modelo.items():
        linha = {"modelo": modelo, "rotulo": info_modelo(modelo)["rotulo"]}
        linha.update(resumo_modelo(respostas, perguntas))
        juiz = _medias_do_juiz(pasta, modelo, resumo_juizes)
        for metrica in ("correcao", "completude", "fidelidade"):
            linha[f"{metrica}_media"] = (juiz.get(metrica) or {}).get("media") if juiz else None
        tabela.append(linha)
    revisar = para_revisar(por_modelo, perguntas)
    na_lista = {(r["modelo"], r["id"]) for r in revisar}
    conferencia["atuais"] = {}            # as respostas fora da lista com algo escrito na planilha, como estão agora
    for reg in (conferencia["planilha"] or {}).get("linhas", []):
        chave = reg.get("chave")
        if chave and chave not in na_lista and chave[1] in por_modelo.get(chave[0], {}) and chave[1] in perguntas:
            conferencia["atuais"][chave] = _linha_revisar(chave[0], chave[1], por_modelo[chave[0]][chave[1]],
                                                          perguntas[chave[1]], reg.get("motivo", ""))
    return {"rodada": pasta.name, "calculada_em": datetime.now().isoformat(timespec="seconds"),
            "versao_chatbot": config.VERSAO_CHATBOT, "versao_da_rodada": configuracao.get("versao_chatbot"),
            "perguntas": configuracao.get("perguntas"), "total_perguntas": len(perguntas),
            "limiar": configuracao.get("busca", {}).get("similaridade_minima"),
            "linhas_repetidas": repetidas, "tabela": tabela, "comparacoes": comparacoes(por_modelo, perguntas),
            "revisar": revisar, "reclassificadas": reclassificadas(por_modelo), "conferencia": conferencia,
            "notas_em_categoria_mudada": (_notas_em_categoria_mudada(pasta, por_modelo, resumo_juizes["lingua"])
                                          if resumo_juizes else 0),
            "lingua_dos_juizes": (resumo_juizes or {}).get("lingua"),
            "avisos_dos_juizes": (resumo_juizes or {}).get("avisos_da_lingua", []),
            "notas_antigas_dos_juizes": sum((resumo_juizes or {}).get("notas_antigas", {}).values()),
            "metodo_dos_juizes": (resumo_juizes or {}).get("metodo")}


def _valor(v, casas=1) -> str:
    if v is None:
        return "-"
    if casas == "pct":
        return f"{round(100 * v)}%"
    if isinstance(v, float):
        return f"{v:.{casas}f}".replace(".", ",")
    return str(v)


def _p(v: float) -> str:
    return f"{v:.3f}".replace(".", ",")


def colunas(resultado: dict) -> list[tuple]:
    lista = list(COLUNAS)
    if any(l.get(c) is not None for l in resultado["tabela"] for c, _, _ in COLUNAS_JUIZ):
        lista += COLUNAS_JUIZ
    return lista


def _texto_conferencia(conferencia: dict) -> str:
    alteradas, mantidas = conferencia.get("alteradas", []), conferencia.get("mantidas", 0)
    texto = "Classificação conferida à mão (coluna \"sua conferência\" do revisar.csv): "
    if alteradas:
        texto += (f"{len(alteradas)} resposta(s) mudaram de categoria "
                  f"({_texto_reclassificadas(alteradas, 'automatica', 'conferida')})")
    else:
        texto += "nenhuma resposta mudou de categoria"
    return (texto + f"; {mantidas} ficaram como o programa classificou. As contagens e as comparações usam a categoria "
            "conferida; o arquivo de respostas não muda.")


def _comando(resultado: dict) -> str:
    try:
        from avaliar_ragas import comando_dos_juizes
    except ImportError:
        return "avaliar-ragas.bat"
    return comando_dos_juizes(resultado.get("lingua_dos_juizes") or config.JUIZES_LINGUA)


def _texto_notas_mudadas(n: int, comando: str = "avaliar-ragas.bat") -> str:
    return (f"Atenção: {n} nota(s) dos juízes foram dadas antes da conferência, numa categoria que ela mudou, e ainda "
            f"contam como antes nas médias; rode {comando}, que refaz só essas.")


def _decididas(resultado: dict) -> int:
    """Quantas respostas da lista do revisar.csv têm uma decisão que vale."""
    validas = {(d["modelo"], d["id"]) for d in (resultado.get("conferencia") or {}).get("decisoes", [])
               if d["situacao"] in ("aplicada", "mantida")}
    return sum((l["modelo"], l["id"]) in validas for l in resultado["revisar"])


def _texto_lingua(resultado: dict) -> str:
    return ("As médias dos juízes são as dos juízes " + ("em português (os exemplos dos prompts do RAGAS em português, "
            "versão 15)." if resultado["lingua_dos_juizes"] == "portugues" else "com os prompts do RAGAS como vêm, em "
            "inglês."))


def texto_markdown(resultado: dict) -> str:
    limiar = resultado.get("limiar")
    limiar_txt = _valor(float(limiar), 2) if limiar is not None else "-"
    linhas = [f"# Confiabilidade da rodada {resultado['rodada']}", "",
              f"Perguntas: {resultado['perguntas'].get('arquivo')} (assinatura "
              f"{resultado['perguntas'].get('assinatura')}), {resultado['total_perguntas']} na rodada. "
              f"Código da rodada: versão {resultado['versao_da_rodada']}. Calculada em {resultado['calculada_em']}.",
              "", "| " + " | ".join(t for _, t, _ in colunas(resultado)) + " |",
              "|" + "-|" * len(colunas(resultado))]
    for linha in resultado["tabela"]:
        linhas.append("| " + " | ".join(_valor(linha.get(c), casas) for c, _, casas in colunas(resultado)) + " |")
    linhas += ["", "Respondeu sem base = respondeu (ou se absteve acrescentando algo sem citar) a uma pergunta que "
               "os documentos não respondem: o caso que o requisito do trabalho quer evitar. Abstenção pelo limiar = "
               f"nenhum trecho passou na similaridade mínima ({limiar_txt}); é igual para todos os modelos, porque "
               "os trechos estão congelados, e por isso as taxas contam só as perguntas que chegaram ao modelo. A "
               "classificação das respostas é automática; o revisar.csv lista as que merecem conferência à mão, e "
               "a decisão escrita na coluna \"sua conferência\" passa a valer aqui."]
    if resultado.get("lingua_dos_juizes") and any(l.get(c) is not None for l in resultado["tabela"]
                                                  for c, _, _ in COLUNAS_JUIZ):
        linhas += ["", _texto_lingua(resultado)]
    for aviso in resultado.get("avisos_dos_juizes", []):
        linhas += ["", f"Atenção: {aviso}."]
    if resultado.get("reclassificadas"):
        linhas += ["", f"Classificação refeita pelas regras da versão {config.VERSAO_CHATBOT}: "
                   f"{len(resultado['reclassificadas'])} resposta(s) mudaram de categoria em relação à gravada na "
                   f"geração ({_texto_reclassificadas(resultado['reclassificadas'])}). O arquivo de respostas não "
                   "muda."]
    conferencia = resultado.get("conferencia") or {}
    if conferencia.get("alteradas") or conferencia.get("mantidas"):
        linhas += ["", _texto_conferencia(conferencia)]
    if conferencia.get("avisos"):
        linhas += ["", "Atenção: decisões do revisar.csv que não valeram ou pedem cuidado: "
                   + "; ".join(conferencia["avisos"]) + "."]
    if resultado.get("notas_em_categoria_mudada"):
        linhas += ["", _texto_notas_mudadas(resultado["notas_em_categoria_mudada"], _comando(resultado))]
    if resultado.get("notas_antigas_dos_juizes"):
        linhas += ["", f"Atenção: {resultado['notas_antigas_dos_juizes']} nota(s) dos juízes foram dadas por um "
                   f"método anterior à versão {resultado.get('metodo_dos_juizes')} e não entram nas médias; rode "
                   f"{_comando(resultado)} para refazê-las."]
    if resultado.get("linhas_repetidas"):
        linhas += ["", "Atenção: respostas repetidas para a mesma pergunta (duas execuções ao mesmo tempo?); vale a "
                   "última de cada pergunta: " + ", ".join(f"{m}: {n}" for m, n in resultado["linhas_repetidas"].items())]
    linhas += ["", "## Comparação dos modelos (McNemar exato)", ""]
    for c in resultado["comparacoes"]:
        if not c["perguntas"]:
            continue
        a, b = info_modelo(c["modelo_a"])["rotulo"], info_modelo(c["modelo_b"])["rotulo"]
        linhas.append(f"- {a} x {b}, {c['criterio']} ({c['perguntas']} perguntas): só o {a}: {len(c['so_a'])}"
                      + (f" ({', '.join(c['so_a'])})" if c["so_a"] else "") + f"; só o {b}: {len(c['so_b'])}"
                      + (f" ({', '.join(c['so_b'])})" if c["so_b"] else "") + f"; p = {_p(c['p'])}")
    return "\n".join(linhas) + "\n"


def _decisao_para_gravar(registro: dict | None, situacao: str | None) -> str:
    """O texto da coluna "sua conferência" no revisar.csv novo: a decisão como estava, com a marca no começo se
    ela precisa ser conferida de novo."""
    if registro is None:
        return ""
    texto = registro["decisao"].strip()
    if texto and situacao == "desatualizada" and not texto.startswith(MARCA_DESATUALIZADA):
        return f"{MARCA_DESATUALIZADA} {texto}"
    return texto


def linhas_do_revisar(resultado: dict) -> tuple[list[str], list[list[str]]]:
    """O cabeçalho e as linhas do revisar.csv novo, com tudo o que a pessoa escreveu (versão 14).

    Cada resposta da lista leva a decisão e as colunas a mais que já tinha
    (se a mesma resposta estava em mais de uma linha, vão todas). As linhas
    de respostas que saíram da lista e têm decisão ou algo escrito nas
    colunas a mais vão para o fim, com o texto e a categoria atuais da
    resposta quando ela está na rodada, para a decisão poder voltar a valer
    quando a marca for apagada. As linhas sem modelo ou id que tinham algo
    escrito também ficam, no fim.
    """
    conferencia = resultado.get("conferencia") or {}
    planilha = conferencia.get("planilha") or {"linhas": [], "extras": []}
    extras = planilha["extras"]
    atuais = conferencia.get("atuais") or {}
    situacao = {(d["modelo"], d["id"]): d["situacao"] for d in conferencia.get("decisoes", [])}
    antigas: dict[tuple[str, str], list[dict]] = {}
    soltas = []
    for reg in planilha["linhas"]:
        if reg.get("chave"):
            antigas.setdefault(reg["chave"], []).append(reg)
        elif reg["decisao"] or any(v.strip() for v in reg["extras"]) or any(reg[c].strip() for c in CAMPOS_REVISAR):
            soltas.append(reg)

    def montar(campos: dict, reg: dict | None, chave) -> list[str]:
        return ([str(campos.get(c, "")) for c in CAMPOS_REVISAR] + [_decisao_para_gravar(reg, situacao.get(chave))]
                + (list(reg["extras"]) if reg else [""] * len(extras)))

    saida, na_lista = [], set()
    for linha in resultado["revisar"]:
        chave = (linha["modelo"], linha["id"])
        na_lista.add(chave)
        for reg in antigas.get(chave) or [None]:
            saida.append(montar(linha, reg, chave))
    for chave, regs in antigas.items():
        if chave in na_lista:
            continue
        for reg in regs:
            if reg["decisao"] or any(v.strip() for v in reg["extras"]):
                saida.append(montar(atuais.get(chave) or reg, reg, chave))
    for reg in soltas:
        saida.append([reg.get(c, "") for c in CAMPOS_REVISAR] + [reg["decisao"]] + list(reg["extras"]))
    return CAMPOS_REVISAR + [COLUNA_CONFERENCIA] + extras, saida


def _gravar_revisar(pasta: Path, cabecalho: list[str], linhas: list[list[str]]) -> None:
    """Grava o revisar.csv por um arquivo temporário, trocado no fim: uma queda no meio não o deixa pela metade.
    Se o conteúdo vai mudar, guarda antes uma cópia do de antes em revisar_anteriores/, com a data e a hora no
    nome; com o mesmo conteúdo, não grava nada."""
    caminho = pasta / ARQUIVO_REVISAR
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    novo = buffer.getvalue().encode("utf-8-sig")
    antigo = caminho.read_bytes() if caminho.exists() else None
    if antigo == novo:
        return
    copia = None
    if antigo and antigo.strip():
        copias = pasta / PASTA_REVISAR_ANTERIORES
        copias.mkdir(exist_ok=True)
        base = f"revisar_{datetime.now():%Y-%m-%d_%H%M%S}"
        copia, n = copias / f"{base}.csv", 2
        while copia.exists():
            copia, n = copias / f"{base}_{n}.csv", n + 1
        copia.write_bytes(antigo)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_bytes(novo)
    for tentativa in range(5):
        try:
            os.replace(temporario, caminho)
            return
        except PermissionError:
            if tentativa == 4:
                temporario.unlink(missing_ok=True)
                if copia is not None:            # o arquivo de antes ficou onde estava: a cópia não é preciso
                    copia.unlink(missing_ok=True)
                raise
            time.sleep(0.5)


def gravar(pasta: Path, resultado: dict) -> None:
    conferencia = {k: v for k, v in (resultado.get("conferencia") or {}).items() if k not in ("planilha", "atuais")}
    (pasta / "confiabilidade.json").write_text(json.dumps({**resultado, "conferencia": conferencia},
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / "confiabilidade.md").write_text(texto_markdown(resultado), encoding="utf-8")
    with open(pasta / "confiabilidade.csv", "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(["modelo"] + [t for _, t, _ in colunas(resultado)])
        for linha in resultado["tabela"]:
            escritor.writerow([linha["modelo"]] + [_valor(linha.get(c), casas) for c, _, casas in colunas(resultado)])
    _gravar_revisar(pasta, *linhas_do_revisar(resultado))


def imprimir(resultado: dict) -> None:
    print(f"Rodada {resultado['rodada']}: {resultado['total_perguntas']} perguntas "
          f"({resultado['perguntas'].get('arquivo')})\n")
    for linha in resultado["tabela"]:
        print(f"{linha['rotulo']} ({linha['respondidas']} de {resultado['total_perguntas']} perguntas):")
        print(f"  com resposta nos documentos: {linha['respondiveis']} | respondeu {linha['respondeu']} | "
              f"abstenção pelo limiar {linha['absteve_antes']} | do modelo {linha['absteve_modelo']} | "
              f"com acréscimo {linha['acrescimo_respondivel']} | respondeu "
              f"{_valor(linha['taxa_resposta'], 'pct')} das que chegaram ao modelo")
        print(f"  sem resposta nos documentos: {linha['sem_resposta']} | absteve-se pelo limiar "
              f"{linha['absteve_limiar_certo']} | o modelo {linha['absteve_modelo_certo']} | respondeu sem base "
              f"{linha['respondeu_sem_base']} | absteve-se {_valor(linha['taxa_abstencao_certa'], 'pct')} das que "
              "chegaram ao modelo")
        print(f"  vazias {linha['vazias']} | mistas {linha['mistas']} | sem citação {linha['sem_citacao']} | "
              f"cortadas {linha['cortadas']} | tempo médio {_valor(linha['tempo_medio_s'])} s (mediano "
              f"{_valor(linha['tempo_mediano_s'])} s) | escrita {_valor(linha['tokens_por_s'])} tokens/s"
              + (f" | raciocinou {linha['raciocinou']}" if linha["raciocinou"] else ""))
        if any(linha.get(c) is not None for c, _, _ in COLUNAS_JUIZ):
            print(f"  juízes: correção (F1) média {_valor(linha['correcao_media'], 2)} | completude média "
                  f"{_valor(linha['completude_media'], 2)} | fidelidade média {_valor(linha['fidelidade_media'], 2)}")
    if resultado.get("lingua_dos_juizes") and any(l.get(c) is not None for l in resultado["tabela"]
                                                  for c, _, _ in COLUNAS_JUIZ):
        print("\n" + _texto_lingua(resultado))
    for aviso in resultado.get("avisos_dos_juizes", []):
        print(f"Atenção: {aviso}.")
    if resultado.get("reclassificadas"):
        print(f"\nClassificação refeita pelas regras da versão {config.VERSAO_CHATBOT}: "
              f"{len(resultado['reclassificadas'])} resposta(s) mudaram de categoria "
              f"({_texto_reclassificadas(resultado['reclassificadas'])}). O arquivo de respostas não muda.")
    conferencia = resultado.get("conferencia") or {}
    if conferencia.get("alteradas") or conferencia.get("mantidas"):
        print("\n" + _texto_conferencia(conferencia))
    for aviso in conferencia.get("avisos", []):
        print(f"Atenção (revisar.csv): {aviso}")
    if resultado.get("notas_em_categoria_mudada"):
        print("\n" + _texto_notas_mudadas(resultado["notas_em_categoria_mudada"], _comando(resultado)))
    if resultado.get("notas_antigas_dos_juizes"):
        print(f"\nAtenção: {resultado['notas_antigas_dos_juizes']} nota(s) dos juízes são de um método anterior à "
              f"versão {resultado.get('metodo_dos_juizes')} e não entram nas médias; rode {_comando(resultado)} para "
              "refazê-las.")
    if resultado.get("linhas_repetidas"):
        print(f"\nAtenção: respostas repetidas (vale a última de cada pergunta): {resultado['linhas_repetidas']}")
    if resultado["comparacoes"]:
        print("\nMcNemar exato (cada par de modelos):")
        for c in resultado["comparacoes"]:
            if c["perguntas"]:
                print(f"  {info_modelo(c['modelo_a'])['rotulo']} x {info_modelo(c['modelo_b'])['rotulo']}, "
                      f"{c['criterio']}: {len(c['so_a'])} x {len(c['so_b'])}, p = {_p(c['p'])}")
    decididas = _decididas(resultado)
    print(f"\n{len(resultado['revisar'])} resposta(s) para conferir à mão em revisar.csv"
          + (f" ({decididas} já com decisão)" if decididas else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tabela de confiabilidade de uma rodada de respostas.")
    parser.add_argument("--rodada", type=Path, default=None, help="pasta da rodada (padrão: a mais recente)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        pasta = args.rodada or rodada_mais_recente()
        if pasta is None:
            raise ErroRodada(f"nenhuma rodada em {pasta_das_rodadas()}; rode gerar-respostas.bat antes.")
        pasta = Path(pasta)
        if not pasta.is_absolute() and not pasta.exists():
            pasta = config.BASE_DIR / pasta
        resultado = avaliar_rodada(pasta)
    except ErroRodada as erro:
        print(f"ERRO: {erro}")
        return 1
    imprimir(resultado)
    try:
        gravar(pasta, resultado)
    except PermissionError as erro:
        print(f"\nERRO: não consegui gravar {getattr(erro, 'filename', '') or 'um dos arquivos'}; feche-o (no Excel?) "
              "e rode de novo. As decisões do revisar.csv não foram apagadas.")
        return 1
    print(f"\nTabela gravada em {pasta / 'confiabilidade.md'} (e .csv, .json; conferência em revisar.csv)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
