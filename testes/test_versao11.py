"""Testes da versão 11: o juiz recebe os trechos com o cabeçalho que o modelo leu.

Até a versão 10, a fidelidade e a cobertura recebiam só o texto de cada
trecho, e a menção ao documento que o modelo leu no cabeçalho ("conforme a
Resolução nº 480") virava afirmação sem apoio. As notas da versão 10
aproveitam a correção e a completude, que não usam os trechos, e refazem a
fidelidade; a cobertura é refeita.
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from test_ragas import JUIZ_FALSO, _ClienteFalso, _do_juiz, _Saida
from utilitarios import configuracao
from test_rodada import _ComRodada
from test_versao10 import _AvaliadorQueGuarda

import avaliar_ragas as ar
import gerar_respostas as gr
from consulta import mensagem_usuario
from recuperacao import Passagem

TRECHO = {"numero": 2, "fonte": "res_480.pdf", "documento": "Resolução CONSUNI/UNIPAMPA nº 480, de 20 de agosto de 2026",
          "texto": "Art. 37. É permitido solicitar no máximo dois trancamentos totais.", "pagina_inicio": 9,
          "pagina_fim": 10, "artigo_inicio": 35, "artigo_fim": 38, "localizacao": "TÍTULO III, CAPÍTULO II",
          "secao": "Do trancamento de matrícula", "similaridade": 0.62, "ids": ["res_480.pdf#00059"]}


class _AvaliadorQueGuardaOsTrechos(_AvaliadorQueGuarda):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trechos = []

    def fidelidade(self, pergunta, resposta, trechos):
        self.trechos.append(("fidelidade", list(trechos)))
        return super().fidelidade(pergunta, resposta, trechos)

    def cobertura(self, pergunta, trechos, referencia):
        self.trechos.append(("cobertura", list(trechos)))
        return super().cobertura(pergunta, trechos, referencia)


class TestCabecalhoDosTrechos(unittest.TestCase):
    def test_igual_ao_que_o_modelo_le(self):
        for mudanca in ({}, {"pagina_fim": 9, "artigo_fim": 35}, {"artigo_inicio": None, "artigo_fim": None},
                        {"localizacao": "", "secao": ""}, {"secao": ""}):
            trecho = dict(TRECHO, **mudanca)
            prompt = mensagem_usuario("Pergunta?", [Passagem(**trecho)])
            linha_do_prompt = next(l for l in prompt.splitlines() if l.startswith("[2] "))
            self.assertEqual(ar.cabecalho_do_trecho(trecho), linha_do_prompt[len("[2] "):])

    def test_trecho_do_juiz_tem_o_cabecalho_e_o_texto(self):
        trechos = ar._trechos({"passagens": [TRECHO, dict(TRECHO, texto="")]})
        self.assertEqual(trechos, [ar.cabecalho_do_trecho(TRECHO) + "\n" + TRECHO["texto"]])
        self.assertIn("Resolução CONSUNI/UNIPAMPA nº 480", trechos[0])
        self.assertNotIn("[2]", trechos[0])                                         # sem o número do trecho


class TestPromptNoLimiteDaJanela(unittest.TestCase):
    def test_nota_marcada_quando_o_prompt_chega_perto_do_limite(self):
        class _ClienteQueConta(_ClienteFalso):
            def __init__(self, respostas, tokens):
                super().__init__(respostas)
                self.tokens = tokens

            def chat(self, **kwargs):
                resposta = super().chat(**kwargs)
                resposta["prompt_eval_count"] = self.tokens
                return resposta
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True, "max_tokens": 2048}], OLLAMA_NUM_CTX=8192):
            perto = ar.JuizOllama("j:1b", _ClienteQueConta(['{"claims": ["a"]}'], 6500))
            perto.generate("prompt", _Saida)
            longe = ar.JuizOllama("j:1b", _ClienteQueConta(['{"claims": ["a"]}'], 3000))
            longe.generate("prompt", _Saida)
        self.assertEqual(perto.registro[0]["aviso"], ar.PROMPT_NO_LIMITE)
        self.assertEqual(perto.registro[0]["tokens_do_prompt"], 6500)
        self.assertNotIn("aviso", longe.registro[0])
        medida = ar._medir(lambda: (0.5, perto.registro))
        self.assertEqual(medida["aviso"], ar.PROMPT_NO_LIMITE)
        self.assertIn("prompt no limite da janela", ar._descrever(medida))
        self.assertNotIn("aviso", ar._medir(lambda: (0.5, longe.registro)))


class TestAvaliacaoDaVersao11(_ComRodada):
    def _juiz(self, pasta):
        destino = ar.pasta_do_juiz(pasta, JUIZ_FALSO)
        destino.mkdir(exist_ok=True)
        return destino

    def _gravar(self, destino, modelo, linhas):
        ar.arquivo_ragas(destino, modelo).write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas),
                                                     encoding="utf-8")

    def _nota_da_versao_10(self, primeira):
        """A nota que a versão 10 deu à P1, com o texto julgado que a versão 11 também julga."""
        return {"id": "P1", "modelo": "modelo-a:1b", "juiz": JUIZ_FALSO, "metodo": "10", "sem_resposta": False,
                "categoria": primeira["categoria"], "abstencao": False, "texto_julgado": primeira["texto_julgado"],
                "correcao": {"valor": 0.33, "detalhes": [{"etapa": "da versão 10"}], "segundos": 40.0},
                "completude": {"valor": 1.0, "afirmacoes_da_resposta_correta": 2, "conferidas_pelo_juiz": 2,
                               "encontradas_na_resposta": 2},
                "fidelidade": {"valor": 0.0, "detalhes": [], "segundos": 30.0}, "tem_erro": False}

    def _primeira_avaliacao(self, pasta):
        """O que a avaliação de agora julga na P1 (para montar a nota antiga com o mesmo texto)."""
        avaliador = _AvaliadorQueGuardaOsTrechos()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        linha = _do_juiz(pasta, "modelo-a:1b")["P1"]
        ar.arquivo_ragas(ar.pasta_do_juiz(pasta, JUIZ_FALSO), "modelo-a:1b").unlink()
        (ar.pasta_do_juiz(pasta, JUIZ_FALSO) / ar.ARQUIVO_COBERTURA).unlink()
        return linha, avaliador

    def test_juiz_recebe_os_trechos_com_o_cabecalho(self):
        pasta, _ = self.rodar()
        linha, avaliador = self._primeira_avaliacao(pasta)
        self.assertEqual(linha["metodo"], ar.VERSAO_DO_METODO)
        contextos = gr.ler_contextos(pasta)
        esperado = ar._trechos(contextos["P1"])
        recebidos = dict((tipo, t) for tipo, t in avaliador.trechos)
        self.assertEqual(recebidos["fidelidade"], esperado)
        self.assertTrue(all(t.startswith("Documento: ") for t in recebidos["fidelidade"]))
        self.assertTrue(all(t.startswith("Documento: ") for t in recebidos["cobertura"]))

    def test_nota_da_versao_10_aproveita_a_correcao_e_refaz_a_fidelidade(self):
        pasta, _ = self.rodar()
        primeira, _ = self._primeira_avaliacao(pasta)
        destino = self._juiz(pasta)
        self._gravar(destino, "modelo-a:1b", [self._nota_da_versao_10(primeira)])
        avaliador = _AvaliadorQueGuardaOsTrechos()
        saida = io.StringIO()
        with redirect_stdout(saida):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        nova = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertEqual(nova["metodo"], ar.VERSAO_DO_METODO)
        self.assertEqual(nova["correcao"]["valor"], 0.33)                            # aproveitada
        self.assertEqual(nova["completude"]["valor"], 1.0)
        self.assertEqual(nova["correcao_do_metodo"], "10")
        self.assertEqual(nova["fidelidade"]["valor"], 0.5)                           # refeita, com o cabeçalho
        self.assertNotIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)
        self.assertIn(("fidelidade", "Quantos trancamentos posso fazer?"), avaliador.chamadas)
        self.assertIn("a correção e a completude já dadas são aproveitadas", saida.getvalue())
        self.assertIn("correção aproveitada 0.33", saida.getvalue())                 # sem o tempo da nota antiga
        linhas = gr.ler_respostas(ar.arquivo_ragas(destino, "modelo-a:1b"))
        self.assertEqual([l.get("metodo") for l in linhas if l["id"] == "P1"], ["10", ar.VERSAO_DO_METODO])

    def test_nova_tentativa_depois_de_erro_na_fidelidade_continua_aproveitando(self):
        pasta, _ = self.rodar()
        primeira, _ = self._primeira_avaliacao(pasta)
        destino = self._juiz(pasta)
        self._gravar(destino, "modelo-a:1b", [self._nota_da_versao_10(primeira)])
        falha = _AvaliadorQueGuardaOsTrechos(falhar_em={"Quantos trancamentos posso fazer?"})
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], falha)
        com_erro = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertTrue(com_erro["tem_erro"])                                      # a fidelidade falhou
        self.assertEqual(com_erro["correcao"]["valor"], 0.33)
        de_novo = _AvaliadorQueGuardaOsTrechos()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], de_novo)
        nova = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertFalse(nova["tem_erro"])
        self.assertEqual((nova["correcao"]["valor"], nova["correcao_do_metodo"]), (0.33, "10"))
        self.assertNotIn(("correcao", "Quantos trancamentos posso fazer?"), de_novo.chamadas)

    def test_correcao_refeita_quando_nao_vale_mais(self):
        pasta, _ = self.rodar()
        primeira, _ = self._primeira_avaliacao(pasta)
        destino = self._juiz(pasta)
        casos = {"erro na correção": {"correcao": {"valor": None, "erro": "ValueError"}, "tem_erro": True},
                 "outro texto julgado": {"texto_julgado": "Um texto que não é o de agora."},
                 "versão 09": {"metodo": None},
                 "outro juiz": {"juiz": "outro-juiz:7b"},
                 "a pergunta era sem resposta": {"sem_resposta": True},
                 "outra resposta correta": {"metodo": ar.VERSAO_DO_METODO, "tem_erro": True,
                                            "resposta_correta_assinatura": "0000000000000000"}}
        for nome, mudanca in casos.items():
            with self.subTest(nome):
                self._gravar(destino, "modelo-a:1b", [dict(self._nota_da_versao_10(primeira), **mudanca)])
                avaliador = _AvaliadorQueGuardaOsTrechos()
                with redirect_stdout(io.StringIO()):
                    ar.executar(pasta, ["modelo-a:1b"], avaliador)
                nova = _do_juiz(pasta, "modelo-a:1b")["P1"]
                self.assertEqual(nova["correcao"]["valor"], 0.75)                    # a do juiz de agora
                self.assertNotIn("correcao_do_metodo", nova)
                self.assertIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)

    def test_cobertura_de_metodo_anterior_e_refeita_e_fica_fora_das_medias(self):
        pasta, _ = self.rodar()
        destino = self._juiz(pasta)
        (destino / ar.ARQUIVO_CONFIGURACAO_JUIZ).write_text(json.dumps([{"juiz": JUIZ_FALSO}]), encoding="utf-8")
        antiga = {"id": "P1", "cobertura": {"valor": 0.0, "detalhes": []}, "juiz": JUIZ_FALSO}   # sem "metodo"
        (destino / ar.ARQUIVO_COBERTURA).write_text(json.dumps(antiga) + "\n", encoding="utf-8")
        self.assertEqual(ar.ler_cobertura(destino / ar.ARQUIVO_COBERTURA), {})
        self.assertIsNone(ar.resumir_juizes(pasta)["cobertura"]["por_juiz"][JUIZ_FALSO]["media"])
        avaliador = _AvaliadorQueGuardaOsTrechos()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        self.assertIn(("cobertura", "Quantos trancamentos posso fazer?"), avaliador.chamadas)
        linhas = gr.ler_respostas(destino / ar.ARQUIVO_COBERTURA)
        self.assertEqual([l.get("metodo") for l in linhas if l["id"] == "P1"], [None, ar.VERSAO_DO_METODO])
        self.assertEqual(ar.resumir_juizes(pasta)["cobertura"]["por_juiz"][JUIZ_FALSO]["media"], 1.0)
        segundo = _AvaliadorQueGuardaOsTrechos()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], segundo)
        self.assertEqual(segundo.chamadas, [])                                       # não refaz de novo


if __name__ == "__main__":
    unittest.main()
