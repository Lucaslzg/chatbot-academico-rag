"""Avaliação das respostas com o RAGAS: os juízes comparam cada resposta com a resposta correta e com os trechos.

    python avaliar_ragas.py                      # a rodada mais recente, todos os modelos dela, todos os juízes
    python avaliar_ragas.py --rodada avaliacao/rodadas/2026-11-20_0900_perguntas_reais
    python avaliar_ragas.py --limite 3           # só as 3 primeiras perguntas (para medir o tempo dos juízes)
    python avaliar_ragas.py --modelos phi4-mini
    python avaliar_ragas.py --juiz ministral-3:8b
    python avaliar_ragas.py --portugues --so-piloto   # os juízes em português, só nas respostas do piloto (versão 13)
    python avaliar_ragas.py --ingles                  # os juízes com os prompts do RAGAS como vêm, em inglês

Precisa do RAGAS (instalar-avaliacao.bat, uma vez) e dos juízes instalados no
Ollama (config.JUIZES; o verificar-modelos.bat confere).

Métricas (Seção 2.2.2 da monografia; Es et al., 2024):

* correção (Factual Correctness, modo F1): o juiz divide a resposta do modelo
  e a resposta correta em afirmações e confere quantas de cada lado a outra
  sustenta;
* completude (versão 10): só o segundo lado dessa mesma conta, a parte das
  afirmações da resposta correta que a resposta traz. Sai dos veredictos que
  o juiz já deu na correção, sem pedir nada a mais a ele. É a "claim recall"
  do ALCE (Gao et al., 2023). Diferente do F1, ela não tira ponto da resposta
  que diz de onde veio a informação ("de acordo com o Art. 37 da Resolução
  nº 480"), que o gabarito não menciona: no teste de 03/11/2026, isso zerou
  o F1 de uma resposta com os fatos certos. Qual das duas vira a nota
  principal fica para o piloto com a avaliação humana;
* fidelidade (Faithfulness): parte das afirmações da resposta que os trechos
  entregues ao modelo sustentam. Mede se o modelo inventou;
* cobertura dos trechos (Context Recall): parte das afirmações da resposta
  correta que os trechos contêm. Os trechos são os mesmos para todos os
  modelos, então ela é calculada uma vez por pergunta e mede a busca,
  inclusive nas perguntas reais, que não dizem onde está a resposta.

O juiz recebe a resposta sem as marcas de citação ([1], [2][3]...), desde a
versão 10: os trechos chegam a ele sem número, então ele não tem como conferir
uma marca, e ela virava uma afirmação julgada falsa ("a resposta cita os
documentos [2] e [3]"). A resposta gravada não muda; a presença de citação é
contada à parte, na tabela de confiabilidade.

Quais respostas entram (decisão D4: abstenção não vira nota zero):

* correção e completude: perguntas que os documentos respondem, com
  resposta correta, e que o modelo respondeu. As abstenções ficam fora da
  nota e aparecem na tabela de confiabilidade (avaliar-respostas.bat);
* fidelidade: toda resposta dada (não abstenção) que teve trechos, inclusive
  as dadas a perguntas que os documentos não respondem;
* cobertura: perguntas com resposta correta e com trechos.

O que é abstenção sai da classificação desta versão, refeita sobre o texto
gravado (avaliar_respostas.categoria), e não da gravada na geração: a regra
corrigida na versão 10 (a recusa com uma citação solta é abstenção) vale
também para as rodadas já geradas. Desde a versão 14, vale antes a decisão
escrita à mão na coluna "sua conferência" do revisar.csv
(avaliar_respostas.aplicar_conferencia), se o texto da resposta for o mesmo
que estava lá: a nota dada numa categoria que o juiz trata de outro jeito é
refeita (uma resposta que virou abstenção perde a nota; uma abstenção que
virou resposta passa a ter nota). A troca entre duas categorias julgadas do
mesmo jeito (resposta, mista, abstenção com acréscimo) não refaz a nota.

Dois juízes (versão 09), de famílias diferentes entre si e dos modelos
comparados: cada um avalia a rodada inteira, um depois do outro, e a nota de
cada resposta é a média dos dois (só entram as respostas que todos os juízes
avaliaram). A concordância entre eles (correlação de Pearson e diferença
média) também é relatada. Um juiz da mesma família de um modelo avaliado é
avisado: ele tenderia a favorecer as respostas desse modelo.

Cada juiz roda pela interface nativa do Ollama (não pela compatível com a
OpenAI): assim a janela de contexto (OLLAMA_NUM_CTX) e a placa de vídeo ficam
sob controle, e a saída é forçada ao formato JSON que o RAGAS espera
(structured outputs), o que evita respostas que não podem ser lidas. O juiz
que raciocina (o Gemma 4) recebe think=False. Temperatura 0 e semente fixa: a
mesma resposta recebe a mesma nota. As instruções do RAGAS ficam como vêm
dele, em inglês.

O juiz em português (versão 13, --portugues): os mesmos juízes e as mesmas
métricas, com os exemplos dos prompts do RAGAS em português e uma frase na
instrução pedindo a saída em português (prompts_em_portugues.py). Os juízes
em inglês escrevem cerca de metade das afirmações em inglês e às vezes
traduzem errado, o que derruba a nota de respostas certas. Na versão 13, ele
só avaliava as respostas sorteadas para o piloto (--so-piloto); o piloto de
14/11/2026 o escolheu, e desde a versão 15 ele é o padrão da rodada inteira
(config.JUIZES_LINGUA), com a cobertura dos trechos também em português. Com
--ingles, os juízes usam os prompts do RAGAS como vêm.

Onde as notas ficam, na pasta da rodada:

* juiz_<juiz>/: as notas de cada juiz, pergunta a pergunta, com o que ele
  devolveu em cada etapa (as afirmações e os veredictos, para conferir as
  notas zero e para o piloto com avaliação humana): ragas_<modelo>.jsonl,
  ragas_cobertura.jsonl, ragas_configuracao.json e o resumo dele
  (ragas_resumo.md, .csv e .json);
* ragas_juizes.md, .csv e .json: a média dos juízes, a concordância entre
  eles e a comparação dos modelos pelo teste de Wilcoxon pareado;
* juizes_em_portugues/juiz_<juiz>/: as notas do juiz em português (versão
  13), no mesmo formato, com "lingua": "portugues" em cada nota e no registro
  do juiz, e juizes_em_portugues/ragas_juizes.*: o resumo dos juízes em
  português (versão 15), quando eles avaliam a rodada inteira. Ficam numa
  subpasta, e não ao lado das outras, porque as versões até a 12 leem toda
  pasta juiz_* da rodada como um juiz em inglês. A tabela de confiabilidade
  usa os juízes da língua de config.JUIZES_LINGUA quando eles avaliaram a
  rodada inteira, e os em inglês quando não.

Se parar, rodar de novo continua de onde parou (as perguntas com erro do juiz
são tentadas de novo). Cada nota guarda a versão do método que a produziu
(campo "metodo"); as de outro método ficam no arquivo, são refeitas e não
entram nas médias. Desde a versão 11, o juiz recebe os trechos como o modelo
os recebeu, com o cabeçalho de cada um (o título do documento, as páginas, o
local e os artigos); nas notas da versão 10, a correção e a completude, que
não usam os trechos, são aproveitadas, e só a fidelidade é refeita. As rodadas avaliadas pelas versões 06 a 08, com um
juiz só, têm as notas soltas na pasta da rodada; elas continuam lá e a tabela
de confiabilidade ainda as lê quando não há a pasta de nenhum juiz.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path

import config
from avaliar_respostas import aplicar_conferencia, categoria, tratamento_do_juiz
from estatistica import concordancia_de_notas, wilcoxon_pareado
from gerar_respostas import (ARQUIVO_CONTEXTOS, ErroRodada, Trava, abrir_rodada, arquivo_respostas, ler_contextos,
                             ler_respostas, nome_arquivo_modelo, pasta_das_rodadas, rodada_mais_recente,
                             reparar_respostas)
from modelos import argumentos_chat, familia, info_modelo, juiz as opcoes_do_juiz, juizes, problemas_de_familia

ARQUIVO_COBERTURA = "ragas_cobertura.jsonl"
ARQUIVO_CONFIGURACAO_JUIZ = "ragas_configuracao.json"
PREFIXO_PASTA_JUIZ = "juiz_"
# As pastas dos juízes em português (versão 13) ficam numa subpasta da rodada, juizes_em_portugues/juiz_<juiz>/, e
# não ao lado das outras: as versões até a 12 leem toda pasta juiz_* da rodada como um juiz em inglês, e uma pasta
# em português ali misturaria as notas das duas línguas sem aviso, se uma versão antiga fosse usada de novo.
PASTA_JUIZES_EM_PORTUGUES = "juizes_em_portugues"
LINGUAS = ("ingles", "portugues")       # a língua dos prompts do juiz; "ingles" é o RAGAS como vem
RESUMO_JUIZES = "ragas_juizes"          # .md, .csv e .json na pasta da rodada
# A chave do piloto (piloto.py, que importa este módulo): de onde --so-piloto tira as respostas sorteadas.
PASTA_PILOTO = "piloto"
ARQUIVO_CHAVE_PILOTO = "piloto_chave.json"
METRICAS = ("correcao", "completude", "fidelidade")
# A versão em que passou a valer o jeito atual de preparar o que vai para os juízes: a resposta sem as marcas de
# citação e a recusa com citação solta como abstenção (versão 10); os trechos com o cabeçalho que o modelo leu
# (versão 11). As notas de outro método são refeitas.
VERSAO_DO_METODO = "11"
# Métodos anteriores cuja correção e completude continuam valendo: da 10 para a 11 só mudou o que o juiz recebe dos
# trechos, e a correção compara a resposta com a resposta correta, sem os trechos.
CORRECAO_VALE_DESDE = ("10",)


# O Ollama corta sem avisar o prompt que não cabe na janela (OLLAMA_NUM_CTX), e a saída do juiz precisa de
# num_predict tokens dela: quando o prompt mais a saída chegam ao tamanho da janela, a nota fica marcada.
PROMPT_NO_LIMITE = "o prompt do juiz chegou perto do limite da janela de contexto e pode ter sido cortado"


class ErroJuiz(Exception):
    """O juiz não pode ser usado (RAGAS não instalado, Ollama fechado, modelo ausente...)."""


def opcoes_juiz(modelo: str | None = None) -> dict:
    """Opções de um juiz no Ollama (o primeiro de config.JUIZES, sem nome): determinístico, com a janela do projeto."""
    if modelo:
        conf = opcoes_do_juiz(modelo)
    else:
        lista = juizes()
        conf = lista[0] if lista else {"placa_de_video": True}
    opcoes = {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX,
              "num_predict": int(conf.get("max_tokens", 2048))}
    if config.OLLAMA_SEED is not None:
        opcoes["seed"] = config.OLLAMA_SEED
    if not conf.get("placa_de_video"):
        opcoes["num_gpu"] = 0
    return opcoes


def arquivo_ragas(pasta: Path, modelo: str) -> Path:
    return pasta / f"ragas_{nome_arquivo_modelo(modelo)}.jsonl"


def _pasta_da_lingua(pasta: Path, lingua: str) -> Path:
    """Onde ficam as pastas dos juízes de uma língua: a da rodada (inglês) ou juizes_em_portugues/ dentro dela."""
    return pasta / PASTA_JUIZES_EM_PORTUGUES if lingua == "portugues" else pasta


def pasta_do_juiz(pasta: Path, juiz: str, lingua: str = "ingles") -> Path:
    """Onde ficam as notas de um juiz, dentro da pasta da rodada (as do juiz em português, em juizes_em_portugues/)."""
    return _pasta_da_lingua(pasta, lingua) / f"{PREFIXO_PASTA_JUIZ}{nome_arquivo_modelo(juiz)}"


def lingua_de(item) -> str:
    """A língua dos prompts de um avaliador, de uma nota ou de um registro do juiz; sem ela, inglês (até a 12)."""
    valor = item.get("lingua") if isinstance(item, dict) else getattr(item, "lingua", None)
    return valor or "ingles"


def ultimas_por_id(linhas: list[dict]) -> dict[str, dict]:
    """A última linha de cada pergunta (uma tentativa nova substitui a que deu erro)."""
    saida: dict[str, dict] = {}
    for linha in linhas:
        saida[linha["id"]] = linha
    return saida


def do_metodo_atual(linha: dict) -> bool:
    return linha.get("metodo") == VERSAO_DO_METODO


def ler_cobertura(caminho: Path, so_metodo_atual: bool = True) -> dict[str, dict]:
    """As notas de cobertura de um ragas_cobertura.jsonl (a última de cada pergunta), só as do método atual.

    As rodadas das versões 06 a 08, com as notas soltas na pasta da rodada, são lidas com so_metodo_atual=False.
    """
    linhas = ultimas_por_id(ler_respostas(caminho))
    return {i: l for i, l in linhas.items() if not so_metodo_atual or do_metodo_atual(l)}


def ler_notas(caminho: Path, so_metodo_atual: bool = True) -> tuple[dict[str, dict], int]:
    """As notas de um ragas_<modelo>.jsonl (a última de cada pergunta) e quantas são de um método anterior.

    As de método anterior ficam no arquivo, mas não entram nas médias. As
    rodadas das versões 06 a 08 (um juiz só, notas soltas na pasta da rodada)
    são lidas com so_metodo_atual=False.
    """
    linhas = ultimas_por_id(ler_respostas(caminho))
    if not so_metodo_atual:
        return linhas, 0
    atuais = {i: l for i, l in linhas.items() if do_metodo_atual(l)}
    return atuais, len(linhas) - len(atuais)


# O juiz
class JuizOllama:
    """Adaptador do RAGAS para o Ollama nativo, com saída forçada ao esquema JSON pedido.

    É criado por criar_juiz(), que o torna subclasse da classe-base do RAGAS
    (InstructorBaseRagasLLM); assim este módulo pode ser importado sem o RAGAS
    instalado (os testes da lógica não precisam dele).
    """

    def __init__(self, modelo: str, cliente=None, opcoes: dict | None = None):
        self.modelo = modelo
        self.opcoes = dict(opcoes or opcoes_juiz(modelo))
        self._cliente = cliente
        self.registro: list[dict] = []            # o que o juiz devolveu desde a última limpeza

    @property
    def cliente(self):
        if self._cliente is None:
            import ollama
            self._cliente = ollama.Client(host=config.OLLAMA_HOST,
                                          timeout=opcoes_do_juiz(self.modelo).get("tempo_limite",
                                                                                  config.OLLAMA_TIMEOUT))
        return self._cliente

    def generate(self, prompt: str, response_model):
        from pydantic import ValidationError
        opcoes = dict(self.opcoes)
        for tentativa in (1, 2):
            resposta = self.cliente.chat(model=self.modelo, messages=[{"role": "user", "content": prompt}],
                                         format=response_model.model_json_schema(), options=dict(opcoes),
                                         stream=False, keep_alive="30m", **argumentos_chat(self.modelo))
            mensagem = resposta["message"] if isinstance(resposta, dict) else resposta.message
            texto = (mensagem["content"] if isinstance(mensagem, dict) else mensagem.content) or ""
            try:
                objeto = response_model.model_validate_json(texto)
            except ValidationError:
                if tentativa == 2:
                    raise
                opcoes["num_predict"] = 2 * opcoes.get("num_predict", 2048)   # a saída pode ter sido cortada
                continue
            etapa = {"etapa": response_model.__name__, "saida": objeto.model_dump()}
            tokens = resposta.get("prompt_eval_count") if isinstance(resposta, dict) else getattr(
                resposta, "prompt_eval_count", None)
            if tokens:
                etapa["tokens_do_prompt"] = tokens
                if tokens + opcoes.get("num_predict", 0) >= opcoes.get("num_ctx", config.OLLAMA_NUM_CTX):
                    etapa["aviso"] = PROMPT_NO_LIMITE
            self.registro.append(etapa)
            return objeto

    async def agenerate(self, prompt: str, response_model):
        return await asyncio.to_thread(self.generate, prompt, response_model)

    def descarregar(self) -> None:
        try:
            self.cliente.chat(model=self.modelo, messages=[], keep_alive=0)
        except Exception:
            pass


def _importar_ragas():
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")     # o RAGAS não manda dados de uso para fora
    try:
        from ragas.llms.base import InstructorBaseRagasLLM
        from ragas.metrics.collections import ContextRecall, FactualCorrectness, Faithfulness
    except ImportError as erro:
        raise ErroJuiz("o RAGAS não está instalado neste ambiente. Rode instalar-avaliacao.bat (uma vez) e depois, de "
                       "novo, o arquivo que você rodou (avaliar-ragas.bat ou juizes-em-portugues.bat). "
                       f"Detalhe: {erro}") from erro
    return InstructorBaseRagasLLM, FactualCorrectness, Faithfulness, ContextRecall


def criar_juiz(modelo: str | None = None, cliente=None) -> JuizOllama:
    """Um juiz pronto para o RAGAS; sem nome, o primeiro de config.JUIZES."""
    base = _importar_ragas()[0]
    if modelo is None:
        lista = juizes()
        if not lista:
            raise ErroJuiz("nenhum juiz em config.JUIZES")
        modelo = lista[0]["modelo"]
    classe = type("JuizOllamaRagas", (JuizOllama, base), {})
    return classe(modelo, cliente)


class AvaliadorRagas:
    """As três métricas do RAGAS com o mesmo juiz. Cada método devolve (nota, o que o juiz devolveu).

    Com lingua="portugues" (versão 13), os prompts vão com os exemplos em
    português e a frase que pede a saída em português (prompts_em_portugues.py):
    os da correção e da fidelidade desde a versão 13, e o da cobertura dos
    trechos desde a 15.
    """

    def __init__(self, juiz: JuizOllama, lingua: str = "ingles"):
        if lingua not in LINGUAS:
            raise ValueError(f"língua {lingua!r}; as possíveis são {', '.join(LINGUAS)}")
        _, FactualCorrectness, Faithfulness, ContextRecall = _importar_ragas()
        self.juiz = juiz
        self.lingua = lingua
        self._correcao = FactualCorrectness(llm=juiz, mode="f1")
        self._fidelidade = Faithfulness(llm=juiz)
        self._cobertura = ContextRecall(llm=juiz)
        if lingua == "portugues":
            from prompts_em_portugues import TraducaoIncompleta, em_portugues
            try:
                self._correcao.prompt = em_portugues(self._correcao.prompt)
                self._correcao.nli_prompt = em_portugues(self._correcao.nli_prompt)
                self._fidelidade.statement_generator_prompt = em_portugues(self._fidelidade.statement_generator_prompt)
                self._fidelidade.nli_statement_prompt = em_portugues(self._fidelidade.nli_statement_prompt)
                self._cobertura.prompt = em_portugues(self._cobertura.prompt)
            except TraducaoIncompleta as erro:
                raise ErroJuiz(f"{erro}. O juiz em português foi preparado para o RAGAS de "
                               "requirements-avaliacao.txt.") from erro

    def _medir(self, corrotina) -> tuple[float, list[dict]]:
        self.juiz.registro = []
        resultado = asyncio.run(corrotina)
        return float(resultado.value), self.juiz.registro

    def correcao(self, pergunta: str, resposta: str, referencia: str):
        return self._medir(self._correcao.ascore(response=resposta, reference=referencia))

    def fidelidade(self, pergunta: str, resposta: str, trechos: list[str]):
        return self._medir(self._fidelidade.ascore(user_input=pergunta, response=resposta,
                                                   retrieved_contexts=trechos))

    def cobertura(self, pergunta: str, trechos: list[str], referencia: str):
        return self._medir(self._cobertura.ascore(user_input=pergunta, retrieved_contexts=trechos,
                                                  reference=referencia))


def _erro_de_conexao(erro: Exception) -> bool:
    import httpx
    return isinstance(erro, (ConnectionError, httpx.TransportError))


def _medir(funcao, *args) -> dict:
    inicio = time.perf_counter()
    try:
        valor, detalhes = funcao(*args)
        medida = {"valor": round(valor, 4), "detalhes": detalhes, "segundos": round(time.perf_counter() - inicio, 1)}
        if any(isinstance(d, dict) and d.get("aviso") for d in detalhes or []):
            medida["aviso"] = PROMPT_NO_LIMITE
        return medida
    except Exception as erro:          # o juiz falhou nesta pergunta: fica registrado e é tentado de novo depois
        if _erro_de_conexao(erro):
            raise
        return {"valor": None, "erro": f"{type(erro).__name__}: {erro}"[:500],
                "segundos": round(time.perf_counter() - inicio, 1)}


# A avaliação
def cabecalho_do_trecho(p: dict) -> str:
    """O cabeçalho de um trecho, igual ao que o modelo lê no prompt (consulta.mensagem_usuario), sem o número."""
    paginas = (f"p. {p.get('pagina_inicio')}" if p.get("pagina_inicio") == p.get("pagina_fim")
               else f"p. {p.get('pagina_inicio')}-{p.get('pagina_fim')}")
    partes = [f"Documento: {p.get('documento', '')}", paginas]
    local = (p.get("localizacao") or "") + (f" ({p['secao']})" if p.get("secao") else "")
    if local.strip():
        partes.append(local.strip())
    if p.get("artigo_inicio") is not None:
        partes.append(f"Art. {p['artigo_inicio']}" if p.get("artigo_inicio") == p.get("artigo_fim")
                      else f"Arts. {p['artigo_inicio']} a {p['artigo_fim']}")
    return " | ".join(partes)


def _trechos(contexto: dict) -> list[str]:
    """Os trechos como o modelo os recebeu: o cabeçalho e o texto de cada um (versão 11).

    Sem o número do trecho, que também sai da resposta (texto_para_o_juiz). Até
    a versão 10, o juiz recebia só o texto, e a menção ao documento que o
    modelo leu no cabeçalho ("conforme a Resolução nº 480") virava, na
    fidelidade, uma afirmação sem apoio nos trechos.
    """
    return [cabecalho_do_trecho(p) + "\n" + p["texto"] for p in contexto.get("passagens", []) if p.get("texto")]


# Marcas de citação: [1], [2][3], [1, 2], [1-3], [8, II], [3, § 2º]... (um colchete com algum número dentro,
# que não seja o texto de um link em Markdown), com o espaço de antes e, se vier pontuação logo depois, o de depois.
_RE_MARCA_DE_CITACAO = re.compile(r"[ \t]*\[[^\[\]\n]{0,40}?\d[^\[\]\n]{0,40}?\](?!\()(?:[ \t]+(?=[.,;:!?)]))?")


def texto_para_o_juiz(resposta: str) -> str:
    """A resposta sem as marcas de citação, como vai para o juiz (versão 10).

    Os trechos chegam ao juiz sem número, então ele não tem como conferir um
    "[1]", e a marca virava uma afirmação julgada falsa. Só as marcas saem (o
    resto do texto, inclusive o recuo das listas, fica como está). O texto
    gravado não muda; a presença de citação é contada na tabela de
    confiabilidade.
    """
    return _RE_MARCA_DE_CITACAO.sub("", resposta or "").strip()


def completude(detalhes: list[dict] | None) -> dict | None:
    """Quanto da resposta correta a resposta traz, a partir do que o juiz devolveu na correção.

    A correção (F1) do RAGAS tem dois lados, nesta ordem: divide a resposta em
    afirmações e confere cada uma contra a resposta correta; depois divide a
    resposta correta e confere cada afirmação contra a resposta. A completude é
    o segundo lado: as afirmações da resposta correta que o juiz achou na
    resposta, sobre as que ele conferiu. None quando esse lado não tem
    veredicto (a resposta correta não rendeu afirmação).

    Se o juiz devolver menos veredictos que afirmações, a conta usa os
    veredictos, como o próprio RAGAS faz no F1; os dois números ficam
    gravados, para conferir.
    """
    lados: list[dict] = []
    for etapa in detalhes or []:
        saida = etapa.get("saida") or {}
        if etapa.get("etapa") == "ClaimDecompositionOutput":
            lados.append({"afirmacoes": len(saida.get("claims") or []), "veredictos": []})
        elif etapa.get("etapa") == "NLIStatementOutput" and lados:
            lados[-1]["veredictos"] += [bool(d.get("verdict")) for d in saida.get("statements") or []]
    if len(lados) < 2 or not lados[1]["veredictos"]:
        return None
    achadas = lados[1]["veredictos"]
    return {"valor": round(sum(achadas) / len(achadas), 4), "afirmacoes_da_resposta_correta": lados[1]["afirmacoes"],
            "conferidas_pelo_juiz": len(achadas), "encontradas_na_resposta": sum(achadas)}


def avaliar_cobertura(pasta: Path, perguntas: list[dict], contextos: dict[str, dict], avaliador,
                      saida=print, destino: Path | None = None) -> int:
    """Cobertura dos trechos, uma vez por pergunta. `destino`: a pasta do juiz (sem ela, a da rodada)."""
    caminho = (destino or pasta) / ARQUIVO_COBERTURA
    feitas = {i for i, l in ultimas_por_id(reparar_respostas(caminho)).items()
              if "erro" not in l["cobertura"] and do_metodo_atual(l)}
    alvo = [p for p in perguntas if not p["sem_resposta"] and p.get("resposta_correta")
            and _trechos(contextos[p["id"]]) and p["id"] not in feitas]
    if not alvo:
        return 0
    saida(f"Cobertura dos trechos (uma vez por pergunta): {len(alvo)} a avaliar.")
    with open(caminho, "a", encoding="utf-8") as arquivo:
        for n, item in enumerate(alvo, 1):
            medida = _medir(avaliador.cobertura, item["pergunta"], _trechos(contextos[item["id"]]),
                            item["resposta_correta"])
            linha = {"id": item["id"], "cobertura": medida, "juiz": avaliador.juiz.modelo, "metodo": VERSAO_DO_METODO,
                     "data_hora": datetime.now().isoformat(timespec="seconds")}
            if lingua_de(avaliador) != "ingles":
                linha["lingua"] = lingua_de(avaliador)
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
            saida(f"  [{n}/{len(alvo)}] {item['id']}: " + _descrever(medida))
    return len(alvo)


def _descrever(medida: dict) -> str:
    if medida.get("valor") is None:
        return f"erro do juiz ({medida.get('erro', '')[:80]})"
    return f"{medida['valor']:.2f} ({medida['segundos']:.0f} s)" + (" [prompt no limite da janela]" if medida.get("aviso") else "")


def _assinatura(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:16]


def _correcao_aproveitavel(anterior: dict | None, item: dict, tipo: str, texto: str, juiz: str,
                           lingua: str = "ingles") -> bool:
    """Se a correção e a completude de uma nota anterior continuam valendo, sem pedir ao juiz de novo.

    Valem as notas dos métodos de CORRECAO_VALE_DESDE e as do método atual que
    tiveram erro só na fidelidade (a nova tentativa refaz só ela), quando: o
    juiz é o mesmo, com os prompts na mesma língua; a pergunta continua com
    resposta nos documentos e com a mesma resposta correta (as notas da versão
    10 não guardam a assinatura dela, mas as perguntas de uma rodada ficam
    congeladas em perguntas.json); o juiz julgou o mesmo texto, na mesma
    categoria; e a correção está lá, sem erro.
    """
    if anterior is None or anterior.get("metodo") not in (*CORRECAO_VALE_DESDE, VERSAO_DO_METODO):
        return False
    if lingua_de(anterior) != lingua:
        return False
    if (anterior.get("juiz") != juiz or bool(anterior.get("sem_resposta")) != bool(item["sem_resposta"])
            or anterior.get("categoria") != tipo or anterior.get("texto_julgado") != texto):
        return False
    if not item["sem_resposta"] and item.get("resposta_correta"):
        assinatura = anterior.get("resposta_correta_assinatura")
        correcao = anterior.get("correcao")
        return ((assinatura is None or assinatura == _assinatura(item["resposta_correta"]))
                and correcao is not None and correcao.get("valor") is not None)
    return False


def avaliar_modelo(pasta: Path, modelo: str, perguntas: list[dict], contextos: dict[str, dict], avaliador,
                   saida=print, destino: Path | None = None, ids: set[str] | None = None) -> int:
    """Correção, completude e fidelidade das respostas de um modelo (as que ainda não têm nota deste método).

    As respostas vêm da pasta da rodada; as notas vão para `destino` (a pasta
    do juiz; sem ela, a da rodada). Uma nota de método anterior (sem "metodo"
    ou com outra versão) é refeita: a linha nova vai para o fim do arquivo e
    vale, e a antiga fica guardada antes dela. Da nota da versão 10, a correção e
    a completude são aproveitadas (_correcao_aproveitavel), e só a fidelidade é
    refeita. `ids`: só estas perguntas (as respostas sorteadas para o piloto).
    A nota do juiz em português leva "lingua": "portugues"; a do juiz em
    inglês fica como até a versão 12, sem o campo.
    """
    lingua = lingua_de(avaliador)
    respostas = ultimas_por_id(ler_respostas(arquivo_respostas(pasta, modelo)))
    aplicar_conferencia(pasta, {modelo: respostas}, so_estes_modelos=True,          # versão 14 (os avisos saem
                        perguntas={p["id"]: p for p in perguntas})                   # uma vez só, em executar)
    caminho = arquivo_ragas(destino or pasta, modelo)
    anteriores = ultimas_por_id(reparar_respostas(caminho))
    feitas = {i for i, l in anteriores.items()          # a nota dada numa categoria tratada de outro jeito é refeita
              if not l.get("tem_erro") and do_metodo_atual(l) and lingua_de(l) == lingua
              and (i not in respostas
                   or tratamento_do_juiz(l.get("categoria")) == tratamento_do_juiz(categoria(respostas[i])))}
    alvo = [p for p in perguntas if p["id"] in respostas and p["id"] not in feitas and (ids is None or p["id"] in ids)]
    antigas = sum(1 for p in alvo if p["id"] in anteriores and not do_metodo_atual(anteriores[p["id"]]))
    preparadas = {}                                   # o que vai para o juiz, pelas regras desta versão
    for p in alvo:
        if p["id"] in respostas:
            resposta = respostas[p["id"]]
            preparadas[p["id"]] = (categoria(resposta), texto_para_o_juiz(resposta.get("resposta") or ""))
    aproveitaveis = sum(1 for p in alvo if p["id"] in preparadas
                        and _correcao_aproveitavel(anteriores.get(p["id"]), p, *preparadas[p["id"]],
                                                   avaliador.juiz.modelo, lingua))
    rotulo = info_modelo(modelo)["rotulo"]
    if not respostas:
        saida(f"{rotulo}: nenhuma resposta nesta rodada.")
        return 0
    if not alvo:
        saida(f"{rotulo}: todas as respostas já avaliadas.")
        return 0
    saida(f"{rotulo}: {len(alvo)} respostas a avaliar."
          + (f" {antigas} delas tinham nota de um método anterior à versão {VERSAO_DO_METODO}: a nota antiga fica "
             "no arquivo, e a nova é a que vale." if antigas else "")
          + (f" Em {aproveitaveis}, a correção e a completude já dadas são aproveitadas, e só a fidelidade é "
             "refeita." if aproveitaveis else ""))
    with open(caminho, "a", encoding="utf-8") as arquivo:
        for n, item in enumerate(alvo, 1):
            trechos = _trechos(contextos[item["id"]])
            tipo, texto = preparadas[item["id"]]            # pelas regras desta versão, não a gravada na geração
            linha = {"id": item["id"], "modelo": modelo, "juiz": avaliador.juiz.modelo, "metodo": VERSAO_DO_METODO,
                     "sem_resposta": item["sem_resposta"], "categoria": tipo, "abstencao": tipo == "abstencao",
                     "texto_julgado": None, "correcao": None, "completude": None, "fidelidade": None,
                     "data_hora": None}
            if lingua != "ingles":
                linha["lingua"] = lingua
            if tipo == "vazia" or (tipo != "abstencao" and not texto):
                linha["resposta_vazia"] = True     # nada para julgar, nem antes nem depois de tirar as citações
            elif tipo != "abstencao":
                linha["texto_julgado"] = texto
                anterior = anteriores.get(item["id"])
                if not item["sem_resposta"] and item.get("resposta_correta"):
                    linha["resposta_correta_assinatura"] = _assinatura(item["resposta_correta"])
                if _correcao_aproveitavel(anterior, item, tipo, texto, avaliador.juiz.modelo, lingua):
                    linha["correcao"], linha["completude"] = anterior.get("correcao"), anterior.get("completude")
                    linha["correcao_do_metodo"] = anterior.get("correcao_do_metodo") or anterior["metodo"]
                elif not item["sem_resposta"] and item.get("resposta_correta"):
                    linha["correcao"] = _medir(avaliador.correcao, item["pergunta"], texto, item["resposta_correta"])
                    if linha["correcao"].get("valor") is not None:
                        linha["completude"] = completude(linha["correcao"].get("detalhes"))
                if trechos:
                    linha["fidelidade"] = _medir(avaliador.fidelidade, item["pergunta"], texto, trechos)
            linha["tem_erro"] = any(m is not None and m.get("valor") is None
                                    for m in (linha["correcao"], linha["fidelidade"]))
            linha["data_hora"] = datetime.now().isoformat(timespec="seconds")
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
            partes = []
            if linha.get("correcao_do_metodo"):
                partes.append(f"correção aproveitada {linha['correcao']['valor']:.2f}")
            elif linha["correcao"] is not None:
                partes.append("correção " + _descrever(linha["correcao"]))
            if linha["completude"] is not None:
                partes.append(f"completude {linha['completude']['valor']:.2f}")
            if linha["fidelidade"] is not None:
                partes.append("fidelidade " + _descrever(linha["fidelidade"]))
            vazio = "resposta vazia, sem nota" if linha.get("resposta_vazia") else "abstenção, sem nota"
            saida(f"  [{n}/{len(alvo)}] {item['id']}: " + ("; ".join(partes) or vazio))
    return len(alvo)


# Resumo
def _valores(linhas: dict[str, dict], chave: str) -> dict[str, float]:
    return {i: l[chave]["valor"] for i, l in linhas.items()
            if l.get(chave) is not None and l[chave].get("valor") is not None}


def _estatisticas(valores: list[float]) -> dict:
    if not valores:
        return {"n": 0, "media": None, "mediana": None, "zeros": 0}
    return {"n": len(valores), "media": round(statistics.mean(valores), 3),
            "mediana": round(statistics.median(valores), 3), "zeros": sum(v == 0 for v in valores)}


def medias_ragas(pasta: Path, modelo: str, so_metodo_atual: bool = False) -> dict:
    """Médias das notas de um juiz para um modelo (o resumo do juiz e a tabela de confiabilidade).

    Sem so_metodo_atual, lê todas as notas: é o caso das rodadas das versões
    06 a 08, com as notas do único juiz soltas na pasta da rodada.
    """
    linhas, antigas = ler_notas(arquivo_ragas(pasta, modelo), so_metodo_atual)
    medias = {m: _estatisticas(list(_valores(linhas, m).values())) for m in METRICAS}
    return {**medias, "erros_do_juiz": sum(bool(l.get("tem_erro")) for l in linhas.values()), "notas_antigas": antigas}


def resumir(pasta: Path, destino: Path | None = None) -> dict:
    """Resumo das notas de um juiz (as que estão em `destino`; sem ela, na pasta da rodada).

    Na pasta de um juiz, entram só as notas do método atual (VERSAO_DO_METODO).
    """
    configuracao, perguntas = abrir_rodada(pasta)
    base = destino or pasta
    so_atual = destino is not None
    modelos = [m["modelo"] for m in configuracao.get("modelos", []) if arquivo_ragas(base, m["modelo"]).exists()]
    por_modelo = {m: ler_notas(arquivo_ragas(base, m), so_atual)[0] for m in modelos}
    cobertura = ler_cobertura(base / ARQUIVO_COBERTURA, so_atual)
    tabela = []
    for modelo in modelos:
        linha = {"modelo": modelo, "rotulo": info_modelo(modelo)["rotulo"]}
        linha.update(medias_ragas(base, modelo, so_atual))
        tabela.append(linha)
    comparacoes = []
    for a, b in combinations(modelos, 2):
        for chave in METRICAS:
            va, vb = _valores(por_modelo[a], chave), _valores(por_modelo[b], chave)
            comuns = sorted(set(va) & set(vb))
            teste = wilcoxon_pareado([va[i] for i in comuns], [vb[i] for i in comuns])
            comparacoes.append({"modelo_a": a, "modelo_b": b, "metrica": chave, "perguntas": len(comuns), **teste})
    valores_cobertura = [l["cobertura"]["valor"] for l in cobertura.values() if l["cobertura"].get("valor") is not None]
    nomes_juizes = sorted({l.get("juiz") for linhas in por_modelo.values() for l in linhas.values()} - {None})
    caminho_juiz = base / ARQUIVO_CONFIGURACAO_JUIZ
    registros_juiz = json.loads(caminho_juiz.read_text(encoding="utf-8")) if caminho_juiz.exists() else []
    opcoes = (next((r.get("opcoes") for r in reversed(registros_juiz) if r.get("opcoes")), None)
              or opcoes_juiz(nomes_juizes[0] if nomes_juizes else None))
    return {"rodada": pasta.name, "calculado_em": datetime.now().isoformat(timespec="seconds"),
            "juiz": nomes_juizes, "opcoes_juiz": opcoes, "registro_do_juiz": registros_juiz,
            "lingua": lingua_do_registro(registros_juiz),
            "perguntas": configuracao.get("perguntas"), "metodo": VERSAO_DO_METODO if so_atual else None,
            "notas_antigas": sum(t["notas_antigas"] for t in tabela),
            "cobertura": _estatisticas(valores_cobertura), "tabela": tabela, "comparacoes": comparacoes,
            "total_perguntas": len(perguntas)}


def _num(v, casas: int = 2) -> str:
    return "-" if v is None else f"{v:.{casas}f}".replace(".", ",")


NOMES = {"correcao": "correção (F1)", "completude": "completude", "fidelidade": "fidelidade",
         "cobertura": "cobertura dos trechos"}
TITULOS = {"correcao": "Correção (F1)", "completude": "Completude", "fidelidade": "Fidelidade",
           "cobertura": "Cobertura dos trechos"}
EXPLICACAO = ("Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as "
              "abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta "
              "correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz "
              "de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: "
              "confira o que ele devolveu")


def _aviso_notas_antigas(antigas: int) -> list[str]:
    if not antigas:
        return []
    return ["", f"Atenção: {antigas} nota(s) dada(s) por um método anterior à versão {VERSAO_DO_METODO} (antes de "
            "a versão 10 tirar as marcas de citação do texto julgado, ou de a versão 11 mandar ao juiz o cabeçalho dos "
            "trechos) ficam guardadas nos arquivos, mas não entram nas médias. Rode avaliar-ragas.bat para refazê-las."]


def texto_markdown(resumo: dict) -> str:
    c = resumo["cobertura"]
    em_portugues = resumo.get("lingua") == "portugues"
    so_piloto = em_portugues and not c.get("n")      # versão 13: só as respostas do piloto, sem a cobertura
    linhas = [f"# Avaliação com o RAGAS da rodada {resumo['rodada']}", "",
              f"Juiz: {', '.join(resumo['juiz']) or '-'} (temperatura 0, janela de "
              f"{resumo['opcoes_juiz']['num_ctx']} tokens). Calculado em {resumo['calculado_em']}.", ""]
    if so_piloto:                    # só as respostas do piloto: sem a cobertura e sem a comparação dos modelos
        linhas += ["Juiz em português (versão 13): os exemplos dos prompts do RAGAS em português e a instrução de "
                   "escrever a saída em português. Ele só avaliou as respostas sorteadas para o piloto, que são de "
                   "perguntas diferentes em cada modelo, e não calcula a cobertura dos trechos: estas médias não são "
                   "o resultado da rodada nem comparam os modelos. A comparação com a avaliação humana está no "
                   "resultado do piloto (avaliar-piloto.bat).", ""]
    else:
        if em_portugues:
            linhas += ["Juiz em português: os exemplos dos prompts do RAGAS em português e a instrução de escrever a "
                       "saída em português (prompts_em_portugues.py).", ""]
        linhas += [f"Cobertura dos trechos (a mesma para todos os modelos): média {_num(c['media'])}, mediana "
                   f"{_num(c['mediana'])}, em {c['n']} perguntas; {c['zeros']} com nota zero.", ""]
    linhas += ["| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção "
              "| Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |",
              "|-|-|-|-|-|-|-|-|-|-|"]
    for t in resumo["tabela"]:
        linhas.append(f"| {t['rotulo']} | {_num(t['correcao']['media'])} | {_num(t['correcao']['mediana'])} | "
                      f"{t['correcao']['n']} | {t['correcao']['zeros']} | {_num(t['completude']['media'])} | "
                      f"{_num(t['completude']['mediana'])} | {_num(t['fidelidade']['media'])} | "
                      f"{t['fidelidade']['n']} | {t['erros_do_juiz']} |")
    linhas += ["", EXPLICACAO + " no ragas_<modelo>.jsonl."]
    linhas += _aviso_notas_antigas(resumo.get("notas_antigas", 0))
    if so_piloto:
        return "\n".join(linhas) + "\n"
    linhas += ["", "## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)", ""]
    for comp in resumo["comparacoes"]:
        if not comp["perguntas"]:
            continue
        a, b = info_modelo(comp["modelo_a"])["rotulo"], info_modelo(comp["modelo_b"])["rotulo"]
        linhas.append(f"- {NOMES[comp['metrica']]}, {a} x {b}: {comp['perguntas']} perguntas, mediana da "
                      f"diferença {_num(comp['mediana_diferenca'])}, p = {_num(comp['p'], 3)}")
    return "\n".join(linhas) + "\n"


def gravar_resumo(pasta: Path, resumo: dict) -> None:
    (pasta / "ragas_resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / "ragas_resumo.md").write_text(texto_markdown(resumo), encoding="utf-8")
    with open(pasta / "ragas_resumo.csv", "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(["modelo", "rotulo", "correcao_media", "correcao_mediana", "correcao_n", "correcao_zeros",
                           "completude_media", "completude_mediana", "completude_n", "fidelidade_media",
                           "fidelidade_n", "erros_do_juiz", "notas_antigas"])
        for t in resumo["tabela"]:
            escritor.writerow([t["modelo"], t["rotulo"], _num(t["correcao"]["media"], 3),
                               _num(t["correcao"]["mediana"], 3), t["correcao"]["n"], t["correcao"]["zeros"],
                               _num(t["completude"]["media"], 3), _num(t["completude"]["mediana"], 3),
                               t["completude"]["n"], _num(t["fidelidade"]["media"], 3), t["fidelidade"]["n"],
                               t["erros_do_juiz"], t["notas_antigas"]])


def registrar_juiz(pasta: Path, avaliador) -> None:
    """Grava (uma vez por juiz) qual juiz avaliou a rodada, com que opções e com que versão do RAGAS."""
    caminho = pasta / ARQUIVO_CONFIGURACAO_JUIZ
    registros = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else []
    try:
        from importlib.metadata import version
        versao_ragas = version("ragas")
    except Exception:
        versao_ragas = None
    atual = {"juiz": avaliador.juiz.modelo, "opcoes": getattr(avaliador.juiz, "opcoes", None),
             "ragas": versao_ragas, "versao_chatbot": config.VERSAO_CHATBOT}
    if lingua_de(avaliador) != "ingles":
        atual["lingua"] = lingua_de(avaliador)
    if not any({k: r.get(k) for k in atual} == atual for r in registros):
        registros.append(dict(atual, inicio=datetime.now().isoformat(timespec="seconds")))
        caminho.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")


def lingua_do_registro(registros: list[dict]) -> str:
    """A língua dos prompts de uma pasta de juiz, pelo registro dela (sem o campo, inglês, como até a versão 12)."""
    return next((r["lingua"] for r in registros if isinstance(r, dict) and r.get("lingua")), "ingles")


# Os juízes juntos
def pastas_dos_juizes(pasta: Path, lingua: str = "ingles") -> list[tuple[str, Path]]:
    """(juiz, pasta) de cada juiz que já avaliou a rodada com os prompts na língua pedida, na ordem de
    config.JUIZES e depois a do nome.

    Os juízes em inglês ficam nas pastas juiz_* da rodada, e os em português,
    nas de juizes_em_portugues/ (versão 13); o registro de cada pasta
    (ragas_configuracao.json) também tem de ser da língua pedida. As notas em
    português ficam fora do resumo da rodada e da tabela de confiabilidade, que
    pedem as em inglês. Duas pastas do mesmo juiz na mesma língua (uma cópia de
    segurança dentro da rodada, por exemplo) são recusadas: uma tomaria o lugar
    da outra sem aviso.
    """
    encontrados = []
    for caminho in sorted(_pasta_da_lingua(pasta, lingua).glob(f"{PREFIXO_PASTA_JUIZ}*")):
        registro = caminho / ARQUIVO_CONFIGURACAO_JUIZ
        if not caminho.is_dir() or not registro.exists():
            continue
        try:
            registros = json.loads(registro.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(registros, list) or lingua_do_registro(registros) != lingua:
            continue
        nome = next((r.get("juiz") for r in registros if isinstance(r, dict) and r.get("juiz")), None)
        if nome:
            repetido = next((c for j, c in encontrados if j == nome), None)
            if repetido is not None:
                raise ErroRodada(f"a rodada {pasta.name} tem duas pastas do juiz {nome}"
                                 + (" em português" if lingua == "portugues" else "")
                                 + f": {repetido.name} e {caminho.name}. Deixe só uma na pasta da rodada (uma cópia "
                                 "de segurança pode ir para fora dela); com as duas, as notas de uma tomariam o lugar "
                                 "das da outra.")
            encontrados.append((nome, caminho))
    ordem = {j["modelo"]: i for i, j in enumerate(juizes())}
    return sorted(encontrados, key=lambda par: (ordem.get(par[0], len(ordem)), par[0]))


def faltam_notas(pasta: Path, lingua: str = "ingles") -> dict[str, int]:
    """Quantas notas faltam a cada juiz da língua para a rodada inteira (versão 15): respostas sem nota do método
    atual, ou com erro do juiz, e perguntas sem cobertura dos trechos. Um juiz de config.JUIZES que ainda não tem
    pasta nessa língua conta com todas as notas faltando. {} sem nenhum juiz nessa língua."""
    configuracao, perguntas = abrir_rodada(pasta)
    contextos = ler_contextos(pasta) if (pasta / ARQUIVO_CONTEXTOS).exists() else {}
    modelos = [m["modelo"] for m in configuracao.get("modelos", [])]
    respostas = {m: set(ultimas_por_id(ler_respostas(arquivo_respostas(pasta, m)))) for m in modelos}
    com_cobertura = {p["id"] for p in perguntas if not p["sem_resposta"] and p.get("resposta_correta")
                     and p["id"] in contextos and _trechos(contextos[p["id"]])}
    faltam = {}
    for juiz, caminho in pastas_dos_juizes(pasta, lingua):
        n = 0
        for modelo in modelos:
            notas, _ = ler_notas(arquivo_ragas(caminho, modelo))
            n += len(respostas[modelo] - {i for i, l in notas.items() if not l.get("tem_erro")})
        cobertura = ler_cobertura(caminho / ARQUIVO_COBERTURA)
        n += len(com_cobertura - {i for i, l in cobertura.items() if "erro" not in (l.get("cobertura") or {})})
        faltam[juiz] = n
    if faltam:
        todas = sum(len(r) for r in respostas.values()) + len(com_cobertura)
        for juiz in (j["modelo"] for j in juizes()):
            faltam.setdefault(juiz, todas)
    return faltam


def _media_dos_juizes(notas: list[dict[str, float]]) -> dict[str, float]:
    """Média das notas, só nas respostas que todos os juízes avaliaram."""
    if not notas:
        return {}
    comuns = set.intersection(*(set(n) for n in notas))
    return {i: round(statistics.mean(n[i] for n in notas), 4) for i in sorted(comuns)}


def resumir_juizes(pasta: Path, lingua: str = "ingles") -> dict | None:
    """A média dos juízes, a concordância entre eles e a comparação dos modelos (None sem nenhum juiz).

    Só os juízes com os prompts na língua pedida; o resumo da rodada é o dos juízes em inglês.
    """
    configuracao, perguntas = abrir_rodada(pasta)
    pastas = pastas_dos_juizes(pasta, lingua)
    if not pastas:
        return None
    nomes = [j for j, _ in pastas]
    modelos = [m["modelo"] for m in configuracao.get("modelos", [])]
    notas: dict[str, dict] = {}                   # juiz -> modelo -> métrica -> {pergunta: nota}
    cobertura: dict[str, dict[str, float]] = {}   # juiz -> {pergunta: nota}
    erros: dict[str, dict[str, int]] = {}
    antigas: dict[str, dict[str, int]] = {}       # notas de um método anterior: no arquivo, fora das médias
    for juiz, caminho in pastas:
        notas[juiz], erros[juiz], antigas[juiz] = {}, {}, {}
        for modelo in modelos:
            linhas, antigas[juiz][modelo] = ler_notas(arquivo_ragas(caminho, modelo))
            notas[juiz][modelo] = {m: _valores(linhas, m) for m in METRICAS}
            erros[juiz][modelo] = sum(bool(l.get("tem_erro")) for l in linhas.values())
        linhas = ler_cobertura(caminho / ARQUIVO_COBERTURA)
        cobertura[juiz] = {i: l["cobertura"]["valor"] for i, l in linhas.items()
                           if l.get("cobertura") and l["cobertura"].get("valor") is not None}
    tabela, combinadas = [], {}
    for modelo in modelos:
        if not any(notas[j][modelo][m] for j in nomes for m in METRICAS):
            continue
        linha = {"modelo": modelo, "rotulo": info_modelo(modelo)["rotulo"], "familia": familia(modelo),
                 "por_juiz": {j: {m: _estatisticas(list(notas[j][modelo][m].values())) for m in METRICAS}
                              for j in nomes},
                 "erros_do_juiz": {j: erros[j][modelo] for j in nomes}}
        combinadas[modelo] = {m: _media_dos_juizes([notas[j][modelo][m] for j in nomes]) for m in METRICAS}
        for m in METRICAS:
            linha[m] = _estatisticas(list(combinadas[modelo][m].values()))
        tabela.append(linha)
    concordancia = []
    for a, b in combinations(nomes, 2):
        for m in METRICAS:
            pares = [(notas[a][modelo][m][i], notas[b][modelo][m][i]) for modelo in modelos
                     for i in sorted(set(notas[a][modelo][m]) & set(notas[b][modelo][m]))]
            concordancia.append({"juiz_a": a, "juiz_b": b, "metrica": m, **concordancia_de_notas(pares)})
        pares = [(cobertura[a][i], cobertura[b][i]) for i in sorted(set(cobertura[a]) & set(cobertura[b]))]
        concordancia.append({"juiz_a": a, "juiz_b": b, "metrica": "cobertura", **concordancia_de_notas(pares)})
    comparacoes = []
    for a, b in combinations(list(combinadas), 2):
        for m in METRICAS:
            va, vb = combinadas[a][m], combinadas[b][m]
            comuns = sorted(set(va) & set(vb))
            teste = wilcoxon_pareado([va[i] for i in comuns], [vb[i] for i in comuns])
            comparacoes.append({"modelo_a": a, "modelo_b": b, "metrica": m, "perguntas": len(comuns), **teste})
    return {"rodada": pasta.name, "calculado_em": datetime.now().isoformat(timespec="seconds"),
            "metodo": VERSAO_DO_METODO, "lingua": lingua, "faltam": faltam_notas(pasta, lingua),
            "juizes": [{"modelo": j, "rotulo": info_modelo(j)["rotulo"], "familia": familia(j),
                        "pasta": caminho.relative_to(pasta).as_posix()} for j, caminho in pastas],
            "perguntas": configuracao.get("perguntas"), "total_perguntas": len(perguntas),
            "cobertura": {"media_dos_juizes": _estatisticas(list(_media_dos_juizes(list(cobertura.values())).values())),
                          "por_juiz": {j: _estatisticas(list(cobertura[j].values())) for j in nomes}},
            "tabela": tabela, "concordancia": concordancia, "comparacoes": comparacoes,
            "notas_antigas": {j: sum(antigas[j].values()) for j in nomes}}


def medias_dos_juizes(pasta: Path, modelo: str, resumo: dict | None = None) -> dict | None:
    """Correção, completude e fidelidade de um modelo na média dos juízes (para a tabela de confiabilidade)."""
    resumo = resumo if resumo is not None else resumir_juizes(pasta)
    if not resumo:
        return None
    return next(({m: linha[m] for m in METRICAS} for linha in resumo["tabela"] if linha["modelo"] == modelo), None)


def _rotulo(nome: str) -> str:
    return info_modelo(nome)["rotulo"]


def texto_markdown_juizes(resumo: dict) -> str:
    nomes = [j["modelo"] for j in resumo["juizes"]]
    c = resumo["cobertura"]
    descricao = ", ".join(f"{j['rotulo']} ({j['familia'] or 'família não marcada'})" for j in resumo["juizes"])
    linhas = [f"# Avaliação com o RAGAS da rodada {resumo['rodada']}", "",
              f"Juízes{' em português' if resumo.get('lingua') == 'portugues' else ''}: {descricao}. A nota de "
              "cada resposta é a média dos juízes; entram só as respostas que "
              f"todos avaliaram. Calculado em {resumo['calculado_em']}.", "",
              f"Cobertura dos trechos (a mesma para todos os modelos): média dos juízes "
              f"{_num(c['media_dos_juizes']['media'])}, em {c['media_dos_juizes']['n']} perguntas ("
              + "; ".join(f"{_rotulo(j)}: {_num(c['por_juiz'][j]['media'])}" for j in nomes) + ").", ""]
    if any(resumo.get("faltam", {}).values()):
        linhas += [_texto_faltam(resumo["faltam"], resumo.get("lingua", "ingles")), ""]
    cabecalho = ["Modelo"]
    for m in METRICAS:
        cabecalho += [f"{TITULOS[m]} (média dos juízes)", "Respostas"] + [f"{TITULOS[m]}, {_rotulo(j)}" for j in nomes]
    cabecalho.append("Erros dos juízes")
    linhas += ["| " + " | ".join(cabecalho) + " |", "|" + "-|" * len(cabecalho)]
    for t in resumo["tabela"]:
        celulas = [t["rotulo"]]
        for m in METRICAS:
            celulas += [_num(t[m]["media"]), str(t[m]["n"])] + [_num(t["por_juiz"][j][m]["media"]) for j in nomes]
        celulas.append(str(sum(t["erros_do_juiz"].values())))
        linhas.append("| " + " | ".join(celulas) + " |")
    linhas += ["", EXPLICACAO + " por cada juiz na pasta dele (juiz_<nome>/ragas_<modelo>.jsonl)."]
    linhas += _aviso_notas_antigas(sum((resumo.get("notas_antigas") or {}).values()))
    linhas.append("")
    if len(nomes) > 1:
        linhas += ["## Concordância entre os juízes", ""]
        for item in resumo["concordancia"]:
            linhas.append(f"- {NOMES.get(item['metrica'], item['metrica'])}, {_rotulo(item['juiz_a'])} x "
                          f"{_rotulo(item['juiz_b'])}: {item['n']} notas dos dois, correlação de Pearson "
                          f"{_num(item['pearson'])}, diferença média {_num(item['diferenca_media'])}")
        linhas.append("")
    linhas += ["## Comparação dos modelos (Wilcoxon pareado, na média dos juízes, nas perguntas que os dois têm "
               "nota)", ""]
    for comp in resumo["comparacoes"]:
        if not comp["perguntas"]:
            continue
        linhas.append(f"- {NOMES[comp['metrica']]}, {_rotulo(comp['modelo_a'])} x {_rotulo(comp['modelo_b'])}: "
                      f"{comp['perguntas']} perguntas, mediana da diferença {_num(comp['mediana_diferenca'])}, "
                      f"p = {_num(comp['p'], 3)}")
    return "\n".join(linhas) + "\n"


def comando_dos_juizes(lingua: str) -> str:
    """O comando que avalia (ou completa) a rodada com os juízes de uma língua."""
    return "avaliar-ragas.bat" + ("" if lingua == config.JUIZES_LINGUA else f" --{lingua}")


def _texto_faltam(faltam: dict[str, int], lingua: str) -> str:
    return ("Atenção: a avaliação dos juízes" + (" em português" if lingua == "portugues" else "")
            + " não está completa (faltam " + "; ".join(f"{_rotulo(j)}: {n} nota(s)" for j, n in faltam.items())
            + "); a média dos juízes sai só das respostas que todos avaliaram. Rode " + comando_dos_juizes(lingua)
            + " para completar.")


def gravar_resumo_juizes(pasta: Path, resumo: dict) -> None:
    (pasta / f"{RESUMO_JUIZES}.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / f"{RESUMO_JUIZES}.md").write_text(texto_markdown_juizes(resumo), encoding="utf-8")
    nomes = [j["modelo"] for j in resumo["juizes"]]
    with open(pasta / f"{RESUMO_JUIZES}.csv", "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        cabecalho = ["modelo", "rotulo"]
        for m in METRICAS:
            cabecalho += [f"{m}_media_juizes", f"{m}_n"] + [f"{m}_{nome_arquivo_modelo(j)}" for j in nomes]
        escritor.writerow(cabecalho + ["erros_dos_juizes"])
        for t in resumo["tabela"]:
            linha = [t["modelo"], t["rotulo"]]
            for m in METRICAS:
                linha += [_num(t[m]["media"], 3), t[m]["n"]] + [_num(t["por_juiz"][j][m]["media"], 3) for j in nomes]
            escritor.writerow(linha + [sum(t["erros_do_juiz"].values())])


# Execução
def ids_do_piloto(pasta: Path) -> dict[str, set[str]]:
    """As respostas sorteadas para o piloto da rodada, {modelo: {pergunta}}, lidas da chave dele (piloto.py)."""
    caminho = pasta / PASTA_PILOTO / ARQUIVO_CHAVE_PILOTO
    if not caminho.exists():
        raise ErroRodada(f"não há piloto na rodada {pasta.name} ({caminho.parent}); rode preparar-piloto.bat antes.")
    ids: dict[str, set[str]] = {}
    try:
        for item in json.loads(caminho.read_text(encoding="utf-8"))["amostra"]:
            ids.setdefault(item["modelo"], set()).add(item["id"])
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroRodada(f"a chave do piloto ({caminho}) não pôde ser lida ({type(erro).__name__}: {erro}). Ela é "
                         "gravada pelo preparar-piloto.bat e não deve ser editada; se foi, volte o arquivo ao que "
                         "era (o sorteio é o mesmo com a mesma semente).") from erro
    return ids


def _avisar_conferencia(pasta: Path, modelos: list[str], perguntas: list[dict], saida=print) -> None:
    """Uma vez por execução, e não por juiz: as respostas com a categoria conferida à mão no revisar.csv e os
    avisos das decisões que não valem (versão 14)."""
    por_modelo = {m: ultimas_por_id(ler_respostas(arquivo_respostas(pasta, m))) for m in modelos}
    conferencia = aplicar_conferencia(pasta, por_modelo, so_estes_modelos=True,
                                      perguntas={p["id"]: p for p in perguntas})
    for modelo in modelos:
        ids = [a["id"] for a in conferencia["alteradas"] if a["modelo"] == modelo]
        if ids:
            saida(f"{info_modelo(modelo)['rotulo']}: categoria conferida à mão no revisar.csv em {', '.join(ids)}.")
    for aviso in conferencia["avisos"]:
        saida(f"Atenção (revisar.csv): {aviso}")


def executar(pasta: Path, modelos: list[str], avaliadores, limite: int | None = None, saida=print,
             ids_por_modelo: dict[str, set[str]] | None = None) -> dict | None:
    """Cada juiz avalia a rodada, um depois do outro; no fim, o resumo dos juízes juntos.

    `avaliadores`: um AvaliadorRagas por juiz (ou um só). Cada juiz é
    descarregado da placa de vídeo antes do próximo. `ids_por_modelo`: só
    estas respostas ({modelo: {pergunta}}, as do piloto), sem a cobertura dos
    trechos. O juiz em português grava na pasta dele (juizes_em_portugues/).
    O resumo dos juízes (ragas_juizes) de cada língua que avaliou vai para a
    pasta dessa língua; com --so-piloto, só o dos juízes em inglês. Devolve o
    da língua de config.JUIZES_LINGUA (ou o outro, se só ele mudou; sem
    nenhum, None).
    """
    if not isinstance(avaliadores, (list, tuple)):
        avaliadores = [avaliadores]
    configuracao, perguntas = abrir_rodada(pasta)
    if not (pasta / ARQUIVO_CONTEXTOS).exists():
        raise ErroRodada(f"a rodada {pasta.name} não tem {ARQUIVO_CONTEXTOS}; rode gerar-respostas.bat --continuar")
    contextos = ler_contextos(pasta)
    if limite:
        perguntas = perguntas[:limite]
    with Trava(pasta):           # nem outra avaliação nem a geração rodando ao mesmo tempo nesta rodada
        _avisar_conferencia(pasta, modelos, perguntas, saida)
        for avaliador in avaliadores:
            nome, lingua = avaliador.juiz.modelo, lingua_de(avaliador)
            destino = pasta_do_juiz(pasta, nome, lingua)
            destino.mkdir(parents=True, exist_ok=True)
            saida(f"\nJuiz {_rotulo(nome)} ({nome})" + (", em português" if lingua == "portugues" else "") + ":")
            registrar_juiz(destino, avaliador)
            try:
                if ids_por_modelo is None:
                    avaliar_cobertura(pasta, perguntas, contextos, avaliador, saida, destino=destino)
                for modelo in modelos:
                    if ids_por_modelo is not None and modelo not in ids_por_modelo:
                        continue
                    avaliar_modelo(pasta, modelo, perguntas, contextos, avaliador, saida, destino=destino,
                                   ids=None if ids_por_modelo is None else ids_por_modelo[modelo])
            finally:
                descarregar = getattr(avaliador.juiz, "descarregar", None)
                if descarregar:
                    descarregar()
            gravar_resumo(destino, resumir(pasta, destino))
    resumos = {}
    for lingua in dict.fromkeys(lingua_de(a) for a in avaliadores):
        if lingua != "ingles" and ids_por_modelo is not None:
            continue                 # os juízes em português só no piloto: o piloto compara, sem resumo da rodada
        resumo = resumir_juizes(pasta, lingua)
        if resumo:
            gravar_resumo_juizes(_pasta_da_lingua(pasta, lingua), resumo)
            resumos[lingua] = resumo
    return resumos.get(config.JUIZES_LINGUA) or next(iter(resumos.values()), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avalia as respostas de uma rodada com o RAGAS (juízes locais).")
    parser.add_argument("--rodada", type=Path, default=None, help="pasta da rodada (padrão: a mais recente)")
    parser.add_argument("--modelos", nargs="+", default=None, help="só estes modelos (padrão: os da rodada)")
    parser.add_argument("--juiz", "--juizes", dest="juizes", nargs="+", default=None,
                        help="só estes juízes (padrão: os de config.JUIZES)")
    parser.add_argument("--limite", type=int, default=None, help="só as N primeiras perguntas")
    parser.add_argument("--so-piloto", action="store_true",
                        help="só as respostas sorteadas para o piloto (piloto/piloto_chave.json), sem a cobertura")
    parser.add_argument("--portugues", action="store_true",
                        help="os juízes com os prompts em português (o padrão desde a versão 15, em config.JUIZES_LINGUA)")
    parser.add_argument("--ingles", action="store_true",
                        help="os juízes com os prompts do RAGAS como vêm, em inglês")
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
        configuracao, _ = abrir_rodada(pasta)
        if args.portugues and args.ingles:
            raise ErroJuiz("use --portugues ou --ingles, não os dois")
        lingua = "portugues" if args.portugues else "ingles" if args.ingles else config.JUIZES_LINGUA
        if lingua not in LINGUAS:
            raise ErroJuiz(f"config.JUIZES_LINGUA = {lingua!r}; as possíveis são {', '.join(LINGUAS)}")
        modelos = args.modelos or [m["modelo"] for m in configuracao.get("modelos", [])
                                   if ler_respostas(arquivo_respostas(pasta, m["modelo"]))]
        ids_por_modelo = None
        if args.so_piloto:
            ids_por_modelo = ids_do_piloto(pasta)
            fora = [m for m in modelos if m not in ids_por_modelo]
            modelos = [m for m in modelos if m in ids_por_modelo]
            if not modelos:
                raise ErroRodada("nenhum dos modelos pedidos tem resposta sorteada para o piloto desta rodada.")
            for modelo in fora:
                print(f"AVISO: {_rotulo(modelo)} ({modelo}) não tem resposta sorteada para o piloto e fica de fora.")
        nomes_juizes = args.juizes or [j["modelo"] for j in juizes()]
        if not nomes_juizes:
            raise ErroJuiz("nenhum juiz em config.JUIZES")
        lista = [criar_juiz(nome) for nome in nomes_juizes]
        for problema in problemas_de_familia(modelos, nomes_juizes):
            print(f"AVISO: {problema}. Nenhum modelo da avaliação deveria repetir a família de outro: serve para "
                  "testar o caminho, não para o resultado final.")
        for juiz in lista:
            _conferir_juiz(juiz)
        avaliadores = [AvaliadorRagas(j, lingua=lingua) for j in lista]
        print(f"Rodada {pasta.name}; juízes: " + ", ".join(_rotulo(j) for j in nomes_juizes)
              + (" (prompts em português)" if lingua == "portugues" else " (prompts do RAGAS, em inglês)")
              + "; modelos: " + ", ".join(_rotulo(m) for m in modelos))
        if ids_por_modelo is not None:
            _, perguntas = abrir_rodada(pasta)
            dentro = {p["id"] for p in (perguntas[:args.limite] if args.limite else perguntas)}
            print("Só as respostas sorteadas para o piloto" + (f", nas {args.limite} primeiras perguntas"
                                                               if args.limite else "") + ": " + ", ".join(
                f"{_rotulo(m)}: {len(ids_por_modelo[m] & dentro)}" for m in modelos) + ".")
        resumo = executar(pasta, modelos, avaliadores, args.limite, ids_por_modelo=ids_por_modelo)
    except KeyboardInterrupt:
        print("\nAvaliação interrompida. As notas já calculadas estão gravadas; rode de novo o mesmo arquivo "
              "(avaliar-ragas.bat ou juizes-em-portugues.bat) para continuar.")
        return 1
    except (ErroRodada, ErroJuiz) as erro:
        print(f"\nERRO: {erro}")
        return 1
    except Exception as erro:
        if _erro_de_conexao(erro):
            print(f"\nERRO: não foi possível falar com o Ollama ({erro}). Abra o Ollama e rode de novo; as notas já "
                  "calculadas estão gravadas.")
            return 1
        raise
    if resumo is None:                       # só os juízes em português do piloto: o resumo da rodada não muda
        print(f"\nNotas dos juízes em português gravadas em {pasta / PASTA_JUIZES_EM_PORTUGUES} (uma pasta por juiz, "
              "com o resumo dele). Como são só as do piloto, elas não entram no resumo da rodada nem na tabela de "
              "confiabilidade: o avaliar-piloto.bat as compara com as dos juízes em inglês e com a sua avaliação.")
        return 0
    print("\n" + texto_markdown_juizes(resumo))
    destino = _pasta_da_lingua(pasta, resumo.get("lingua", "ingles"))
    print(f"Resumo gravado em {destino / (RESUMO_JUIZES + '.md')} (e .csv, .json); o de cada juiz fica na pasta dele "
          f"({destino / PREFIXO_PASTA_JUIZ}<juiz>).")
    return 0


def _conferir_juiz(juiz: JuizOllama) -> None:
    from modelos import instalados, nome_completo
    try:
        nomes = instalados(juiz.cliente.list())
    except Exception as erro:
        raise ErroJuiz(f"não foi possível conectar ao Ollama: {erro}. Abra o Ollama e rode de novo.") from erro
    if nome_completo(juiz.modelo) not in nomes:
        raise ErroJuiz(f"o juiz {juiz.modelo} não está instalado no Ollama; rode: ollama pull {juiz.modelo}")


if __name__ == "__main__":
    sys.exit(main())
