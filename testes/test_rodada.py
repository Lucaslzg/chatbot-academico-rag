"""Testes da rodada de avaliação (gerar_respostas.py) e da tabela de confiabilidade
(avaliar_respostas.py), com a busca simulada e o Ollama simulado."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from ollama_falso import OllamaFalso
from utilitarios import configuracao

import avaliar_respostas
import config
import consulta
import gerar_respostas as gr
from perguntas import carregar_perguntas
from recuperacao import Contexto, Passagem, Trecho

MODELOS_TESTE = {"modelo-a:1b": {"rotulo": "Modelo A", "raciocinio": False, "tempo_limite": 30},
                 "modelo-b:2b": {"rotulo": "Modelo B", "raciocinio": True, "tempo_limite": 30}}
CSV = ("id;pergunta;resposta_correta;sem_resposta\n"
       "P1;Quantos trancamentos posso fazer?;Quatro.;não\n"
       "P2;Qual o cardápio do RU hoje?;;sim\n"
       "P3;Qual o valor da bolsa?;;sim\n")


def _passagem(numero: int, texto: str) -> Passagem:
    return Passagem(numero, "norma.pdf", "Resolução de teste", texto, 3, 3, 37, 37, "CAPÍTULO I", "", 0.71,
                    [f"id{numero}"])


class _RecuperadorFalso:
    """Devolve um contexto pronto por pergunta e conta as buscas."""

    def __init__(self):
        self.buscas = []

    @staticmethod
    def modo_valido(modo=None):
        return "hibrida"

    def preparar(self, modo):
        pass

    def configuracao(self, modo, k):
        return {"modo_busca": modo, "top_k": k, "similaridade_minima": config.SIMILARIDADE_MINIMA}

    def recuperar(self, pergunta, k=None, modo=None):
        self.buscas.append(pergunta)
        if "cardápio" in pergunta:          # nada passou no limiar: abstenção antes do modelo
            return Contexto(pergunta, [], [Trecho("x", "texto qualquer", {"fonte": "norma.pdf"}, 0.3)], 0.3, True,
                            {"modo_busca": "hibrida"}, 0.01)
        passagens = [_passagem(1, "Art. 37 São permitidos 4 trancamentos totais."),
                     _passagem(2, "Art. 38 O trancamento parcial...")]
        return Contexto(pergunta, passagens, [Trecho("id1", passagens[0].texto, {"fonte": "norma.pdf"}, 0.71, 0.03, 1, 2)],
                        0.71, False, {"modo_busca": "hibrida"}, 0.02)


class _ComRodada(unittest.TestCase):
    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)
        self.arquivo = self.pasta / "perguntas_teste.csv"
        self.arquivo.write_text(CSV, encoding="utf-8")
        self._config = configuracao(AVALIACAO_DIR=self.pasta / "avaliacao", MODELOS=MODELOS_TESTE,
                                    MODELOS_COMPARACAO=list(MODELOS_TESTE), DOCS_DIR=self.pasta / "sem_docs",
                                    REGISTROS_DIR=self.pasta / "registros", SO_PROCESSADOR=True)
        self._config.__enter__()
        self.conjunto = carregar_perguntas(self.arquivo, documentos=[])
        self.recuperador = _RecuperadorFalso()

    def tearDown(self):
        self._config.__exit__(None, None, None)
        self._pasta.cleanup()

    def rodar(self, pasta_rodada=None, modelos=None, limite=None, agora=None):
        """Cria (ou continua) uma rodada e gera as respostas com o Ollama simulado."""
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), placa=1.0)
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco), redirect_stdout(io.StringIO()):
            if pasta_rodada is None:
                pasta_rodada = gr.criar_rodada(self.conjunto, modelos or list(MODELOS_TESTE), self.recuperador,
                                               limite, agora or datetime(2026, 11, 20, 9, 0))
            gr.executar(pasta_rodada, modelos or list(MODELOS_TESTE))
        return pasta_rodada, servidor


class TestRodada(_ComRodada):
    def test_rodada_completa(self):
        pasta, servidor = self.rodar()
        self.assertEqual(pasta.name, "2026-11-20_0900_perguntas_teste")
        configuracao_rodada = json.loads((pasta / "configuracao.json").read_text(encoding="utf-8"))
        self.assertEqual(configuracao_rodada["versao_chatbot"], config.VERSAO_CHATBOT)
        self.assertEqual(configuracao_rodada["perguntas"]["assinatura"], self.conjunto.assinatura)
        self.assertEqual(configuracao_rodada["busca"]["modo_busca"], "hibrida")
        self.assertEqual([m["modelo"] for m in configuracao_rodada["modelos"]], list(MODELOS_TESTE))
        self.assertEqual(configuracao_rodada["modelos"][0]["opcoes"]["num_gpu"], 0)
        self.assertEqual(configuracao_rodada["modelos"][1]["argumentos"], {"think": False})
        self.assertEqual(configuracao_rodada["modelos"][0]["rodou_em"], "processador")
        self.assertIn("Use SOMENTE", configuracao_rodada["prompt_sistema"])
        self.assertTrue((pasta / "perguntas_original.csv").exists())
        self.assertEqual(len(json.loads((pasta / "perguntas.json").read_text(encoding="utf-8"))), 3)
        self.assertEqual(len(json.loads((pasta / "contextos.json").read_text(encoding="utf-8"))), 3)
        # os trechos foram buscados uma vez só, não uma vez por modelo
        self.assertEqual(len(self.recuperador.buscas), 3)
        for modelo in MODELOS_TESTE:
            linhas = gr.ler_respostas(gr.arquivo_respostas(pasta, modelo))
            self.assertEqual([l["id"] for l in linhas], ["P1", "P2", "P3"])
            self.assertTrue(linhas[0]["citacao_explicita"])
            self.assertFalse(linhas[1]["gerada_pelo_llm"])          # abstenção antes do modelo
            self.assertTrue(linhas[1]["abstencao"])
            self.assertFalse(linhas[2]["abstencao"])                # o simulado responde mesmo sem base
        # cada modelo recebeu exatamente as mesmas mensagens para a mesma pergunta
        pedidos = [p for p in servidor.requisicoes if p.get("messages")]
        por_modelo = {}
        for p in pedidos:
            por_modelo.setdefault(p["model"], []).append(p["messages"])
        self.assertEqual(por_modelo["modelo-a:1b"], por_modelo["modelo-b:2b"])
        self.assertEqual(len(por_modelo["modelo-a:1b"]), 2)           # P2 nem chamou o modelo
        self.assertIs(next(p for p in pedidos if p["model"] == "modelo-b:2b")["think"], False)
        descargas = [p["model"] for p in servidor.requisicoes if p.get("keep_alive") == 0]
        self.assertEqual(descargas, list(MODELOS_TESTE))
        # a rodada não escreve no registro do chat
        self.assertFalse((self.pasta / "registros" / "interacoes.jsonl").exists())

    def test_continuar_depois_de_interromper(self):
        pasta, _ = self.rodar(modelos=["modelo-a:1b"])
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        # simula uma queda: a última resposta ficou pela metade e a anterior se perdeu
        arquivo.write_text(linhas[0] + "\n" + linhas[2][:25] + "\n", encoding="utf-8")
        buscas_antes = len(self.recuperador.buscas)
        self.rodar(pasta_rodada=pasta, modelos=["modelo-a:1b", "modelo-b:2b"])
        respostas = gr.ler_respostas(arquivo)
        self.assertEqual([r["id"] for r in respostas], ["P1", "P2", "P3"])
        self.assertEqual(respostas[0], json.loads(linhas[0]))           # a já gravada não mudou
        self.assertEqual(len(self.recuperador.buscas), buscas_antes)     # não buscou de novo
        configuracao_rodada = json.loads((pasta / "configuracao.json").read_text(encoding="utf-8"))
        self.assertEqual([m["modelo"] for m in configuracao_rodada["modelos"]], ["modelo-a:1b", "modelo-b:2b"])
        self.assertEqual(len(gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-b:2b"))), 3)

    def test_rodada_ja_completa_nao_chama_o_modelo(self):
        pasta, _ = self.rodar()
        _, servidor = self.rodar(pasta_rodada=pasta)
        self.assertEqual(servidor.requisicoes, [])

    def test_limite_e_pasta_que_ja_existe(self):
        agora = datetime(2026, 11, 20, 10, 30)
        primeira, _ = self.rodar(limite=2, agora=agora)
        segunda, _ = self.rodar(limite=2, agora=agora)
        self.assertEqual(primeira.name, "2026-11-20_1030_perguntas_teste_limite2")
        self.assertEqual(segunda.name, "2026-11-20_1030_perguntas_teste_limite2_2")
        self.assertEqual(len(json.loads((primeira / "contextos.json").read_text(encoding="utf-8"))), 2)
        self.assertTrue(primeira.exists())                                # nada foi sobrescrito

    def test_rodada_mais_recente(self):
        self.assertIsNone(gr.rodada_mais_recente())
        self.rodar(agora=datetime(2026, 11, 20, 9, 0))
        recente, _ = self.rodar(agora=datetime(2026, 11, 21, 8, 0))
        self.assertEqual(gr.rodada_mais_recente(), recente)

    def test_nome_do_arquivo_do_modelo(self):
        self.assertEqual(gr.nome_arquivo_modelo("qwen3.8:27b"), "qwen3.8_27b")
        self.assertEqual(gr.nome_arquivo_modelo("hf.co/x/y:Q4_K_M"), "hf.co_x_y_Q4_K_M")

    def test_main_com_perguntas_com_erro(self):
        ruim = self.pasta / "ruim.csv"
        ruim.write_text("id;pergunta\nA;um?\nA;dois?\n", encoding="utf-8")
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = gr.main(["--arquivo", str(ruim)])
        self.assertEqual(codigo, 1)
        self.assertIn("validar-perguntas.bat", saida.getvalue())

    def test_main_continuar_sem_rodada(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = gr.main(["--continuar"])
        self.assertEqual(codigo, 1)
        self.assertIn("nenhuma rodada", saida.getvalue())

    def test_main_interrompido_explica_como_continuar(self):
        pasta, _ = self.rodar(limite=1)
        saida = io.StringIO()
        with mock.patch.object(gr, "executar", side_effect=KeyboardInterrupt), redirect_stdout(saida):
            codigo = gr.main(["--rodada", str(pasta)])
        self.assertEqual(codigo, 1)
        self.assertIn("--rodada", saida.getvalue())
        self.assertIn(pasta.name, saida.getvalue())


class TestContextoCongelado(unittest.TestCase):
    def test_ida_e_volta(self):
        contexto = _RecuperadorFalso().recuperar("Quantos trancamentos posso fazer?")
        dados = json.loads(json.dumps(contexto.para_dict()))
        de_volta = Contexto.de_dict(dados)
        self.assertEqual(de_volta, contexto)
        self.assertEqual(consulta.mensagens_para(de_volta.pergunta, de_volta.passagens),
                         consulta.mensagens_para(contexto.pergunta, contexto.passagens))

    def test_chat_e_rodada_mandam_o_mesmo_ao_modelo(self):
        recuperador = _RecuperadorFalso()
        assistente = consulta.AssistenteRAG(recuperador=recuperador, cliente_llm=object())
        enviadas = []

        def gerar_falso(mensagens, ao_receber=None):
            enviadas.append(mensagens)
            return "São 4 [1].", {}

        with mock.patch.object(assistente, "gerar", gerar_falso), configuracao(REGISTRAR_INTERACOES=False):
            pelo_chat = assistente.responder("Quantos trancamentos posso fazer?")
            congelado = Contexto.de_dict(json.loads(json.dumps(pelo_chat.contexto.para_dict())))
            pela_rodada = assistente.responder_com_contexto(congelado, registrar=False)
        self.assertEqual(enviadas[0], enviadas[1])
        self.assertEqual((pelo_chat.texto, pelo_chat.citadas), (pela_rodada.texto, pela_rodada.citadas))
        self.assertIn("geracao_s", pela_rodada.tempos)


class TestConfiabilidade(_ComRodada):
    def test_tabela_da_rodada(self):
        pasta, _ = self.rodar()
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        linha = next(l for l in resultado["tabela"] if l["modelo"] == "modelo-a:1b")
        self.assertEqual((linha["respondidas"], linha["respondiveis"], linha["respondeu"]), (3, 1, 1))
        self.assertEqual((linha["sem_resposta"], linha["absteve_limiar_certo"], linha["absteve_modelo_certo"],
                          linha["respondeu_sem_base"]), (2, 1, 0, 1))
        self.assertEqual(linha["absteve_antes"] + linha["absteve_modelo"], 0)
        self.assertEqual(linha["taxa_resposta"], 1.0)
        self.assertEqual(linha["taxa_abstencao_certa"], 0.0)            # a única que chegou ao modelo foi respondida
        self.assertEqual(resultado["limiar"], config.SIMILARIDADE_MINIMA)
        self.assertEqual({(r["modelo"], r["id"]) for r in resultado["revisar"]},
                         {("modelo-a:1b", "P3"), ("modelo-b:2b", "P3")})
        self.assertIsNotNone(linha["tempo_medio_s"])
        self.assertIsNotNone(linha["tokens_por_s"])
        self.assertEqual(len(resultado["comparacoes"]), 2)                # 1 par x 2 critérios
        self.assertEqual(resultado["comparacoes"][0]["p"], 1.0)            # os dois se comportaram igual
        with redirect_stdout(io.StringIO()):
            codigo = avaliar_respostas.main(["--rodada", str(pasta)])
        self.assertEqual(codigo, 0)
        markdown = (pasta / "confiabilidade.md").read_text(encoding="utf-8")
        self.assertIn("Respondeu sem base (perigoso)", markdown)
        self.assertNotIn("\u2014", markdown)
        self.assertTrue((pasta / "confiabilidade.csv").read_text(encoding="utf-8-sig").startswith("modelo;Modelo"))

    def test_abstencao_do_modelo_e_contada_a_parte(self):
        pasta, _ = self.rodar()
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        linhas = gr.ler_respostas(arquivo)
        # a categoria é refeita sobre o texto (versão 10): o texto precisa ser o de uma abstenção
        linhas[0].update(resposta=config.MENSAGEM_ABSTENCAO, citadas=[], citacao_explicita=False, abstencao=True,
                         motivo_abstencao="modelo", categoria="abstencao")
        arquivo.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        linha = next(l for l in resultado["tabela"] if l["modelo"] == "modelo-a:1b")
        self.assertEqual((linha["respondeu"], linha["absteve_modelo"]), (0, 1))
        comparacao = next(c for c in resultado["comparacoes"] if c["criterio"].startswith("respondeu"))
        self.assertEqual((comparacao["so_a"], comparacao["so_b"]), ([], ["P1"]))

    def test_rodada_sem_respostas(self):
        with redirect_stdout(io.StringIO()):
            pasta = gr.criar_rodada(self.conjunto, list(MODELOS_TESTE), self.recuperador)
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = avaliar_respostas.main(["--rodada", str(pasta)])
        self.assertEqual(codigo, 1)
        self.assertIn("ainda não tem respostas", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
