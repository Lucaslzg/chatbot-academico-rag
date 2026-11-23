"""Testes da escolha do modelo de linguagem, das opções enviadas ao Ollama
(só no processador, raciocínio desligado) e da conferência dos modelos."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from pathlib import Path

from ollama_falso import OllamaFalso
from utilitarios import configuracao

import config
import consulta
import modelos
import verificar_modelos

MODELOS_TESTE = {
    "llama3.1:8b": {"rotulo": "Llama 3.1 8B", "raciocinio": False, "tempo_limite": 30},
    "qwen3.8:27b": {"rotulo": "Qwen 3.8 27B", "raciocinio": True, "tempo_limite": 30},
    "llama3.2:3b": {"rotulo": "Llama 3.2 3B", "raciocinio": False, "tempo_limite": 30},
    "juiz:7b": {"rotulo": "Juiz 7B", "raciocinio": False, "tempo_limite": 30},
}
TODOS = tuple(MODELOS_TESTE)


def _config_modelos(**extra):
    valores = dict(MODELOS=MODELOS_TESTE, MODELOS_COMPARACAO=["llama3.1:8b", "qwen3.8:27b", "llama3.2:3b"],
                   JUIZES=[{"modelo": "juiz:7b", "placa_de_video": True, "tempo_limite": 30}],
                   SO_PROCESSADOR=True)
    valores.update(extra)
    return configuracao(**valores)


class TestOpcoes(unittest.TestCase):
    def test_so_no_processador(self):
        with configuracao(SO_PROCESSADOR=True):
            self.assertEqual(modelos.opcoes_geracao()["num_gpu"], 0)
            self.assertNotIn("num_gpu", modelos.opcoes_geracao(so_processador=False))   # o juiz
        with configuracao(SO_PROCESSADOR=False):
            self.assertNotIn("num_gpu", modelos.opcoes_geracao())

    def test_mesmas_opcoes_para_todos_os_modelos(self):
        with configuracao(TEMPERATURA=0.2, OLLAMA_NUM_CTX=8192, OLLAMA_SEED=42, SO_PROCESSADOR=True,
                          OLLAMA_NUM_PREDICT=1024, AMOSTRAGEM={"top_k": 40, "top_p": 0.9}):
            self.assertEqual(modelos.opcoes_geracao(),
                             {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1024, "top_k": 40, "top_p": 0.9,
                              "seed": 42, "num_gpu": 0})
        with configuracao(OLLAMA_SEED=None):
            self.assertNotIn("seed", modelos.opcoes_geracao())

    def test_raciocinio_desligado_so_nos_modelos_que_raciocinam(self):
        with _config_modelos():
            self.assertEqual(modelos.argumentos_chat("qwen3.8:27b"), {"think": False})
            self.assertEqual(modelos.argumentos_chat("llama3.1:8b"), {})
            self.assertEqual(modelos.argumentos_chat("desconhecido:1b"), {})

    def test_modelo_fora_da_lista_usa_os_padroes(self):
        with _config_modelos(OLLAMA_TIMEOUT=123):
            info = modelos.info_modelo("outro:1b")
        self.assertEqual(info, {"rotulo": "outro:1b", "raciocinio": False, "tempo_limite": 123})

    def test_onde_rodou(self):
        ps = {"models": [{"model": "a:1b", "size": 100, "size_vram": 0},
                         {"model": "b:1b", "size": 100, "size_vram": 100},
                         {"model": "c:1b", "size": 100, "size_vram": 40},
                         {"model": "d:latest", "size": 100, "size_vram": 0}]}
        self.assertEqual(modelos.onde_rodou(ps, "a:1b")["local"], "processador")
        self.assertEqual(modelos.onde_rodou(ps, "b:1b")["local"], "placa de vídeo")
        self.assertEqual(modelos.onde_rodou(ps, "c:1b"), {"local": "dividido", "fracao_na_placa": 0.4,
                                                         "tamanho_gb": 0.0})
        self.assertEqual(modelos.onde_rodou(ps, "d")["local"], "processador")    # "d" = "d:latest"
        self.assertIsNone(modelos.onde_rodou(ps, "e:1b"))

    def test_config_real_tem_os_tres_comparados_e_os_dois_juizes(self):
        self.assertEqual(len(config.MODELOS_COMPARACAO), 3)
        for nome in config.MODELOS_COMPARACAO:
            self.assertIn(nome, config.MODELOS, nome)
        self.assertIn(config.OLLAMA_MODEL, config.MODELOS)
        self.assertTrue(config.MODELOS["qwen3.8:27b"]["raciocinio"])
        self.assertTrue(config.SO_PROCESSADOR)
        self.assertEqual(config.EMBEDDING_DISPOSITIVO, "cpu")
        self.assertEqual(len(config.JUIZES), 2)
        for juiz in config.JUIZES:
            self.assertTrue(juiz["placa_de_video"])
            self.assertIn(juiz["modelo"], config.MODELOS)
        self.assertTrue(config.MODELOS["gemma4:e4b-it-qat"]["raciocinio"])      # o juiz que pensa recebe think=False

    def test_config_real_nao_repete_familia(self):
        nomes_juizes = [j["modelo"] for j in config.JUIZES]
        self.assertEqual(modelos.problemas_de_familia(config.MODELOS_COMPARACAO, nomes_juizes), [])
        self.assertEqual(modelos.sem_familia(list(config.MODELOS_COMPARACAO) + nomes_juizes), [])


class TestFamilias(unittest.TestCase):
    MODELOS = {"a:1b": {"rotulo": "A", "familia": "F1"}, "b:1b": {"rotulo": "B", "familia": "F2"},
               "c:1b": {"rotulo": "C", "familia": "F1"}, "d:1b": {"rotulo": "D"}}

    def test_familias_diferentes_nao_tem_problema(self):
        with configuracao(MODELOS=self.MODELOS):
            self.assertEqual(modelos.problemas_de_familia(["a:1b"], ["b:1b"]), [])
            self.assertEqual(modelos.familia("a:1b"), "F1")
            self.assertIsNone(modelos.familia("d:1b"))

    def test_mesma_familia_entre_comparados_e_entre_juiz_e_comparado(self):
        with configuracao(MODELOS=self.MODELOS):
            self.assertEqual(modelos.problemas_de_familia(["a:1b", "c:1b"], []),
                             ["A (comparado) e C (comparado) são da mesma família: F1"])
            self.assertEqual(modelos.problemas_de_familia(["a:1b"], ["b:1b", "c:1b"]),
                             ["A (comparado) e C (juiz) são da mesma família: F1"])

    def test_o_mesmo_modelo_nos_dois_papeis(self):
        with configuracao(MODELOS=self.MODELOS):
            self.assertEqual(modelos.problemas_de_familia(["a:1b"], ["a:1b"]),
                             ["A (a:1b) aparece como comparado e como juiz"])

    def test_sem_familia_marcada(self):
        with configuracao(MODELOS=self.MODELOS):
            self.assertEqual(modelos.sem_familia(["a:1b", "d:1b", "d:1b", "fora:1b"]), ["d:1b", "fora:1b"])
            self.assertEqual(modelos.problemas_de_familia(["d:1b"], ["fora:1b"]), [])

    def test_juizes_e_o_juiz_antigo(self):
        with configuracao(JUIZES=[{"modelo": "x:1b", "max_tokens": 9}, {"modelo": ""}]):
            self.assertEqual([j["modelo"] for j in modelos.juizes()], ["x:1b"])
            self.assertEqual(modelos.juiz("x:1b")["max_tokens"], 9)
            self.assertEqual(modelos.juiz("outro:1b"), {"modelo": "outro:1b", "placa_de_video": True})
        with configuracao(JUIZES=None), mock.patch.object(config, "JUIZ", {"modelo": "velho:3b"}, create=True):
            self.assertEqual(modelos.juizes(), [{"modelo": "velho:3b"}])


class TestChatComOutroModelo(unittest.TestCase):
    PASSAGEM = consulta.Passagem(1, "res.pdf", "Resolução", "Art. 1 O trancamento...", 1, 1, 1, 1, "", "", 0.7)

    def _assistente(self, modelo_llm=None):
        contexto = consulta.Contexto("Posso trancar?", [self.PASSAGEM], [], 0.7, False, {"modo_busca": "hibrida"})

        class _Recuperador:
            def recuperar(self, pergunta):
                return contexto
        return consulta.AssistenteRAG(recuperador=_Recuperador(), modelo_llm=modelo_llm)

    def test_modelo_escolhido_recebe_think_false_e_num_gpu_zero(self):
        servidor = OllamaFalso(modelos=TODOS, placa=1.0, pensantes=("qwen3.8:27b",))
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco), tempfile.TemporaryDirectory() as pasta, \
                configuracao(REGISTROS_DIR=Path(pasta)):
            assistente = self._assistente("qwen3.8:27b")
            assistente.verificar_ollama()
            resposta = assistente.responder("Posso trancar?")
            registro = json.loads((Path(pasta) / "interacoes.jsonl").read_text(encoding="utf-8"))
        pedido = servidor.requisicoes[-1]
        self.assertEqual(pedido["model"], "qwen3.8:27b")
        self.assertIs(pedido["think"], False)
        self.assertEqual(pedido["options"]["num_gpu"], 0)
        self.assertEqual(resposta.citadas, [1])
        self.assertNotIn("raciocinio_caracteres", resposta.estatisticas_llm)
        self.assertEqual(registro["configuracao"]["modelo_llm"], "qwen3.8:27b")
        self.assertTrue(registro["configuracao"]["so_processador"])
        self.assertTrue(registro["configuracao"]["raciocinio_desligado"])
        self.assertEqual(registro["configuracao"]["versao_chatbot"], config.VERSAO_CHATBOT)

    def test_modelo_sem_raciocinio_nao_recebe_think(self):
        servidor = OllamaFalso(modelos=TODOS)
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco, OLLAMA_MODEL="llama3.1:8b"), \
                configuracao(REGISTRAR_INTERACOES=False):
            self._assistente().responder("Posso trancar?")
        self.assertEqual(servidor.requisicoes[-1]["model"], "llama3.1:8b")
        self.assertNotIn("think", servidor.requisicoes[-1])

    def test_raciocinio_que_nao_desliga_fica_registrado(self):
        with OllamaFalso(modelos=TODOS, pensa_sempre=("qwen3.8:27b",)) as endereco, \
                _config_modelos(OLLAMA_HOST=endereco), configuracao(REGISTRAR_INTERACOES=False):
            resposta = self._assistente("qwen3.8:27b").responder("Posso trancar?")
        self.assertGreater(resposta.estatisticas_llm["raciocinio_caracteres"], 0)
        self.assertNotIn("Vou ler", resposta.texto)              # o raciocínio não entra na resposta

    def test_aquecer_usa_as_mesmas_opcoes_e_descarregar_libera(self):
        servidor = OllamaFalso(modelos=TODOS, placa=1.0)
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco):
            assistente = self._assistente("llama3.2:3b")
            assistente.aquecer()
            self.assertEqual(servidor.carregados["llama3.2:3b"]["size_vram"], 0)   # carregou no processador
            assistente.descarregar()
            self.assertNotIn("llama3.2:3b", servidor.carregados)
        carga, descarga = servidor.requisicoes
        self.assertEqual(carga["options"]["num_gpu"], 0)
        self.assertEqual(descarga["keep_alive"], 0)

    def test_tempo_limite_do_modelo(self):
        with _config_modelos():
            assistente = self._assistente("qwen3.8:27b")
            self.assertEqual(assistente.cliente._client.timeout.read, 30)


class TestVerificarModelos(unittest.TestCase):
    def _rodar(self, argv=None, **falso) -> tuple[int, str, OllamaFalso]:
        servidor = OllamaFalso(**{"modelos": TODOS, "placa": 1.0, **falso})
        saida = io.StringIO()
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco), redirect_stdout(saida):
            codigo = verificar_modelos.main(argv or [])
        return codigo, saida.getvalue(), servidor

    def test_tudo_certo(self):
        codigo, texto, servidor = self._rodar(pensantes=("qwen3.8:27b",))
        self.assertEqual(codigo, 0, texto)
        self.assertIn("Tudo certo", texto)
        self.assertIn("Ollama 0.0.0-falso", texto)
        linhas = {l.split()[0] + l.split()[1]: l for l in texto.splitlines() if l.startswith(("Llama", "Qwen", "Juiz"))}
        self.assertIn("processador", linhas["Qwen3.8"])
        self.assertIn("placa de vídeo", linhas["Juiz7B"])
        self.assertIn("20,0 tokens/s", linhas["Llama3.1"])
        pedidos = {p["model"]: p for p in servidor.requisicoes if p.get("messages")}
        self.assertIs(pedidos["qwen3.8:27b"]["think"], False)
        self.assertEqual(pedidos["llama3.1:8b"]["options"]["num_gpu"], 0)
        self.assertNotIn("num_gpu", pedidos["juiz:7b"]["options"])              # o juiz usa a placa
        descargas = [p["model"] for p in servidor.requisicoes if p.get("keep_alive") == 0]
        self.assertEqual(descargas, ["llama3.1:8b", "qwen3.8:27b", "llama3.2:3b", "juiz:7b"])
        self.assertEqual(servidor.carregados, {})                              # nada fica na memória

    def test_comparado_na_placa_de_video_e_erro(self):
        codigo, texto, _ = self._rodar(ignora_num_gpu=("llama3.1:8b",))
        self.assertEqual(codigo, 1)
        self.assertIn("ERRO: Llama 3.1 8B (llama3.1:8b): rodou com 100% na placa de vídeo", texto)

    def test_juiz_sem_placa_de_video_e_aviso(self):
        codigo, texto, _ = self._rodar(placa=0.0)
        self.assertEqual(codigo, 0)
        self.assertIn("AVISO: Juiz 7B (juiz:7b): o juiz rodou no processador", texto)

    def test_juiz_dividido_entre_placa_e_processador_e_aviso(self):
        codigo, texto, _ = self._rodar(placa=0.6)
        self.assertEqual(codigo, 0)
        self.assertIn("só 60% do juiz coube na placa de vídeo", texto)

    def test_modelo_nao_instalado(self):
        codigo, texto, _ = self._rodar(modelos=("llama3.1:8b", "llama3.2:3b", "juiz:7b"))
        self.assertEqual(codigo, 1)
        self.assertIn("ollama pull qwen3.8:27b", texto)

    def test_raciocinio_que_nao_desliga_e_aviso(self):
        codigo, texto, _ = self._rodar(pensa_sempre=("qwen3.8:27b",))
        self.assertEqual(codigo, 0)
        self.assertIn("raciocinou mesmo com think=False", texto)

    def test_modelo_que_raciocina_sem_estar_marcado(self):
        codigo, texto, _ = self._rodar(pensa_sempre=("llama3.2:3b",))
        self.assertIn("marque \"raciocinio\": True", texto)

    def test_juiz_tambem_comparado_e_erro(self):
        servidor = OllamaFalso(modelos=TODOS, placa=1.0)
        saida = io.StringIO()
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco,
                                                  JUIZES=[{"modelo": "llama3.2:3b", "placa_de_video": True}]), \
                redirect_stdout(saida):
            codigo = verificar_modelos.main([])
        self.assertEqual(codigo, 1)
        self.assertIn("aparece como comparado e como juiz", saida.getvalue())

    def test_familia_repetida_e_erro_e_dois_juizes_na_placa(self):
        com_familia = {nome: {**info, "familia": "Llama" if nome.startswith("llama") else nome}
                       for nome, info in MODELOS_TESTE.items()}
        com_familia["juiz2:7b"] = {"rotulo": "Juiz 2", "raciocinio": True, "tempo_limite": 30, "familia": "J2"}
        servidor = OllamaFalso(modelos=TODOS + ("juiz2:7b",), placa=1.0, pensantes=("qwen3.8:27b", "juiz2:7b"))
        saida = io.StringIO()
        with servidor as endereco, _config_modelos(OLLAMA_HOST=endereco, MODELOS=com_familia,
                                                  JUIZES=[{"modelo": "juiz:7b", "placa_de_video": True},
                                                          {"modelo": "juiz2:7b", "placa_de_video": True}]), \
                redirect_stdout(saida):
            codigo = verificar_modelos.main([])
        texto = saida.getvalue()
        self.assertEqual(codigo, 1)
        self.assertIn("ERRO: Llama 3.1 8B (comparado) e Llama 3.2 3B (comparado) são da mesma família: Llama", texto)
        self.assertIn("Famílias:", texto)
        pedidos = {p["model"]: p for p in servidor.requisicoes if p.get("messages")}
        self.assertNotIn("num_gpu", pedidos["juiz2:7b"]["options"])           # os dois juízes usam a placa
        self.assertIs(pedidos["juiz2:7b"]["think"], False)                     # o juiz que pensa recebe think=False
        self.assertNotIn("raciocinou", texto)

    def test_so_os_modelos_pedidos(self):
        codigo, texto, servidor = self._rodar(argv=["qwen3.8:27b"])
        self.assertEqual(codigo, 0)
        self.assertEqual({p["model"] for p in servidor.requisicoes}, {"qwen3.8:27b"})

    def test_ollama_fechado(self):
        saida = io.StringIO()
        with _config_modelos(OLLAMA_HOST="http://127.0.0.1:9"), redirect_stdout(saida):
            codigo = verificar_modelos.main([])
        self.assertEqual(codigo, 1)
        self.assertIn("Abra o Ollama", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
