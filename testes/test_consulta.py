"""Testes da consulta: citações, abstenção, prompt e geração a partir do Contexto da busca.

Os testes da montagem do contexto (vizinhos, títulos, limite de texto) estão em
test_recuperacao.py, junto com o código que eles testam.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utilitarios import configuracao

import config
import consulta


class TestCitacoesEAbstencao(unittest.TestCase):
    def test_formatos_de_citacao(self):
        texto = "Pode trancar [1]. Veja [2][3], [1, 4] e [2 e 5]. Ignora [9] e [0]."
        self.assertEqual(consulta.extrair_citacoes(texto, 5), [1, 2, 3, 4, 5])

    def test_abstencao_exata_e_parafraseada(self):
        self.assertTrue(consulta.eh_abstencao(config.MENSAGEM_ABSTENCAO, []))
        self.assertTrue(consulta.eh_abstencao("Não encontrei essa informação nos documentos.", []))
        self.assertFalse(consulta.eh_abstencao("O prazo é de 5 dias úteis.", []))

    def test_resposta_com_citacao_nao_e_abstencao(self):
        texto = "Não encontrei o valor da taxa, mas o prazo é de 5 dias [1]."
        self.assertFalse(consulta.eh_abstencao(texto, [1]))

    def test_resposta_mista(self):
        # registro de 21/09/2026: deu as horas dos dois PPCs, com citações, e
        # terminou com a frase de abstenção
        texto = ("Segundo o trecho [1], são 120 horas; no trecho [3], 75 horas.\n\n"
                 f"Portanto, a resposta mais próxima seria: \"{config.MENSAGEM_ABSTENCAO}\"")
        self.assertTrue(consulta.eh_resposta_mista(texto, [1, 3]))
        self.assertFalse(consulta.eh_abstencao(texto, [1, 3]))       # tem resposta citada
        self.assertFalse(consulta.eh_resposta_mista(config.MENSAGEM_ABSTENCAO, []))   # abstenção pura
        self.assertFalse(consulta.eh_resposta_mista("O prazo é de 5 dias [1].", [1]))

    def test_prompt_tem_regras_de_resposta_parcial_e_versoes(self):
        prompt = consulta.prompt_sistema()
        self.assertIn("mesmo que só em parte, não escreva essa frase", prompt)
        self.assertIn("duas versões do PPC", prompt)

    def test_prompt_contem_regras_e_trechos_numerados(self):
        p = consulta.Passagem(1, "res.pdf", "Resolução nº 29", "Art. 48 O Trancamento...", 10, 11, 47, 48,
                              "TÍTULO III, CAPÍTULO IV", "Do trancamento de matrícula", 0.61)
        mensagem = consulta.mensagem_usuario("Posso trancar?", [p])
        self.assertIn("[1] Documento: Resolução nº 29 | p. 10-11 | TÍTULO III, CAPÍTULO IV "
                      "(Do trancamento de matrícula) | Arts. 47 a 48", mensagem)
        self.assertIn("Pergunta: Posso trancar?", mensagem)
        self.assertIn(config.MENSAGEM_ABSTENCAO, consulta.prompt_sistema())
        self.assertEqual(p.referencia(), "res.pdf, p. 10-11, Arts. 47 a 48")


class _RecuperadorFalso:
    """Entrega um Contexto pronto, sem base vetorial e sem modelo de embeddings."""

    def __init__(self, contexto):
        self.contexto = contexto
        self.perguntas = []

    def recuperar(self, pergunta):
        self.perguntas.append(pergunta)
        return self.contexto


class TestAssistenteComContextoPronto(unittest.TestCase):
    """A geração só depende do Contexto: não abre a base nem carrega o modelo de embeddings."""

    def test_erros_da_busca_continuam_sendo_erros_do_chatbot(self):
        # quem trata ErroChatbot (o chat, a futura API) continua recebendo a base vazia
        self.assertTrue(issubclass(consulta.ErroBaseVazia, consulta.ErroChatbot))
        self.assertTrue(issubclass(consulta.ErroOllama, consulta.ErroChatbot))

    def test_abstencao_previa_nao_chama_o_llm(self):
        contexto = consulta.Contexto("Qual é a capital da França?", [], [], 0.42, True, {"modo_busca": "hibrida"})
        assistente = consulta.AssistenteRAG(recuperador=_RecuperadorFalso(contexto), cliente_llm=object())
        with configuracao(REGISTRAR_INTERACOES=False), \
                mock.patch.object(assistente, "gerar", side_effect=AssertionError("o LLM não pode ser chamado")):
            resposta = assistente.responder("Qual é a capital da França?")
        self.assertTrue(resposta.abstencao)
        self.assertEqual(resposta.motivo_abstencao, "similaridade_baixa")
        self.assertFalse(resposta.gerada_pelo_llm)
        self.assertEqual(resposta.texto, config.MENSAGEM_ABSTENCAO)

    def test_gera_com_os_trechos_do_contexto_e_registra_a_busca(self):
        passagem = consulta.Passagem(1, "res.pdf", "Resolução nº 29", "Art. 48 O trancamento...", 10, 11, 47, 48,
                                     "TÍTULO III", "Do trancamento", 0.61)
        contexto = consulta.Contexto("Posso trancar?", [passagem], [], 0.61, False, {"modo_busca": "hibrida"})
        assistente = consulta.AssistenteRAG(recuperador=_RecuperadorFalso(contexto), cliente_llm=object())
        enviadas = []

        def gerar_falso(mensagens, ao_receber=None):
            enviadas.append(mensagens)
            return "Pode trancar [1].", {}

        with tempfile.TemporaryDirectory() as pasta, configuracao(REGISTROS_DIR=Path(pasta)), \
                mock.patch.object(assistente, "gerar", gerar_falso):
            resposta = assistente.responder("Posso trancar?")
            registro = json.loads((Path(pasta) / "interacoes.jsonl").read_text(encoding="utf-8"))
        self.assertIn("[1] Documento: Resolução nº 29 | p. 10-11", enviadas[0][1]["content"])
        self.assertEqual(resposta.citadas, [1])
        self.assertEqual(resposta.fontes(), [passagem])
        self.assertIs(resposta.contexto, contexto)
        self.assertEqual(registro["configuracao"]["modo_busca"], "hibrida")
        self.assertEqual(registro["configuracao"]["modelo_llm"], config.OLLAMA_MODEL)


if __name__ == "__main__":
    unittest.main()
