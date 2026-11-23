"""Confere os modelos de linguagem antes das rodadas (verificar-modelos.bat).

    python verificar_modelos.py                 # os comparados e os juízes
    python verificar_modelos.py qwen3.8:27b     # só os modelos indicados

Para cada modelo de config.MODELOS_COMPARACAO e para cada juiz (config.JUIZES):

1. está instalado no Ollama?
2. responde a uma pergunta curta? Mede o tempo de carga e a velocidade de
   escrita (tokens por segundo), com as mesmas opções das rodadas;
3. rodou onde? Os comparados precisam rodar só no processador (num_gpu = 0,
   config.SO_PROCESSADOR); os juízes, na placa de vídeo;
4. o raciocínio ficou desligado nos modelos marcados com "raciocinio"?

No fim, confere a regra da versão 09: nenhum modelo da avaliação (comparado
ou juiz) repete a família de outro (campo "familia" de config.MODELOS).

Cada modelo é descarregado da memória depois do teste, para o próximo caber
(o Qwen de 27B ocupa cerca de 20 GB). Termina com 1 se algum modelo tiver
erro, para o problema não passar despercebido antes de uma rodada de horas.
"""
from __future__ import annotations

import sys
import time

import config
from modelos import (argumentos_chat, campo, familia, info_modelo, instalados, juiz as opcoes_do_juiz, juizes,
                     nome_completo, onde_rodou, opcoes_geracao, problemas_de_familia, sem_familia)

PERGUNTA_TESTE = "Responda apenas: ok"


def _cliente(tempo_limite: float):
    import ollama
    return ollama.Client(host=config.OLLAMA_HOST, timeout=tempo_limite)


def versao_ollama(cliente) -> str:
    try:
        return cliente._client.get("/api/version").json().get("version", "desconhecida")
    except Exception:
        return "desconhecida"


def papeis() -> list[tuple[str, str]]:
    """(modelo, papel) na ordem da conferência; os juízes por último."""
    return [(m, "comparado") for m in config.MODELOS_COMPARACAO] + [(j["modelo"], "juiz") for j in juizes()]


def verificar_modelo(cliente, nome: str, papel: str, nomes_instalados: set[str]) -> dict:
    info = info_modelo(nome)
    juiz = papel == "juiz"
    na_placa = bool(juiz and opcoes_do_juiz(nome).get("placa_de_video"))
    resultado = {"modelo": nome, "rotulo": info["rotulo"], "papel": papel, "instalado": False,
                 "local": None, "fracao_na_placa": None, "raciocinio": None, "tokens_por_s": None,
                 "carga_s": None, "erros": [], "avisos": []}
    if nome_completo(nome) not in nomes_instalados:
        resultado["erros"].append(f"não está instalado; rode: ollama pull {nome}")
        return resultado
    resultado["instalado"] = True
    opcoes = opcoes_geracao(so_processador=False if na_placa else None)
    argumentos = argumentos_chat(nome)          # o juiz que raciocina também recebe think=False, como na avaliação
    inicio = time.perf_counter()
    try:
        resposta = cliente.chat(model=nome, messages=[{"role": "user", "content": PERGUNTA_TESTE}],
                                options=opcoes, stream=False, keep_alive="5m", **argumentos)
    except Exception as erro:
        resultado["erros"].append(f"não respondeu: {erro}")
        return resultado
    resultado["segundos"] = round(time.perf_counter() - inicio, 1)
    mensagem = campo(resposta, "message", {})
    texto = (campo(mensagem, "content", "") or "").strip()
    pensado = (campo(mensagem, "thinking", "") or "").strip()
    if "<think>" in texto.lower():               # raciocínio escrito no próprio texto da resposta
        pensado = pensado or texto
    resultado["resposta"] = texto[:80]
    resultado["raciocinio"] = bool(pensado)
    gerados, duracao = campo(resposta, "eval_count", 0) or 0, campo(resposta, "eval_duration", 0) or 0
    if gerados and duracao:
        resultado["tokens_por_s"] = round(gerados / (duracao / 1e9), 1)
    resultado["carga_s"] = round((campo(resposta, "load_duration", 0) or 0) / 1e9, 1)
    try:
        local = onde_rodou(cliente.ps(), nome)
    except Exception:
        local = None
    if local:
        resultado["local"], resultado["fracao_na_placa"] = local["local"], local["fracao_na_placa"]
    if not texto:
        resultado["avisos"].append("a resposta veio vazia")
    if pensado and info["raciocinio"]:
        resultado["avisos"].append("raciocinou mesmo com think=False: as respostas ficam mais lentas e o "
                                   "tempo não fica comparável com o dos outros")
    elif pensado:
        resultado["avisos"].append("raciocinou antes de responder; marque \"raciocinio\": True para ele em "
                                   "MODELOS, no config.py")
    if local is None:
        resultado["avisos"].append("o Ollama não informou onde o modelo rodou (ollama ps)")
    elif juiz:
        if na_placa and local["local"] == "processador":
            resultado["avisos"].append("o juiz rodou no processador: a placa de vídeo não foi usada. "
                                       "Atualize o Ollama (a RX 6600 é usada pelo Vulkan) e confira "
                                       "com: ollama ps")
        elif na_placa and local["local"] == "dividido":
            resultado["avisos"].append(f"só {round(100 * local['fracao_na_placa'])}% do juiz coube na "
                                       "placa de vídeo; o resto rodou no processador, mais devagar")
    elif config.SO_PROCESSADOR and local["local"] != "processador":
        resultado["erros"].append(f"rodou com {round(100 * local['fracao_na_placa'])}% na placa de vídeo, "
                                  "mas os modelos comparados precisam rodar só no processador")
    try:
        cliente.chat(model=nome, messages=[], keep_alive=0)      # libera a memória para o próximo
    except Exception:
        pass
    return resultado


def _decimal(valor, casas: int = 1, unidade: str = "") -> str:
    if valor is None:
        return "-"
    return f"{valor:.{casas}f}".replace(".", ",") + unidade


def imprimir(resultados: list[dict], versao: str) -> None:
    endereco = config.OLLAMA_HOST or "http://127.0.0.1:11434"
    print(f"Ollama {versao} em {endereco}\n")
    print(f"{'Modelo':<16} {'Papel':<10} {'Instalado':<10} {'Rodou em':<16} {'Raciocinou':<11} "
          f"{'Escrita':>14} {'Carga':>8}")
    for r in resultados:
        local = r["local"] or "-"
        if r["local"] == "dividido":
            local = f"dividido ({round(100 * r['fracao_na_placa'])}%)"
        raciocinio = "-" if r["raciocinio"] is None else ("sim" if r["raciocinio"] else "não")
        print(f"{r['rotulo'][:16]:<16} {r['papel']:<10} {'sim' if r['instalado'] else 'NÃO':<10} {local:<16} "
              f"{raciocinio:<11} {_decimal(r['tokens_por_s'], 1, ' tokens/s'):>14} "
              f"{_decimal(r['carga_s'], 1, ' s'):>8}")
    problemas = [(r, "ERRO", m) for r in resultados for m in r["erros"]]
    problemas += [(r, "AVISO", m) for r in resultados for m in r["avisos"]]
    if problemas:
        print()
        for r, tipo, mensagem in problemas:
            print(f"{tipo}: {r['rotulo']} ({r['modelo']}): {mensagem}")
    else:
        print("\nTudo certo: os comparados rodam só no processador"
              + (" e os juízes na placa de vídeo." if any(r["papel"] == "juiz" for r in resultados) else "."))
    imprimir_familias()


def conferir_familias() -> tuple[list[str], list[str]]:
    """(problemas, avisos) da regra de famílias, para os modelos do config."""
    nomes_juizes = [j["modelo"] for j in juizes()]
    problemas = problemas_de_familia(list(config.MODELOS_COMPARACAO), nomes_juizes)
    avisos = [f"{info_modelo(m)['rotulo']} ({m}) não tem \"familia\" em MODELOS, no config.py; a regra não foi "
              "conferida para ele" for m in sem_familia(list(config.MODELOS_COMPARACAO) + nomes_juizes)]
    return problemas, avisos


def imprimir_familias() -> None:
    problemas, avisos = conferir_familias()
    nomes = list(dict.fromkeys(list(config.MODELOS_COMPARACAO) + [j["modelo"] for j in juizes()]))
    print("\nFamílias: " + "; ".join(f"{info_modelo(m)['rotulo']}: {familia(m) or '?'}" for m in nomes))
    for mensagem in problemas:
        print(f"ERRO: {mensagem}. Nenhum modelo da avaliação pode repetir a família de outro.")
    for mensagem in avisos:
        print(f"AVISO: {mensagem}")
    if not problemas and not avisos:
        print("Nenhuma família se repete entre os comparados e os juízes.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    lista = papeis()
    if argv:
        lista = [(m, p) for m, p in lista if m in argv] + [(m, "comparado") for m in argv
                                                           if m not in {n for n, _ in lista}]
    maior_espera = max(info_modelo(m)["tempo_limite"] for m, _ in lista) if lista else config.OLLAMA_TIMEOUT
    cliente = _cliente(maior_espera)
    try:
        nomes = instalados(cliente.list())
    except Exception as erro:
        endereco = config.OLLAMA_HOST or "http://127.0.0.1:11434"
        print(f"ERRO: não foi possível conectar ao Ollama em {endereco}. Abra o Ollama (ícone na bandeja "
              f"do Windows) e rode de novo. Detalhe: {erro}")
        return 1
    versao = versao_ollama(cliente)
    resultados = []
    for nome, papel in lista:
        print(f"Testando {info_modelo(nome)['rotulo']} ({nome}, {papel})...", flush=True)
        resultados.append(verificar_modelo(cliente, nome, papel, nomes))
    print()
    imprimir(resultados, versao)
    return 1 if any(r["erros"] for r in resultados) or conferir_familias()[0] else 0


if __name__ == "__main__":
    sys.exit(main())
