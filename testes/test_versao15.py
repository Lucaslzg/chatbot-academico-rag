"""Testes da versão 15: o juiz em português na rodada inteira.

O piloto de 14/11/2026 escolheu o juiz em português (os exemplos dos prompts
do RAGAS em português e a instrução de escrever a saída em português). Na
versão 13, ele só avaliava as respostas do piloto e não calculava a cobertura
dos trechos. Na versão 15, ele é o padrão da rodada inteira
(config.JUIZES_LINGUA), com a cobertura também em português; as notas e o
resumo dos juízes em português ficam em juizes_em_portugues/, e a tabela de
confiabilidade usa os juízes em português quando eles avaliaram a rodada
inteira, e os em inglês quando não.
"""
from __future__ import annotations

import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_ragas import TEM_RAGAS, _AvaliadorFalso, _JuizFalso
from test_rodada import MODELOS_TESTE, _ComRodada
from utilitarios import configuracao

import avaliar_ragas as ar
import avaliar_respostas as av
import config
import prompts_em_portugues as pp


class _AvaliadorEmPortugues(_AvaliadorFalso):
    lingua = "portugues"


@unittest.skipUnless(TEM_RAGAS, "RAGAS não instalado (instalar-avaliacao.bat)")
class TestCoberturaEmPortugues(unittest.TestCase):
    def test_os_exemplos_da_cobertura_traduzidos(self):
        from ragas.metrics.collections.context_recall.util import ContextRecallPrompt
        original = ContextRecallPrompt()
        textos = pp.textos_dos_exemplos(original)
        self.assertEqual(len(textos), 19)
        self.assertEqual([t for t in textos if t not in pp.TRADUCOES], [])
        traduzido = pp.em_portugues(original)
        self.assertEqual([t for t in pp.textos_dos_exemplos(traduzido) if t in pp.TRADUCOES], [])
        self.assertIn(pp.INSTRUCAO_EM_PORTUGUES, traduzido.instruction)
        exemplo = traduzido.examples[0]
        self.assertTrue(exemplo[0].answer.startswith(exemplo[1].classifications[0].statement))   # a estrutura fica
        self.assertEqual([c.attributed for c in exemplo[1].classifications], [1, 1, 0, 0])
        self.assertNotIn("\u2014", "".join(pp.TRADUCOES.values()))


class TestRodadaInteiraEmPortugues(_ComRodada):
    def _avaliar_em_portugues(self, pasta, juizes=("j1:1b", "j2:1b")):
        avaliadores = [_AvaliadorEmPortugues(juiz=j) for j in juizes]
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, list(MODELOS_TESTE), avaliadores)
        return resumo, avaliadores

    def test_notas_cobertura_e_resumo_na_pasta_do_portugues(self):
        pasta, _ = self.rodar()
        resumo, avaliadores = self._avaliar_em_portugues(pasta)
        self.assertIn(("cobertura", "Quantos trancamentos posso fazer?"), avaliadores[0].chamadas)
        self.assertEqual(resumo["lingua"], "portugues")
        self.assertEqual([j for j, _ in ar.pastas_dos_juizes(pasta, "portugues")], ["j1:1b", "j2:1b"])
        self.assertEqual(ar.pastas_dos_juizes(pasta), [])                      # nada nas pastas em inglês
        portugues = pasta / ar.PASTA_JUIZES_EM_PORTUGUES
        self.assertTrue((portugues / "ragas_juizes.md").exists())
        self.assertFalse((pasta / "ragas_juizes.md").exists())
        self.assertIn("Juízes em português", (portugues / "ragas_juizes.md").read_text(encoding="utf-8"))
        um_juiz = (ar.pasta_do_juiz(pasta, "j1:1b", "portugues") / "ragas_resumo.md").read_text(encoding="utf-8")
        self.assertIn("Cobertura dos trechos", um_juiz)                          # a rodada inteira, não o piloto
        self.assertIn("Comparação dos modelos", um_juiz)
        self.assertNotIn("só avaliou as respostas sorteadas para o piloto", um_juiz)

    def test_tabela_usa_os_juizes_em_portugues_da_rodada_inteira(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), [_AvaliadorFalso(juiz="j1:1b")])             # em inglês
        self._avaliar_em_portugues(pasta, ("j1:1b",))
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]):
            resultado = av.avaliar_rodada(pasta)
            self.assertEqual(resultado["lingua_dos_juizes"], "portugues")
            self.assertIn("dos juízes em português", av.texto_markdown(resultado))
            with configuracao(JUIZES_LINGUA="ingles"):
                self.assertEqual(av.avaliar_rodada(pasta)["lingua_dos_juizes"], "ingles")

    def test_juizes_em_portugues_so_do_piloto_ficam_fora_da_tabela(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), [_AvaliadorFalso(juiz="j1:1b")])
            resumo = ar.executar(pasta, list(MODELOS_TESTE), [_AvaliadorEmPortugues(juiz="j1:1b")],
                                 ids_por_modelo={m: {"P1"} for m in MODELOS_TESTE})
        self.assertIsNone(resumo)                                # só o piloto: sem resumo da rodada em português
        self.assertFalse((pasta / ar.PASTA_JUIZES_EM_PORTUGUES / "ragas_juizes.md").exists())
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]):
            self.assertEqual(av.avaliar_rodada(pasta)["lingua_dos_juizes"], "ingles")
        um_juiz = (ar.pasta_do_juiz(pasta, "j1:1b", "portugues") / "ragas_resumo.md").read_text(encoding="utf-8")
        self.assertIn("só avaliou as respostas sorteadas para o piloto", um_juiz)

    def test_a_lingua_da_linha_de_comando(self):
        pasta, _ = self.rodar()
        linguas = []

        def avaliador(juiz, lingua="ingles"):
            linguas.append(lingua)
            falso = _AvaliadorFalso(juiz=juiz.modelo)
            falso.lingua = lingua
            return falso

        def rodar(*opcoes):
            saida = io.StringIO()
            with configuracao(JUIZES=[{"modelo": "j1:1b"}]), \
                    mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                    mock.patch.object(ar, "_conferir_juiz"), mock.patch.object(ar, "AvaliadorRagas", side_effect=avaliador), \
                    redirect_stdout(saida):
                return ar.main(["--rodada", str(pasta), *opcoes]), saida.getvalue()

        self.assertEqual(config.JUIZES_LINGUA, "portugues")
        codigo, saida = rodar()
        self.assertEqual((codigo, linguas[-1]), (0, "portugues"))
        self.assertIn("(prompts em português)", saida)
        self.assertTrue((pasta / ar.PASTA_JUIZES_EM_PORTUGUES / "ragas_juizes.md").exists())
        codigo, saida = rodar("--ingles")
        self.assertEqual((codigo, linguas[-1]), (0, "ingles"))
        self.assertTrue((pasta / "ragas_juizes.md").exists())
        with configuracao(JUIZES_LINGUA="espanhol"):
            codigo, saida = rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("config.JUIZES_LINGUA", saida)

    def test_notas_em_portugues_e_em_ingles_nao_se_misturam(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), [_AvaliadorFalso(juiz="j1:1b", notas={"fidelidade": 0.25})])
        self._avaliar_em_portugues(pasta, ("j1:1b",))
        ingles = json.loads((pasta / "ragas_juizes.json").read_text(encoding="utf-8"))
        portugues = json.loads((pasta / ar.PASTA_JUIZES_EM_PORTUGUES / "ragas_juizes.json").read_text(encoding="utf-8"))
        media = {r["lingua"]: r["tabela"][0]["fidelidade"]["media"] for r in (ingles, portugues)}
        self.assertEqual(media, {"ingles": 0.25, "portugues": 0.5})


class TestAvaliacaoIncompleta(_ComRodada):
    """O que a revisão independente da versão 15 achou: médias de uma avaliação incompleta não entram sem aviso."""

    def _executar(self, pasta, avaliadores, **opcoes):
        with redirect_stdout(io.StringIO()):
            return ar.executar(pasta, list(MODELOS_TESTE), avaliadores, **opcoes)

    def test_portugues_interrompido_fica_fora_e_avisa(self):
        pasta, _ = self.rodar()
        self._executar(pasta, [_AvaliadorFalso(juiz="j1:1b"), _AvaliadorFalso(juiz="j2:1b")])          # inglês, tudo
        self._executar(pasta, [_AvaliadorEmPortugues(juiz="j1:1b")])                                    # português, tudo
        self._executar(pasta, [_AvaliadorEmPortugues(juiz="j2:1b")], limite=1)                          # português, parou
        with configuracao(JUIZES=[{"modelo": "j1:1b"}, {"modelo": "j2:1b"}]):
            self.assertEqual(ar.faltam_notas(pasta, "portugues")["j1:1b"], 0)
            self.assertGreater(ar.faltam_notas(pasta, "portugues")["j2:1b"], 0)
            resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["lingua_dos_juizes"], "ingles")
        markdown = av.texto_markdown(resultado)
        self.assertIn("os juízes em português ainda não avaliaram a rodada inteira", markdown)
        self.assertIn("Rode avaliar-ragas.bat para completar", markdown)
        resumo = (pasta / ar.PASTA_JUIZES_EM_PORTUGUES / "ragas_juizes.md").read_text(encoding="utf-8")
        self.assertIn("a avaliação dos juízes em português não está completa", resumo)

    def test_so_o_portugues_e_incompleto_mostra_as_medias_parciais_com_aviso(self):
        pasta, _ = self.rodar()
        self._executar(pasta, [_AvaliadorEmPortugues(juiz="j1:1b")], limite=1)
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]):
            resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["lingua_dos_juizes"], "portugues")
        self.assertTrue(any("não está completa" in a for a in resultado["avisos_dos_juizes"]))

    def test_os_avisos_dizem_o_comando_da_lingua_da_tabela(self):
        pasta, _ = self.rodar()
        self._executar(pasta, [_AvaliadorFalso(juiz="j1:1b")])                                        # só em inglês
        with redirect_stdout(io.StringIO()):
            av.main(["--rodada", str(pasta)])
        with open(pasta / av.ARQUIVO_REVISAR, encoding="utf-8-sig", newline="") as arquivo:
            linhas = list(csv.DictReader(arquivo, delimiter=";"))
        linhas[0][av.COLUNA_CONFERENCIA] = "corrigir para abstenção"
        with open(pasta / av.ARQUIVO_REVISAR, "w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]), delimiter=";")
            escritor.writeheader()
            escritor.writerows(linhas)
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]):
            markdown = av.texto_markdown(av.avaliar_rodada(pasta))
        self.assertIn("rode avaliar-ragas.bat --ingles, que refaz só essas", markdown)
        self.assertEqual(ar.comando_dos_juizes("portugues"), "avaliar-ragas.bat")

    def test_cobertura_em_portugues_leva_a_lingua_e_a_mensagem_aponta_a_pasta_certa(self):
        pasta, _ = self.rodar()
        saida = io.StringIO()
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]), \
                mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                mock.patch.object(ar, "_conferir_juiz"), \
                mock.patch.object(ar, "AvaliadorRagas", side_effect=lambda juiz, lingua: _AvaliadorEmPortugues(juiz=juiz.modelo)), \
                redirect_stdout(saida):
            self.assertEqual(ar.main(["--rodada", str(pasta)]), 0)
        self.assertIn(str(pasta / ar.PASTA_JUIZES_EM_PORTUGUES / "ragas_juizes.md"), saida.getvalue())
        cobertura = (ar.pasta_do_juiz(pasta, "j1:1b", "portugues") / ar.ARQUIVO_COBERTURA).read_text(encoding="utf-8")
        self.assertTrue(all(json.loads(l)["lingua"] == "portugues" for l in cobertura.splitlines() if l.strip()))


    def test_as_duas_incompletas_fica_a_que_tem_menos_notas_faltando(self):
        pasta, _ = self.rodar()
        self._executar(pasta, [_AvaliadorFalso(juiz="j1:1b", falhar_em={"Qual o valor da bolsa?"})])   # 1 com erro
        self._executar(pasta, [_AvaliadorEmPortugues(juiz="j1:1b")], ids_por_modelo={m: {"P1"} for m in MODELOS_TESTE})
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]):
            faltam_ingles, faltam_portugues = ar.faltam_notas(pasta, "ingles"), ar.faltam_notas(pasta, "portugues")
            resultado = av.avaliar_rodada(pasta)
        self.assertLess(sum(faltam_ingles.values()), sum(faltam_portugues.values()))
        self.assertGreater(sum(faltam_ingles.values()), 0)
        self.assertEqual(resultado["lingua_dos_juizes"], "ingles")
        avisos = " | ".join(resultado["avisos_dos_juizes"])
        self.assertIn("a avaliação dos juízes em inglês não está completa", avisos)
        self.assertIn("os juízes em português também não avaliaram a rodada inteira", avisos)

    def test_juiz_do_config_sem_pasta_na_lingua_conta_como_faltando(self):
        pasta, _ = self.rodar()
        self._executar(pasta, [_AvaliadorFalso(juiz="j1:1b"), _AvaliadorFalso(juiz="j2:1b")])
        self._executar(pasta, [_AvaliadorEmPortugues(juiz="j1:1b")])                        # o j2 não tem pasta em português
        with configuracao(JUIZES=[{"modelo": "j1:1b"}, {"modelo": "j2:1b"}]):
            self.assertGreater(ar.faltam_notas(pasta, "portugues")["j2:1b"], 0)
            self.assertEqual(av.avaliar_rodada(pasta)["lingua_dos_juizes"], "ingles")


if __name__ == "__main__":
    unittest.main()
