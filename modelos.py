"""Modelos de linguagem: as opções de cada um e o que se envia ao Ollama.

O chat (consulta.py), a conferência dos modelos (verificar_modelos.py) e as
rodadas de avaliação usam estas mesmas funções, então todo modelo recebe
exatamente as mesmas opções de geração (temperatura, janela de contexto,
semente) e só o modelo muda entre um teste e outro.

* info_modelo: rótulo, família, raciocínio e tempo limite do modelo
  (config.MODELOS);
* juizes e problemas_de_familia: os juízes da avaliação (config.JUIZES) e a
  regra de que nenhum modelo da avaliação repete a família de outro;
* opcoes_geracao: as opções do Ollama (temperatura, janela, semente, limite
  de tokens e amostragem, todas fixadas); com config.SO_PROCESSADOR, inclui
  num_gpu = 0, que faz o Ollama rodar o modelo inteiro no processador;
* argumentos_chat: think=False para os modelos com raciocínio (o Qwen 3.8),
  que passam a responder direto, sem a etapa de "pensar" antes;
* onde_rodou: lê o que o Ollama informa (ollama ps) e diz se o modelo está no
  processador, na placa de vídeo ou dividido entre os dois.

Não importa nada pesado (nem o Ollama, nem a base vetorial).
"""
from __future__ import annotations

from itertools import combinations

import config


def info_modelo(nome: str) -> dict:
    """Opções do modelo em config.MODELOS; um modelo fora da lista recebe os padrões."""
    padrao = {"rotulo": nome, "raciocinio": False, "tempo_limite": config.OLLAMA_TIMEOUT}
    return {**padrao, **config.MODELOS.get(nome, {})}


def rotulo(nome: str) -> str:
    return info_modelo(nome)["rotulo"]


def familia(nome: str) -> str | None:
    """Família do modelo (config.MODELOS), ou None se não estiver marcada."""
    return info_modelo(nome).get("familia")


def juizes() -> list[dict]:
    """Os juízes da avaliação (config.JUIZES), na ordem em que avaliam.

    Aceita também o JUIZ das versões 06 a 08, que era um só.
    """
    lista = getattr(config, "JUIZES", None)
    if lista is None:
        antigo = getattr(config, "JUIZ", None)
        lista = [antigo] if antigo else []
    return [dict(j) for j in lista if j and j.get("modelo")]


def juiz(nome: str) -> dict:
    """As opções de um juiz pelo nome; um modelo fora de config.JUIZES usa a placa de vídeo."""
    return next((j for j in juizes() if j["modelo"] == nome), {"modelo": nome, "placa_de_video": True})


def problemas_de_familia(comparados: list[str], lista_juizes: list[str]) -> list[str]:
    """Modelos da avaliação que repetem a família de outro (regra da versão 09).

    Um juiz tende a favorecer respostas da própria família, e dois comparados
    da mesma família não representam linhas de modelos diferentes. Devolve uma
    frase por problema (vazia, se estiver tudo certo). Modelo sem família
    marcada não entra aqui: ver sem_familia.
    """
    papeis = [(m, "comparado") for m in comparados] + [(j, "juiz") for j in lista_juizes]
    problemas = []
    for (a, papel_a), (b, papel_b) in combinations(papeis, 2):
        if a == b:
            problemas.append(f"{rotulo(a)} ({a}) aparece como {papel_a} e como {papel_b}")
        elif familia(a) and familia(a) == familia(b):
            problemas.append(f"{rotulo(a)} ({papel_a}) e {rotulo(b)} ({papel_b}) são da mesma família: {familia(a)}")
    return problemas


def sem_familia(nomes: list[str]) -> list[str]:
    """Modelos sem "familia" em config.MODELOS (a regra não pode ser conferida para eles)."""
    return [n for n in dict.fromkeys(nomes) if not familia(n)]


def opcoes_geracao(so_processador: bool | None = None) -> dict:
    """Opções de geração, iguais para todos os modelos.

    `so_processador`: None segue config.SO_PROCESSADOR. O juiz da avaliação
    passa False para usar a placa de vídeo.
    """
    opcoes = {"temperature": config.TEMPERATURA, "num_ctx": config.OLLAMA_NUM_CTX,
              "num_predict": config.OLLAMA_NUM_PREDICT, **config.AMOSTRAGEM}
    if config.OLLAMA_SEED is not None:
        opcoes["seed"] = config.OLLAMA_SEED
    if config.SO_PROCESSADOR if so_processador is None else so_processador:
        opcoes["num_gpu"] = 0          # nenhuma camada do modelo na placa de vídeo
    return opcoes


def argumentos_chat(nome: str) -> dict:
    """Argumentos extras do chat do Ollama: think=False só para modelos com raciocínio.

    Os outros não recebem nada: assim o pedido deles fica igual ao das versões
    anteriores, e um Ollama antigo, que não conhece o think, continua aceitando.
    """
    return {"think": False} if info_modelo(nome)["raciocinio"] else {}


def nome_completo(nome: str) -> str:
    """Nome como o Ollama lista ("llama3.2" vira "llama3.2:latest")."""
    return nome if ":" in nome else nome + ":latest"


def campo(objeto, nome: str, padrao=None):
    """Lê um campo de uma resposta do Ollama (objeto ou dicionário)."""
    if isinstance(objeto, dict):
        return objeto.get(nome, padrao)
    valor = getattr(objeto, nome, padrao)
    return padrao if valor is None else valor


def instalados(resposta_list) -> set[str]:
    """Nomes dos modelos instalados, a partir de cliente.list()."""
    return {campo(m, "model", "") or campo(m, "name", "") for m in campo(resposta_list, "models", [])}


def onde_rodou(resposta_ps, nome: str) -> dict | None:
    """Onde o modelo carregado está, a partir de cliente.ps() (o "ollama ps").

    Devolve {"local": "processador" | "placa de vídeo" | "dividido",
    "fracao_na_placa": 0 a 1, "tamanho_gb": ...} ou None se o modelo não
    estiver carregado.
    """
    alvo = nome_completo(nome)
    for m in campo(resposta_ps, "models", []):
        if (campo(m, "model", "") or campo(m, "name", "")) != alvo:
            continue
        tamanho = int(campo(m, "size", 0) or 0)
        na_placa = int(campo(m, "size_vram", 0) or 0)
        fracao = na_placa / tamanho if tamanho else 0.0
        if na_placa == 0:
            local = "processador"
        elif fracao >= 0.999:
            local = "placa de vídeo"
        else:
            local = "dividido"
        return {"local": local, "fracao_na_placa": round(fracao, 3), "tamanho_gb": round(tamanho / 1e9, 1)}
    return None
