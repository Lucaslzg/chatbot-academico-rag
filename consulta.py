"""Pipeline RAG (Fase 4 da metodologia): recuperação (recuperacao.py) + geração via Ollama.

    python consulta.py

Caminho de cada pergunta (fase de consulta da Figura 1 da monografia):

  1. recuperacao.py busca os fragmentos (busca densa, BM25 ou híbrida,
     conforme MODO_BUSCA), aplica o limiar (SIMILARIDADE_MINIMA) e amplia
     cada fragmento com os vizinhos (JANELA_VIZINHOS); se nada passa no
     limiar, o sistema se abstém sem chamar o LLM (RF06);
  2. o LLM recebe as regras (prompt de sistema), os trechos numerados [1],
     [2]... e a pergunta, e responde citando os números dos trechos (RF04);
  3. o programa mostra as fontes citadas com documento, páginas e artigos
     (RF05). A lista de fontes é montada pelo programa a partir dos
     metadados, não pelo LLM, então não pode ser "alucinada".

A busca não conhece o LLM: este módulo recebe dela um Contexto pronto. A
classe AssistenteRAG não depende do terminal: a interface web/API prevista
para o TCC II pode reutilizá-la chamando `responder()`.

O modelo de linguagem é escolhido na hora (`AssistenteRAG(modelo_llm=...)`,
ou `python consulta.py qwen3.8:27b`); sem escolha, vale config.OLLAMA_MODEL.
As opções enviadas ao Ollama vêm do modelos.py, as mesmas para qualquer
modelo: só no processador (config.SO_PROCESSADOR) e, nos modelos com
raciocínio, com think=False.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime

import config
from modelos import argumentos_chat, campo, info_modelo, instalados, nome_completo, opcoes_geracao
# Os erros e as estruturas (Passagem, Trecho, Contexto) vêm da busca; ficam
# disponíveis também por aqui. ErroBaseVazia continua sendo um ErroChatbot.
from recuperacao import (Contexto, ErroBaseVazia, ErroBusca, ErroChatbot, Passagem,  # noqa: F401
                         Recuperador, Trecho)
from vetorial import ErroEmbeddings, ModeloEmbeddings


# ---------------------------------------------------------------------------
# Erros com mensagens para o usuário final
# ---------------------------------------------------------------------------
class ErroOllama(ErroChatbot):
    pass


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------
@dataclass
class Resposta:
    pergunta: str
    texto: str
    abstencao: bool
    motivo_abstencao: str | None            # "similaridade_baixa" ou "modelo"
    passagens: list[Passagem]
    citadas: list[int]                      # números [n] citados pelo LLM
    citacao_explicita: bool                 # o LLM citou os trechos?
    trechos_recuperados: list[Trecho]
    tempos: dict
    estatisticas_llm: dict = field(default_factory=dict)
    gerada_pelo_llm: bool = True
    mista: bool = False                     # cita trechos e também diz "não encontrei"
    # "resposta", "abstencao", "abstencao_com_acrescimo" (diz que não encontrou
    # e acrescenta algo sem citar), "mista" ou "vazia" (classificar_resposta)
    categoria: str = "resposta"
    contexto: Contexto | None = None        # o que a busca entregou (com a configuração dela)

    def fontes(self) -> list[Passagem]:
        """Passagens que sustentam a resposta (RF05)."""
        if self.abstencao:
            return []
        if self.citacao_explicita:
            return [p for p in self.passagens if p.numero in self.citadas]
        return self.passagens


# ---------------------------------------------------------------------------
# Prompt (guardrails, Seção 3.5 da monografia)
# ---------------------------------------------------------------------------
def prompt_sistema() -> str:
    return (
        "Você é o assistente acadêmico da Universidade Federal do Pampa (UNIPAMPA). Você responde "
        "dúvidas sobre documentos institucionais (normas, resoluções, projetos pedagógicos de curso "
        "e editais).\n\n"
        "Regras:\n"
        "1. Use SOMENTE as informações dos trechos numerados enviados junto com a pergunta. Não use "
        "conhecimento próprio e não faça suposições.\n"
        "2. Depois de cada informação, indique entre colchetes o número do trecho de onde ela veio, "
        "por exemplo [1] ou [2][3].\n"
        f"3. Se os trechos não trouxerem a resposta, responda apenas: \"{config.MENSAGEM_ABSTENCAO}\" "
        "Se trouxerem a resposta, mesmo que só em parte, não escreva essa frase: responda com o que "
        "os trechos informam e diga, em uma frase, o que não foi encontrado.\n"
        "4. Não invente regras, prazos, números, nomes ou procedimentos. Reproduza números e prazos "
        "exatamente como aparecem nos trechos.\n"
        "5. Se um trecho indicar que um dispositivo foi alterado ou revogado, considere apenas a "
        "redação em vigor.\n"
        "6. Se trechos de documentos diferentes trouxerem informações diferentes sobre o mesmo ponto "
        "(por exemplo, duas versões do PPC de um curso, ou uma norma e a portaria que a retifica), "
        "apresente cada uma e diga de qual documento ela vem.\n"
        "7. Responda em português do Brasil, de forma clara e objetiva. Use lista quando houver "
        "etapas ou itens."
    )


def mensagens_para(pergunta: str, passagens: list[Passagem]) -> list[dict]:
    """As duas mensagens enviadas ao modelo: as regras e a pergunta com os trechos."""
    return [{"role": "system", "content": prompt_sistema()},
            {"role": "user", "content": mensagem_usuario(pergunta, passagens)}]


def mensagem_usuario(pergunta: str, passagens: list[Passagem]) -> str:
    blocos = []
    for p in passagens:
        cabecalho = [f"Documento: {p.documento}", p.paginas]
        local = p.localizacao + (f" ({p.secao})" if p.secao else "")
        if local.strip():
            cabecalho.append(local.strip())
        if p.artigos:
            cabecalho.append(p.artigos)
        blocos.append(f"[{p.numero}] " + " | ".join(cabecalho) + "\n" + p.texto)
    return (
        "Trechos dos documentos institucionais:\n\n" + "\n\n".join(blocos)
        + f"\n\nPergunta: {pergunta}\n\n"
        "Responda usando apenas os trechos acima e cite os números entre colchetes. Se a resposta não "
        f"estiver nos trechos, responda apenas: \"{config.MENSAGEM_ABSTENCAO}\""
    )


# ---------------------------------------------------------------------------
# Pós-processamento da resposta
# ---------------------------------------------------------------------------
_RE_CITACAO = re.compile(r"\[\s*(\d+(?:\s*(?:,|;|e|-|–|a)\s*\d+)*)\s*\]")


def extrair_citacoes(texto: str, n_passagens: int) -> list[int]:
    """Números de trechos citados: "[1]", "[2][3]", "[1, 2]", "[1 e 3]" ou "[1-3]"."""
    citadas: list[int] = []
    for m in _RE_CITACAO.finditer(texto):
        numeros: list[int] = []
        for parte in re.split(r"\s*(?:,|;|\be\b)\s*", m.group(1)):
            limites = [int(n) for n in re.findall(r"\d+", parte)]
            if len(limites) == 2 and re.search(r"-|–|\ba\b", parte) and limites[0] <= limites[1] <= limites[0] + 20:
                numeros += list(range(limites[0], limites[1] + 1))      # intervalo: [1-3]
            else:
                numeros += limites
        for numero in numeros:
            if 1 <= numero <= n_passagens and numero not in citadas:
                citadas.append(numero)
    return citadas


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


# Frases que dizem que a informação não está nos trechos (comparadas sem acentos).
_RE_RECUSA = re.compile(
    r"nao encontrei|nao foi (?:possivel )?encontrad|nao (?:ha|existe|consta|constam|esta|estao)\b[^.]{0,60}"
    r"\b(?:informac|dado|mencao|referencia|trecho|documento)|"
    r"(?:trechos?|documentos?)(?: [a-z]+){0,3} nao (?:informa|traz|trazem|contem|menciona|apresenta|trata|tratam|"
    r"fala|falam|responde|respondem|especifica|especificam|indica|indicam|diz|dizem|informam|mencionam|"
    r"apresentam)|nao (?:e|foi) possivel (?:encontrar|responder|identificar|determinar|informar|localizar)|"
    r"nao (?:tenho|possuo|disponho)[^.]{0,30}informac|nenhuma informac|sem informac")
# Frases que só mandam procurar alguém (a segunda frase da mensagem de abstenção, por exemplo).
_RE_ENCAMINHAMENTO = re.compile(r"\b(?:procure|consulte|entre em contato|recomendo|sugiro|busque|dirija-se)\b"
                                r"[^.]{0,80}\b(?:coordenac|secretaria|setor|universidade|unipampa|campus|curso|"
                                r"orientador|professor|prograd|atendimento)")


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", texto) if f.strip()]


def _tem_conteudo(texto: str) -> bool:
    return bool(re.sub(r"[\W_]+", "", re.sub(r"\[[^\]]*\]", " ", texto)))


# A recusa na regra da versão 10 (comparada sem acentos). A forma geral de _RE_RECUSA também pega frases com
# informação ("Não há cobrança de taxa para a emissão do documento"), e por isso não serve para tirar uma resposta
# citada da nota. Aqui, a recusa precisa dizer do que não achou: a informação ("não encontrei essa informação") ou o
# material onde procurou ("não foi encontrada nos documentos disponíveis", "não foi mencionada nos trechos"). Sem isso,
# as mesmas palavras aparecem em frases com informação ("O discente que não foi encontrado na lista deve procurar a
# secretaria", "Não encontrei restrição para trancar a mesma disciplina mais de uma vez").
_RE_RECUSA_PESSOAL = re.compile(r"\bnao (?:encontrei|localizei|achei|(?:consegui|pude) (?:encontrar|localizar|identificar|"
                                r"achar))\b")
_RE_INFORMACAO_LOGO_DEPOIS = re.compile(r"(?:\s+(?:essa|esta|a|as|nenhuma|nenhum|qualquer|tal))?\s+(?:informac|resposta|"
                                        r"mencao|referencia|dados?\b)")
_RE_SEM_A_INFORMACAO = re.compile(r"\bnao (?:tenho|possuo|disponho) (?:de )?(?:essa |esta |nenhuma |qualquer )?informac")
_RE_RECUSA_IMPESSOAL = re.compile(
    r"\bnao foi (?:possivel )?encontrad\w*|\bnao (?:e|foi) possivel (?:encontrar|responder|identificar|determinar|"
    r"informar|localizar)\b|\bnenhuma informac\w*|\bsem informac\w*|\bnao (?:ha|existe|existem|consta|constam)\b"
    r"[^.]{0,40}?\b(?:informac|mencao|referencia)\w*|\bnao (?:consta|constam)\b|\bnao (?:esta|estao) (?:nos|nas|no|na|em)\b|"
    r"\bnao (?:e|foi|sao|foram|esta|estao) (?:\w+ )?(?:mencionad|especificad|informad|encontrad|citad|descrit|apresentad|"
    r"indicad|disponibilizad|abordad|tratad|disponive|present)\w*|\bnao pode ser respondid\w*")
# Os trechos como sujeito, no começo da frase: "Os trechos não informam...", "O documento fornecido não traz...".
_RE_RECUSA_DOS_TRECHOS = re.compile(
    r"^(?:(?:o|os|a|as|nos?|nas?|em)\s+)?(?:trechos?|documentos?|textos?|contextos?)\b(?: [a-z]+){0,3} nao "
    r"(?:informa|informam|traz|trazem|contem|menciona|mencionam|apresenta|apresentam|trata|tratam|aborda|abordam|fala|"
    r"falam|responde|respondem|especifica|especificam|indica|indicam|diz|dizem|cita|citam|faz mencao|fazem mencao)\b")
_RE_MATERIAL = re.compile(
    r"\b(?:nos|nas|no|na|em)\s+(?:\w+\s+){0,2}(?:trechos?\b|(?:documentos?|textos?|contextos?|informac\w*)\s+"
    r"(?:\w+\s+)?(?:fornecid|disponive|disponibilizad|enviad|apresentad|consultad|analisad|recebid)\w*)|"
    r"\bcom\s+(?:os|as)\s+trechos\b|\b(?:essa|esta|tal) (?:informac|pergunta|questao|duvida)")
# Abertura sem informação, seguida de vírgula ("Infelizmente, não encontrei..."; "Com base nos trechos fornecidos, não é
# possível responder"). Sai antes da conferência da frase, e o material citado nela não conta.
_RE_ABERTURA = re.compile(r"^\s*(?:infelizmente|desculpe|lamento|sinto muito|(?:com base|de acordo com|segundo|conforme)\s+"
                          r"(?:n?[oa]s?\s+)?(?:trechos|documentos|informações|informacoes|textos)(?:\s+\w+)?)\s*,\s*"
                          r"(?:mas\s+)?", re.IGNORECASE)
# Vírgula, dois-pontos, ponto e vírgula ou palavra que costuma juntar outra informação à recusa ("não encontrei a taxa,
# mas o prazo é..."). Procurada no texto com acentos, para o "e" não se confundir com o "é".
_RE_JUNCAO = re.compile(r"[,;:]|\b(?:e|mas|porém|contudo|entretanto|todavia|embora|apenas|somente|só|pois|porque|além|"
                        r"exceto|salvo|inclusive|também|já que|uma vez que|no entanto|ou seja)\b")
_RE_COLCHETES = re.compile(r"\[[^\[\]\n]{0,40}\]")
_RE_COLCHETES_JUNTOS = re.compile(r"\]\s*(?:,|;|\be\b)\s*\[")      # "[1] e [2]" e "[1], [2]" contam como uma citação
_MAXIMO_FRASE_DE_RECUSA = 200          # caracteres


def _recusa_clara(frase: str, frase_padrao: str = "") -> bool:
    """A frase (normalizada e sem as marcas de citação) diz claramente que a informação não está nos trechos."""
    if (frase_padrao and frase_padrao in frase) or _RE_SEM_A_INFORMACAO.search(frase) or _RE_RECUSA_DOS_TRECHOS.search(frase):
        return True
    if any(_RE_INFORMACAO_LOGO_DEPOIS.match(frase, m.end()) for m in _RE_RECUSA_PESSOAL.finditer(frase)):
        return True
    recusas = list(_RE_RECUSA_PESSOAL.finditer(frase)) + list(_RE_RECUSA_IMPESSOAL.finditer(frase))
    return any(_RE_MATERIAL.search(frase, m.start()) for m in recusas)


def _so_recusa_com_citacao_solta(texto: str, frase_padrao: str = "") -> bool:
    """O texto inteiro só diz que não encontrou a informação (e talvez mande procurar alguém), com citações soltas.

    É a regra da versão 10 (no teste de 03/11/2026, o Phi-4-mini escreveu
    "Não foi encontrada na informação fornecida quantas vezes você pode trancar
    a mesma disciplina. [1]"). Conservadora de propósito, porque uma resposta
    tomada por abstenção sai da nota de correção e, numa pergunta sem resposta
    nos documentos, deixa de contar como resposta sem base. As frases são
    separadas também nas quebras de linha (uma lista com uma nota no fim é
    resposta), e a marca que vem depois do ponto fica com a frase de antes.
    Cada frase, sem as marcas de citação, precisa:

    * ser curta e não ter número (prazo, valor e artigo são informação);
    * não ter vírgula, dois-pontos, ponto e vírgula nem palavra que junte
      outra informação ("e", "mas", "apenas", "pois"...), fora uma abertura
      sem informação ("Infelizmente,", "Com base nos trechos fornecidos,");
    * ser uma recusa clara (_recusa_clara) ou um encaminhamento sem citação
      própria ("Procure a coordenação do seu curso"; o encaminhamento que cita
      um trecho traz um procedimento, e é informação).

    Na dúvida, fica como resposta, que é como era antes desta regra.
    """
    frases: list[str] = []
    for pedaco in _frases(texto):
        if frases and not _tem_conteudo(pedaco):
            frases[-1] += " " + pedaco               # "...disciplina. [1]": a marca é da frase de antes
        else:
            frases.append(pedaco)
    alguma_recusa = False
    for original in frases:
        if not _tem_conteudo(original):
            continue
        original = _RE_COLCHETES_JUNTOS.sub("][", original)
        sem_marcas = _RE_ABERTURA.sub("", _RE_COLCHETES.sub(" ", original), count=1)
        frase = _normalizar(sem_marcas)
        if len(frase) > _MAXIMO_FRASE_DE_RECUSA or re.search(r"\d", frase) or _RE_JUNCAO.search(sem_marcas.lower()):
            return False
        if _recusa_clara(frase, frase_padrao):
            alguma_recusa = True
        elif not (_RE_ENCAMINHAMENTO.search(frase) and not _RE_COLCHETES.search(original)):
            return False                         # nem recusa nem encaminhamento sem citação: é informação
    return alguma_recusa


def classificar_resposta(texto: str, n_passagens: int) -> str:
    """O que o modelo fez: "resposta", "abstencao", "abstencao_com_acrescimo", "mista" ou "vazia".

    * abstencao: só diz que não encontrou a informação (a frase padrão ou outra
      equivalente) e, no máximo, manda procurar a coordenação. Uma citação
      solta ao lado da recusa não muda nada: desde a versão 10, vale também
      para a recusa com outras palavras ("Não foi encontrada na informação
      fornecida quantas vezes... [1]"), que antes contava como resposta;
    * abstencao_com_acrescimo: diz que não encontrou, mas acrescenta outra
      informação sem citar trecho nenhum ("Não encontrei... Em geral, o
      cardápio custa R$ 3,00"). Numa pergunta que os documentos não
      respondem, é uma resposta sem base, e não uma abstenção;
    * mista: cita trechos e também traz a frase padrão de abstenção;
    * resposta: o resto, inclusive a resposta parcial que cita trechos e diz o
      que não achou ("o prazo é de 5 dias [1]; não encontrei o valor da taxa").

    A classificação é automática: a tabela de confiabilidade lista os casos
    duvidosos (revisar.csv) para conferência à mão.
    """
    if not texto.strip():
        return "vazia"
    normal = _normalizar(texto)
    frases_padrao = [f.strip() for f in _normalizar(config.MENSAGEM_ABSTENCAO).split(".") if f.strip()]
    tem_padrao = bool(frases_padrao) and frases_padrao[0] in normal
    resto = normal
    for frase in frases_padrao:
        resto = resto.replace(frase, " ")
    if tem_padrao and not _tem_conteudo(resto):
        return "abstencao"                       # só a frase padrão (com ou sem uma citação solta)
    if extrair_citacoes(texto, n_passagens):
        if _so_recusa_com_citacao_solta(texto, frases_padrao[0] if frases_padrao else ""):
            return "abstencao"                   # só a recusa, com outras palavras e uma citação solta (versão 10)
        return "mista" if tem_padrao else "resposta"
    frases = _frases(normal)
    recusas = [f for f in frases if _RE_RECUSA.search(f) or (frases_padrao and frases_padrao[0] in f)]
    if not recusas:
        return "resposta"
    sobra = [f for f in frases if f not in recusas and not _RE_ENCAMINHAMENTO.search(f) and _tem_conteudo(f)]
    return "abstencao_com_acrescimo" if sobra else "abstencao"


def eh_abstencao(texto: str, citadas: list[int] | None = None) -> bool:
    """A resposta é uma abstenção (RF06)? Ver classificar_resposta."""
    return classificar_resposta(texto, 99) == "abstencao"


def eh_resposta_mista(texto: str, citadas: list[int]) -> bool:
    """A resposta cita trechos e também traz a frase de abstenção (RF06)?

    Ex. (registro de 21/09/2026): o modelo deu as 120 h do PPC 2019 e as
    75 h do PPC 2023, citando os trechos, e terminou com "Não encontrei essa
    informação nos documentos disponíveis...". Não é abstenção (há resposta
    citada), mas se contradiz. A resposta já apareceu na tela durante a
    geração, então não é cortada: fica marcada no registro e o chat avisa.
    """
    if not citadas:
        return False
    frase = _normalizar(config.MENSAGEM_ABSTENCAO).split(".")[0]
    return frase in _normalizar(texto)


_RE_RACIOCINIO = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)


def separar_raciocinio(texto: str) -> tuple[str, str]:
    """Tira da resposta um raciocínio escrito no próprio texto ("<think>...</think>"),
    que alguns modelos produzem mesmo com think=False. Devolve (resposta, raciocínio)."""
    pedacos = _RE_RACIOCINIO.findall(texto)
    if not pedacos:
        return texto, ""
    return _RE_RACIOCINIO.sub("", texto).strip(), "".join(pedacos)


_campo = campo   # nome usado nas versões anteriores


# ---------------------------------------------------------------------------
# Assistente
# ---------------------------------------------------------------------------
class AssistenteRAG:
    """Recuperação (Recuperador) + geração (Ollama). Recursos pesados são carregados sob demanda."""

    def __init__(self, modelo: ModeloEmbeddings | None = None, colecao=None, cliente_llm=None,
                 titulos: dict[str, str] | None = None, recuperador: Recuperador | None = None,
                 modelo_llm: str | None = None) -> None:
        self.recuperador = recuperador or Recuperador(modelo=modelo, colecao=colecao, titulos=titulos)
        self._cliente = cliente_llm
        self._modelo_llm = modelo_llm

    @property
    def modelo_llm(self) -> str:
        """Modelo de linguagem deste assistente (padrão: config.OLLAMA_MODEL)."""
        return self._modelo_llm or config.OLLAMA_MODEL

    # --- recursos -----------------------------------------------------------
    @property
    def modelo(self):
        return self.recuperador.modelo

    @modelo.setter
    def modelo(self, valor) -> None:
        self.recuperador.modelo = valor

    @property
    def colecao(self):
        return self.recuperador.colecao

    @property
    def titulos(self) -> dict[str, str]:
        return self.recuperador.titulos

    @titulos.setter
    def titulos(self, valor: dict[str, str]) -> None:
        self.recuperador.titulos = valor

    @property
    def cliente(self):
        if self._cliente is None:
            import ollama
            self._cliente = ollama.Client(host=config.OLLAMA_HOST,
                                          timeout=info_modelo(self.modelo_llm)["tempo_limite"])
        return self._cliente

    # --- verificações de inicialização -------------------------------------
    def verificar_base(self) -> list[str]:
        """Confere se a base foi indexada com os parâmetros atuais."""
        return self.recuperador.verificar_base()

    def verificar_ollama(self) -> None:
        """Confere se o Ollama responde e se o modelo gerador está instalado."""
        try:
            resposta = self.cliente.list()
        except Exception as erro:
            raise ErroOllama(self._mensagem_conexao(erro)) from erro
        nomes = instalados(resposta)
        if nome_completo(self.modelo_llm) not in nomes:
            lista = ", ".join(sorted(nomes)) or "nenhum"
            raise ErroOllama(f"O modelo '{self.modelo_llm}' não está instalado no Ollama "
                             f"(instalados: {lista}). Rode: ollama pull {self.modelo_llm}")

    def aquecer(self) -> None:
        """Carrega o LLM na memória antes da primeira pergunta.

        Sem isso, o tempo de carga (vários segundos) cairia na primeira
        resposta e distorceria a medição do tempo de resposta. A carga usa as
        mesmas opções da geração: com outro num_gpu ou outra janela de
        contexto, o Ollama carregaria o modelo de novo na primeira pergunta.
        """
        try:
            self.cliente.chat(model=self.modelo_llm, messages=[], options=opcoes_geracao(),
                              keep_alive=config.OLLAMA_KEEP_ALIVE)
        except Exception:
            pass   # opcional: se falhar, o modelo carrega na primeira pergunta

    def descarregar(self) -> None:
        """Tira o modelo da memória (as rodadas fazem isso antes de passar ao próximo modelo)."""
        try:
            self.cliente.chat(model=self.modelo_llm, messages=[], keep_alive=0)
        except Exception:
            pass

    def _mensagem_conexao(self, erro: Exception) -> str:
        endereco = config.OLLAMA_HOST or "http://127.0.0.1:11434"
        return (f"Não foi possível conectar ao Ollama em {endereco}. Verifique se o Ollama está aberto "
                f"(ícone na bandeja do Windows) ou rode 'ollama serve' em outro terminal. Detalhe: {erro}")

    # Geração
    def gerar(self, mensagens: list[dict], ao_receber=None) -> tuple[str, dict]:
        """Etapa de Generation: envia as mensagens ao Ollama e devolve o texto.

        `ao_receber(pedaco)` é chamado a cada pedaço de texto recebido
        (streaming), para a resposta aparecer enquanto é gerada.
        """
        import httpx
        import ollama

        opcoes = opcoes_geracao()
        partes: list[str] = []
        raciocinio: list[str] = []
        estatisticas: dict = {}
        inicio = time.perf_counter()
        try:
            fluxo = self.cliente.chat(model=self.modelo_llm, messages=mensagens, options=opcoes,
                                      stream=True, keep_alive=config.OLLAMA_KEEP_ALIVE,
                                      **argumentos_chat(self.modelo_llm))
            for parte in fluxo:
                mensagem = _campo(parte, "message", {})
                pensado = _campo(mensagem, "thinking", "") or ""
                if pensado:
                    raciocinio.append(pensado)
                conteudo = _campo(mensagem, "content", "") or ""
                if conteudo:
                    if not partes:
                        estatisticas["primeiro_token_s"] = round(time.perf_counter() - inicio, 3)
                    partes.append(conteudo)
                    if ao_receber:
                        ao_receber(conteudo)
                if _campo(parte, "done", False):
                    estatisticas["motivo_fim"] = _campo(parte, "done_reason", None)   # "length" = cortada
                    for chave in ("prompt_eval_count", "eval_count"):
                        estatisticas[chave] = _campo(parte, chave, 0)
                    for chave in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
                        estatisticas[chave.replace("duration", "s")] = round(_campo(parte, chave, 0) / 1e9, 3)
        except ollama.ResponseError as erro:
            if getattr(erro, "status_code", None) == 404:
                raise ErroOllama(f"O modelo '{self.modelo_llm}' não está instalado no Ollama. "
                                 f"Rode: ollama pull {self.modelo_llm}") from erro
            raise ErroOllama(f"O Ollama recusou a requisição: {erro}") from erro
        except httpx.TimeoutException as erro:
            limite = info_modelo(self.modelo_llm)["tempo_limite"]
            raise ErroOllama(f"O Ollama não respondeu em {limite} s (tempo_limite do modelo em "
                             "MODELOS, ou OLLAMA_TIMEOUT, no config.py).") from erro
        except (ConnectionError, httpx.TransportError) as erro:
            raise ErroOllama(self._mensagem_conexao(erro)) from erro
        texto, no_texto = separar_raciocinio("".join(partes))
        if raciocinio or no_texto:
            # think=False não bastou (ou o modelo não está marcado com raciocínio em MODELOS)
            estatisticas["raciocinio_caracteres"] = len("".join(raciocinio)) + len(no_texto)
        if estatisticas.get("motivo_fim") == "length":
            estatisticas["aviso"] = "a resposta foi cortada no limite de tokens (OLLAMA_NUM_PREDICT)"
        if estatisticas.get("prompt_eval_count", 0) >= config.OLLAMA_NUM_CTX:
            estatisticas["aviso"] = "o prompt ocupou toda a janela de contexto (OLLAMA_NUM_CTX)"
        return texto.strip(), estatisticas

    # --- pipeline completo ----------------------------------------------------
    def responder(self, pergunta: str, ao_receber=None) -> Resposta:
        """Caminho do chat: busca os trechos e gera a resposta."""
        contexto = self.recuperador.recuperar(pergunta)
        return self.responder_com_contexto(contexto, ao_receber)

    def responder_com_contexto(self, contexto: Contexto, ao_receber=None, registrar: bool = True) -> Resposta:
        """Gera a resposta a partir de um Contexto pronto.

        O chat chama com o contexto que acabou de buscar; as rodadas de
        avaliação, com o contexto congelado da pergunta (o mesmo para todos os
        modelos) e sem gravar no registro do chat. É o mesmo código nos dois
        casos, então o que a avaliação mede é o que o chat faz.
        """
        t0 = time.perf_counter()
        pergunta = contexto.pergunta
        if contexto.abstencao_previa:
            # RF06 de forma determinística: nada parecido na base, nem chama o LLM
            resposta = Resposta(pergunta, config.MENSAGEM_ABSTENCAO, True, "similaridade_baixa", [], [],
                                False, contexto.recuperados,
                                {"recuperacao_s": contexto.tempo_s,
                                 "total_s": round(contexto.tempo_s + time.perf_counter() - t0, 3)},
                                gerada_pelo_llm=False, contexto=contexto, categoria="abstencao")
            if registrar:
                self.registrar(resposta)
            return resposta

        passagens = contexto.passagens
        mensagens = mensagens_para(pergunta, passagens)
        texto, estatisticas = self.gerar(mensagens, ao_receber)
        geracao = time.perf_counter() - t0
        citadas = extrair_citacoes(texto, len(passagens))
        categoria = classificar_resposta(texto, len(passagens))
        abstencao = categoria in ("abstencao", "vazia")
        resposta = Resposta(
            pergunta, texto, abstencao, "modelo" if abstencao else None, passagens, citadas,
            bool(citadas), contexto.recuperados,
            {"recuperacao_s": contexto.tempo_s,
             "primeiro_token_s": estatisticas.get("primeiro_token_s"),
             "geracao_s": round(geracao, 3),
             "total_s": round(contexto.tempo_s + geracao, 3)},
            estatisticas, mista=categoria == "mista", contexto=contexto, categoria=categoria)
        if registrar:
            self.registrar(resposta)
        return resposta

    # --- registro (instrumentação para a avaliação) -------------------------
    def registrar(self, resposta: Resposta) -> None:
        """Acrescenta a interação em data/registros/interacoes.jsonl.

        Guarda o que a avaliação precisa: pergunta, contextos entregues ao LLM,
        resposta, abstenção e tempos (Seção 2.2.2: tempo médio de resposta e
        taxa de abstenção; o formato serve de entrada para o RAGAS).
        """
        if not config.REGISTRAR_INTERACOES:
            return
        busca = resposta.contexto.configuracao if resposta.contexto else {}
        registro = {
            "data_hora": datetime.now().isoformat(timespec="seconds"),
            "pergunta": resposta.pergunta,
            "resposta": resposta.texto,
            "abstencao": resposta.abstencao,
            "motivo_abstencao": resposta.motivo_abstencao,
            "resposta_mista": resposta.mista,
            "citadas": resposta.citadas,
            "recuperados": [{"id": t.id, "similaridade": round(t.similaridade, 4),
                             "posicao_densa": t.posicao_densa, "posicao_bm25": t.posicao_bm25}
                            for t in resposta.trechos_recuperados],
            "passagens": [asdict(p) for p in resposta.passagens],
            "tempos": resposta.tempos,
            "estatisticas_llm": resposta.estatisticas_llm,
            "configuracao": {
                "modelo_llm": self.modelo_llm, "temperatura": config.TEMPERATURA,
                "num_ctx": config.OLLAMA_NUM_CTX, "seed": config.OLLAMA_SEED,
                "so_processador": config.SO_PROCESSADOR,
                "raciocinio_desligado": bool(argumentos_chat(self.modelo_llm)),
                "versao_chatbot": config.VERSAO_CHATBOT, **busca,
            },
        }
        try:
            config.REGISTROS_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.REGISTROS_DIR / "interacoes.jsonl", "a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass   # o registro nunca pode derrubar o atendimento


# ---------------------------------------------------------------------------
# Interface de linha de comando
# ---------------------------------------------------------------------------
AJUDA = ("Comandos:\n"
         "  /fontes   mostra os trechos usados na última resposta\n"
         "  /ajuda    mostra estes comandos\n"
         "  sair      encerra o chat")

_NOMES_BUSCA = {"densa": "densa (por sentido)", "bm25": "BM25 (por palavras)",
                "hibrida": "híbrida (por sentido e por palavras)"}


def _decimal(valor: float, casas: int = 2) -> str:
    """Número com vírgula decimal, como se escreve em português."""
    return f"{valor:.{casas}f}".replace(".", ",")


def imprimir_fontes(resposta: Resposta) -> None:
    fontes = resposta.fontes()
    if not fontes:
        return
    titulo = "Fontes citadas" if resposta.citacao_explicita else "Trechos consultados"
    print(f"\n{titulo}:")
    for p in fontes:
        print(f"  [{p.numero}] {p.referencia()} (similaridade {_decimal(p.similaridade)})")


def imprimir_trechos(resposta: Resposta | None) -> None:
    if resposta is None:
        print("Nenhuma pergunta feita ainda.")
        return
    if not resposta.passagens:
        print("Nenhum trecho atingiu a similaridade mínima. Mais próximos encontrados:")
        for t in resposta.trechos_recuperados[:config.TOP_K]:
            print(f"  - {t.fonte}, p. {t.metadados.get('pagina')} (similaridade {_decimal(t.similaridade)})")
        return
    for p in resposta.passagens:
        print(f"\n[{p.numero}] {p.referencia()} (similaridade {_decimal(p.similaridade)})")
        print(p.texto)


def main(argv: list[str] | None = None) -> int:
    """`python consulta.py [modelo]`: sem modelo, usa config.OLLAMA_MODEL."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print("Chatbot acadêmico (protótipo com RAG local)")
    print("Responde com base nos documentos institucionais indexados, com os modelos rodando neste computador.\n")
    print("Preparando o assistente...")
    assistente = AssistenteRAG(modelo_llm=argv[0] if argv else None)
    info = info_modelo(assistente.modelo_llm)
    try:
        modo = Recuperador.modo_valido()
        _ = assistente.colecao
        print(f"  Modelo de embeddings: {assistente.modelo.nome}")
        for aviso in assistente.verificar_base():
            print(f"  Aviso: {aviso}")
        print(f"  Busca: {_NOMES_BUSCA[modo]}")
        if modo != "densa":
            print("  Montando o índice da busca por palavras...")
            assistente.recuperador.preparar(modo)
        detalhes = ["só no processador" if config.SO_PROCESSADOR else "no processador e na placa de vídeo"]
        if info["raciocinio"]:
            detalhes.append("raciocínio desligado")
        print(f"  Modelo de linguagem: {info['rotulo']} ({assistente.modelo_llm}), {', '.join(detalhes)}")
        print("  Conferindo o Ollama...")
        assistente.verificar_ollama()
        print("  Carregando o modelo de linguagem, o que pode levar alguns segundos...")
        assistente.aquecer()
    except (ErroChatbot, ErroEmbeddings) as erro:
        print(f"\nErro: {erro}")
        return 1

    print(f"\nPronto! Digite sua pergunta e tecle Enter.\n{AJUDA}")
    ultima: Resposta | None = None
    while True:
        try:
            pergunta = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pergunta:
            continue
        comando = pergunta.lower()
        if comando in {"sair", "exit", "quit", "/sair"}:
            break
        if comando == "/ajuda":
            print(AJUDA)
            continue
        if comando == "/fontes":
            imprimir_trechos(ultima)
            continue

        print("\nAssistente: ", end="", flush=True)
        try:
            resposta = assistente.responder(pergunta, ao_receber=lambda t: print(t, end="", flush=True))
        except KeyboardInterrupt:
            print("\nResposta interrompida.")
            continue
        except ErroChatbot as erro:
            print(f"\nErro: {erro}")
            continue
        if not resposta.gerada_pelo_llm:
            print(resposta.texto, end="")
        print()
        if resposta.mista:
            print("\nAtenção: a resposta cita trechos dos documentos, mas também diz que não encontrou a "
                  "informação. Confira as fontes abaixo ou digite /fontes.")
        imprimir_fontes(resposta)
        print(f"Tempo de resposta: {_decimal(resposta.tempos['total_s'], 1)} s")
        ultima = resposta
    return 0


if __name__ == "__main__":
    sys.exit(main())
