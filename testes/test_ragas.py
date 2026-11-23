"""Testes da avaliação com o RAGAS (avaliar_ragas.py), dos dois juízes e dos testes estatísticos.

A lógica (quais respostas recebem nota, retomada, resumo, média e
concordância dos juízes) é testada com avaliadores falsos e não precisa do
RAGAS. Os testes da ligação com o RAGAS de verdade só rodam se ele estiver
instalado (instalar-avaliacao.bat); sem ele, aparecem como "skipped".
"""
from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from pydantic import BaseModel
from test_rodada import MODELOS_TESTE, _ComRodada
from utilitarios import configuracao

import avaliar_ragas as ar
import avaliar_respostas
import config
import gerar_respostas as gr
from estatistica import concordancia_de_notas, wilcoxon_pareado

TEM_RAGAS = importlib.util.find_spec("ragas") is not None


JUIZ_FALSO = "juiz-falso:1b"


class _JuizFalso:
    def __init__(self, modelo=JUIZ_FALSO):
        self.modelo = modelo
        self.descarregado = False

    def descarregar(self):
        self.descarregado = True


class _AvaliadorFalso:
    """Notas fixas, com a opção de falhar em algumas perguntas."""

    def __init__(self, falhar_em=(), conexao_cai=False, juiz=JUIZ_FALSO, notas=None):
        self.juiz = _JuizFalso(juiz)
        self.chamadas = []
        self.falhar_em = set(falhar_em)
        self.conexao_cai = conexao_cai
        self.notas = {"correcao": 0.75, "fidelidade": 0.5, "cobertura": 1.0, **(notas or {})}

    def _nota(self, tipo, pergunta, valor):
        self.chamadas.append((tipo, pergunta))
        if self.conexao_cai:
            raise ConnectionError("Ollama fechado")
        if pergunta in self.falhar_em:
            raise ValueError("saída que não pôde ser lida")
        return valor, [{"etapa": tipo, "saida": {"claims": ["x"]}}]

    def correcao(self, pergunta, resposta, referencia):
        return self._nota("correcao", pergunta, self.notas["correcao"])

    def fidelidade(self, pergunta, resposta, trechos):
        return self._nota("fidelidade", pergunta, self.notas["fidelidade"])

    def cobertura(self, pergunta, trechos, referencia):
        return self._nota("cobertura", pergunta, self.notas["cobertura"])


def _do_juiz(pasta, modelo, juiz=JUIZ_FALSO):
    """As notas que um juiz deu às respostas de um modelo (pasta do juiz, versão 09)."""
    return ar.ultimas_por_id(gr.ler_respostas(ar.arquivo_ragas(ar.pasta_do_juiz(pasta, juiz), modelo)))


class TestWilcoxon(unittest.TestCase):
    def test_todas_a_favor_do_primeiro(self):
        r = wilcoxon_pareado([1, 2, 3, 4, 5], [0, 0, 0, 0, 0])
        self.assertEqual((r["n"], r["w_mais"]), (5, 15.0))
        self.assertAlmostEqual(r["p"], 2 / 32)

    def test_diferencas_zero_saem_e_iguais_dao_um(self):
        self.assertEqual(wilcoxon_pareado([0.5, 0.5], [0.5, 0.5])["p"], 1.0)
        self.assertEqual(wilcoxon_pareado([0.5, 1.0, 0.2], [0.5, 0.0, 0.2])["n"], 1)
        self.assertEqual(wilcoxon_pareado([], [])["n"], 0)

    def test_empates_de_tamanho_com_postos_medios(self):
        # diferenças +0,5, -0,5, +0,5: postos 2, 2, 2; W+ = 4; trocas de sinal: 8, p = 2 x 4/8 = 1
        r = wilcoxon_pareado([1.0, 0.0, 1.0], [0.5, 0.5, 0.5])
        self.assertEqual(r["w_mais"], 4.0)
        self.assertEqual(r["p"], 1.0)

    def test_simetrico(self):
        a, b = [0.9, 0.1, 0.8, 0.3, 0.7, 0.2], [0.2, 0.6, 0.1, 0.9, 0.3, 0.4]
        self.assertAlmostEqual(wilcoxon_pareado(a, b)["p"], wilcoxon_pareado(b, a)["p"])

    def test_tamanhos_diferentes(self):
        with self.assertRaises(ValueError):
            wilcoxon_pareado([1, 2], [1])


class TestConcordancia(unittest.TestCase):
    def test_juizes_iguais(self):
        r = concordancia_de_notas([(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
        self.assertEqual((r["n"], r["pearson"], r["diferenca_media"]), (3, 1.0, 0.0))

    def test_juizes_opostos(self):
        r = concordancia_de_notas([(0.0, 1.0), (1.0, 0.0), (0.5, 0.5)])
        self.assertEqual(r["pearson"], -1.0)
        self.assertAlmostEqual(r["diferenca_media"], 0.667)

    def test_sem_variacao_ou_poucas_notas_nao_tem_correlacao(self):
        self.assertIsNone(concordancia_de_notas([(1.0, 0.5), (1.0, 0.2), (1.0, 0.9)])["pearson"])
        self.assertIsNone(concordancia_de_notas([(0.2, 0.4), (0.9, 0.7)])["pearson"])
        self.assertEqual(concordancia_de_notas([]), {"n": 0, "pearson": None, "diferenca_media": None})


class TestOpcoesDoJuiz(unittest.TestCase):
    def test_na_placa_de_video_e_deterministico(self):
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}], OLLAMA_NUM_CTX=8192, OLLAMA_SEED=42):
            opcoes = ar.opcoes_juiz()
        self.assertEqual(opcoes["temperature"], 0)
        self.assertEqual(opcoes["num_ctx"], 8192)
        self.assertEqual(opcoes["seed"], 42)
        self.assertNotIn("num_gpu", opcoes)

    def test_no_processador(self):
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": False}]):
            self.assertEqual(ar.opcoes_juiz()["num_gpu"], 0)

    def test_cada_juiz_com_as_suas_opcoes(self):
        with configuracao(JUIZES=[{"modelo": "a:1b", "placa_de_video": True, "max_tokens": 100},
                                  {"modelo": "b:1b", "placa_de_video": False, "max_tokens": 300}]):
            self.assertEqual(ar.opcoes_juiz("a:1b")["num_predict"], 100)
            self.assertNotIn("num_gpu", ar.opcoes_juiz("a:1b"))
            self.assertEqual(ar.opcoes_juiz("b:1b")["num_predict"], 300)
            self.assertEqual(ar.opcoes_juiz("b:1b")["num_gpu"], 0)
            self.assertEqual(ar.JuizOllama("b:1b", object()).opcoes["num_predict"], 300)


class _Saida(BaseModel):
    claims: list[str]


class _ClienteFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def chat(self, **kwargs):
        self.pedidos.append(kwargs)
        if not kwargs.get("messages"):
            return {"message": {"content": ""}}
        return {"message": {"content": self.respostas.pop(0)}}


class TestJuizOllama(unittest.TestCase):
    def test_saida_forcada_ao_esquema_e_registrada(self):
        cliente = _ClienteFalso(['{"claims": ["a", "b"]}'])
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            juiz = ar.JuizOllama("j:1b", cliente)
            objeto = juiz.generate("prompt", _Saida)
        self.assertEqual(objeto.claims, ["a", "b"])
        pedido = cliente.pedidos[0]
        self.assertEqual(pedido["format"]["title"], "_Saida")
        self.assertEqual(pedido["options"]["temperature"], 0)
        self.assertFalse(pedido["stream"])
        self.assertEqual(juiz.registro, [{"etapa": "_Saida", "saida": {"claims": ["a", "b"]}}])

    def test_saida_cortada_tenta_de_novo_com_mais_espaco(self):
        cliente = _ClienteFalso(['{"claims": ["a"', '{"claims": ["a"]}'])
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True, "max_tokens": 100}]):
            juiz = ar.JuizOllama("j:1b", cliente)
            self.assertEqual(juiz.generate("prompt", _Saida).claims, ["a"])
        self.assertEqual([p["options"]["num_predict"] for p in cliente.pedidos], [100, 200])

    def test_saida_invalida_duas_vezes_e_erro(self):
        cliente = _ClienteFalso(["não é json", "também não"])
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            with self.assertRaises(Exception):
                ar.JuizOllama("j:1b", cliente).generate("prompt", _Saida)

    def test_juiz_com_raciocinio_recebe_think_false(self):
        cliente = _ClienteFalso(['{"claims": []}'])
        with configuracao(MODELOS={"r:1b": {"rotulo": "R", "raciocinio": True}},
                          JUIZES=[{"modelo": "r:1b", "placa_de_video": True}]):
            ar.JuizOllama("r:1b", cliente).generate("prompt", _Saida)
        self.assertIs(cliente.pedidos[0]["think"], False)


class TestAvaliacaoDaRodada(_ComRodada):
    def test_quais_respostas_recebem_nota(self):
        pasta, _ = self.rodar()
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, list(MODELOS_TESTE), avaliador)
        # P1 tem resposta nos documentos e foi respondida: correção e fidelidade.
        # P2 (sem resposta) parou antes do modelo: nada. P3 (sem resposta) foi respondida: só fidelidade.
        por_tipo = {}
        for tipo, pergunta in avaliador.chamadas:
            por_tipo.setdefault(tipo, []).append(pergunta)
        self.assertEqual(por_tipo["cobertura"], ["Quantos trancamentos posso fazer?"])         # uma vez só
        self.assertEqual(por_tipo["correcao"], ["Quantos trancamentos posso fazer?"] * 2)       # os dois modelos
        self.assertEqual(sorted(set(por_tipo["fidelidade"])),
                         ["Qual o valor da bolsa?", "Quantos trancamentos posso fazer?"])
        linhas = _do_juiz(pasta, "modelo-a:1b")
        self.assertEqual(linhas["P1"]["correcao"]["valor"], 0.75)
        self.assertIsNone(linhas["P2"]["correcao"])
        self.assertIsNone(linhas["P3"]["correcao"])
        self.assertEqual(linhas["P3"]["fidelidade"]["valor"], 0.5)
        self.assertEqual(linhas["P1"]["correcao"]["detalhes"], [{"etapa": "correcao", "saida": {"claims": ["x"]}}])
        self.assertTrue(avaliador.juiz.descarregado)
        self.assertFalse(ar.arquivo_ragas(pasta, "modelo-a:1b").exists())          # nada solto na pasta da rodada
        tabela = {t["modelo"]: t for t in resumo["tabela"]}
        self.assertEqual(tabela["modelo-a:1b"]["correcao"]["media"], 0.75)
        self.assertEqual(tabela["modelo-a:1b"]["fidelidade"]["n"], 2)
        self.assertEqual(resumo["cobertura"]["media_dos_juizes"]["media"], 1.0)
        pasta_juiz = ar.pasta_do_juiz(pasta, JUIZ_FALSO)
        self.assertEqual(pasta_juiz.name, "juiz_juiz_falso_1b")
        markdown = (pasta_juiz / "ragas_resumo.md").read_text(encoding="utf-8")       # o resumo do juiz
        self.assertIn("Correção (F1) média", markdown)
        self.assertIn("Completude média", markdown)
        self.assertNotIn("\u2014", markdown)
        self.assertTrue((pasta_juiz / "ragas_resumo.csv").exists())
        juntos = (pasta / "ragas_juizes.md").read_text(encoding="utf-8")              # o dos juízes juntos
        self.assertIn("média dos juízes", juntos)
        self.assertNotIn("\u2014", juntos)
        self.assertTrue((pasta / "ragas_juizes.csv").exists() and (pasta / "ragas_juizes.json").exists())
        registro = json.loads((pasta_juiz / "ragas_configuracao.json").read_text(encoding="utf-8"))
        self.assertEqual([r["juiz"] for r in registro], [JUIZ_FALSO])
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorFalso())          # o mesmo juiz: não repete
        self.assertEqual(len(json.loads((pasta_juiz / "ragas_configuracao.json").read_text(encoding="utf-8"))), 1)

    def test_retoma_e_tenta_de_novo_so_as_que_falharam(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], _AvaliadorFalso(falhar_em={"Qual o valor da bolsa?"}))
        linhas = _do_juiz(pasta, "modelo-a:1b")
        self.assertTrue(linhas["P3"]["tem_erro"])
        self.assertIn("ValueError", linhas["P3"]["fidelidade"]["erro"])
        segundo = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, ["modelo-a:1b"], segundo)
        self.assertEqual(segundo.chamadas, [("fidelidade", "Qual o valor da bolsa?")])     # só a que falhou
        linhas = _do_juiz(pasta, "modelo-a:1b")
        self.assertFalse(linhas["P3"]["tem_erro"])
        self.assertEqual(resumo["tabela"][0]["erros_do_juiz"], {JUIZ_FALSO: 0})

    def test_resposta_vazia_nao_vai_ao_juiz(self):
        pasta, _ = self.rodar()
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        linhas = gr.ler_respostas(arquivo)
        linhas[0]["resposta"] = "   "
        arquivo.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        linha = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertTrue(linha["resposta_vazia"])
        self.assertIsNone(linha["correcao"])
        self.assertFalse(linha["tem_erro"])
        self.assertNotIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)

    def test_conexao_perdida_interrompe(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()), self.assertRaises(ConnectionError):
            ar.executar(pasta, ["modelo-a:1b"], _AvaliadorFalso(conexao_cai=True))
        self.assertFalse((pasta / gr.ARQUIVO_TRAVA).exists())                     # a trava sai mesmo assim

    def test_limite(self):
        pasta, _ = self.rodar()
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador, limite=1)
        self.assertEqual({p for _, p in avaliador.chamadas}, {"Quantos trancamentos posso fazer?"})

    def test_comparacao_dos_modelos(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorFalso())
        correcao = next(c for c in resumo["comparacoes"] if c["metrica"] == "correcao")
        self.assertEqual((correcao["perguntas"], correcao["p"]), (1, 1.0))        # notas iguais

    def test_tabela_de_confiabilidade_mostra_as_medias_dos_juizes(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), [_AvaliadorFalso(juiz="a:1b"),
                                                     _AvaliadorFalso(juiz="b:1b", notas={"correcao": 0.25})])
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        linha = next(t for t in resultado["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual(linha["correcao_media"], 0.5)                           # (0,75 + 0,25) / 2
        self.assertEqual(linha["fidelidade_media"], 0.5)
        self.assertIn("Correção (F1) média (juízes)", avaliar_respostas.texto_markdown(resultado))

    def test_tabela_ainda_le_a_rodada_avaliada_por_um_juiz_so(self):
        # versões 06 a 08: as notas do único juiz ficavam soltas na pasta da rodada
        pasta, _ = self.rodar()
        linha = {"id": "P1", "modelo": "modelo-a:1b", "juiz": "antigo:3b", "sem_resposta": False, "abstencao": False,
                 "correcao": {"valor": 0.4}, "fidelidade": {"valor": 0.9}, "tem_erro": False}
        ar.arquivo_ragas(pasta, "modelo-a:1b").write_text(json.dumps(linha) + "\n", encoding="utf-8")
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        tabela = {t["modelo"]: t for t in resultado["tabela"]}
        self.assertEqual(tabela["modelo-a:1b"]["correcao_media"], 0.4)
        self.assertIsNone(tabela["modelo-b:2b"]["correcao_media"])

    def test_main_sem_ragas_explica_como_instalar(self):
        pasta, _ = self.rodar()
        saida = io.StringIO()
        with mock.patch.object(ar, "_importar_ragas", side_effect=ar.ErroJuiz("rode instalar-avaliacao.bat")), \
                redirect_stdout(saida):
            codigo = ar.main(["--rodada", str(pasta)])
        self.assertEqual(codigo, 1)
        self.assertIn("instalar-avaliacao.bat", saida.getvalue())


class TestDoisJuizes(_ComRodada):
    def _avaliar(self, nota_b=0.25):
        pasta, _ = self.rodar()
        a = _AvaliadorFalso(juiz="a:1b", notas={"correcao": 0.75, "fidelidade": 0.5, "cobertura": 1.0})
        b = _AvaliadorFalso(juiz="b:1b", notas={"correcao": nota_b, "fidelidade": 0.5, "cobertura": 0.5})
        saida = io.StringIO()
        with redirect_stdout(saida):
            resumo = ar.executar(pasta, list(MODELOS_TESTE), [a, b])
        return pasta, resumo, a, b, saida.getvalue()

    def test_cada_juiz_avalia_tudo_na_sua_pasta(self):
        pasta, resumo, a, b, texto = self._avaliar()
        self.assertEqual(sorted(a.chamadas), sorted(b.chamadas))                  # as mesmas respostas
        self.assertTrue(a.juiz.descarregado and b.juiz.descarregado)
        self.assertEqual(_do_juiz(pasta, "modelo-a:1b", "a:1b")["P1"]["correcao"]["valor"], 0.75)
        self.assertEqual(_do_juiz(pasta, "modelo-a:1b", "b:1b")["P1"]["correcao"]["valor"], 0.25)
        self.assertTrue((ar.pasta_do_juiz(pasta, "a:1b") / "ragas_resumo.md").exists())
        self.assertTrue((ar.pasta_do_juiz(pasta, "b:1b") / "ragas_resumo.md").exists())
        self.assertEqual([j["modelo"] for j in resumo["juizes"]], ["a:1b", "b:1b"])
        self.assertIn("Juiz", texto)
        self.assertFalse((pasta / gr.ARQUIVO_TRAVA).exists())

    def test_media_por_resposta_e_por_juiz(self):
        _, resumo, *_ = self._avaliar()
        linha = next(t for t in resumo["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual(linha["correcao"]["media"], 0.5)
        self.assertEqual(linha["por_juiz"]["a:1b"]["correcao"]["media"], 0.75)
        self.assertEqual(linha["por_juiz"]["b:1b"]["correcao"]["media"], 0.25)
        self.assertEqual(resumo["cobertura"]["media_dos_juizes"]["media"], 0.75)

    def test_concordancia_entre_os_juizes(self):
        _, resumo, *_ = self._avaliar()
        correcao = next(c for c in resumo["concordancia"] if c["metrica"] == "correcao")
        self.assertEqual((correcao["juiz_a"], correcao["juiz_b"], correcao["n"]), ("a:1b", "b:1b", 2))
        self.assertEqual(correcao["diferenca_media"], 0.5)
        fidelidade = next(c for c in resumo["concordancia"] if c["metrica"] == "fidelidade")
        self.assertEqual(fidelidade["diferenca_media"], 0.0)

    def test_resposta_que_um_juiz_nao_avaliou_fica_fora_da_media(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], [_AvaliadorFalso(juiz="a:1b"),
                                                 _AvaliadorFalso(juiz="b:1b", falhar_em={"Qual o valor da bolsa?"})])
        resumo = ar.resumir_juizes(pasta)
        linha = next(t for t in resumo["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual(linha["por_juiz"]["a:1b"]["fidelidade"]["n"], 2)
        self.assertEqual(linha["por_juiz"]["b:1b"]["fidelidade"]["n"], 1)
        self.assertEqual(linha["fidelidade"]["n"], 1)                             # só a que os dois avaliaram
        self.assertEqual(linha["erros_do_juiz"], {"a:1b": 0, "b:1b": 1})

    def test_resumo_dos_juizes_em_markdown_e_csv(self):
        pasta, *_ = self._avaliar()
        texto = (pasta / "ragas_juizes.md").read_text(encoding="utf-8")
        self.assertIn("## Concordância entre os juízes", texto)
        self.assertIn("Correção (F1), a:1b", texto)
        self.assertIn("Completude, b:1b", texto)
        self.assertIn("correlação de Pearson", texto)
        self.assertNotIn("\u2014", texto)
        cabecalho = (pasta / "ragas_juizes.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
        self.assertEqual(cabecalho[:6], ["modelo", "rotulo", "correcao_media_juizes", "correcao_n",
                                         "correcao_a_1b", "correcao_b_1b"])

    def test_main_avisa_juiz_da_mesma_familia_e_avalia_com_todos(self):
        pasta, _ = self.rodar()
        modelos_teste = {**MODELOS_TESTE,
                         "modelo-a:1b": {**MODELOS_TESTE["modelo-a:1b"], "familia": "Família A"},
                         "j1:1b": {"rotulo": "Juiz 1", "familia": "Família A"},
                         "j2:1b": {"rotulo": "Juiz 2", "familia": "Família J"}}
        criados = []

        def criar(nome, cliente=None):
            criados.append(nome)
            return _JuizFalso(nome)

        class _Avaliador(_AvaliadorFalso):
            def __init__(self, juiz, lingua="ingles"):
                super().__init__(juiz=juiz.modelo)

        saida = io.StringIO()
        with configuracao(MODELOS=modelos_teste, JUIZES=[{"modelo": "j1:1b"}, {"modelo": "j2:1b"}]), \
                mock.patch.object(ar, "criar_juiz", side_effect=criar), \
                mock.patch.object(ar, "_conferir_juiz"), mock.patch.object(ar, "AvaliadorRagas", _Avaliador), \
                redirect_stdout(saida):
            codigo = ar.main(["--rodada", str(pasta), "--ingles"])
        self.assertEqual(codigo, 0, saida.getvalue())
        self.assertEqual(criados, ["j1:1b", "j2:1b"])
        self.assertIn("AVISO: Modelo A (comparado) e Juiz 1 (juiz) são da mesma família: Família A", saida.getvalue())
        self.assertTrue(ar.pasta_do_juiz(pasta, "j2:1b").is_dir())

    def test_modelo_sem_respostas_fica_de_fora(self):
        pasta, _ = self.rodar(modelos=["modelo-a:1b"])
        with configuracao(MODELOS={**MODELOS_TESTE, "parado:1b": {"rotulo": "Parado"}}):
            configuracao_rodada = json.loads((pasta / "configuracao.json").read_text(encoding="utf-8"))
            configuracao_rodada["modelos"].append({"modelo": "parado:1b"})        # entrou na rodada e não respondeu
            (pasta / "configuracao.json").write_text(json.dumps(configuracao_rodada), encoding="utf-8")
            saida = io.StringIO()
            with redirect_stdout(saida):
                ar.avaliar_modelo(pasta, "parado:1b", [], {}, _AvaliadorFalso())
            self.assertIn("Parado: nenhuma resposta nesta rodada.", saida.getvalue())
            usados = []
            with configuracao(JUIZES=[{"modelo": "j1:1b"}]), \
                    mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                    mock.patch.object(ar, "_conferir_juiz"), \
                    mock.patch.object(ar, "AvaliadorRagas", lambda juiz, lingua="ingles": _AvaliadorFalso(juiz=juiz.modelo)), \
                    mock.patch.object(ar, "executar", side_effect=lambda pasta, modelos, *a, **k: usados.extend(modelos)
                                      or {"rodada": "x", "calculado_em": "", "juizes": [], "cobertura": {
                                          "media_dos_juizes": {"media": None, "n": 0}, "por_juiz": {}},
                                          "tabela": [], "concordancia": [], "comparacoes": []}), \
                    redirect_stdout(io.StringIO()):
                ar.main(["--rodada", str(pasta)])
        self.assertEqual(usados, ["modelo-a:1b"])

    def test_main_so_um_juiz(self):
        pasta, _ = self.rodar()
        with configuracao(JUIZES=[{"modelo": "j1:1b"}, {"modelo": "j2:1b"}]), \
                mock.patch.object(ar, "criar_juiz", side_effect=lambda nome, cliente=None: _JuizFalso(nome)), \
                mock.patch.object(ar, "_conferir_juiz"), \
                mock.patch.object(ar, "AvaliadorRagas", lambda juiz, lingua="ingles": _AvaliadorFalso(juiz=juiz.modelo)), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(ar.main(["--rodada", str(pasta), "--juiz", "j2:1b", "--ingles"]), 0)
        self.assertEqual([j for j, _ in ar.pastas_dos_juizes(pasta)], ["j2:1b"])


@unittest.skipUnless(TEM_RAGAS, "RAGAS não instalado (instalar-avaliacao.bat)")
class TestComORagas(unittest.TestCase):
    """As métricas de verdade do RAGAS, com um juiz que devolve saídas prontas."""

    class _ClientePorEsquema:
        def __init__(self, veredicto=1):
            self.veredicto = veredicto
            self.titulos = []

        def chat(self, **kwargs):
            if not kwargs.get("messages"):
                return {"message": {"content": ""}}
            titulo = kwargs["format"]["title"]
            self.titulos.append(titulo)
            v = self.veredicto
            saidas = {
                "ClaimDecompositionOutput": {"claims": ["São permitidos 4 trancamentos totais."]},
                "StatementGeneratorOutput": {"statements": ["São permitidos 4 trancamentos totais."]},
                "NLIStatementOutput": {"statements": [{"statement": "São permitidos 4 trancamentos totais.",
                                                       "reason": "está no trecho", "verdict": v}]},
                "ContextRecallOutput": {"classifications": [{"statement": "Quatro trancamentos.",
                                                             "reason": "está no trecho", "attributed": v}]},
            }
            return {"message": {"content": json.dumps(saidas[titulo], ensure_ascii=False)}}

    def _avaliador(self, veredicto=1):
        cliente = self._ClientePorEsquema(veredicto)
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            juiz = ar.criar_juiz("j:1b", cliente)
        return ar.AvaliadorRagas(juiz), cliente

    def test_o_juiz_e_aceito_pelo_ragas(self):
        from ragas.llms.base import InstructorBaseRagasLLM
        avaliador, _ = self._avaliador()
        self.assertIsInstance(avaliador.juiz, InstructorBaseRagasLLM)

    def test_metricas_com_tudo_sustentado(self):
        avaliador, cliente = self._avaliador(veredicto=1)
        correcao, detalhes = avaliador.correcao("Quantos?", "São 4 [1].", "Quatro.")
        self.assertEqual(correcao, 1.0)
        self.assertEqual([d["etapa"] for d in detalhes],
                         ["ClaimDecompositionOutput", "NLIStatementOutput"] * 2)
        fidelidade, _ = avaliador.fidelidade("Quantos?", "São 4 [1].", ["Art. 37 São permitidos 4."])
        self.assertEqual(fidelidade, 1.0)
        cobertura, _ = avaliador.cobertura("Quantos?", ["Art. 37 São permitidos 4."], "Quatro.")
        self.assertEqual(cobertura, 1.0)

    def test_metricas_com_nada_sustentado(self):
        avaliador, _ = self._avaliador(veredicto=0)
        self.assertEqual(avaliador.correcao("Quantos?", "São 9.", "Quatro.")[0], 0.0)
        self.assertEqual(avaliador.fidelidade("Quantos?", "São 9.", ["Art. 37 São permitidos 4."])[0], 0.0)

    def test_completude_e_o_lado_conferido_contra_a_resposta(self):
        # versão 10: o juiz sustenta só as afirmações conferidas contra a resposta do modelo (o segundo lado da
        # conta do F1). O F1 dá zero e a completude, um: confirma a ordem dos lados no RAGAS de verdade.
        base = self._ClientePorEsquema

        class _Cliente(base):
            def chat(cliente, **kwargs):
                if kwargs.get("messages") and kwargs["format"]["title"] == "NLIStatementOutput":
                    cliente.veredicto = int("RESPOSTA-DO-MODELO" in kwargs["messages"][0]["content"])
                return base.chat(cliente, **kwargs)

        cliente = _Cliente()
        with configuracao(JUIZES=[{"modelo": "j:1b", "placa_de_video": True}]):
            avaliador = ar.AvaliadorRagas(ar.criar_juiz("j:1b", cliente))
        f1, detalhes = avaliador.correcao("Quantos?", "RESPOSTA-DO-MODELO: são 4.", "Quatro.")
        self.assertEqual(f1, 0.0)
        self.assertEqual(ar.completude(detalhes)["valor"], 1.0)
        avaliador_tudo, _ = self._avaliador(veredicto=1)
        self.assertEqual(ar.completude(avaliador_tudo.correcao("Quantos?", "São 4.", "Quatro.")[1])["valor"], 1.0)
        avaliador_nada, _ = self._avaliador(veredicto=0)
        self.assertEqual(ar.completude(avaliador_nada.correcao("Quantos?", "São 9.", "Quatro.")[1])["valor"], 0.0)


if __name__ == "__main__":
    unittest.main()
