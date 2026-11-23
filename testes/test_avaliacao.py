"""Testes da avaliação da busca (avaliar_recuperacao.py) e do arquivo de perguntas.

Rodar da pasta do projeto:  python -m unittest discover -s testes -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from utilitarios import RAIZ, ModeloEmbeddingsFalso, configuracao, criar_ppc_sintetico  # noqa: F401

import avaliar_recuperacao as av
import config
import ingestao
import recuperacao
import vetorial
from test_recuperacao import PERGUNTA, _recuperador

RES480 = "Res_480-2026_Normas_dos_Processos_Academicos_da_Graduacao.pdf"
RES29 = "Res_029-2011_Normas_Basicas_de_Graduacao_consolidada_ate_Res_480-2026.pdf"
PPC = "PPC_EngComp_Bage_2023_revisao_2024-01-02.pdf"
CAL = "Calendario_Academico_Graduacao_2026_Portaria_1602-2025.pdf"


def _meta(fonte, texto="", pagina=1, pagina_fim=None, artigos=None):
    m = {"fonte": fonte, "texto": texto, "pagina": pagina, "pagina_fim": pagina_fim or pagina}
    if artigos:
        m["artigo_inicio"], m["artigo_fim"] = artigos
    return m


class TestCriteriosDeRelevancia(unittest.TestCase):
    def test_artigos_do_documento_certo(self):
        item = {"fonte": RES480, "artigos": [37]}
        self.assertTrue(av.relevante(_meta(RES480, artigos=(36, 38)), item))
        self.assertFalse(av.relevante(_meta(RES480, artigos=(39, 40)), item))
        self.assertFalse(av.relevante(_meta(RES29, artigos=(36, 38)), item))   # mesmo artigo, outra norma
        self.assertFalse(av.relevante(_meta(RES480), item))                    # fragmento sem artigo

    def test_alternativas(self):
        # frequência mínima: Res. 480/2026, Art. 53, ou Res. 29/2011, Art. 59
        item = {"alternativas": [{"fonte": RES480, "artigos": [53]}, {"fonte": RES29, "artigos": [59]}]}
        self.assertTrue(av.relevante(_meta(RES29, artigos=(59, 59)), item))
        self.assertTrue(av.relevante(_meta(RES480, artigos=(52, 53)), item))
        self.assertFalse(av.relevante(_meta(RES480, artigos=(59, 59)), item))

    def test_paginas(self):
        item = {"fonte": PPC, "paginas": [406, 410]}
        self.assertTrue(av.relevante(_meta(PPC, pagina=405, pagina_fim=406), item))
        self.assertFalse(av.relevante(_meta(PPC, pagina=411), item))

    def test_trecho_sem_diferenciar_acentos_e_espacos(self):
        item = {"fonte": CAL, "trecho": "TRANCAMENTO TOTAL 2026/1"}
        texto = "23/02 a 10/04 | Trancamento   total 2026/1: Período para solicitação."
        self.assertTrue(av.relevante(_meta(CAL, texto=texto), item))
        self.assertFalse(av.relevante(_meta(CAL, texto="TRANCAMENTO PARCIAL 2026/1"), item))

    def test_criterios_combinados_valem_juntos(self):
        item = {"fonte": PPC, "paginas": [406, 410], "trecho": "mínimo"}
        self.assertTrue(av.relevante(_meta(PPC, "Grupo II (mínimo 8h, máximo 29h)", pagina=409), item))
        self.assertFalse(av.relevante(_meta(PPC, "Monitoria | 60 | Certificado", pagina=409), item))
        self.assertFalse(av.relevante(_meta(PPC, "carga horária mínima", pagina=93), item))

    def test_pergunta_sem_criterio_nao_acerta_nada(self):
        self.assertFalse(av.relevante(_meta(PPC, "qualquer texto"), {"id": "X", "pergunta": "?"}))

    def test_descricao_do_esperado(self):
        item = {"alternativas": [{"fonte": RES480, "artigos": [53]}, {"fonte": PPC, "paginas": [406, 410]}]}
        self.assertEqual(av.descrever_esperado(item), f"{RES480}, Art. 53 | {PPC}, p. 406-410")


class TestMetricas(unittest.TestCase):
    def test_acerto_contexto_e_mrr(self):
        itens = [{"id": "R1", "pergunta": "a?", "fonte": RES480, "artigos": [37]},
                 {"id": "R2", "pergunta": "b?", "fonte": RES480, "artigos": [53]},
                 {"id": "N1", "pergunta": "c?", "sem_resposta": True}]
        recuperados = [[(_meta(RES480, artigos=(10, 10)), 0.8), (_meta(RES480, artigos=(37, 37)), 0.7)],
                       [(_meta(RES480, artigos=(1, 1)), 0.6)],
                       [(_meta(RES480, artigos=(1, 1)), 0.3)]]
        res = av.avaliar_resultados(itens, recuperados, k=4)
        self.assertEqual((res["n_respondiveis"], res["n_sem_resposta"]), (2, 1))
        self.assertEqual(res["acerto_1"], 0.0)
        self.assertEqual(res["acerto_k"], 0.5)
        self.assertEqual(res["contexto_k"], 0.5)
        self.assertAlmostEqual(res["mrr"], 0.25)         # (1/2 + 0) / 2
        self.assertEqual(res["linhas"][0]["esperado"], f"{RES480}, Art. 37")

    def test_lista_de_recuperados_no_resultado(self):
        # desde 21/09/2026 o JSON guarda o que veio no lugar do trecho esperado
        itens = [{"id": "R1", "pergunta": "a?", "fonte": RES480, "artigos": [37]},
                 {"id": "N1", "pergunta": "c?", "sem_resposta": True}]
        outro = dict(_meta(RES480, artigos=(10, 12)), texto="Art. 10 O discente...", id=f"{RES480}#00003")
        certo = dict(_meta(RES480, artigos=(37, 37)), texto="Art. 37 Ao longo do curso...")
        res = av.avaliar_resultados(itens, [[(outro, 0.81234), (certo, 0.7)], [(outro, 0.3)]], k=4)
        lista = res["linhas"][0]["recuperados"]
        self.assertEqual(len(lista), 2)
        self.assertEqual(lista[0]["artigos"], "Arts. 10 a 12")
        self.assertEqual(lista[0]["similaridade"], 0.8123)
        self.assertFalse(lista[0]["relevante"])
        self.assertEqual(lista[0]["id"], f"{RES480}#00003")
        self.assertTrue(lista[1]["relevante"])
        self.assertEqual(lista[1]["inicio"], "Art. 37 Ao longo do curso...")
        self.assertFalse(res["linhas"][1]["recuperados"][0]["relevante"])   # sem resposta: nada é relevante


class TestCorteEMcNemar(unittest.TestCase):
    def test_mcnemar_exato_reproduz_os_valores_de_21_09(self):
        # comparação de segmentações (CONTEXTO, seção 10.6): 16 x 3 e 8 x 1; critérios antigos: 15 x 5
        self.assertAlmostEqual(av.mcnemar_exato(16, 3), 2 * 1160 / 2 ** 19)       # = 0,0044
        self.assertAlmostEqual(av.mcnemar_exato(8, 1), 2 * 10 / 2 ** 9)           # = 0,039
        self.assertAlmostEqual(av.mcnemar_exato(15, 5), 2 * 21700 / 2 ** 20)      # = 0,041
        self.assertEqual(av.mcnemar_exato(7, 8), 1.0)                              # empate
        self.assertEqual(av.mcnemar_exato(0, 0), 1.0)
        self.assertEqual(av.mcnemar_exato(3, 16), av.mcnemar_exato(16, 3))

    def test_perdida_pelo_corte_e_abstencao_previa(self):
        itens = [{"id": "R1", "pergunta": "a?", "fonte": RES480, "artigos": [37]},
                 {"id": "R2", "pergunta": "b?", "fonte": RES480, "artigos": [53]},
                 {"id": "N1", "pergunta": "c?", "sem_resposta": True}]
        certo37 = _meta(RES480, artigos=(37, 37))
        recuperados = [[(_meta(RES480, artigos=(1, 1)), 0.62), (certo37, 0.45)],   # certo em 2º, abaixo do limiar
                       [(_meta(RES480, artigos=(53, 53)), 0.70)],
                       [(_meta(RES480, artigos=(1, 1)), 0.40)]]
        contextos = [[_meta(RES480, artigos=(1, 1))], [_meta(RES480, artigos=(53, 53))], []]
        res = av.avaliar_resultados(itens, recuperados, k=4, contextos=contextos, limiar=0.5)
        self.assertEqual(res["perdidas_pelo_corte"], ["R1"])
        self.assertTrue(res["linhas"][0]["perdida_pelo_corte"])
        self.assertTrue(res["linhas"][2]["abstencao_previa"])
        self.assertFalse(res["linhas"][1]["abstencao_previa"])
        # se o trecho certo chega por outro caminho (vizinho de outro trecho), a pergunta não foi perdida
        contextos[0].append(certo37)
        self.assertEqual(av.avaliar_resultados(itens, recuperados, 4, contextos, limiar=0.5)["perdidas_pelo_corte"], [])

    def test_corte_so_conta_dentro_dos_k_primeiros(self):
        # o trecho certo está em 5º (k = 4) e abaixo do limiar: o corte não o tirou, a busca é que o
        # deixou fora dos 4 primeiros
        itens = [{"id": "R1", "pergunta": "a?", "fonte": RES480, "artigos": [37]}]
        outros = [(_meta(RES480, artigos=(n, n)), 0.7) for n in range(1, 5)]
        recuperados = [outros + [(_meta(RES480, artigos=(37, 37)), 0.45)]]
        res = av.avaliar_resultados(itens, recuperados, k=4, contextos=[[m for m, _ in outros]], limiar=0.5)
        self.assertEqual(res["perdidas_pelo_corte"], [])

    def test_maior_similaridade_vem_da_busca_densa(self):
        # na híbrida, o 1º da lista pode não ser o mais parecido: vale a maior da busca densa
        itens = [{"id": "N1", "pergunta": "c?", "sem_resposta": True}]
        res = av.avaliar_resultados(itens, [[(_meta(RES480), 0.30)]], k=4, maiores=[0.55], limiar=0.5)
        self.assertEqual(res["sims_sem_resposta"], [0.55])
        self.assertFalse(res["linhas"][0]["abstencao_previa"])

    def test_comparar_pares(self):
        def resultado(acertos):
            return {"linhas": [{"id": i, "no_contexto": ok} for i, ok in acertos.items()]
                    + [{"id": "N1", "sem_resposta": True}]}
        densa = resultado({"R1": True, "R2": False, "R3": True, "R4": False})
        hibrida = resultado({"R1": True, "R2": True, "R3": False, "R4": True})
        comparacao = av.comparar_pares(densa, hibrida)
        self.assertEqual((comparacao["so_base"], comparacao["so_outra"]), (["R3"], ["R2", "R4"]))
        self.assertEqual(comparacao["p"], av.mcnemar_exato(1, 2))


class TestAvaliacaoComBuscasControladas(unittest.TestCase):
    """avaliar_base e comparar_pares com o Recuperador de similaridades escolhidas (test_recuperacao)."""

    def setUp(self):
        self._config = configuracao(SIMILARIDADE_MINIMA=0.50, TOP_K=4, JANELA_VIZINHOS=0, RRF_K=60,
                                    CANDIDATOS_FUSAO=50, CONTEXTO_NO_EMBEDDING=True)
        self._config.__enter__()
        self.itens = [{"id": "R1", "pergunta": PERGUNTA, "fonte": "doc3.pdf", "trecho": "2026/1"},
                      {"id": "N1", "pergunta": "Qual é o de?", "sem_resposta": True}]

    def tearDown(self):
        self._config.__exit__(None, None, None)

    def test_hibrida_acerta_onde_a_densa_erra(self):
        densa = av.avaliar_base(self.itens, 4, "densa", _recuperador())
        hibrida = av.avaliar_base(self.itens, 4, "hibrida", _recuperador())
        self.assertFalse(densa["linhas"][0]["no_contexto"])
        self.assertTrue(hibrida["linhas"][0]["no_contexto"])
        self.assertEqual(hibrida["linhas"][0]["posicao"], 2)
        comparacao = av.comparar_pares(densa, hibrida)
        self.assertEqual((comparacao["so_base"], comparacao["so_outra"]), ([], ["R1"]))

    def test_perdida_pelo_corte_na_hibrida(self):
        # com similaridade 0,45, o trecho certo fica em 2º na fusão, mas o corte o tira do contexto
        sims = [0.62, 0.61, 0.60, 0.45, 0.58, 0.57]
        hibrida = av.avaliar_base(self.itens, 4, "hibrida", _recuperador(sims))
        self.assertEqual(hibrida["perdidas_pelo_corte"], ["R1"])
        # na densa ele está em 6º, fora dos 4 primeiros: não é perda do corte
        self.assertEqual(av.avaliar_base(self.itens, 4, "densa", _recuperador(sims))["perdidas_pelo_corte"], [])

    def test_abstencao_previa_registrada_como_o_recuperador_decidiu(self):
        # pergunta só com palavras vazias: o BM25 não acha nada e o modo bm25 se abstém, embora a
        # busca densa tenha um trecho acima do limiar
        self.assertTrue(av.avaliar_base(self.itens, 4, "bm25", _recuperador())["linhas"][1]["abstencao_previa"])
        self.assertFalse(av.avaliar_base(self.itens, 4, "densa", _recuperador())["linhas"][1]["abstencao_previa"])


class TestAvaliacaoNaBase(unittest.TestCase):
    """avaliar_base e comparar_buscas no ChromaDB real, com o modelo de embeddings falso."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        raiz = Path(cls._tmp.name)
        documentos = raiz / "documentos"
        documentos.mkdir()
        criar_ppc_sintetico(documentos / "ppc.pdf")
        modelo = ModeloEmbeddingsFalso()
        cliente = vetorial.abrir_cliente(raiz / "chroma")
        ingestao.ingerir(pasta=documentos, modelo=modelo, cliente=cliente, pasta_relatorios=raiz / "rel",
                         saida=lambda *a, **k: None)
        colecao = vetorial.obter_colecao(cliente, vetorial.nome_colecao(modelo.nome))
        cls.recuperador = recuperacao.Recuperador(modelo=modelo, colecao=colecao, titulos={})
        cls.itens = [{"id": "R1", "pergunta": "Qual a carga horária do estágio curricular obrigatório?",
                      "fonte": "ppc.pdf", "trecho": "180 horas"},
                     {"id": "N1", "pergunta": "Qual é a capital da França?", "sem_resposta": True}]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_avaliar_base_usa_o_contexto_do_chat(self):
        with configuracao(SIMILARIDADE_MINIMA=0.05):
            res = av.avaliar_base(self.itens, 4, "hibrida", self.recuperador)
        self.assertEqual(res["modo"], "hibrida")
        self.assertEqual(res["contexto_k"], 1.0)
        self.assertEqual(res["configuracao"]["modo_busca"], "hibrida")
        primeiro = res["linhas"][0]["recuperados"][0]
        self.assertIn("posicao_densa", primeiro)
        self.assertIn("posicao_bm25", primeiro)

    def test_comparar_buscas(self):
        with configuracao(SIMILARIDADE_MINIMA=0.05):
            comparacao = av.comparar_buscas(self.itens, 4, self.recuperador)
        self.assertEqual(list(comparacao["resultados"]), ["densa", "bm25", "hibrida"])
        self.assertEqual(set(comparacao["comparacoes_com_densa"]), {"bm25", "hibrida"})
        for c in comparacao["comparacoes_com_densa"].values():
            self.assertEqual(c["p"], 1.0)      # as três acertam a única pergunta respondível


class TestArquivoDePerguntas(unittest.TestCase):
    """Regras do conjunto GERADO (perguntas_recuperacao.json), mais estritas que as
    de um conjunto qualquer: as perguntas reais não precisam terminar com "?" nem
    dizer onde está a resposta, e quem as confere é o perguntas.py."""

    def test_arquivo_valido(self):
        dados = json.loads((config.AVALIACAO_DIR / "perguntas_recuperacao.json").read_text(encoding="utf-8"))
        itens = dados["perguntas"]
        ids = [i["id"] for i in itens]
        self.assertEqual(len(ids), len(set(ids)), "id repetido")
        for item in itens:
            self.assertTrue(item["pergunta"].strip().endswith("?"), item["id"])
            if item.get("sem_resposta"):
                self.assertFalse(item.get("resposta_correta"), item["id"])
                continue
            self.assertTrue(item.get("resposta_correta", "").strip(), item["id"])
            self.assertNotIn("\u2014", item["resposta_correta"], item["id"])
            criterios = av.criterios(item)
            self.assertTrue(criterios, item["id"])
            for c in criterios:
                self.assertTrue(c.get("fonte", "").endswith(".pdf"), item["id"])
                self.assertTrue(any(k in c for k in ("artigos", "paginas", "trecho")), item["id"])
                if "paginas" in c:
                    self.assertEqual(len(c["paginas"]), 2, item["id"])
                    self.assertLessEqual(c["paginas"][0], c["paginas"][1], item["id"])


class TestConjuntoDePerguntasNaAvaliacao(unittest.TestCase):
    """O avaliar_recuperacao.py lê qualquer conjunto pelo perguntas.py."""

    CABECALHO = "id;pergunta;resposta_correta;sem_resposta;fonte\n"

    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)
        self._config = configuracao(AVALIACAO_DIR=self.pasta, DOCS_DIR=self.pasta / "sem_documentos")
        self._config.__enter__()

    def tearDown(self):
        self._config.__exit__(None, None, None)
        self._pasta.cleanup()

    def _csv(self, nome: str, linhas: str) -> Path:
        caminho = self.pasta / nome
        caminho.write_text(self.CABECALHO + linhas, encoding="utf-8")
        return caminho

    def _rodar(self, argv: list[str]) -> tuple[int, str]:
        import io
        from contextlib import redirect_stdout
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = av.main(argv)
        return codigo, saida.getvalue()

    def test_perguntas_sem_local_da_resposta_nao_sao_avaliadas_na_busca(self):
        arquivo = self._csv("reais.csv", ";como tranco?;Pelo sistema.;;\n;cardapio do RU?;;sim;\n")
        codigo, texto = self._rodar(["--arquivo", str(arquivo), "--comparar-buscas"])
        self.assertEqual(codigo, 0)
        self.assertIn("não se aplica", texto)
        self.assertFalse((self.pasta / "resultados").exists())      # nem chegou a buscar

    def test_arquivo_com_erro_nao_e_avaliado(self):
        arquivo = self._csv("erro.csv", "A;P1?;r;;\nA;P2?;r;;\n")
        codigo, texto = self._rodar(["--arquivo", str(arquivo)])
        self.assertEqual(codigo, 1)
        self.assertIn("id repetido", texto)

    def test_arquivo_inexistente(self):
        codigo, texto = self._rodar(["--arquivo", str(self.pasta / "nao_existe.csv")])
        self.assertEqual(codigo, 1)
        self.assertIn("não encontrado", texto)

    def test_resultado_grava_versao_e_perguntas_usadas(self):
        from unittest import mock
        arquivo = self._csv("reais.csv", f";Quantos trancamentos?;Quatro.;;{RES480}\n;Sem fonte?;Algo.;;\n"
                                         ";cardapio?;;sim;\n")
        falso = {"k": 6, "resultados": {}, "comparacoes_com_densa": {}}
        with mock.patch.object(av, "comparar_buscas", return_value=falso) as comparar, \
                mock.patch.object(av, "imprimir_comparacao_buscas"):
            codigo, texto = self._rodar(["--arquivo", str(arquivo), "--comparar-buscas", "--k", "6"])
        self.assertEqual(codigo, 0)
        avaliadas = comparar.call_args.args[0]
        self.assertEqual([i["id"] for i in avaliadas], ["P001", "P003"])   # a sem fonte fica de fora
        self.assertIn("P002", texto)
        gravados = list((self.pasta / "resultados").glob("buscas_*_reais.json"))
        self.assertEqual(len(gravados), 1)
        dados = json.loads(gravados[0].read_text(encoding="utf-8"))
        self.assertEqual(dados["versao_chatbot"], config.VERSAO_CHATBOT)
        self.assertEqual(dados["perguntas"]["arquivo"], "reais.csv")
        self.assertEqual(dados["perguntas"]["avaliadas"], 2)
        self.assertEqual(dados["perguntas"]["fora_sem_local"], ["P002"])
        self.assertEqual(len(dados["perguntas"]["assinatura"]), 12)

    def test_arquivo_padrao_e_o_do_config(self):
        from unittest import mock
        arquivo = self._csv("ativo.csv", f";Quantos trancamentos?;Quatro.;;{RES480}\n")
        falso = {"k": 4, "resultados": {}, "comparacoes_com_densa": {}}
        with configuracao(ARQUIVO_PERGUNTAS=arquivo), \
                mock.patch.object(av, "comparar_buscas", return_value=falso), \
                mock.patch.object(av, "imprimir_comparacao_buscas"):
            codigo, _ = self._rodar(["--comparar-buscas"])
        self.assertEqual(codigo, 0)
        self.assertTrue(list((self.pasta / "resultados").glob("buscas_*_ativo.json")))


if __name__ == "__main__":
    unittest.main()
