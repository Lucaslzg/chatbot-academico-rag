"""Rodada de avaliação: as respostas de cada modelo para o mesmo conjunto de perguntas.

    python gerar_respostas.py                       # nova rodada: perguntas do config, os três modelos
    python gerar_respostas.py --limite 3            # só as 3 primeiras perguntas (para medir o tempo)
    python gerar_respostas.py --modelos llama3.2:3b # só os modelos indicados
    python gerar_respostas.py --continuar           # continua a rodada mais recente
    python gerar_respostas.py --rodada avaliacao/rodadas/2026-11-20_0900_perguntas_reais
    python gerar_respostas.py --arquivo avaliacao/perguntas_reais.csv

Só o modelo muda entre um teste e outro (Seção 2.2 da monografia):

1. lê e confere as perguntas (perguntas.py); um arquivo com erros não roda;
2. busca os trechos de cada pergunta uma vez (com a busca e o TOP_K do
   config) e cria a pasta da rodada, avaliacao/rodadas/<data>_<hora>_<conjunto>/,
   com configuracao.json (versão do código, perguntas usadas e assinatura,
   busca, modelos e opções enviadas ao Ollama, regras do prompt, computador),
   perguntas.json (as perguntas usadas), a cópia do arquivo original e
   contextos.json (os trechos congelados: todos os modelos recebem estes);
3. para cada modelo, na ordem de config.MODELOS_COMPARACAO: confere se está
   instalado, carrega, confere se rodou só no processador, responde a todas
   as perguntas e descarrega antes do próximo. Cada resposta é gravada em
   respostas_<modelo>.jsonl assim que fica pronta, pelo mesmo código do chat
   (AssistenteRAG.responder_com_contexto), com as opções enviadas e um
   código (SHA-256) das mensagens, que prova que os modelos receberam o mesmo.

Se a rodada parar no meio (Ctrl+C, queda de energia, computador desligado),
--continuar retoma: usa os trechos já congelados (não busca de novo) e pula
as perguntas que cada modelo já respondeu. Antes de continuar, confere que
nada mudou desde o início da rodada (opções de geração, regras do prompt,
frase de abstenção, raciocínio, versão instalada de cada modelo); se algo
mudou, recusa e diz o quê, porque misturar configurações estragaria a
comparação. Duas execuções ao mesmo tempo na mesma rodada são barradas por um
arquivo de trava (.em_uso). Nada é sobrescrito: cada rodada nova ganha uma
pasta nova.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from modelos import argumentos_chat, campo, info_modelo, nome_completo, onde_rodou, opcoes_geracao
from perguntas import ConjuntoPerguntas, ErroPerguntas, carregar_perguntas

ARQUIVO_CONFIGURACAO = "configuracao.json"
ARQUIVO_PERGUNTAS = "perguntas.json"
ARQUIVO_CONTEXTOS = "contextos.json"
ARQUIVO_TRAVA = ".em_uso"


class ErroRodada(Exception):
    """A rodada não pode começar ou continuar (pasta incompleta, configuração mudou...)."""


def pasta_das_rodadas() -> Path:
    return config.AVALIACAO_DIR / "rodadas"


def nome_arquivo_modelo(nome: str) -> str:
    """"qwen3.8:27b" -> "qwen3.8_27b" (nome que serve para arquivo no Windows)."""
    return re.sub(r"[^A-Za-z0-9.]+", "_", nome).strip("_")


def arquivo_respostas(pasta: Path, modelo: str) -> Path:
    return pasta / f"respostas_{nome_arquivo_modelo(modelo)}.jsonl"


def _ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))


def rodada_mais_recente() -> Path | None:
    """A rodada criada por último (pela data gravada, não pelo nome da pasta:
    uma cópia de segurança ao lado da original não passa na frente)."""
    candidatas = []
    for pasta in pasta_das_rodadas().glob("*"):
        caminho = pasta / ARQUIVO_CONFIGURACAO
        if not caminho.is_file():
            continue
        try:
            criada = _ler_json(caminho).get("criada_em", "")
        except (OSError, ValueError):
            continue
        candidatas.append((criada, -len(pasta.name), pasta.name, pasta))     # empate: o nome mais curto
    return max(candidatas)[3] if candidatas else None


def _gravar_json(caminho: Path, dados) -> None:
    """Grava num arquivo temporário e troca no fim: uma queda no meio não deixa
    JSON pela metade. No Windows, a troca é repetida se o antivírus ou o
    OneDrive estiverem com o arquivo aberto naquele instante."""
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(temporario, "w", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(dados, ensure_ascii=False, indent=1,
                                 default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        arquivo.flush()
        os.fsync(arquivo.fileno())
    for tentativa in range(5):
        try:
            os.replace(temporario, caminho)
            return
        except PermissionError:
            if tentativa == 4:
                raise
            time.sleep(0.5)


# Trava: uma execução por rodada
class Trava:
    """Arquivo .em_uso na pasta da rodada enquanto uma execução a usa."""

    def __init__(self, pasta: Path):
        self.caminho = pasta / ARQUIVO_TRAVA

    def __enter__(self):
        try:
            descritor = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ErroRodada(f"outra execução está usando a rodada {self.caminho.parent.name} (ou uma execução "
                             f"anterior foi fechada à força). Se tiver certeza de que nenhuma está aberta, apague o "
                             f"arquivo {self.caminho} e rode de novo.") from None
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            arquivo.write(f"processo {os.getpid()}, desde {datetime.now().isoformat(timespec='seconds')}\n")
        return self

    def __exit__(self, *exc):
        try:
            self.caminho.unlink()
        except OSError:
            pass


# Criação da rodada
def _computador() -> dict:
    return {"sistema": platform.platform(), "processador": platform.processor() or platform.machine(),
            "nucleos_logicos": os.cpu_count(), "python": platform.python_version()}


def descrever_modelos(nomes: list[str]) -> list[dict]:
    return [{"modelo": nome, "rotulo": info_modelo(nome)["rotulo"], "opcoes": opcoes_geracao(),
             "argumentos": argumentos_chat(nome), "tempo_limite": info_modelo(nome)["tempo_limite"]}
            for nome in nomes]


def condicoes_atuais() -> dict:
    """O que precisa ser igual do começo ao fim de uma rodada."""
    from consulta import prompt_sistema
    return {"opcoes": opcoes_geracao(), "prompt_sistema": prompt_sistema(),
            "mensagem_abstencao": config.MENSAGEM_ABSTENCAO}


def criar_rodada(conjunto: ConjuntoPerguntas, modelos: list[str], recuperador, limite: int | None = None,
                 agora: datetime | None = None, saida=print) -> Path:
    """Busca os trechos de cada pergunta e cria a pasta da rodada.

    A busca vem antes da pasta: se ela falhar (base vazia, modelo de
    embeddings ausente), não fica pasta pela metade.
    """
    agora = agora or datetime.now()
    perguntas = conjunto.perguntas[:limite] if limite else list(conjunto.perguntas)
    modo = recuperador.modo_valido()
    contextos = congelar_contextos(perguntas, recuperador, saida)
    nome = f"{agora:%Y-%m-%d_%H%M}_{conjunto.nome}" + (f"_limite{limite}" if limite else "")
    pasta = pasta_das_rodadas() / nome
    sufixo = 2
    while pasta.exists():
        pasta = pasta_das_rodadas() / f"{nome}_{sufixo}"
        sufixo += 1
    pasta.mkdir(parents=True)
    try:
        configuracao = {
            "versao_chatbot": config.VERSAO_CHATBOT,
            "criada_em": agora.isoformat(timespec="seconds"),
            "perguntas": dict(conjunto.identificacao(), usadas=len(perguntas), limite=limite),
            "busca": recuperador.configuracao(modo, config.TOP_K),
            "modelos": descrever_modelos(modelos),
            "so_processador": config.SO_PROCESSADOR,
            **{chave: valor for chave, valor in condicoes_atuais().items() if chave != "opcoes"},
            "computador": _computador(),
        }
        _gravar_json(pasta / ARQUIVO_PERGUNTAS, perguntas)
        shutil.copy2(conjunto.arquivo, pasta / f"perguntas_original{conjunto.arquivo.suffix.lower()}")
        _gravar_json(pasta / ARQUIVO_CONTEXTOS, contextos)
        _gravar_json(pasta / ARQUIVO_CONFIGURACAO, configuracao)       # por último: a pasta só vale com ele
    except BaseException:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    return pasta


def congelar_contextos(perguntas: list[dict], recuperador, saida=print) -> list[dict]:
    """Busca os trechos de cada pergunta uma vez (com a busca e o TOP_K do config)."""
    modo = recuperador.modo_valido()
    recuperador.preparar(modo)
    aquecer = getattr(recuperador, "aquecer", None)
    if aquecer:
        aquecer()         # carrega o modelo de embeddings antes: o tempo de carga não entra na 1ª pergunta
    contextos = []
    inicio = time.perf_counter()
    for n, item in enumerate(perguntas, 1):
        contexto = recuperador.recuperar(item["pergunta"], k=config.TOP_K, modo=modo)
        contextos.append({"id": item["id"], "contexto": contexto.para_dict()})
        if n % 10 == 0 or n == len(perguntas):
            saida(f"  trechos buscados: {n}/{len(perguntas)}")
    saida(f"  trechos congelados ({time.perf_counter() - inicio:.0f} s)")
    return contextos


def abrir_rodada(pasta: Path) -> tuple[dict, list[dict]]:
    """Configuração e perguntas de uma rodada existente."""
    if not (pasta / ARQUIVO_CONFIGURACAO).exists() or not (pasta / ARQUIVO_PERGUNTAS).exists():
        raise ErroRodada(f"{pasta} não é uma pasta de rodada (falta {ARQUIVO_CONFIGURACAO} ou {ARQUIVO_PERGUNTAS}).")
    return _ler_json(pasta / ARQUIVO_CONFIGURACAO), _ler_json(pasta / ARQUIVO_PERGUNTAS)


def ler_contextos(pasta: Path) -> dict[str, dict]:
    return {c["id"]: c["contexto"] for c in _ler_json(pasta / ARQUIVO_CONTEXTOS)}


# Respostas
def ler_respostas(caminho: Path) -> list[dict]:
    """Linhas válidas do arquivo (só leitura: uma linha cortada é ignorada aqui
    e consertada pelo reparar_respostas, antes de a geração acrescentar algo)."""
    if not caminho.exists():
        return []
    validas = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        try:
            validas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return validas


def reparar_respostas(caminho: Path) -> list[dict]:
    """Deixa o arquivo só com linhas inteiras e terminado em quebra de linha.

    Uma queda no meio da gravação deixa a última linha cortada; sem o
    conserto, a próxima resposta ficaria grudada nela. O arquivo novo é
    gravado à parte e trocado no fim, para uma queda no conserto não perder nada.
    """
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8")
    validas = ler_respostas(caminho)
    limpo = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in validas)
    if texto != limpo:
        temporario = caminho.with_suffix(caminho.suffix + ".tmp")
        with open(temporario, "w", encoding="utf-8") as arquivo:
            arquivo.write(limpo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    return validas


def codigo_mensagens(mensagens: list[dict]) -> str:
    """SHA-256 (16 primeiros dígitos) das mensagens enviadas ao modelo."""
    return hashlib.sha256(json.dumps(mensagens, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def linha_resposta(item: dict, modelo: str, resposta, mensagens: list[dict]) -> dict:
    return {
        "id": item["id"], "pergunta": item["pergunta"], "modelo": modelo,
        "resposta": resposta.texto, "categoria": resposta.categoria, "abstencao": resposta.abstencao,
        "motivo_abstencao": resposta.motivo_abstencao, "gerada_pelo_llm": resposta.gerada_pelo_llm,
        "citadas": resposta.citadas, "citacao_explicita": resposta.citacao_explicita, "mista": resposta.mista,
        "tempos": resposta.tempos, "estatisticas_llm": resposta.estatisticas_llm,
        "codigo_mensagens": codigo_mensagens(mensagens) if resposta.gerada_pelo_llm else None,
        "opcoes": opcoes_geracao(), "versao_chatbot": config.VERSAO_CHATBOT,
        "data_hora": datetime.now().isoformat(timespec="seconds"),
    }


def _digest(cliente, modelo: str) -> str | None:
    try:
        for m in campo(cliente.list(), "models", []):
            if (campo(m, "model", "") or campo(m, "name", "")) == nome_completo(modelo):
                return campo(m, "digest", None)
    except Exception:
        return None
    return None


def conferir_condicoes(configuracao: dict, modelos: list[str]) -> list[str]:
    """Diferenças entre o que a rodada gravou e o que está valendo agora."""
    atuais = condicoes_atuais()
    diferencas = []
    for chave in ("prompt_sistema", "mensagem_abstencao"):
        if chave in configuracao and configuracao[chave] != atuais[chave]:
            diferencas.append(f"{chave} mudou desde o início da rodada")
    gravados = {m["modelo"]: m for m in configuracao.get("modelos", [])}
    for modelo in modelos:
        if modelo not in gravados:
            continue
        if gravados[modelo].get("opcoes") != atuais["opcoes"]:
            diferencas.append(f"opções de geração de {modelo}: gravadas {gravados[modelo].get('opcoes')}, "
                              f"agora {atuais['opcoes']}")
        if gravados[modelo].get("argumentos", {}) != argumentos_chat(modelo):
            diferencas.append(f"raciocínio de {modelo}: gravado {gravados[modelo].get('argumentos')}, "
                              f"agora {argumentos_chat(modelo)}")
    return diferencas


def gerar_modelo(pasta: Path, modelo: str, perguntas: list[dict], contextos: dict[str, dict],
                 assistente=None, saida=print) -> int:
    """Responde, com um modelo, às perguntas que ele ainda não respondeu nesta rodada.

    Devolve quantas respostas novas gravou. `assistente`: para os testes; sem
    ele, cria um AssistenteRAG com o modelo (que não busca nada: só gera).
    """
    from consulta import AssistenteRAG, Contexto, mensagens_para
    caminho = arquivo_respostas(pasta, modelo)
    feitas = {r["id"] for r in reparar_respostas(caminho)}
    faltam = [p for p in perguntas if p["id"] not in feitas]
    rotulo = info_modelo(modelo)["rotulo"]
    if not faltam:
        saida(f"{rotulo}: as {len(perguntas)} perguntas já estão respondidas.")
        return 0
    saida(f"{rotulo} ({modelo}): {len(faltam)} de {len(perguntas)} perguntas a responder.")
    assistente = assistente or AssistenteRAG(recuperador=_SemBusca(), modelo_llm=modelo)
    assistente.verificar_ollama()
    _conferir_versao_do_modelo(pasta, modelo, assistente.cliente)
    saida("  carregando o modelo...")
    assistente.aquecer()
    gravadas = 0
    inicio = time.perf_counter()
    try:
        _conferir_processador(pasta, modelo, assistente.cliente)
        with open(caminho, "a", encoding="utf-8") as arquivo:
            for item in faltam:
                contexto = Contexto.de_dict(contextos[item["id"]])
                resposta = assistente.responder_com_contexto(contexto, registrar=False)
                if resposta.categoria == "vazia":          # tenta mais uma vez antes de aceitar
                    resposta = assistente.responder_com_contexto(contexto, registrar=False)
                mensagens = mensagens_para(contexto.pergunta, contexto.passagens)
                arquivo.write(json.dumps(linha_resposta(item, modelo, resposta, mensagens), ensure_ascii=False) + "\n")
                arquivo.flush()
                os.fsync(arquivo.fileno())
                gravadas += 1
                situacao = {"abstencao": "abstenção", "abstencao_com_acrescimo": "abstenção com acréscimo",
                            "mista": "resposta mista", "vazia": "resposta vazia"}.get(resposta.categoria, "respondeu")
                if not resposta.gerada_pelo_llm:
                    situacao += ", sem chamar o modelo"
                if (resposta.estatisticas_llm or {}).get("motivo_fim") == "length":
                    situacao += ", cortada no limite de tokens"
                saida(f"  [{len(feitas) + gravadas}/{len(perguntas)}] {item['id']}: "
                      f"{resposta.tempos.get('total_s', 0):.1f} s ({situacao})")
    finally:
        assistente.descarregar()
    saida(f"  {rotulo}: {gravadas} respostas em {time.perf_counter() - inicio:.0f} s.")
    return gravadas


def _atualizar_modelo(pasta: Path, modelo: str, **valores) -> dict:
    caminho = pasta / ARQUIVO_CONFIGURACAO
    configuracao = _ler_json(caminho)
    for m in configuracao.get("modelos", []):
        if m["modelo"] == modelo:
            m.update(valores)
    _gravar_json(caminho, configuracao)
    return configuracao


def _conferir_versao_do_modelo(pasta: Path, modelo: str, cliente) -> None:
    """Grava a versão instalada (digest) do modelo e recusa continuar se ela mudou
    (um "ollama pull" no meio da rodada trocaria o modelo sem aviso)."""
    digest = _digest(cliente, modelo)
    gravado = next((m for m in _ler_json(pasta / ARQUIVO_CONFIGURACAO).get("modelos", []) if m["modelo"] == modelo), {})
    if gravado.get("digest") and digest and gravado["digest"] != digest:
        raise ErroRodada(f"o modelo {modelo} instalado no Ollama mudou desde o início da rodada (versão "
                         f"{gravado['digest'][:12]} antes, {digest[:12]} agora). Crie uma rodada nova.")
    if digest and not gravado.get("digest"):
        _atualizar_modelo(pasta, modelo, digest=digest)


def _conferir_processador(pasta: Path, modelo: str, cliente) -> None:
    """Depois de carregar: grava onde o modelo rodou e para se não foi só no processador."""
    try:
        local = onde_rodou(cliente.ps(), modelo)
    except Exception:
        local = None
    if local is None:
        return
    _atualizar_modelo(pasta, modelo, rodou_em=local["local"], fracao_na_placa=local["fracao_na_placa"])
    if config.SO_PROCESSADOR and local["local"] != "processador":
        raise ErroRodada(f"o Ollama carregou {modelo} com {round(100 * local['fracao_na_placa'])}% na placa de "
                         "vídeo, mas os modelos comparados precisam rodar só no processador. Rode "
                         "verificar-modelos.bat para ver o que aconteceu.")


class _SemBusca:
    """A rodada não busca nada na geração: os trechos já estão congelados."""

    def recuperar(self, pergunta):
        raise RuntimeError("a rodada usa os trechos congelados em contextos.json")


def executar(pasta: Path, modelos: list[str], saida=print, fabrica_assistente=None) -> None:
    """Gera, modelo a modelo, as respostas que faltam na rodada."""
    with Trava(pasta):
        configuracao, perguntas = abrir_rodada(pasta)
        if not (pasta / ARQUIVO_CONTEXTOS).exists():
            raise ErroRodada(f"a rodada {pasta.name} perdeu o {ARQUIVO_CONTEXTOS} (os trechos congelados). Buscar "
                             "de novo misturaria trechos diferentes na mesma rodada: crie uma rodada nova.")
        contextos = ler_contextos(pasta)
        faltando = [p["id"] for p in perguntas if p["id"] not in contextos]
        if faltando:
            raise ErroRodada(f"contextos.json não tem os trechos de {len(faltando)} pergunta(s): {faltando[:5]}")
        diferencas = conferir_condicoes(configuracao, modelos)
        if diferencas:
            raise ErroRodada("a configuração mudou desde o início da rodada, e misturar configurações estragaria a "
                             "comparação. Volte a configuração do config.py ou crie uma rodada nova:\n  - "
                             + "\n  - ".join(diferencas))
        if configuracao.get("versao_chatbot") != config.VERSAO_CHATBOT:
            saida(f"Aviso: a rodada começou com a versão {configuracao.get('versao_chatbot')} do código e continua "
                  f"com a {config.VERSAO_CHATBOT}; cada resposta grava a versão que a gerou.")
        conhecidos = {m["modelo"] for m in configuracao.get("modelos", [])}
        novos = [m for m in modelos if m not in conhecidos]
        if novos:
            configuracao["modelos"] = configuracao.get("modelos", []) + descrever_modelos(novos)
            _gravar_json(pasta / ARQUIVO_CONFIGURACAO, configuracao)
        for modelo in modelos:
            assistente = fabrica_assistente(modelo) if fabrica_assistente else None
            gerar_modelo(pasta, modelo, perguntas, contextos, assistente, saida)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera as respostas de cada modelo para as perguntas de avaliação.")
    parser.add_argument("--arquivo", "--perguntas", dest="arquivo", type=Path, default=None,
                        help="arquivo de perguntas (padrão: ARQUIVO_PERGUNTAS do config.py)")
    parser.add_argument("--limite", type=int, default=None, help="usa só as N primeiras perguntas")
    parser.add_argument("--modelos", nargs="+", default=None,
                        help="modelos desta rodada (padrão: MODELOS_COMPARACAO do config.py)")
    parser.add_argument("--continuar", action="store_true", help="continua a rodada mais recente")
    parser.add_argument("--rodada", type=Path, default=None, help="continua esta rodada")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    from consulta import ErroChatbot
    from vetorial import ErroEmbeddings
    pasta = None
    try:
        if args.rodada or args.continuar:
            pasta = args.rodada or rodada_mais_recente()
            if pasta is None:
                raise ErroRodada(f"nenhuma rodada em {pasta_das_rodadas()} para continuar.")
            pasta = Path(pasta)
            if not pasta.is_absolute() and not pasta.exists():
                pasta = config.BASE_DIR / pasta
            configuracao, _ = abrir_rodada(pasta)
            modelos = args.modelos or [m["modelo"] for m in configuracao.get("modelos", [])]
            print(f"Continuando a rodada {pasta.name}")
        else:
            conjunto = carregar_perguntas(args.arquivo)
            if conjunto.erros:
                raise ErroRodada(f"o arquivo de perguntas {conjunto.arquivo.name} tem {len(conjunto.erros)} "
                                 "erro(s); rode validar-perguntas.bat para ver e corrigir.")
            modelos = args.modelos or list(config.MODELOS_COMPARACAO)
            from recuperacao import Recuperador
            print(f"Nova rodada: {conjunto.arquivo.name} ({len(conjunto.perguntas)} perguntas"
                  + (f", usando só as {args.limite} primeiras" if args.limite else "") + f"); modelos: "
                  + ", ".join(info_modelo(m)["rotulo"] for m in modelos))
            print("Buscando os trechos de cada pergunta (uma vez só, para todos os modelos)...")
            pasta = criar_rodada(conjunto, modelos, Recuperador(), args.limite)
            print(f"Pasta da rodada: {pasta}")
        executar(pasta, modelos)
    except KeyboardInterrupt:
        print("\nRodada interrompida. " + _como_continuar(pasta))
        return 1
    except (ErroRodada, ErroPerguntas) as erro:
        print(f"\nERRO: {erro}")
        return 1
    except (ErroChatbot, ErroEmbeddings) as erro:
        print(f"\nERRO: {erro}\n" + _como_continuar(pasta))
        return 1
    print(f"\nRodada completa em {pasta}.\nPróximo passo: avaliar-respostas.bat")
    return 0


def _como_continuar(pasta: Path | None) -> str:
    if pasta is not None and (pasta / ARQUIVO_CONFIGURACAO).exists():
        return ("As respostas já geradas estão gravadas; para continuar: gerar-respostas.bat --rodada "
                f"\"{pasta}\"")
    return "A rodada não chegou a ser criada; corrija o problema e rode gerar-respostas.bat de novo."


if __name__ == "__main__":
    sys.exit(main())
