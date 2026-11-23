"""Testes da versão 13: o juiz em português, só nas respostas do piloto, e o piloto com as duas línguas lado a lado.

Os juízes em inglês escrevem cerca de metade das afirmações em inglês e às
vezes traduzem errado. A versão 13 deixa rodar os mesmos juízes com os
exemplos dos prompts do RAGAS em português e a instrução de escrever a saída
em português, só nas respostas sorteadas para o piloto, numa subpasta da
rodada (juizes_em_portugues/juiz_<juiz>), sem misturar com as notas em inglês
nem nesta versão nem nas anteriores; o piloto compara as duas versões com a
avaliação humana.
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import test_ragas
from test_piloto import JUIZES, MODELOS, _ComRodadaDoPiloto
from test_ragas import JUIZ_FALSO, TEM_RAGAS, _AvaliadorFalso, _do_juiz, _JuizFalso
from test_rodada import MODELOS_TESTE, _ComRodada
from utilitarios import configuracao

import avaliar_ragas as ar
import avaliar_respostas
import gerar_respostas as gr
import piloto
import prompts_em_portugues as pp

P1 = "Quantos trancamentos posso fazer?"


class _AvaliadorEmPortugues(_AvaliadorFalso):
    lingua = "portugues"


def _cliente_que_guarda():
    """O cliente do Ollama de mentira do test_ragas, guardando os prompts que o juiz recebeu."""
    base = test_ragas.TestComORagas._ClientePorEsquema

    class _Cliente(base):
        def __init__(self):
            super().__init__()
            self.prompts = []

        def chat(self, **kwargs):
            if kwargs.get("messages"):
                self.prompts.append((kwargs["format"]["title"], kwargs["messages"][0]["content"]))
            return base.chat(self, **kwargs)

    return _Cliente()


@unittest.skipUnless(TEM_RAGAS, "RAGAS não instalado (instalar-avaliacao.bat)")
class TestPromptsEmPortugues(unittest.TestCase):
    def _prompts(self):
        from ragas.metrics.collections.factual_correctness import util as correcao
        from ragas.metrics.collections.faithfulness import util as fidelidade
        return {
            correcao.ClaimDecompositionPrompt: [
                correcao.ClaimDecompositionInput(response="Você tem 8 dias de licença.", atomicity=a, coverage=c)
                for a in ("low", "high") for c in ("low", "high")],
            correcao.NLIStatementPrompt: [correcao.NLIStatementInput(context="Trecho.", statements=["Afirmação."])],
            fidelidade.StatementGeneratorPrompt: [fidelidade.StatementGeneratorInput(question="Pergunta?",
                                                                                     answer="Resposta.")],
            fidelidade.NLIStatementPrompt: [fidelidade.NLIStatementInput(context="Trecho.", statements=["Afirmação."])],
        }

    def test_todos_os_exemplos_traduzidos_e_o_original_intacto(self):
        for classe, entradas in self._prompts().items():
            original = classe()
            antes = [original.to_string(e) for e in entradas]
            novo = pp.em_portugues(original)
            self.assertFalse(set(pp.textos_dos_exemplos(original)) - set(pp.TRADUCOES))
            self.assertEqual(novo.language, "portuguese")
            for entrada, texto_antes in zip(entradas, antes):
                texto = novo.to_string(entrada)
                self.assertTrue(texto.startswith(original.instruction.rstrip() + "\n" + pp.INSTRUCAO_EM_PORTUGUES))
                self.assertEqual([t for t in pp.TRADUCOES if t in texto], [], classe.__name__)   # nada em inglês
                self.assertEqual(original.to_string(entrada), texto_antes)                     # o original não muda
                self.assertEqual(classe().to_string(entrada), texto_antes)                      # nem a classe
                if hasattr(entrada, "atomicity"):           # as opções do RAGAS nos exemplos não são traduzidas
                    self.assertEqual(texto.count(f'"atomicity": "{entrada.atomicity}"'), 3)    # 2 exemplos e a entrada
        nli = pp.em_portugues(next(c for c in self._prompts() if c.__name__ == "NLIStatementPrompt")())
        self.assertIn('"statement": "John cursa Biologia."', nli._generate_examples())    # a mesma tradução nos dois
        self.assertIn('"John cursa Biologia."', nli._generate_examples().split("Output:")[0])   # lados do exemplo

    def test_traducao_que_falta_vira_erro_do_juiz(self):
        from ragas.metrics.collections.faithfulness import util as fidelidade
        falta = pp.textos_dos_exemplos(fidelidade.StatementGeneratorPrompt())[0]
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            juiz = ar.criar_juiz("j:1b", _cliente_que_guarda())
        with mock.patch.dict(pp.TRADUCOES):
            del pp.TRADUCOES[falta]
            with self.assertRaises(pp.TraducaoIncompleta) as erro:
                pp.em_portugues(fidelidade.StatementGeneratorPrompt())
            self.assertIn("sem tradução", str(erro.exception))
            with self.assertRaises(ar.ErroJuiz) as erro:
                ar.AvaliadorRagas(juiz, lingua="portugues")
            self.assertIn("requirements-avaliacao.txt", str(erro.exception))
            self.assertEqual(ar.AvaliadorRagas(juiz).lingua, "ingles")       # em inglês, não precisa da tradução
        self.assertIn(falta, pp.TRADUCOES)

    def test_o_juiz_recebe_os_prompts_em_portugues(self):
        cliente = _cliente_que_guarda()
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            avaliador = ar.AvaliadorRagas(ar.criar_juiz("j:1b", cliente), lingua="portugues")
        self.assertEqual(avaliador.correcao("Quantos?", "São 4.", "Quatro.")[0], 1.0)
        self.assertEqual(avaliador.fidelidade("Quantos?", "São 4.", ["Art. 37 São permitidos 4."])[0], 1.0)
        self.assertEqual([t for t, _ in cliente.prompts], ["ClaimDecompositionOutput", "NLIStatementOutput"] * 2
                         + ["StatementGeneratorOutput", "NLIStatementOutput"])
        for titulo, prompt in cliente.prompts:
            self.assertIn(pp.INSTRUCAO_EM_PORTUGUES, prompt)
            self.assertEqual([t for t in pp.TRADUCOES if t in prompt], [], titulo)
        self.assertIn("Charles Babbage foi um matemático, filósofo e crítico gastronômico francês.", cliente.prompts[0][1])
        self.assertIn("John cursa Biologia.", cliente.prompts[1][1])
        self.assertIn("Quem foi Albert Einstein e pelo que ele é mais conhecido?", cliente.prompts[4][1])
        avaliador.cobertura("Quantos?", ["Art. 37 São permitidos 4."], "Quatro.")   # em português desde a versão 15
        titulo, prompt = cliente.prompts[-1]
        self.assertEqual(titulo, "ContextRecallOutput")
        self.assertIn(pp.INSTRUCAO_EM_PORTUGUES, prompt)
        self.assertIn("O que você pode me dizer sobre Albert Einstein?", prompt)
        self.assertEqual([t for t in pp.TRADUCOES if t in prompt], [])
        em_ingles_cliente = _cliente_que_guarda()               # o juiz em inglês continua com o RAGAS como vem
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            em_ingles = ar.AvaliadorRagas(ar.criar_juiz("j:1b", em_ingles_cliente))
        em_ingles.correcao("Quantos?", "São 4.", "Quatro.")
        em_ingles.cobertura("Quantos?", ["Art. 37 São permitidos 4."], "Quatro.")
        self.assertNotIn(pp.INSTRUCAO_EM_PORTUGUES, em_ingles_cliente.prompts[0][1])
        self.assertIn("Charles Babbage was a French mathematician, philosopher, and food critic.",
                      em_ingles_cliente.prompts[0][1])


class TestJuizEmPortugues(_ComRodada):
    def _piloto(self, pasta, amostra):
        destino = pasta / ar.PASTA_PILOTO
        destino.mkdir(exist_ok=True)
        (destino / ar.ARQUIVO_CHAVE_PILOTO).write_text(json.dumps({"amostra": amostra}), encoding="utf-8")

    def test_lingua_que_nao_existe(self):
        with self.assertRaises(ValueError):
            ar.AvaliadorRagas(_JuizFalso(), lingua="espanhol")

    def test_pasta_separada_sem_cobertura_e_sem_o_resumo_da_rodada(self):
        pasta, _ = self.rodar()
        avaliador = _AvaliadorEmPortugues()
        saida = io.StringIO()
        with redirect_stdout(saida):
            resumo = ar.executar(pasta, list(MODELOS_TESTE), avaliador, ids_por_modelo={"modelo-a:1b": {"P1", "P3"}})
        self.assertIsNone(resumo)
        self.assertIn("em português", saida.getvalue())
        destino = ar.pasta_do_juiz(pasta, JUIZ_FALSO, "portugues")
        self.assertEqual(destino.relative_to(pasta).as_posix(), "juizes_em_portugues/juiz_juiz_falso_1b")
        self.assertFalse(ar.pasta_do_juiz(pasta, JUIZ_FALSO).exists())            # nada na pasta do juiz em inglês
        self.assertNotIn("cobertura", {t for t, _ in avaliador.chamadas})
        self.assertFalse((destino / ar.ARQUIVO_COBERTURA).exists())
        self.assertFalse((pasta / "ragas_juizes.md").exists())                    # o resumo da rodada não muda
        linhas = ar.ultimas_por_id(gr.ler_respostas(ar.arquivo_ragas(destino, "modelo-a:1b")))
        self.assertEqual(set(linhas), {"P1", "P3"})
        self.assertTrue(all(l["lingua"] == "portugues" for l in linhas.values()))
        self.assertEqual(linhas["P1"]["correcao"]["valor"], 0.75)
        self.assertFalse(ar.arquivo_ragas(destino, "modelo-b:2b").exists())       # modelo sem resposta sorteada
        registro = json.loads((destino / ar.ARQUIVO_CONFIGURACAO_JUIZ).read_text(encoding="utf-8"))
        self.assertEqual([(r["juiz"], r["lingua"]) for r in registro], [(JUIZ_FALSO, "portugues")])
        texto = (destino / "ragas_resumo.md").read_text(encoding="utf-8")
        self.assertIn("Juiz em português (versão 13)", texto)
        for trecho in ("Cobertura dos trechos", "Wilcoxon", "\u2014"):   # só as respostas do piloto: nada disso
            self.assertNotIn(trecho, texto)
        with redirect_stdout(io.StringIO()):                                       # de novo: nada a refazer
            ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorEmPortugues(), ids_por_modelo={"modelo-a:1b": {"P1"}})
        self.assertEqual(len(json.loads((destino / ar.ARQUIVO_CONFIGURACAO_JUIZ).read_text(encoding="utf-8"))), 1)

    def test_juiz_em_portugues_fica_fora_do_resumo_e_da_confiabilidade(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            antes = ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorFalso())
            ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorEmPortugues(notas={"correcao": 0.0, "fidelidade": 0.0}),
                        ids_por_modelo={"modelo-a:1b": {"P1"}, "modelo-b:2b": {"P1"}})
        self.assertNotIn("lingua", _do_juiz(pasta, "modelo-a:1b")["P1"])          # a nota em inglês, como na 12
        self.assertEqual([j for j, _ in ar.pastas_dos_juizes(pasta)], [JUIZ_FALSO])
        self.assertEqual([(j, c.relative_to(pasta).as_posix()) for j, c in ar.pastas_dos_juizes(pasta, "portugues")],
                         [(JUIZ_FALSO, "juizes_em_portugues/juiz_juiz_falso_1b")])
        # as versões até a 12 leem toda pasta juiz_* da rodada como um juiz em inglês: a em português não está ali
        self.assertEqual([c.name for c in pasta.glob("juiz_*")], ["juiz_juiz_falso_1b"])
        self.assertEqual(ar.resumir_juizes(pasta, "portugues")["juizes"][0]["pasta"],
                         "juizes_em_portugues/juiz_juiz_falso_1b")
        self.assertEqual(ar.resumir_juizes(pasta)["tabela"], antes["tabela"])
        em_portugues = ar.resumir_juizes(pasta, "portugues")
        self.assertEqual(next(t for t in em_portugues["tabela"] if t["modelo"] == "modelo-a:1b")["correcao"]["media"],
                         0.0)
        resultado = avaliar_respostas.avaliar_rodada(pasta)                        # a tabela de confiabilidade
        self.assertEqual(next(t for t in resultado["tabela"] if t["modelo"] == "modelo-a:1b")["correcao_media"], 0.75)

    def test_so_piloto_avalia_so_as_respostas_sorteadas(self):
        pasta, _ = self.rodar()
        self._piloto(pasta, [{"codigo": "P01", "modelo": "modelo-b:2b", "id": "P1"}])
        ids = ar.ids_do_piloto(pasta)
        self.assertEqual(ids, {"modelo-b:2b": {"P1"}})
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), avaliador, ids_por_modelo=ids)
        self.assertEqual(avaliador.chamadas, [("correcao", P1), ("fidelidade", P1)])      # sem a cobertura
        self.assertEqual(set(_do_juiz(pasta, "modelo-b:2b")), {"P1"})
        self.assertEqual(_do_juiz(pasta, "modelo-a:1b"), {})

    def test_correcao_nao_passa_de_uma_lingua_para_a_outra(self):
        item = {"id": "P1", "sem_resposta": False, "resposta_correta": "Quatro."}
        anterior = {"metodo": ar.VERSAO_DO_METODO, "juiz": JUIZ_FALSO, "sem_resposta": False, "categoria": "resposta",
                    "texto_julgado": "São 4.", "correcao": {"valor": 1.0},
                    "resposta_correta_assinatura": ar._assinatura("Quatro.")}
        self.assertTrue(ar._correcao_aproveitavel(anterior, item, "resposta", "São 4.", JUIZ_FALSO))
        self.assertFalse(ar._correcao_aproveitavel(anterior, item, "resposta", "São 4.", JUIZ_FALSO, "portugues"))
        em_portugues = dict(anterior, lingua="portugues")
        self.assertTrue(ar._correcao_aproveitavel(em_portugues, item, "resposta", "São 4.", JUIZ_FALSO, "portugues"))
        self.assertFalse(ar._correcao_aproveitavel(em_portugues, item, "resposta", "São 4.", JUIZ_FALSO))

    def test_main(self):
        pasta, _ = self.rodar()
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(ar.main(["--rodada", str(pasta), "--portugues", "--ingles"]), 1)   # as duas línguas
            self.assertEqual(ar.main(["--rodada", str(pasta), "--so-piloto"]), 1)       # sem piloto na rodada
        self.assertIn("use --portugues ou --ingles", saida.getvalue())
        self.assertIn("preparar-piloto.bat", saida.getvalue())
        self._piloto(pasta, [{"codigo": "P01", "modelo": "modelo-a:1b", "id": "P1"},
                             {"codigo": "P02", "modelo": "modelo-b:2b", "id": "P1"}])
        linguas = []

        def avaliador(juiz, lingua="ingles"):
            linguas.append(lingua)
            falso = _AvaliadorFalso(juiz=juiz.modelo)
            falso.lingua = lingua
            return falso

        saida = io.StringIO()
        with configuracao(JUIZES=[{"modelo": "j1:1b"}, {"modelo": "j2:1b"}]), \
                mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                mock.patch.object(ar, "_conferir_juiz"), mock.patch.object(ar, "AvaliadorRagas", side_effect=avaliador), \
                redirect_stdout(saida):
            codigo = ar.main(["--rodada", str(pasta), "--portugues", "--so-piloto"])
        self.assertEqual(codigo, 0, saida.getvalue())
        self.assertEqual(linguas, ["portugues", "portugues"])
        self.assertIn("Só as respostas sorteadas para o piloto: Modelo A: 1, Modelo B: 1.", saida.getvalue())
        self.assertIn("avaliar-piloto.bat", saida.getvalue())
        self.assertFalse((pasta / "ragas_juizes.md").exists())
        self.assertEqual([j for j, _ in ar.pastas_dos_juizes(pasta, "portugues")], ["j1:1b", "j2:1b"])
        self.assertEqual(ar.pastas_dos_juizes(pasta), [])

    def test_so_piloto_com_limite_e_modelo_fora_da_chave(self):
        pasta, _ = self.rodar()
        self._piloto(pasta, [{"codigo": "P01", "modelo": "modelo-a:1b", "id": "P1"},
                             {"codigo": "P02", "modelo": "modelo-a:1b", "id": "P3"}])
        saida = io.StringIO()
        with configuracao(JUIZES=[{"modelo": "j1:1b"}]), \
                mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                mock.patch.object(ar, "_conferir_juiz"), \
                mock.patch.object(ar, "AvaliadorRagas", lambda juiz, lingua="ingles": _AvaliadorFalso(juiz=juiz.modelo)), \
                redirect_stdout(saida):
            codigo = ar.main(["--rodada", str(pasta), "--so-piloto", "--limite", "1", "--ingles"])
        self.assertEqual(codigo, 0, saida.getvalue())
        self.assertIn("AVISO: Modelo B (modelo-b:2b) não tem resposta sorteada para o piloto e fica de fora.",
                      saida.getvalue())
        self.assertIn("Só as respostas sorteadas para o piloto, nas 1 primeiras perguntas: Modelo A: 1.",
                      saida.getvalue())
        self.assertEqual(set(_do_juiz(pasta, "modelo-a:1b", "j1:1b")), {"P1"})

    def test_chave_do_piloto_ilegivel(self):
        pasta, _ = self.rodar()
        self._piloto(pasta, [])
        (pasta / ar.PASTA_PILOTO / ar.ARQUIVO_CHAVE_PILOTO).write_text('{"amostra": [{"codigo": "P01"', encoding="utf-8")
        with self.assertRaises(gr.ErroRodada) as erro:
            ar.ids_do_piloto(pasta)
        self.assertIn("a chave do piloto", str(erro.exception))
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.assertEqual(ar.main(["--rodada", str(pasta), "--so-piloto"]), 1)
        self.assertIn("ERRO: a chave do piloto", saida.getvalue())

    def test_duas_pastas_do_mesmo_juiz_sao_recusadas(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], _AvaliadorFalso())
        original = ar.pasta_do_juiz(pasta, JUIZ_FALSO)
        copia = pasta / (original.name + " - Copia")                 # o que o Explorador do Windows faz ao copiar
        copia.mkdir()
        for arquivo in original.iterdir():
            (copia / arquivo.name).write_bytes(arquivo.read_bytes())
        with self.assertRaises(gr.ErroRodada) as erro:
            ar.pastas_dos_juizes(pasta)
        self.assertIn("duas pastas do juiz juiz-falso:1b", str(erro.exception))
        resultado = io.StringIO()
        with redirect_stdout(resultado):
            self.assertEqual(avaliar_respostas.main(["--rodada", str(pasta)]), 1)
        self.assertIn("duas pastas do juiz", resultado.getvalue())


class TestPilotoComAsDuasLinguas(_ComRodadaDoPiloto):
    def notas_em_portugues(self, juiz, valores):
        """As notas de um juiz em português: valores = {(modelo, id): (correção, completude, fidelidade)}."""
        destino = ar.pasta_do_juiz(self.pasta, juiz, "portugues")
        destino.mkdir(parents=True, exist_ok=True)
        (destino / ar.ARQUIVO_CONFIGURACAO_JUIZ).write_text(json.dumps([{"juiz": juiz, "lingua": "portugues"}]),
                                                            encoding="utf-8")
        for modelo in MODELOS:
            linhas = [{"id": i, "modelo": m, "juiz": juiz, "metodo": ar.VERSAO_DO_METODO, "lingua": "portugues",
                       "correcao": {"valor": c}, "completude": {"valor": comp}, "fidelidade": {"valor": f},
                       "tem_erro": False} for (m, i), (c, comp, f) in valores.items() if m == modelo]
            ar.arquivo_ragas(destino, modelo).write_text("".join(json.dumps(l) + "\n" for l in linhas),
                                                         encoding="utf-8")

    def _avaliar(self, juizes_em_portugues=tuple(JUIZES)):
        self.preparar()
        amostra = self.chave()["amostra"]
        humanas, em_ingles, em_portugues = {}, {}, {}
        niveis = [(2, 1.0), (1, 0.5), (0, 0.0)]
        for n, item in enumerate(amostra):
            nivel, nota = niveis[n % 3]
            humanas[item["codigo"]] = (("incorreta", "parcial", "correta")[nivel], ("infiel", "parcial", "fiel")[nivel])
            em_portugues[(item["modelo"], item["id"])] = (nota, nota, nota)              # concorda em tudo
            em_ingles[(item["modelo"], item["id"])] = (nota, 1.0 - nota, nota)           # a completude ao contrário
        for juiz in JUIZES:
            self.notas_de_juiz(juiz, em_ingles)
        for juiz in juizes_em_portugues:
            self.notas_em_portugues(juiz, em_portugues)
        self.preencher(humanas)
        return piloto.comparar(self.pasta), amostra

    def _diferenca(self, resultado, comparacao, avaliador):
        return next(d for d in resultado["diferencas"] if d["comparacao"] == comparacao and d["avaliador"] == avaliador)

    def test_lado_a_lado_e_portugues_menos_ingles(self):
        resultado, amostra = self._avaliar()
        self.assertEqual(resultado["linguas"], ["ingles", "portugues"])
        primeira = [r["avaliador"] for r in resultado["resultados"] if (r["humana"], r["metrica_do_juiz"])
                    == ("correcao", "correcao")]
        self.assertEqual(primeira, ["juiz-a:1b", "juiz-a:1b|pt", "juiz-b:1b", "juiz-b:1b|pt", "media_dos_juizes",
                                    "media_dos_juizes|pt"])
        rotulos = {r["avaliador"]: r["rotulo"] for r in resultado["resultados"]}
        self.assertEqual(rotulos["juiz-a:1b"], "Juiz Um, em inglês")
        self.assertEqual(rotulos["juiz-a:1b|pt"], "Juiz Um, em português")
        self.assertEqual(rotulos["media_dos_juizes|pt"], "média dos juízes, em português")
        completude_pt = next(r for r in resultado["resultados"] if r["avaliador"] == "media_dos_juizes|pt"
                             and r["metrica_do_juiz"] == "completude")
        self.assertEqual((completude_pt["n"], completude_pt["kappa_ponderado"], completude_pt["spearman"]), (10, 1.0, 1.0))
        self.assertEqual(completude_pt["lingua"], "portugues")
        for avaliador in ("juiz-a:1b", "media_dos_juizes"):
            completude = self._diferenca(resultado, "português menos inglês: completude", avaliador)
            self.assertEqual(completude["spearman"], 2.0)                            # +1 em português, -1 em inglês
            self.assertGreater(completude["kappa"], 1.0)
            self.assertGreater(completude["spearman_ic95"][0], 0)
            self.assertEqual(self._diferenca(resultado, "português menos inglês: fidelidade", avaliador)["spearman"], 0.0)
        self.assertEqual(self._diferenca(resultado, "português menos inglês: completude", "media_dos_juizes")["rotulo"],
                         "média dos juízes")
        f1_menos = {d["avaliador"] for d in resultado["diferencas"] if d["comparacao"] == "F1 menos completude"}
        self.assertEqual(f1_menos, set(primeira))                                     # dentro de cada língua
        self.assertEqual(self._diferenca(resultado, "F1 menos completude", "juiz-a:1b|pt")["spearman"], 0.0)
        self.assertEqual(self._diferenca(resultado, "F1 menos completude", "juiz-a:1b|pt")["linguas"], ["portugues"])
        self.assertEqual(self._diferenca(resultado, "F1 menos completude", "juiz-a:1b")["linguas"], ["ingles"])
        self.assertEqual(self._diferenca(resultado, "português menos inglês: completude", "juiz-a:1b")["linguas"],
                         ["portugues", "ingles"])
        self.assertIsNone(resultado["aviso_das_linguas"])
        contra_a_media = self._diferenca(resultado, "juiz menos a média: completude", "juiz-b:1b|pt")
        self.assertEqual(contra_a_media["spearman"], 0.0)                             # contra a média em português
        self.assertNotIn("kappa", contra_a_media)
        self.assertIn("juiz-a:1b|pt", resultado["itens"][0]["juizes"])
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        for trecho in ("Cada juiz aparece duas vezes", "português menos inglês: completude", "Português menos inglês:",
                       "Juiz Um, em português", "(média dos juízes, em inglês; média dos juízes, em português)",
                       "correção x completude (média dos juízes, em português)", "todo acima de zero",
                       "colunas: a média dos juízes)"):
            self.assertIn(trecho, texto)
        # na tabela por modelo e nas matrizes, o inglês antes do português em cada comparação
        self.assertLess(texto.index("correção x completude (média dos juízes, em inglês)"),
                        texto.index("correção x completude (média dos juízes, em português)"))
        self.assertNotIn("\u2014", texto)

    def test_sem_o_juiz_em_portugues_fica_como_na_versao_12(self):
        resultado, _ = self._avaliar(juizes_em_portugues=())
        self.assertEqual(resultado["linguas"], ["ingles"])
        self.assertFalse([r for r in resultado["resultados"] if r["avaliador"].endswith(piloto.SUFIXO_PORTUGUES)])
        self.assertFalse([d for d in resultado["diferencas"] if d["comparacao"].startswith("português")])
        self.assertEqual({r["rotulo"] for r in resultado["resultados"]}, {"Juiz Um", "Juiz Dois", "média dos juízes"})
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        self.assertNotIn("português", texto)
        self.assertIn("## Por modelo: nível do juiz menos o da pessoa, em média (média dos juízes)", texto)

    def test_um_juiz_so_em_portugues(self):
        # juizes-em-portugues.bat --juiz juiz-a:1b, ou o outro juiz parou: os juízes não são os mesmos nas duas línguas
        resultado, _ = self._avaliar(juizes_em_portugues=("juiz-a:1b",))
        self.assertNotIn("media_dos_juizes|pt", {r["avaliador"] for r in resultado["resultados"]})
        em_portugues = {d["avaliador"] for d in resultado["diferencas"] if d["comparacao"].startswith("português")}
        self.assertEqual(em_portugues, {"juiz-a:1b"})                                  # sem média em português
        self.assertFalse([d for d in resultado["diferencas"]
                          if d["comparacao"].startswith("juiz menos") and d["avaliador"].endswith("|pt")])
        # na tabela por modelo e nas matrizes, o juiz que está nas duas línguas, e não a média contra um juiz só
        self.assertEqual(piloto._principais([r["avaliador"] for r in resultado["resultados"]]),
                         ["juiz-a:1b", "juiz-a:1b|pt"])
        self.assertIn("os juízes não são os mesmos nas duas línguas", resultado["aviso_das_linguas"])
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        for trecho in ("(Juiz Um, em inglês; Juiz Um, em português)", "colunas: o juiz)",
                       "Juízes em inglês, com os prompts do RAGAS como vêm: Juiz Um e Juiz Dois. Em português",
                       "a regra da língua, que usa a média dos juízes, não pode ser aplicada", "sem --juiz"):
            self.assertIn(trecho, texto)
        self.assertNotIn("Cada juiz aparece duas vezes", texto)
        self.assertLess(texto.index("correção x completude (Juiz Um, em inglês)"),
                        texto.index("correção x completude (Juiz Um, em português)"))

    def test_media_nao_se_compara_com_juizes_diferentes(self):
        # os dois em inglês e, em português, o juiz um e outro juiz: as duas médias não são dos mesmos juízes
        with configuracao(MODELOS={**piloto.config.MODELOS, "juiz-c:1b": {"rotulo": "Juiz Três"}}):
            resultado, _ = self._avaliar(juizes_em_portugues=("juiz-a:1b", "juiz-c:1b"))
        self.assertIn("media_dos_juizes|pt", {r["avaliador"] for r in resultado["resultados"]})
        em_portugues = {d["avaliador"] for d in resultado["diferencas"] if d["comparacao"].startswith("português")}
        self.assertEqual(em_portugues, {"juiz-a:1b"})
        self.assertIsNotNone(resultado["aviso_das_linguas"])


class TestIntervaloDaDiferenca(unittest.TestCase):
    def test_lado_do_zero_sem_arredondar(self):
        self.assertEqual(piloto.lado_do_zero((-0.31, -0.004)), "abaixo")
        self.assertEqual(piloto.lado_do_zero((0.004, 0.52)), "acima")
        self.assertEqual(piloto.lado_do_zero((-0.2, 0.3)), "passa")
        self.assertEqual(piloto.lado_do_zero((0.0, 0.3)), "passa")                   # o zero está no intervalo
        self.assertIsNone(piloto.lado_do_zero(None))
        self.assertEqual(piloto._ic_da_diferenca((-0.31, -0.004)), " (-0,31 a -0,004; todo abaixo de zero)")
        self.assertEqual(piloto._ic_da_diferenca((0.004, 0.52)), " (0,004 a 0,52; todo acima de zero)")
        self.assertEqual(piloto._ic_da_diferenca((-0.2, 0.3)), " (-0,20 a 0,30)")
        self.assertEqual(piloto._ic_da_diferenca(None), "")


if __name__ == "__main__":
    unittest.main()
