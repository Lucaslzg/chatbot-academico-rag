"""Servidor HTTP que imita a API do Ollama, para testes sem placa de vídeo nem modelo.

Implementa só o que o chatbot usa: GET /api/tags, /api/ps e /api/version e
POST /api/chat (com e sem streaming). A resposta simulada cita o trecho [1],
a não ser que a pergunta contenha a palavra "desconhecido": aí devolve a
frase de abstenção. Serve para testar o encadeamento com a biblioteca
`ollama` de verdade (conexão, streaming, erros HTTP, opções enviadas), não a
qualidade das respostas.

Também imita onde o modelo roda e o raciocínio:

* placa: fração do modelo que o Ollama põe na placa de vídeo quando o pedido
  não traz num_gpu = 0 (1.0 = placa disponível; 0.0 = sem placa);
* ignora_num_gpu: modelos que vão para a placa mesmo com num_gpu = 0 (para
  testar a conferência);
* pensantes: modelos que mandam um "thinking" antes da resposta, a não ser
  que o pedido traga think = False; pensa_sempre: mandam mesmo assim.

Cada pedido recebido fica em `requisicoes` (o corpo JSON), na ordem.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

TAMANHO_PADRAO = 5_000_000_000


class _Manipulador(BaseHTTPRequestHandler):
    modelos = ("llama3.1:8b",)
    ultima_requisicao: dict = {}
    requisicoes: list = []
    carregados: dict = {}
    placa = 0.0
    ignora_num_gpu: tuple = ()
    pensantes: tuple = ()
    pensa_sempre: tuple = ()
    versao = "0.0.0-falso"
    resposta_texto: str | None = None
    motivo_fim = "stop"
    digests: dict = {}

    def log_message(self, *args):  # silencioso
        pass

    def _json(self, codigo: int, corpo: dict) -> None:
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": m, "model": m, "size": 1, "digest": self.digests.get(m, "")}
                                        for m in self.modelos]})
        elif self.path == "/api/ps":
            self._json(200, {"models": [{"name": m, "model": m, "size": v["size"], "size_vram": v["size_vram"],
                                         "expires_at": "2026-11-03T12:00:00Z"}
                                        for m, v in self.carregados.items()]})
        elif self.path == "/api/version":
            self._json(200, {"version": self.versao})
        else:
            self._json(404, {"error": "not found"})

    def _carregar(self, modelo: str, opcoes: dict) -> None:
        sem_placa = opcoes.get("num_gpu") == 0 and modelo not in self.ignora_num_gpu
        fracao = 0.0 if sem_placa else (1.0 if modelo in self.ignora_num_gpu else self.placa)
        self.carregados[modelo] = {"size": TAMANHO_PADRAO, "size_vram": int(TAMANHO_PADRAO * fracao)}

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        type(self).ultima_requisicao = corpo
        self.requisicoes.append(corpo)
        if self.path != "/api/chat":
            self._json(404, {"error": "not found"})
            return
        modelo = corpo.get("model")
        if modelo not in self.modelos:
            self._json(404, {"error": f"model '{modelo}' not found"})
            return
        mensagens = corpo.get("messages") or []
        if not mensagens:   # pedido de carga (ou descarga, com keep_alive 0) do modelo
            if corpo.get("keep_alive") in (0, "0", "0s"):
                self.carregados.pop(modelo, None)
                motivo = "unload"
            else:
                self._carregar(modelo, corpo.get("options") or {})
                motivo = "load"
            self._json(200, {"model": modelo, "done": True, "done_reason": motivo,
                             "message": {"role": "assistant", "content": ""}})
            return
        self._carregar(modelo, corpo.get("options") or {})
        pergunta = mensagens[-1]["content"]
        if self.resposta_texto is not None:
            texto = self.resposta_texto
        elif "desconhecido" in pergunta.split("Pergunta:")[-1]:
            texto = config.MENSAGEM_ABSTENCAO
        else:
            texto = "Conforme o documento, a regra está descrita no trecho [1]. Veja também [2]."
        pensa = modelo in self.pensa_sempre or (modelo in self.pensantes and corpo.get("think") is not False)
        pensamento = "Vou ler os trechos antes de responder." if pensa else ""
        pedacos = [texto[i:i + 12] for i in range(0, len(texto), 12)]
        if not corpo.get("stream", True):
            mensagem = {"role": "assistant", "content": texto}
            if pensamento:
                mensagem["thinking"] = pensamento
            self._json(200, {"model": modelo, "done": True, "message": mensagem,
                             "total_duration": 2_000_000_000, "load_duration": 500_000_000,
                             "prompt_eval_count": 10, "prompt_eval_duration": 100_000_000,
                             "eval_count": 20, "eval_duration": 1_000_000_000})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if pensamento:
            linha = {"model": modelo, "done": False,
                     "message": {"role": "assistant", "content": "", "thinking": pensamento}}
            self.wfile.write((json.dumps(linha) + "\n").encode())
        for pedaco in pedacos:
            linha = {"model": modelo, "done": False, "message": {"role": "assistant", "content": pedaco}}
            self.wfile.write((json.dumps(linha) + "\n").encode())
            self.wfile.flush()
        final = {"model": modelo, "done": True, "done_reason": self.motivo_fim,
                 "message": {"role": "assistant", "content": ""},
                 "total_duration": 1_500_000_000, "load_duration": 100_000_000,
                 "prompt_eval_count": 321, "prompt_eval_duration": 200_000_000,
                 "eval_count": len(pedacos), "eval_duration": 1_000_000_000}
        self.wfile.write((json.dumps(final) + "\n").encode())


class OllamaFalso:
    """Uso: `with OllamaFalso() as endereco: ...` (sobe o servidor numa porta livre).

    Depois do bloco (ou dentro dele), `self.requisicoes` tem os pedidos recebidos.
    """

    def __init__(self, modelos=("llama3.1:8b",), placa: float = 0.0, ignora_num_gpu=(), pensantes=(),
                 pensa_sempre=(), resposta_texto: str | None = None, motivo_fim: str = "stop",
                 digests: dict | None = None):
        self.modelos = tuple(modelos)
        self.atributos = {"modelos": self.modelos, "placa": placa, "ignora_num_gpu": tuple(ignora_num_gpu),
                          "pensantes": tuple(pensantes), "pensa_sempre": tuple(pensa_sempre),
                          "resposta_texto": resposta_texto, "motivo_fim": motivo_fim, "digests": dict(digests or {})}
        self.requisicoes: list = []
        self.carregados: dict = {}

    def __enter__(self) -> str:
        manipulador = type("Manipulador", (_Manipulador,),
                           dict(self.atributos, requisicoes=self.requisicoes, carregados=self.carregados))
        self.manipulador = manipulador
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        self.thread = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def __exit__(self, *exc) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()
