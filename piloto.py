"""Piloto dos juízes: as notas de uma pessoa contra as dos juízes, numa amostra de respostas (versão 12).

    python piloto.py preparar            # sorteia as respostas e grava o material (rodada mais recente)
    python piloto.py comparar            # depois de preenchida a planilha: a concordância com os juízes
    python piloto.py preparar --rodada avaliacao/rodadas/2026-11-03_1112_perguntas_recuperacao

A monografia prevê conferir os juízes contra a avaliação humana antes de usar
as notas deles. O piloto:

1. sorteia config.PILOTO_POR_MODELO respostas de cada modelo, com a semente
   config.PILOTO_SEMENTE, entre as que recebem as três notas dos juízes:
   perguntas com resposta correta que o modelo respondeu (resposta, mista ou
   abstenção com acréscimo, pela classificação desta versão). Só entram as
   perguntas que todos os modelos da rodada responderam: se um modelo parou
   numa parte das perguntas, as outras diriam, só por aparecerem, que a
   resposta não é dele;
2. grava na pasta piloto/ da rodada o caderno de leitura (piloto_caderno.html:
   para cada resposta, a pergunta, a resposta correta, a resposta do modelo e
   os trechos que ele recebeu) e a planilha (piloto_notas.csv), com um código
   por resposta, em ordem sorteada. O caderno e a planilha não dizem qual
   modelo respondeu nem as notas dos juízes, para não influenciar quem
   avalia, e o caderno mostra as respostas sem as marcas de formatação que
   variam de um modelo para outro (negrito, títulos, tipo e espaçamento das
   marcas de lista); a chave fica em piloto_chave.json;
3. quem avalia preenche, para cada código, a correção (correta, parcial ou
   incorreta, comparada com a resposta correta) e a fidelidade (fiel, parcial
   ou infiel, comparada com os trechos);
4. comparar lê a planilha e as notas dos juízes, converte as notas deles (de
   0 a 1) nos mesmos três níveis com os cortes de config.PILOTO_CORTES,
   fixados antes de existirem as notas da pessoa, e calcula, para cada juiz e
   para a média dos dois, o kappa ponderado, a correlação de Spearman (que não
   depende dos cortes) e a concordância exata, com intervalos de confiança
   por bootstrap. A correção é comparada com o F1 e com a completude, para
   decidir qual delas vira a nota principal; o resultado traz também a
   diferença entre as duas, a de cada juiz para a média e o desvio por modelo.
   Só sai resultado com a planilha terminada, para ele não influenciar as
   notas que faltam;
5. se os juízes em português avaliaram as respostas do piloto (versão 13:
   juizes-em-portugues.bat, que roda avaliar_ragas.py --portugues
   --so-piloto), comparar põe cada juiz e a média em inglês e em português
   lado a lado, com a diferença entre as duas línguas (português menos
   inglês, no kappa e no Spearman, com intervalo), para decidir em que língua
   o juiz escreve as afirmações. A diferença entre o F1 e a completude e a de
   cada juiz para a média são calculadas dentro de cada língua.

Nada é apagado: preparar não grava por cima de um piloto existente, e
--refazer guarda o anterior numa pasta com a data e a hora no nome.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import random
import re
import statistics
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import config
from avaliar_ragas import (ARQUIVO_CHAVE_PILOTO, METRICAS, PASTA_PILOTO, arquivo_ragas, ler_notas, pastas_dos_juizes,
                           texto_para_o_juiz)
from avaliar_respostas import categoria
from estatistica import intervalo_bootstrap, kappa_ponderado, spearman
from gerar_respostas import (ErroRodada, abrir_rodada, arquivo_respostas, ler_contextos, ler_respostas,
                             pasta_das_rodadas, rodada_mais_recente)
from modelos import info_modelo

# PASTA_PILOTO ("piloto") vem do avaliar_ragas, que lê a chave para avaliar só as respostas sorteadas (--so-piloto).
ARQUIVO_CHAVE = ARQUIVO_CHAVE_PILOTO                # piloto_chave.json
ARQUIVO_CADERNO = "piloto_caderno.html"
ARQUIVO_PLANILHA = "piloto_notas.csv"
RESULTADO = "piloto_resultado"                     # .md e .json
CATEGORIAS_JULGADAS = ("resposta", "mista", "abstencao_com_acrescimo")
NIVEIS = {"correcao": ("incorreta", "parcial", "correta"), "fidelidade": ("infiel", "parcial", "fiel")}
COLUNAS = ("codigo", "correcao", "fidelidade", "observacao")
# O que a pessoa pode escrever na planilha (sem acentos, em minúsculas), para cada nível de 0 a 2.
ACEITOS = {
    "correcao": ({"incorreta", "incorreto", "i", "errada", "0"}, {"parcial", "p", "0,5", "0.5"},
                 {"correta", "correto", "c", "certa", "1"}),
    "fidelidade": ({"infiel", "i", "0"}, {"parcial", "p", "0,5", "0.5"}, {"fiel", "f", "1"}),
}
# Qual nota do juiz entra em cada comparação (a correção humana é comparada com o F1 e com a completude).
COMPARACOES = (("correcao", "correcao"), ("correcao", "completude"), ("fidelidade", "fidelidade"))
NOMES_METRICAS = {"correcao": "correção (F1)", "completude": "completude", "fidelidade": "fidelidade"}
MEDIA = "media_dos_juizes"
# Nas chaves dos avaliadores, o juiz (ou a média) com os prompts em português (versão 13): "ministral-3:8b|pt".
SUFIXO_PORTUGUES = "|pt"


class ErroPiloto(Exception):
    """O piloto não pode seguir (planilha incompleta, piloto já existente...)."""


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().strip().lower()


def pasta_do_piloto(pasta: Path) -> Path:
    return pasta / PASTA_PILOTO


def _cortes(cortes=None) -> dict[str, tuple[float, float]]:
    """Os cortes de cada avaliação humana: {"correcao": (baixo, alto), "fidelidade": (baixo, alto)}.

    Os da correção valem para o F1 e para a completude. Um par só vale para as duas.
    """
    cortes = config.PILOTO_CORTES if cortes is None else cortes
    if isinstance(cortes, dict):
        return {c: (float(cortes[c][0]), float(cortes[c][1])) for c in ("correcao", "fidelidade")}
    baixo, alto = cortes
    return {c: (float(baixo), float(alto)) for c in ("correcao", "fidelidade")}


# Sorteio
def _respostas_por_modelo(pasta: Path) -> dict[str, dict[str, dict]]:
    configuracao, _ = abrir_rodada(pasta)
    return {item["modelo"]: {l["id"]: l for l in ler_respostas(arquivo_respostas(pasta, item["modelo"]))}
            for item in configuracao.get("modelos", [])}


def perguntas_comuns(respostas: dict[str, dict[str, dict]]) -> set[str]:
    """As perguntas que todos os modelos com respostas na rodada responderam."""
    conjuntos = [set(r) for r in respostas.values() if r]
    return set.intersection(*conjuntos) if conjuntos else set()


def avisos_do_sorteio(pasta: Path) -> list[str]:
    """Os avisos sobre as perguntas que ficam fora do sorteio porque algum modelo não as respondeu."""
    _, perguntas = abrir_rodada(pasta)
    com_resposta = {p["id"] for p in perguntas if not p.get("sem_resposta") and p.get("resposta_correta")}
    respostas = _respostas_por_modelo(pasta)
    avisos = [f"{info_modelo(m)['rotulo']} não tem respostas nesta rodada e fica fora do piloto."
              for m, r in sorted(respostas.items()) if not r]
    respondidas = {m: set(r) & com_resposta for m, r in respostas.items() if r}
    todas = set().union(*respondidas.values()) if respondidas else set()
    comuns = set.intersection(*respondidas.values()) if respondidas else set()
    if comuns != todas:
        avisos.append(f"Só entram as {len(comuns)} perguntas com resposta correta que todos os modelos responderam, de "
                      f"{len(todas)} (" + ", ".join(f"{info_modelo(m)['rotulo']} respondeu a {len(r)}"
                                                    for m, r in sorted(respondidas.items()) if r != todas)
                      + "). Para sortear entre todas, complete as respostas com gerar-respostas.bat --continuar e as "
                        "notas com avaliar-ragas.bat, e sorteie de novo com preparar-piloto.bat --refazer.")
    return avisos


def elegiveis(pasta: Path) -> dict[str, list[str]]:
    """Por modelo, as perguntas cuja resposta recebe as três notas dos juízes (ids em ordem).

    Só entram as perguntas que todos os modelos responderam (item 1 do começo do arquivo).
    """
    _, perguntas = abrir_rodada(pasta)
    com_resposta = {p["id"] for p in perguntas if not p.get("sem_resposta") and p.get("resposta_correta")}
    respostas = _respostas_por_modelo(pasta)
    comuns = perguntas_comuns(respostas)
    saida = {}
    for modelo, linhas in respostas.items():
        ids = [i for i, l in linhas.items() if i in com_resposta and i in comuns and l.get("gerada_pelo_llm", True)
               and categoria(l) in CATEGORIAS_JULGADAS and texto_para_o_juiz(l.get("resposta") or "")]
        if ids:
            saida[modelo] = sorted(ids)
    return saida


def sortear(pasta: Path, por_modelo: int | None = None, semente: int | None = None) -> list[dict]:
    """A amostra do piloto: por_modelo respostas de cada modelo e um código para cada uma, em ordem sorteada.

    O mesmo arquivo de respostas, com a mesma semente, dá sempre a mesma
    amostra, para o sorteio poder ser repetido e conferido.
    """
    por_modelo = config.PILOTO_POR_MODELO if por_modelo is None else por_modelo
    semente = config.PILOTO_SEMENTE if semente is None else semente
    sorteio = random.Random(semente)
    amostra = []
    for modelo, ids in sorted(elegiveis(pasta).items()):
        escolhidos = sorted(sorteio.sample(ids, min(por_modelo, len(ids))))
        amostra += [{"modelo": modelo, "id": i} for i in escolhidos]
    sorteio.shuffle(amostra)
    largura = max(2, len(str(len(amostra))))
    return [dict(item, codigo=f"P{n:0{largura}d}") for n, item in enumerate(amostra, 1)]


# Material
_RE_NEGRITO = re.compile(r"\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|__(.+?)__")      # dentro da mesma linha
_RE_TITULO = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M)
_RE_MARCA_DE_LISTA = re.compile(r"^([ \t]*)(?:[*\-\u2022]|(\d+)\.)[ \t]+", re.M)


def _marca_de_lista(m: re.Match) -> str:
    """A marca de lista no formato do caderno: "- " ou "1. ", com recuo de 4 espaços por nível (até 2 níveis)."""
    recuo = len(m.group(1).expandtabs(4))
    nivel = 0 if recuo == 0 else 1 if recuo <= 4 else 2
    return "    " * nivel + (f"{m.group(2)}. " if m.group(2) else "- ")


def texto_do_caderno(texto: str) -> str:
    """A resposta como aparece no caderno, sem as marcas de formatação que variam de um modelo para outro.

    Tira o negrito e os títulos do Markdown e põe todas as listas num formato
    só ("- " ou "1. "), porque o tipo e o espaçamento das marcas de lista
    mudam de um modelo para outro (o Qwen 3.8 27B escreve "*" e três
    espaços). O recuo das listas de dentro vira um recuo só, de 4 espaços por
    nível, para o item de dentro continuar dentro. As palavras da resposta
    não mudam.
    """
    texto = _RE_NEGRITO.sub(lambda m: next(g for g in m.groups() if g is not None), texto or "")
    texto = _RE_TITULO.sub("", texto)
    texto = _RE_MARCA_DE_LISTA.sub(_marca_de_lista, texto)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _cabecalho_trecho(p: dict) -> str:
    paginas = (f"p. {p.get('pagina_inicio')}" if p.get("pagina_inicio") == p.get("pagina_fim")
               else f"p. {p.get('pagina_inicio')}-{p.get('pagina_fim')}")
    partes = [str(p.get("documento") or p.get("fonte") or ""), paginas]
    local = (p.get("localizacao") or "") + (f" ({p['secao']})" if p.get("secao") else "")
    if local.strip():
        partes.append(local.strip())
    if p.get("artigo_inicio") is not None:
        partes.append(f"Art. {p['artigo_inicio']}" if p.get("artigo_inicio") == p.get("artigo_fim")
                      else f"Arts. {p['artigo_inicio']} a {p['artigo_fim']}")
    return " | ".join(x for x in partes if x)


GUIA = """
<h2>Como avaliar</h2>
<p>Para cada código, preencha duas colunas da planilha <code>piloto_notas.csv</code> (abre no Excel; salve no mesmo
formato). O caderno não diz qual modelo respondeu nem as notas dos juízes, de propósito, e mostra as respostas sem
negrito e com as listas num formato só, para o estilo não revelar o modelo.</p>
<p><b>Correção</b>: compare a resposta do modelo com a <b>resposta correta</b>.</p>
<ul>
<li><b>correta</b>: traz o essencial da resposta correta e não afirma nada errado;</li>
<li><b>parcial</b>: traz parte do essencial, ou deixa de fora algo importante, sem afirmar nada errado;</li>
<li><b>incorreta</b>: não traz o essencial, ou afirma algo que contradiz a resposta correta.</li>
</ul>
<p><b>Fidelidade</b>: compare a resposta do modelo com os <b>trechos</b> que ele recebeu (e não com a resposta
correta).</p>
<ul>
<li><b>fiel</b>: tudo o que a resposta afirma está nos trechos;</li>
<li><b>parcial</b>: algum detalhe não está nos trechos;</li>
<li><b>infiel</b>: a informação principal não está nos trechos, ou os contradiz.</li>
</ul>
<p>As marcas de citação ([1], [2]) e a menção à fonte (documento, artigo) não contam a favor nem contra.
Se não souber decidir, deixe em branco e escreva o motivo na coluna de observação. Linha sem nota e sem observação
conta como não terminada: o resultado só sai com a planilha terminada, para não influenciar as notas que faltam.</p>
"""


def caderno_html(amostra: list[dict], pasta: Path, semente: int | None = None) -> str:
    """O caderno de leitura: um bloco por código, sem o nome do modelo nem as notas dos juízes."""
    semente = config.PILOTO_SEMENTE if semente is None else semente
    _, perguntas = abrir_rodada(pasta)
    por_id = {p["id"]: p for p in perguntas}
    contextos = ler_contextos(pasta)
    respostas = {}
    for modelo in {a["modelo"] for a in amostra}:
        respostas[modelo] = {l["id"]: l for l in ler_respostas(arquivo_respostas(pasta, modelo))}
    e = html.escape
    blocos = []
    for item in amostra:
        pergunta = por_id[item["id"]]
        resposta = texto_do_caderno(respostas[item["modelo"]][item["id"]].get("resposta") or "")
        trechos = contextos.get(item["id"], {}).get("passagens", [])
        partes = [f'<section id="{e(item["codigo"])}"><h2>{e(item["codigo"])}</h2>',
                  f"<p><b>Pergunta:</b> {e(pergunta['pergunta'])}</p>",
                  f"<p><b>Resposta correta:</b> {e(pergunta.get('resposta_correta') or '')}</p>",
                  f'<div class="resposta"><b>Resposta do modelo:</b><div class="texto">{e(resposta)}</div></div>',
                  f"<details><summary>Trechos que o modelo recebeu ({len(trechos)})</summary>"]
        for p in trechos:
            partes.append(f'<div class="trecho"><b>[{e(str(p.get("numero", "")))}] {e(_cabecalho_trecho(p))}</b>'
                          f'<div class="texto">{e(p.get("texto") or "")}</div></div>')
        partes.append("</details></section>")
        blocos.append("\n".join(partes))
    estilo = """
<style>
:root { color-scheme: light dark; --fundo: #ffffff; --texto: #1d1d1f; --caixa: #f3f4f6; --borda: #d0d4da; }
@media (prefers-color-scheme: dark) { :root { --fundo: #17181b; --texto: #e8e8ea; --caixa: #23252a; --borda: #3a3d44; } }
body { background: var(--fundo); color: var(--texto); font-family: system-ui, sans-serif; line-height: 1.5;
       max-width: 900px; margin: 0 auto; padding: 16px; }
section { border-top: 2px solid var(--borda); padding-top: 8px; margin-top: 24px; }
.texto { white-space: pre-wrap; background: var(--caixa); border: 1px solid var(--borda); border-radius: 6px;
         padding: 8px 10px; margin: 6px 0 12px; }
.trecho { margin: 10px 0; font-size: 0.95em; }
summary { cursor: pointer; font-weight: bold; }
</style>"""
    return ("<!doctype html>\n<html lang=\"pt-BR\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>Piloto dos juízes</title>{estilo}\n</head>\n<body>\n<h1>Piloto dos juízes: rodada "
            f"{e(pasta.name)}</h1>\n<p>{len(amostra)} respostas, sorteadas com a semente "
            f"{semente}.</p>\n{GUIA}\n" + "\n".join(blocos) + "\n</body>\n</html>\n")


def preparar(pasta: Path, por_modelo: int | None = None, semente: int | None = None, refazer: bool = False,
             saida=print) -> Path:
    """Sorteia a amostra e grava a chave, o caderno e a planilha na pasta piloto/ da rodada."""
    destino = pasta_do_piloto(pasta)
    if destino.exists():
        if not refazer:
            raise ErroPiloto(f"já existe um piloto nesta rodada ({destino}). Para sortear de novo sem perder o "
                             "atual, use --refazer: o piloto atual vai para uma pasta com a data e a hora no nome.")
        guardado = pasta / f"{PASTA_PILOTO}_{datetime.now():%Y%m%d_%H%M%S}"
        destino.rename(guardado)
        saida(f"O piloto anterior foi guardado em {guardado.name}.")
    semente = config.PILOTO_SEMENTE if semente is None else semente
    por_modelo = config.PILOTO_POR_MODELO if por_modelo is None else por_modelo
    for aviso in avisos_do_sorteio(pasta):
        saida(aviso)
    amostra = sortear(pasta, por_modelo, semente)
    if not amostra:
        raise ErroPiloto("nenhuma resposta da rodada recebe as notas dos juízes (perguntas com resposta correta que "
                         "todos os modelos responderam); não há o que sortear.")
    contagem = {}
    for item in amostra:
        contagem[item["modelo"]] = contagem.get(item["modelo"], 0) + 1
    poucos = {m: n for m, n in contagem.items() if n < por_modelo}
    if poucos:
        saida("Atenção: " + ", ".join(f"{info_modelo(m)['rotulo']} só tem {n}" for m, n in sorted(poucos.items()))
              + f" das {por_modelo} respostas pedidas; entram todas as que podem ser sorteadas.")
    destino.mkdir()
    chave = {"rodada": pasta.name, "criado_em": datetime.now().isoformat(timespec="seconds"),
             "versao_chatbot": config.VERSAO_CHATBOT, "semente": semente, "por_modelo": por_modelo,
             "cortes": {c: list(v) for c, v in _cortes().items()}, "amostra": amostra}
    (destino / ARQUIVO_CHAVE).write_text(json.dumps(chave, ensure_ascii=False, indent=1), encoding="utf-8")
    (destino / ARQUIVO_CADERNO).write_text(caderno_html(amostra, pasta, semente), encoding="utf-8")
    with open(destino / ARQUIVO_PLANILHA, "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(list(COLUNAS))
        for item in amostra:
            escritor.writerow([item["codigo"], "", "", ""])
    saida(f"Piloto sorteado: {len(amostra)} respostas (" + ", ".join(f"{info_modelo(m)['rotulo']}: {n}"
                                                                     for m, n in sorted(contagem.items())) + ").")
    saida(f"Leia {destino / ARQUIVO_CADERNO} no navegador e preencha {destino / ARQUIVO_PLANILHA}.")
    return destino


# Comparação
def _ler_texto(caminho: Path) -> str:
    """O texto da planilha em qualquer codificação que o Excel grava (UTF-8, ANSI ou "Texto Unicode")."""
    dados = caminho.read_bytes()
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16")
    if b"\x00" in dados[:400]:                     # UTF-16 sem a marca do começo
        return dados.decode("utf-16-le" if dados[1:2] == b"\x00" else "utf-16-be", errors="replace")
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def ler_planilha(caminho: Path) -> tuple[dict[str, dict[str, int]], list[str], set[str], list[str]]:
    """A planilha da pessoa: as notas ({código: {"correcao": nível, "fidelidade": nível}}), os problemas, os
    códigos com observação e os avisos.

    Aceita o que o Excel grava (ponto e vírgula, vírgula ou tabulação, acentos,
    maiúsculas, fim de linha de Windows ou de Mac) e as abreviações de ACEITOS.
    O separador é o do cabeçalho, e não o mais comum no arquivo, porque a
    observação pode ter vírgulas. Célula em branco é nota que falta, não erro.
    Os problemas (nota que não é um dos níveis, linhas repetidas que discordam)
    começam pelo código e impedem a comparação; o aviso de linha repetida que
    concorda, não.
    """
    if not caminho.exists():
        raise ErroPiloto(f"a planilha {caminho} não existe; rode preparar-piloto.bat antes.")
    texto = _ler_texto(caminho)
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    separador = max((";", ",", "\t"), key=primeira.count)
    try:
        linhas = [l for l in csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
                  if any(c.strip() for c in l)]
    except csv.Error as erro:
        raise ErroPiloto(f"a planilha {caminho.name} não pôde ser lida ({erro}); salve de novo pelo Excel, como CSV.")
    cabecalho = [_sem_acento(c) for c in linhas[0]] if linhas else []
    faltam = [c for c in COLUNAS[:3] if c not in cabecalho]
    if faltam:
        raise ErroPiloto(f"a planilha {caminho.name} não tem a coluna {', '.join(faltam)} na primeira linha, que deve "
                         f"ser {';'.join(COLUNAS)}.")
    posicao = {c: cabecalho.index(c) for c in COLUNAS if c in cabecalho}
    notas, problemas, observacoes, repetidos, avisos = {}, [], set(), set(), []
    for linha in linhas[1:]:
        def celula(coluna: str) -> str:
            i = posicao.get(coluna)
            return linha[i] if i is not None and i < len(linha) else ""
        codigo = celula("codigo").strip().upper()
        if not codigo:
            continue
        if codigo in notas and codigo not in repetidos:
            repetidos.add(codigo)
            avisos.append(f"{codigo}: código repetido na planilha (as notas das linhas foram juntadas)")
        atual = notas.setdefault(codigo, {})
        if celula("observacao").strip():
            observacoes.add(codigo)
        for campo in ("correcao", "fidelidade"):
            bruto = celula(campo)
            valor = _sem_acento(bruto)
            if not valor:
                continue
            nivel = next((n for n, aceitos in enumerate(ACEITOS[campo]) if valor in aceitos), None)
            if nivel is None:
                problemas.append(f"{codigo}: {campo} \"{bruto.strip()}\" não é " + ", ".join(NIVEIS[campo][::-1]))
            elif campo in atual and atual[campo] != nivel:
                problemas.append(f"{codigo}: {campo} diferente nas linhas repetidas; deixe uma linha só")
            else:
                atual[campo] = nivel
    return notas, problemas, observacoes, avisos


def nivel_do_juiz(nota: float, cortes: tuple[float, float]) -> int:
    """A nota do juiz (de 0 a 1) nos três níveis: 0 abaixo do primeiro corte, 2 a partir do segundo, 1 entre eles."""
    baixo, alto = cortes
    folga = 1e-9                                   # uma soma como 1/3 + 2/3 não pode cair abaixo do corte por arredondamento
    return 2 if nota >= alto - folga else 1 if nota >= baixo - folga else 0


def notas_dos_juizes(pasta: Path, amostra: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    """{avaliador: {código: {métrica: nota}}}, para cada juiz e para a média dos juízes (quando todos deram nota).

    Primeiro os juízes em inglês; depois, se avaliaram as respostas do
    piloto, os em português (versão 13), com SUFIXO_PORTUGUES na chave. A média
    de cada língua é só a dos juízes daquela língua.
    """
    saida: dict[str, dict[str, dict[str, float]]] = {}
    for lingua, sufixo in (("ingles", ""), ("portugues", SUFIXO_PORTUGUES)):
        juizes = pastas_dos_juizes(pasta, lingua)
        for juiz, caminho in juizes:
            notas: dict[str, dict[str, float]] = {}
            linhas_por_modelo = {}
            for item in amostra:
                if item["modelo"] not in linhas_por_modelo:
                    linhas_por_modelo[item["modelo"]] = ler_notas(arquivo_ragas(caminho, item["modelo"]))[0]
                linha = linhas_por_modelo[item["modelo"]].get(item["id"])
                if not linha:
                    continue
                valores = {m: (linha.get(m) or {}).get("valor") for m in METRICAS}
                notas[item["codigo"]] = {m: v for m, v in valores.items() if v is not None}
            saida[juiz + sufixo] = notas
        if len(juizes) > 1:
            media = {}
            for item in amostra:
                codigo = item["codigo"]
                notas_do_item = [saida[j + sufixo].get(codigo, {}) for j, _ in juizes]
                juntas = {m: round(statistics.mean(n[m] for n in notas_do_item), 4) for m in METRICAS
                          if all(m in n for n in notas_do_item)}
                if juntas:
                    media[codigo] = juntas
            saida[MEDIA + sufixo] = media
    return saida


def _base_e_lingua(avaliador: str) -> tuple[str, str]:
    """("ministral-3:8b|pt") -> ("ministral-3:8b", "portugues")."""
    if avaliador.endswith(SUFIXO_PORTUGUES):
        return avaliador[:-len(SUFIXO_PORTUGUES)], "portugues"
    return avaliador, "ingles"


def _rotulo(avaliador: str, com_lingua: bool = False) -> str:
    """O nome do avaliador para o resultado; com_lingua quando há juízes nas duas línguas."""
    base, lingua = _base_e_lingua(avaliador)
    nome = "média dos juízes" if base == MEDIA else info_modelo(base)["rotulo"]
    return nome + ((", em português" if lingua == "portugues" else ", em inglês") if com_lingua else "")


def _ordem(avaliadores) -> list[str]:
    """Os avaliadores na ordem do resultado: cada juiz e depois a média, com o em português logo após o em inglês."""
    ordem: list[str] = []
    for avaliador in avaliadores:
        base, _ = _base_e_lingua(avaliador)
        for chave in (base, base + SUFIXO_PORTUGUES):
            if chave in avaliadores and chave not in ordem:
                ordem.append(chave)
    return ordem


def _juizes_por_lingua(avaliadores) -> dict[str, list[str]]:
    """Os juízes de cada língua, sem a média: {"ingles": [...], "portugues": [...]}, na ordem do resultado."""
    juizes: dict[str, list[str]] = {"ingles": [], "portugues": []}
    for avaliador in _ordem(avaliadores):
        base, lingua = _base_e_lingua(avaliador)
        if base != MEDIA:
            juizes[lingua].append(base)
    return juizes


def _mesmos_juizes(avaliadores) -> bool:
    """Se os juízes em português são os mesmos que em inglês (só aí as médias das duas línguas se comparam)."""
    juizes = _juizes_por_lingua(avaliadores)
    return set(juizes["ingles"]) == set(juizes["portugues"])


def _principais(avaliadores) -> list[str]:
    """Os avaliadores da tabela por modelo e das matrizes: de cada língua, a média dos juízes ou, com um juiz só,
    ele. Se os juízes das duas línguas não forem os mesmos, os juízes que estão nas duas, cada um em inglês e em
    português, para a comparação entre as línguas ser sempre do mesmo avaliador."""
    juizes = _juizes_por_lingua(avaliadores)
    if juizes["ingles"] and juizes["portugues"] and not _mesmos_juizes(avaliadores):
        comuns = [j for j in juizes["ingles"] if j in juizes["portugues"]]
        if comuns:
            return [chave for j in comuns for chave in (j, j + SUFIXO_PORTUGUES)]
    principais = []
    for sufixo, lingua in (("", "ingles"), (SUFIXO_PORTUGUES, "portugues")):
        principais += [MEDIA + sufixo] if MEDIA + sufixo in avaliadores else [j + sufixo for j in juizes[lingua]]
    return principais


def _aviso_das_linguas(avaliadores) -> str | None:
    """O aviso para quando os juízes em português não são os mesmos que em inglês."""
    juizes = _juizes_por_lingua(avaliadores)
    if not juizes["portugues"] or _mesmos_juizes(avaliadores):
        return None
    nomes = {l: " e ".join(_rotulo(j) for j in juizes[l]) or "nenhum" for l in juizes}
    return (f"Atenção: os juízes não são os mesmos nas duas línguas (em inglês: {nomes['ingles']}; em português: "
            f"{nomes['portugues']}). A comparação entre as línguas vale só para o juiz que está nas duas, e a regra "
            "da língua, que usa a média dos juízes, não pode ser aplicada. Para ela, os dois juízes precisam ter "
            "avaliado nas duas línguas: rode até o fim o avaliar-ragas.bat e o juizes-em-portugues.bat (sem --juiz) e "
            "o avaliar-piloto.bat de novo.")


def _kappa(itens: list[tuple], cortes: tuple[float, float]) -> float | None:
    """Kappa ponderado de itens (nível da pessoa, nota do juiz, ...)."""
    return kappa_ponderado([(h, nivel_do_juiz(j, cortes)) for h, j, *_ in itens], 3) if itens else None


def _spearman(itens: list[tuple]) -> float | None:
    """Spearman entre o nível da pessoa (0, 0,5 ou 1) e a nota do juiz, em itens (nível, nota, ...)."""
    return spearman([(h / 2, j) for h, j, *_ in itens])


def _diferenca_de_kappa(itens: list[tuple], corte: tuple[float, float]):
    """Kappa da primeira nota menos o da segunda, nos mesmos itens (nível da pessoa, nota 1, nota 2)."""
    um = _kappa([(h, a) for h, a, _ in itens], corte)
    dois = _kappa([(h, b) for h, _, b in itens], corte)
    return None if um is None or dois is None else round(um - dois, 3)


def _diferenca_de_spearman(itens: list[tuple]):
    """Spearman da primeira nota menos o da segunda, nos mesmos itens (nível da pessoa, nota 1, nota 2)."""
    um = _spearman([(h, a) for h, a, _ in itens])
    dois = _spearman([(h, b) for h, _, b in itens])
    return None if um is None or dois is None else round(um - dois, 3)


def comparar(pasta: Path) -> dict:
    """A concordância entre a pessoa e cada juiz (e a média dos juízes), por métrica."""
    destino = pasta_do_piloto(pasta)
    caminho_chave = destino / ARQUIVO_CHAVE
    if not caminho_chave.exists():
        raise ErroPiloto(f"não há piloto nesta rodada ({destino}); rode preparar-piloto.bat antes.")
    chave = json.loads(caminho_chave.read_text(encoding="utf-8"))
    amostra = chave["amostra"]
    cortes = _cortes(chave.get("cortes"))
    semente = chave.get("semente", config.PILOTO_SEMENTE)
    reamostras = config.PILOTO_REAMOSTRAS
    juizes = notas_dos_juizes(pasta, amostra)
    if not juizes:
        raise ErroPiloto("nenhum juiz avaliou esta rodada ainda; rode avaliar-ragas.bat antes.")
    humanas, problemas, observacoes, avisos = ler_planilha(destino / ARQUIVO_PLANILHA)
    codigos = [a["codigo"] for a in amostra]
    problemas += [f"{c}: código que não está no sorteio" for c in sorted(set(humanas) - set(codigos))]
    pendentes = [c for c in codigos if c not in observacoes
                 and not all(campo in humanas.get(c, {}) for campo in ("correcao", "fidelidade"))]
    if pendentes or problemas:
        partes = []
        if problemas:
            partes.append("corrija " + "; ".join(problemas))
        if pendentes:
            partes.append("falta nota em " + ", ".join(pendentes) + " (preencha a correção e a fidelidade de cada "
                          "código ou, se não souber decidir, escreva o motivo na coluna observacao)")
        raise ErroPiloto("a planilha ainda não está pronta: " + "; e ".join(partes) + ". O resultado só sai com a "
                         "planilha terminada, para não influenciar as notas que faltam.")
    modelos = sorted({a["modelo"] for a in amostra})
    ordem = _ordem(list(juizes))
    linguas = [l for l in ("ingles", "portugues") if any(_base_e_lingua(a)[1] == l for a in ordem)]
    com_lingua = "portugues" in linguas

    def rotulo(avaliador: str) -> str:
        return _rotulo(avaliador, com_lingua)

    resultados = []
    for humana, metrica in COMPARACOES:             # cada comparação com os avaliadores lado a lado
        for avaliador in ordem:
            notas = juizes[avaliador]
            corte = cortes[humana]
            itens = [(humanas[a["codigo"]][humana], notas[a["codigo"]][metrica], a["modelo"]) for a in amostra
                     if humana in humanas.get(a["codigo"], {}) and metrica in notas.get(a["codigo"], {})]
            niveis = [(h, nivel_do_juiz(j, corte), m) for h, j, m in itens]
            matriz = [[sum(1 for h, j, _ in niveis if h == i and j == k) for k in range(3)] for i in range(3)]
            por_modelo = {}
            for modelo in modelos:
                deste = [(h, j) for h, j, m in niveis if m == modelo]
                if deste:
                    por_modelo[modelo] = {"rotulo": info_modelo(modelo)["rotulo"], "n": len(deste),
                                          "diferenca_media": round(statistics.mean(j - h for h, j in deste), 2),
                                          "concordancia_exata": round(sum(h == j for h, j in deste) / len(deste), 2)}
            resultados.append({
                "avaliador": avaliador, "rotulo": rotulo(avaliador), "lingua": _base_e_lingua(avaliador)[1],
                "humana": humana, "metrica_do_juiz": metrica,
                "n": len(itens), "kappa_ponderado": _kappa(itens, corte),
                "kappa_ic95": intervalo_bootstrap(itens, lambda x, c=corte: _kappa(x, c), reamostras, semente),
                "spearman": _spearman(itens),
                "spearman_ic95": intervalo_bootstrap(itens, _spearman, reamostras, semente),
                "concordancia_exata": round(sum(h == j for h, j, _ in niveis) / len(niveis), 3) if niveis else None,
                "nivel_unico": len(niveis) > 1 and (len({h for h, _, _ in niveis}) == 1 or len({j for _, j, _ in niveis}) == 1),
                "matriz": matriz, "por_modelo": por_modelo})
    diferencas = []

    def diferenca(comparacao: str, avaliador: str, itens: list[tuple], corte: tuple[float, float],
                  com_kappa: bool, nome: str, linguas: list[str]) -> None:
        linha = {"comparacao": comparacao, "avaliador": avaliador, "rotulo": nome, "linguas": linguas, "n": len(itens),
                 "spearman": _diferenca_de_spearman(itens),
                 "spearman_ic95": intervalo_bootstrap(itens, _diferenca_de_spearman, reamostras, semente)}
        if com_kappa:
            linha.update(kappa=_diferenca_de_kappa(itens, corte),
                         kappa_ic95=intervalo_bootstrap(itens, lambda x: _diferenca_de_kappa(x, corte), reamostras,
                                                        semente))
        diferencas.append(linha)

    def pares(humana: str, metrica: str, primeira: dict, segunda: dict) -> list[tuple]:
        """(nível da pessoa, nota 1, nota 2) nas respostas que têm as três."""
        return [(humanas[a["codigo"]][humana], primeira[a["codigo"]][metrica], segunda[a["codigo"]][metrica])
                for a in amostra if humana in humanas.get(a["codigo"], {})
                and metrica in primeira.get(a["codigo"], {}) and metrica in segunda.get(a["codigo"], {})]
    for avaliador in ordem:                          # o juiz em português contra o em inglês (versão 13)
        base, lingua = _base_e_lingua(avaliador)
        if lingua != "portugues" or base not in juizes or (base == MEDIA and not _mesmos_juizes(ordem)):
            continue                                 # a média só se os juízes forem os mesmos nas duas línguas
        for humana, metrica in COMPARACOES:
            diferenca(f"português menos inglês: {NOMES_METRICAS[metrica]}", base,
                      pares(humana, metrica, juizes[avaliador], juizes[base]), cortes[humana], com_kappa=True,
                      nome=_rotulo(base), linguas=["portugues", "ingles"])
    for avaliador in ordem:                          # o F1 contra a completude, nas mesmas respostas
        notas = juizes[avaliador]
        itens = [(humanas[a["codigo"]]["correcao"], notas[a["codigo"]]["correcao"], notas[a["codigo"]]["completude"])
                 for a in amostra if "correcao" in humanas.get(a["codigo"], {})
                 and {"correcao", "completude"} <= set(notas.get(a["codigo"], {}))]
        diferenca("F1 menos completude", avaliador, itens, cortes["correcao"], com_kappa=True, nome=rotulo(avaliador),
                  linguas=[_base_e_lingua(avaliador)[1]])
    for avaliador in ordem:                          # cada juiz contra a média da língua dele, nas mesmas respostas
        base, lingua = _base_e_lingua(avaliador)
        media = MEDIA + (SUFIXO_PORTUGUES if lingua == "portugues" else "")
        if base == MEDIA or media not in juizes:
            continue
        for humana, metrica in COMPARACOES:
            diferenca(f"juiz menos a média: {NOMES_METRICAS[metrica]}", avaliador,
                      pares(humana, metrica, juizes[avaliador], juizes[media]), cortes[humana], com_kappa=False,
                      nome=rotulo(avaliador), linguas=[lingua])
    faltando = {campo: sorted(c for c in codigos if campo not in humanas.get(c, {}))
                for campo in ("correcao", "fidelidade")}
    sem_juiz = {j: {m: sorted(c for c in codigos if m not in n.get(c, {})) for m in METRICAS} for j, n in juizes.items()}
    itens_gravados = [{"codigo": a["codigo"], "modelo": a["modelo"], "id": a["id"],
                       "humana": humanas.get(a["codigo"], {}), "com_observacao": a["codigo"] in observacoes,
                       "juizes": {j: n.get(a["codigo"], {}) for j, n in juizes.items()}} for a in amostra]
    resultado = {"rodada": pasta.name, "calculado_em": datetime.now().isoformat(timespec="seconds"),
                 "versao_chatbot": config.VERSAO_CHATBOT, "semente": semente, "linguas": linguas,
                 "juizes_por_lingua": _juizes_por_lingua(ordem), "aviso_das_linguas": _aviso_das_linguas(ordem),
                 "cortes": {c: list(v) for c, v in cortes.items()}, "reamostras": reamostras,
                 "respostas": len(amostra), "notas_que_faltam": faltando, "sem_nota_do_juiz": sem_juiz,
                 "avisos_da_planilha": avisos, "resultados": resultados, "diferencas": diferencas,
                 "itens": itens_gravados}
    (destino / f"{RESULTADO}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    (destino / f"{RESULTADO}.md").write_text(texto_markdown(resultado), encoding="utf-8")
    return resultado


def _num(v, casas: int = 2) -> str:
    if v is None:
        return "-"
    texto = f"{v:.{casas}f}".replace(".", ",")
    return texto[1:] if texto.startswith("-") and not texto.strip("-0,") else texto      # -0,00 vira 0,00


def _com_sinal(v, casas: int = 2) -> str:
    return "-" if v is None else ("+" if v > 0 else "") + _num(v, casas)


def _ic(ic) -> str:
    return "" if not ic else f" ({_num(ic[0])} a {_num(ic[1])})"


def _limite(v: float) -> str:
    """Um limite de intervalo de uma diferença, com casas a mais quando duas casas o arredondariam para zero."""
    casas = 2
    while v != 0 and round(v, casas) == 0 and casas < 4:
        casas += 1
    return _num(v, casas)


def lado_do_zero(ic) -> str | None:
    """Onde o intervalo de uma diferença fica em relação ao zero, pelos valores sem arredondar."""
    if not ic:
        return None
    return "acima" if ic[0] > 0 else "abaixo" if ic[1] < 0 else "passa"


def _ic_da_diferenca(ic) -> str:
    """O intervalo de uma diferença e o lado do zero em que ele fica, que é o que as regras do piloto olham."""
    if not ic:
        return ""
    lado = {"acima": "; todo acima de zero", "abaixo": "; todo abaixo de zero", "passa": ""}[lado_do_zero(ic)]
    return f" ({_limite(ic[0])} a {_limite(ic[1])}{lado})"


def texto_markdown(resultado: dict) -> str:
    cortes = _cortes(resultado["cortes"])
    c_baixo, c_alto = cortes["correcao"]
    f_baixo, f_alto = cortes["fidelidade"]
    com_lingua = "portugues" in resultado.get("linguas", [])
    linhas = [f"# Piloto dos juízes da rodada {resultado['rodada']}", "",
              f"{resultado['respostas']} respostas sorteadas (semente {resultado['semente']}). As notas dos juízes "
              f"viram níveis pelos cortes fixados antes do piloto. Correção (F1 e completude): abaixo de "
              f"{_num(c_baixo)}, incorreta; a partir de {_num(c_alto)}, correta; entre os dois, parcial. Fidelidade: "
              f"abaixo de {_num(f_baixo)}, infiel; "
              + ("só 1,00 (todas as afirmações nos trechos), fiel" if f_alto >= 1 else f"a partir de {_num(f_alto)}, fiel")
              + f"; entre os dois, parcial. Calculado em {resultado['calculado_em']}.", ""]
    avaliadores = list(dict.fromkeys(r["avaliador"] for r in resultado["resultados"]))
    if com_lingua:
        if _mesmos_juizes(avaliadores):
            linhas += ["Cada juiz aparece duas vezes: em inglês, com os prompts do RAGAS como vêm, e em português "
                       "(versão 13), com os exemplos dos prompts em português e a instrução de escrever a saída em "
                       "português. A média de cada língua é a dos juízes daquela língua.", ""]
        else:
            juizes = _juizes_por_lingua(avaliadores)
            linhas += ["Juízes em inglês, com os prompts do RAGAS como vêm: "
                       + (" e ".join(_rotulo(j) for j in juizes["ingles"]) or "nenhum") + ". Em português (versão 13), "
                       "com os exemplos dos prompts em português e a instrução de escrever a saída em português: "
                       + (" e ".join(_rotulo(j) for j in juizes["portugues"]) or "nenhum") + ".", ""]
            linhas += [_aviso_das_linguas(avaliadores), ""]
    linhas += ["| Avaliação humana | Nota do juiz | Avaliador | Respostas | Kappa ponderado (IC 95%) | Spearman (IC 95%) | "
               "Concordância exata |", "|-|-|-|-|-|-|-|"]
    for r in resultado["resultados"]:
        unico = " (um nível só de um lado)" if r.get("nivel_unico") else ""
        linhas.append(f"| {r['humana'].replace('correcao', 'correção')} | {NOMES_METRICAS[r['metrica_do_juiz']]} | "
                      f"{r['rotulo']} | {r['n']} | {_num(r['kappa_ponderado'])}{_ic(r.get('kappa_ic95'))}{unico} | "
                      f"{_num(r['spearman'])}{_ic(r.get('spearman_ic95'))} | {_num(r['concordancia_exata'])} |")
    linhas += ["", "Kappa ponderado (linear): 1 é concordância total e 0 é o que o acaso daria; discordar por um "
               "nível conta metade. Referência usual (Landis e Koch, 1977): de 0,41 a 0,60, moderada; de 0,61 a 0,80, "
               "substancial; acima de 0,80, quase perfeita. Spearman: se as notas sobem e descem juntas, sem depender "
               "dos cortes; com três níveis do lado da pessoa, ele não chega a 1 nem com a ordem toda certa (no máximo "
               "cerca de 0,94 com os níveis divididos por igual). IC 95%: intervalo de confiança de 95% por bootstrap "
               f"({resultado.get('reamostras', 0)} reamostras das respostas, com a semente do sorteio). Com cerca de 30 "
               "respostas, o intervalo do kappa costuma ter perto de 0,5 de largura: diferenças menores que isso podem "
               "ser só acaso. Sem intervalo: poucas respostas, ou reamostras demais em que a medida não sai. \"Um nível "
               "só de um lado\": a pessoa ou o juiz deu o mesmo nível a todas as respostas, e aí o kappa não mede "
               "concordância (dá 0 ou não sai)."]
    if any(0 < r["n"] < 20 for r in resultado["resultados"]):
        linhas += ["", "Atenção: há linhas com menos de 20 respostas; nelas, os números são só uma pista."]
    if resultado.get("diferencas"):
        linhas += ["", "## Diferenças, nas mesmas respostas", "",
                   "| Comparação | Avaliador | Respostas | No kappa (IC 95%) | No Spearman (IC 95%) |", "|-|-|-|-|-|"]
        for d in resultado["diferencas"]:
            kappa = (f"{_com_sinal(d['kappa'])}{_ic_da_diferenca(d.get('kappa_ic95'))}" if "kappa" in d
                     else "não se aplica")
            linhas.append(f"| {d['comparacao']} | {d['rotulo']} | {d['n']} | {kappa} | "
                          f"{_com_sinal(d['spearman'])}{_ic_da_diferenca(d.get('spearman_ic95'))} |")
        linhas += ["", "Positivo: a primeira nota concorda mais com a pessoa. Se o intervalo passa pelo zero, estas "
                   "respostas não bastam para dizer qual das duas concorda mais; quando ele não passa, a tabela diz "
                   "\"todo acima de zero\" ou \"todo abaixo de zero\", conferido nos valores sem arredondar (um "
                   "limite muito perto de zero aparece com mais casas). Na comparação de cada juiz com a "
                   "média, só o Spearman, que não depende dos cortes: com o corte de fiel em 1, a média só é fiel "
                   "quando os dois juízes dão 1, o que puxaria o kappa da média para baixo. São várias comparações ao "
                   "mesmo tempo, então um intervalo que não passa pelo zero ainda pode ser acaso; valem as que as "
                   "regras combinadas antes do piloto mandam olhar."]
        if any(d["comparacao"].startswith("português menos inglês") for d in resultado["diferencas"]):
            linhas += ["", "Português menos inglês: o mesmo juiz (ou a média) com os prompts em português e em inglês, "
                       "nas respostas que as duas versões avaliaram; positivo quando a versão em português concorda "
                       "mais com a pessoa. Aqui o kappa também vale, porque as duas notas passam pelos mesmos cortes. "
                       "O F1 contra a completude e cada juiz contra a média são comparados dentro de cada língua."]
    principais = _principais(avaliadores)
    medias = [a for a in principais if _base_e_lingua(a)[0] == MEDIA]
    colunas = ("a média dos juízes" if len(medias) == len(principais) else "o juiz" if not medias
               else "o avaliador indicado em cada tabela")
    posicao = {a: i for i, a in enumerate(principais)}
    comparacoes = {c: i for i, c in enumerate(COMPARACOES)}
    escolhidos = sorted((r for r in resultado["resultados"] if r["avaliador"] in posicao),
                        key=lambda r: (comparacoes[(r["humana"], r["metrica_do_juiz"])], posicao[r["avaliador"]]))
    nomes_modelos = []
    for r in escolhidos:
        for modelo, info in r["por_modelo"].items():
            if (modelo, info["rotulo"]) not in nomes_modelos:
                nomes_modelos.append((modelo, info["rotulo"]))
    if nomes_modelos:
        linhas += ["", "## Por modelo: nível do juiz menos o da pessoa, em média ("
                   + "; ".join(_rotulo(a, com_lingua) for a in principais) + ")", "",
                   "| Comparação | " + " | ".join(r for _, r in nomes_modelos) + " |",
                   "|-|" + "-|" * len(nomes_modelos)]
        for r in escolhidos:
            celulas = [(f"{_com_sinal(r['por_modelo'][m]['diferenca_media'])} ({r['por_modelo'][m]['n']})"
                        if m in r["por_modelo"] else "-") for m, _ in nomes_modelos]
            qual = f" ({r['rotulo']})" if len(principais) > 1 else ""
            linhas.append(f"| {r['humana'].replace('correcao', 'correção')} x {NOMES_METRICAS[r['metrica_do_juiz']]}"
                          f"{qual} | " + " | ".join(celulas) + " |")
        linhas += ["", "Positivo: o juiz deu níveis mais altos que a pessoa nas respostas daquele modelo (entre "
                   "parênteses, quantas respostas). Com cerca de 10 respostas por modelo, só diferenças grandes dizem "
                   "alguma coisa."]
    faltando = {c: v for c, v in resultado["notas_que_faltam"].items() if v}
    if faltando:
        linhas += ["", "Notas em branco na planilha (com o motivo na observação): " + "; ".join(
            f"{c.replace('correcao', 'correção')}: {', '.join(v)}" for c, v in faltando.items())]
    sem_juiz = []
    for j, metricas in resultado["sem_nota_do_juiz"].items():
        listas = [v for v in metricas.values()]
        if listas and all(v == listas[0] for v in listas):           # as mesmas respostas em todas as notas
            sem_juiz += [f"{_rotulo(j, com_lingua)}: {', '.join(listas[0])}"] if listas[0] else []
        else:
            sem_juiz += [f"{_rotulo(j, com_lingua)}, {NOMES_METRICAS[m]}: {', '.join(v)}"
                         for m, v in metricas.items() if v]
    if sem_juiz:
        linhas += ["", "Respostas sem nota de um juiz (ficam fora da comparação com ele): " + "; ".join(sem_juiz)]
    if resultado.get("avisos_da_planilha"):
        linhas += ["", "Avisos da planilha: " + "; ".join(resultado["avisos_da_planilha"])]
    linhas += ["", f"## Quantas vezes cada nível coincidiu (linhas: a pessoa; colunas: {colunas})", ""]
    for r in escolhidos:
        nomes = NIVEIS[r["humana"]]
        linhas += [f"**{r['humana'].replace('correcao', 'correção')} x {NOMES_METRICAS[r['metrica_do_juiz']]} "
                   f"({r['rotulo']})**", "", "| | " + " | ".join(nomes) + " |", "|-|-|-|-|"]
        for i, nome in enumerate(nomes):
            linhas.append(f"| {nome} | " + " | ".join(str(x) for x in r["matriz"][i]) + " |")
        linhas.append("")
    return "\n".join(linhas) + "\n"


def _pasta(argumento: Path | None) -> Path:
    pasta = argumento or rodada_mais_recente()
    if pasta is None:
        raise ErroRodada(f"nenhuma rodada em {pasta_das_rodadas()}; rode gerar-respostas.bat antes.")
    pasta = Path(pasta)
    if not pasta.is_absolute() and not pasta.exists():
        pasta = config.BASE_DIR / pasta
    return pasta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Piloto dos juízes contra a avaliação humana.")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_preparar = sub.add_parser("preparar", help="sorteia as respostas e grava o caderno e a planilha")
    p_preparar.add_argument("--rodada", type=Path, default=None)
    p_preparar.add_argument("--por-modelo", type=int, default=None)
    p_preparar.add_argument("--semente", type=int, default=None)
    p_preparar.add_argument("--refazer", action="store_true", help="guarda o piloto atual e sorteia de novo")
    p_comparar = sub.add_parser("comparar", help="compara a planilha preenchida com as notas dos juízes")
    p_comparar.add_argument("--rodada", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        pasta = _pasta(args.rodada)
        if args.comando == "preparar":
            preparar(pasta, args.por_modelo, args.semente, args.refazer)
            return 0
        resultado = comparar(pasta)
    except (ErroRodada, ErroPiloto) as erro:
        print(f"ERRO: {erro}")
        return 1
    print(texto_markdown(resultado))
    print(f"Resultado gravado em {pasta_do_piloto(pasta) / (RESULTADO + '.md')} (e .json).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
