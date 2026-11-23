"""Testes da recuperação: busca por palavras (BM25), fusão, limiar, corte e montagem do contexto.

Rodam sem o modelo de embeddings real e sem o Ollama. Os testes do
Recuperador usam uma coleção falsa com vetores escolhidos, em que a
similaridade de cada fragmento com qualquer pergunta é exatamente a pedida:
assim dá para montar à mão os casos em que a busca densa erra e a busca por
palavras acerta.
"""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from utilitarios import RAIZ, ModeloEmbeddingsFalso, configuracao, criar_ppc_sintetico

import config
import ingestao
import recuperacao as rec
import vetorial
from vetorial import id_fragmento


def _silencioso(*_args, **_kwargs):
    pass


# ===========================================================================
# Busca por palavras
# ===========================================================================
class TestTokenizacao(unittest.TestCase):
    def test_acentos_maiusculas_e_palavras_vazias(self):
        self.assertEqual(rec.tokenizar("Qual o período para solicitar o TRANCAMENTO total em 2026/1?"),
                         ["periodo", "solicitar", "trancamento", "total", "2026", "1"])
        self.assertEqual(rec.tokenizar("Ação, exceção e regência"), ["acao", "excecao", "regencia"])

    def test_numeros_e_romanos_ficam(self):
        self.assertEqual(rec.tokenizar("Cálculo I"), ["calculo", "i"])
        self.assertEqual(rec.tokenizar("Cálculo II"), ["calculo", "ii"])
        self.assertEqual(rec.tokenizar("Art. 3º"), ["art", "3"])

    def test_simbolos_separam_palavras(self):
        # travessão curto, "§" e "º" não podem juntar as palavras vizinhas
        self.assertEqual(rec.tokenizar("2019\u20132023"), ["2019", "2023"])
        self.assertEqual(rec.tokenizar("Arts. 47\u201348"), ["arts", "47", "48"])
        self.assertEqual(rec.tokenizar("§1º do Art. 5"), ["1", "art", "5"])

    def test_texto_do_bm25_tem_secao_e_artigo(self):
        meta = {"secao": "Do trancamento de matrícula", "artigo_inicio": 48}
        self.assertEqual(rec.texto_para_bm25("O discente pode...", meta),
                         "Do trancamento de matrícula Art. 48\nO discente pode...")
        self.assertEqual(rec.texto_para_bm25("Texto.", {"secao": "Apresentação"}), "Apresentação\nTexto.")
        self.assertEqual(rec.texto_para_bm25("Texto.", meta, incluir_cabecalho=False), "Texto.")


class TestBM25(unittest.TestCase):
    """Notas conferidas à mão com a fórmula do docstring de IndiceBM25 (k1 = 1,2; b = 0,75)."""

    def setUp(self):
        # palavras de cada texto, sem as vazias: a = 3, b = 2, c = 4 (média 3)
        self.indice = rec.IndiceBM25(["a", "b", "c"], ["trancamento total do semestre", "trancamento parcial",
                                                       "semestre letivo e semestre especial"], k1=1.2, b=0.75)

    def test_notas_calculadas_a_mao(self):
        idf_2 = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))   # palavra em 2 dos 3 textos
        idf_1 = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))   # palavra em 1 dos 3
        # "a" tem o comprimento médio: o termo do comprimento vale k1 = 1,2
        nota_a = idf_2 * 2.2 / (1 + 1.2) + idf_1 * 2.2 / (1 + 1.2)
        # "b" tem 2 palavras: desconto menor, k1 * (0,25 + 0,75 * 2/3) = 0,9
        nota_b = idf_2 * 2.2 / (1 + 0.9)
        resultado = self.indice.buscar("trancamento total", 5)
        self.assertEqual([i for i, _ in resultado], ["a", "b"])
        self.assertAlmostEqual(resultado[0][1], nota_a, places=9)
        self.assertAlmostEqual(resultado[1][1], nota_b, places=9)

    def test_repeticao_e_comprimento(self):
        # "semestre" aparece 2 vezes em "c" (4 palavras) e 1 vez em "a" (3 palavras)
        idf = math.log(1 + 1.5 / 2.5)
        nota_c = idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 4 / 3))
        nota_a = idf * 2.2 / (1 + 1.2)
        resultado = dict(self.indice.buscar("semestre", 5))
        self.assertAlmostEqual(resultado["c"], nota_c, places=9)
        self.assertAlmostEqual(resultado["a"], nota_a, places=9)
        self.assertLess(nota_c, 2 * nota_a)     # repetir ajuda, mas não dobra a nota

    def test_sem_palavra_util_ou_fora_do_vocabulario(self):
        self.assertEqual(self.indice.buscar("qual o de", 5), [])
        self.assertEqual(self.indice.buscar("inexistente", 5), [])

    def test_limite_e_empate(self):
        self.assertEqual(len(self.indice.buscar("trancamento", 1)), 1)
        iguais = rec.IndiceBM25(["y", "x"], ["prazo de recurso", "prazo de recurso"])
        self.assertEqual([i for i, _ in iguais.buscar("prazo", 5)], ["x", "y"])   # empate: ordem do id


class TestFusao(unittest.TestCase):
    def test_exemplo_da_explicacao(self):
        # A: 1º só na densa; B: 3º na densa e 2º no BM25
        resultado = rec.fundir_rrf([["A", "X", "B"], ["Y", "B"]], k=60)
        notas = dict(resultado)
        self.assertAlmostEqual(notas["A"], 1 / 61)
        self.assertAlmostEqual(notas["B"], 1 / 63 + 1 / 62)
        # B sobe; A e Y empatam (1º lugar em uma lista cada) e o id desempata
        self.assertEqual([i for i, _ in resultado], ["B", "A", "Y", "X"])

    def test_item_de_uma_lista_so(self):
        self.assertEqual(rec.fundir_rrf([["A"], []], k=60), [("A", 1 / 61)])


# ===========================================================================
# Recuperador com similaridades escolhidas
# ===========================================================================
class _ModeloFixo:
    """Toda pergunta vira o mesmo vetor [1, 0]."""
    nome = "teste/modelo-fixo"

    def codificar_consulta(self, pergunta):
        return [1.0, 0.0]


class _ColecaoControlada:
    """Imita o ChromaDB. O vetor de cada fragmento é [s, raiz(1 - s²)]: o
    cosseno com a pergunta [1, 0] é exatamente a similaridade s pedida."""

    def __init__(self, fragmentos, empates_invertidos=False):
        self.dados = {}
        for texto, meta, similaridade in fragmentos:
            vetor = [similaridade, math.sqrt(max(0.0, 1 - similaridade ** 2))]
            self.dados[id_fragmento(meta["fonte"], meta["indice"])] = (texto, meta, vetor)
        self.metadata = {"assinatura": "teste"}
        self.consultas = 0
        # True: devolve os empatados do maior id para o menor, como o ChromaDB pode fazer
        self.empates_invertidos = empates_invertidos

    def count(self):
        return len(self.dados)

    def query(self, query_embeddings, n_results, include=None):
        self.consultas += 1
        pergunta = np.asarray(query_embeddings[0])
        cosseno = {i: float(np.dot(pergunta, v[2])) for i, v in self.dados.items()}
        ordem = sorted(sorted(cosseno, reverse=self.empates_invertidos), key=lambda i: -cosseno[i])[:n_results]
        return {"ids": [ordem], "documents": [[self.dados[i][0] for i in ordem]],
                "metadatas": [[self.dados[i][1] for i in ordem]],
                "distances": [[1 - cosseno[i] for i in ordem]]}

    def get(self, ids=None, include=None):
        ids = list(self.dados) if ids is None else [i for i in ids if i in self.dados]
        include = include or []
        resultado = {"ids": ids}
        if "documents" in include:
            resultado["documents"] = [self.dados[i][0] for i in ids]
        if "metadatas" in include:
            resultado["metadatas"] = [self.dados[i][1] for i in ids]
        if "embeddings" in include:
            resultado["embeddings"] = [self.dados[i][2] for i in ids]
        return resultado


PERGUNTA = "Qual o período para solicitar o trancamento total em 2026/1?"
TEXTOS = [
    "Art. 36 O discente mantém-se em situação regular durante o trancamento total.",
    "Data limite para registro do aproveitamento e da dispensa de 2026/2.",
    "Se o período da licença coincidir com o início do semestre letivo.",
    "Trancamento total 2026/1: de 23/02 a 10/04.",      # o trecho certo
    "Os prazos para a implantação serão de curto prazo.",
    "O período letivo especial é definido pela coordenação.",
]
# Busca densa: o trecho certo (doc3) fica em 6º, atrás de trechos parecidos.
SIMILARIDADES = [0.62, 0.61, 0.60, 0.55, 0.58, 0.57]


def _meta(n, secao=""):
    """Cada texto num documento próprio (doc0.pdf, doc1.pdf...): as passagens não se juntam."""
    meta = {"fonte": f"doc{n}.pdf", "documento": f"Documento {n}", "indice": 0, "n_fragmentos": 1,
            "pagina": 1, "pagina_fim": 1, "localizacao": "", "secao": secao, "sobreposicao_chars": 0,
            "separador_anterior": "\n"}
    if n == 0:
        meta["artigo_inicio"] = meta["artigo_fim"] = 36
    return meta


def _recuperador(similaridades=SIMILARIDADES):
    colecao = _ColecaoControlada([(t, _meta(n), s) for n, (t, s) in enumerate(zip(TEXTOS, similaridades))])
    return rec.Recuperador(modelo=_ModeloFixo(), colecao=colecao, titulos={})


def _documentos(contexto):
    """Números dos documentos no contexto, na ordem em que o LLM os recebe."""
    return [int(p.fonte[3:-4]) for p in contexto.passagens]


class TestRecuperador(unittest.TestCase):
    def setUp(self):
        self._config = configuracao(SIMILARIDADE_MINIMA=0.50, TOP_K=4, JANELA_VIZINHOS=0, RRF_K=60,
                                    CANDIDATOS_FUSAO=50, CONTEXTO_NO_EMBEDDING=True)
        self._config.__enter__()

    def tearDown(self):
        self._config.__exit__(None, None, None)

    def test_densa_nao_traz_o_trecho_certo(self):
        contexto = _recuperador().recuperar(PERGUNTA, modo="densa")
        self.assertEqual(_documentos(contexto), [0, 1, 2, 4])
        self.assertEqual(contexto.recuperados[5].fonte, "doc3.pdf")         # 6º na busca densa

    def test_hibrida_traz_o_trecho_que_so_as_palavras_acharam(self):
        contexto = _recuperador().recuperar(PERGUNTA, modo="hibrida")
        # fusão: doc0 = 1/61 + 1/62; doc3 = 1/66 + 1/61; doc1 = 1/62 + 1/65; doc2 = 1/63 + 1/64
        self.assertEqual(_documentos(contexto), [0, 3, 1, 2])
        certo = next(t for t in contexto.recuperados if t.fonte == "doc3.pdf")
        self.assertEqual((certo.posicao_densa, certo.posicao_bm25), (6, 1))
        self.assertAlmostEqual(certo.nota, 1 / 66 + 1 / 61)
        self.assertAlmostEqual(certo.similaridade, 0.55)                    # cosseno vem da busca densa

    def test_bm25_ordena_por_palavras(self):
        trechos = _recuperador().buscar(PERGUNTA, n=2, modo="bm25")
        self.assertEqual([t.fonte for t in trechos], ["doc3.pdf", "doc0.pdf"])
        self.assertTrue(all(t.nota == t.nota_bm25 for t in trechos))

    def test_corte_vale_tambem_na_hibrida(self):
        # o trecho certo agora tem similaridade 0,45: o BM25 o põe em 1º, mas o corte o tira
        contexto = _recuperador([0.62, 0.61, 0.60, 0.45, 0.58, 0.57]).recuperar(PERGUNTA, modo="hibrida")
        self.assertNotIn(3, _documentos(contexto))
        self.assertEqual(_documentos(contexto), [0, 1, 2, 5])               # o próximo que passa entra
        self.assertTrue(all(p.similaridade >= 0.50 for p in contexto.passagens))

    def test_abstencao_pela_busca_densa_em_qualquer_modo(self):
        fracas = [s * 0.7 for s in SIMILARIDADES]                          # maior: 0,434
        for modo in rec.MODOS_BUSCA:
            contexto = _recuperador(fracas).recuperar(PERGUNTA, modo=modo)
            self.assertTrue(contexto.abstencao_previa, modo)
            self.assertEqual(contexto.passagens, [], modo)
            self.assertAlmostEqual(contexto.maior_similaridade, 0.62 * 0.7)

    def test_poucos_trechos_passam_contexto_igual_nas_buscas(self):
        # só 0 e 1 passam no limiar: as três buscas entregam os mesmos dois trechos
        sims = [0.62, 0.55, 0.45, 0.40, 0.44, 0.43]
        for modo in rec.MODOS_BUSCA:
            self.assertEqual(sorted(_documentos(_recuperador(sims).recuperar(PERGUNTA, modo=modo))), [0, 1], modo)

    def test_contexto_nao_depende_da_janela_do_llm(self):
        # 4 trechos de uns 1.000 caracteres: pela regra antiga, uma janela de 2.048 tokens daria
        # um orçamento de 2.000 caracteres (2 trechos); agora o limite é o mesmo para qualquer LLM
        longos = [(texto + " complemento" * 80, _meta(n), s)
                  for n, (texto, s) in enumerate(zip(TEXTOS, SIMILARIDADES))]
        resultados = []
        for janela_do_llm in (2048, 8192):
            recuperador = rec.Recuperador(modelo=_ModeloFixo(), colecao=_ColecaoControlada(longos), titulos={})
            with configuracao(OLLAMA_NUM_CTX=janela_do_llm, CONTEXTO_MAX_CARACTERES=20000):
                resultados.append([p.texto for p in recuperador.recuperar(PERGUNTA, modo="hibrida").passagens])
        self.assertEqual(len(resultados[0]), 4)
        self.assertEqual(resultados[0], resultados[1])

    def test_configuracao_vai_com_o_contexto(self):
        contexto = _recuperador().recuperar(PERGUNTA, modo="hibrida")
        self.assertEqual(contexto.configuracao["modo_busca"], "hibrida")
        self.assertEqual(contexto.configuracao["rrf_k"], 60)
        self.assertEqual(contexto.configuracao["assinatura_base"], "teste")
        self.assertNotIn("rrf_k", _recuperador().recuperar(PERGUNTA, modo="densa").configuracao)

    def test_modo_invalido(self):
        with self.assertRaises(rec.ErroBusca):
            _recuperador().recuperar(PERGUNTA, modo="semantica")
        with configuracao(MODO_BUSCA="xyz"), self.assertRaises(rec.ErroBusca):
            rec.Recuperador.modo_valido()

    def test_indice_bm25_montado_uma_vez_da_colecao(self):
        recuperador = _recuperador()
        recuperador.preparar("hibrida")
        indice = recuperador.indice_bm25
        recuperador.recuperar(PERGUNTA, modo="hibrida")
        self.assertIs(recuperador.indice_bm25, indice)
        self.assertEqual(len(indice), 6)

    def test_bm25_le_o_nome_da_secao(self):
        # "afastamento" só existe no nome da seção de doc4, não no texto
        fragmentos = [(t, _meta(n, "Do afastamento para estudos" if n == 4 else ""), s)
                      for n, (t, s) in enumerate(zip(TEXTOS, SIMILARIDADES))]
        recuperador = rec.Recuperador(modelo=_ModeloFixo(), colecao=_ColecaoControlada(fragmentos), titulos={})
        self.assertEqual([i for i, _ in recuperador.indice_bm25.buscar("afastamento", 6)], ["doc4.pdf#00000"])
        with configuracao(CONTEXTO_NO_EMBEDDING=False):
            sem_cabecalho = rec.Recuperador(modelo=_ModeloFixo(), colecao=_ColecaoControlada(fragmentos), titulos={})
            self.assertEqual(sem_cabecalho.indice_bm25.buscar("afastamento", 6), [])

    def test_similaridade_igual_ao_limiar_entra(self):
        contexto = _recuperador([0.50, 0.45, 0.44, 0.43, 0.42, 0.41]).recuperar(PERGUNTA, modo="densa")
        self.assertFalse(contexto.abstencao_previa)
        self.assertEqual(_documentos(contexto), [0])

    def test_candidato_que_so_o_bm25_achou(self):
        # 14 fragmentos e 10 candidatos de cada busca: o trecho certo (similaridade 0,52) fica em
        # 14º, o último, na busca densa, fora dos candidatos dela; só o BM25 o traz, e a
        # similaridade dele vem do vetor guardado na base
        fragmentos = [(f"Assunto geral numero {n}.", _meta(n), 0.90 - 0.02 * n) for n in range(14)]
        fragmentos[11] = ("Trancamento total 2026/1: de 23/02 a 10/04.", _meta(11), 0.52)
        recuperador = rec.Recuperador(modelo=_ModeloFixo(), colecao=_ColecaoControlada(fragmentos), titulos={})
        with configuracao(CANDIDATOS_FUSAO=10):
            candidatos, maior = recuperador._candidatos(PERGUNTA, "hibrida", 10)
            contexto = recuperador.recuperar(PERGUNTA, modo="hibrida")
        self.assertEqual(sum(t.posicao_densa is not None for t in candidatos), 10)
        certo = next(t for t in candidatos if t.fonte == "doc11.pdf")
        self.assertIsNone(certo.posicao_densa)
        self.assertEqual(certo.posicao_bm25, 1)
        self.assertAlmostEqual(certo.similaridade, 0.52)
        self.assertEqual(certo.texto, "Trancamento total 2026/1: de 23/02 a 10/04.")
        self.assertIn(11, _documentos(contexto))
        self.assertAlmostEqual(maior, 0.90)
        # com 14 candidatos de cada busca, a busca densa também alcança o trecho certo (14º)
        with configuracao(CANDIDATOS_FUSAO=14):
            candidatos, _ = recuperador._candidatos(PERGUNTA, "hibrida", recuperador._profundidade(4, "hibrida"))
        self.assertEqual(sum(t.posicao_densa is not None for t in candidatos), 14)
        self.assertEqual(next(t for t in candidatos if t.fonte == "doc11.pdf").posicao_densa, 14)

    def test_empates_na_fronteira_da_busca_densa(self):
        # 20 cópias do mesmo texto (mesmo vetor) ocupam as posições 6 a 25; o ChromaDB pode devolver
        # os empatados em qualquer ordem. Os 10 primeiros têm de ser sempre os mesmos: no empate, o
        # menor id em ordem alfabética ("doc10.pdf#00000" vem antes de "doc5.pdf#00000")
        fragmentos = [(f"Texto {n}.", _meta(n), 0.90 - 0.02 * n) for n in range(5)]
        fragmentos += [("Texto repetido.", _meta(n), 0.60) for n in range(5, 25)]
        fragmentos += [(f"Texto {n}.", _meta(n), 0.50) for n in range(25, 30)]
        for invertidos in (False, True):
            colecao = _ColecaoControlada(fragmentos, empates_invertidos=invertidos)
            recuperador = rec.Recuperador(modelo=_ModeloFixo(), colecao=colecao, titulos={})
            trechos = recuperador.buscar(PERGUNTA, n=10, modo="densa")
            self.assertEqual([t.fonte for t in trechos],
                             [f"doc{n}.pdf" for n in (0, 1, 2, 3, 4, 10, 11, 12, 13, 14)], invertidos)


# ===========================================================================
# Montagem do contexto (testes que estavam em test_consulta.py)
# ===========================================================================
class _ColecaoFalsa:
    """Imita o `get` do ChromaDB para testar a montagem do contexto."""

    def __init__(self, fragmentos):
        self.dados = {id_fragmento(m["fonte"], m["indice"]): (t, m) for t, m in fragmentos}

    def get(self, ids, include=None):
        achados = [i for i in ids if i in self.dados]
        return {"ids": achados, "documents": [self.dados[i][0] for i in achados],
                "metadatas": [self.dados[i][1] for i in achados]}


def _meta_doc(indice, pagina, artigo, sobre=0, sep="\n", n=6):
    return {"fonte": "doc.pdf", "documento": "Documento", "indice": indice, "n_fragmentos": n,
            "pagina": pagina, "pagina_fim": pagina, "artigo_inicio": artigo, "artigo_fim": artigo,
            "localizacao": "CAPÍTULO I", "secao": "Seção", "sobreposicao_chars": sobre,
            "separador_anterior": sep}


class TestMontagemDoContexto(unittest.TestCase):
    def setUp(self):
        # fragmento 2 repete "Frase B." no início (sobreposição de 8 caracteres)
        fragmentos = [("Art. 1 Frase A.", _meta_doc(0, 1, 1)), ("Art. 2 Frase X. Frase B.", _meta_doc(1, 1, 2)),
                      ("Frase B. Frase C.", _meta_doc(2, 2, 2, sobre=8, sep="")),
                      ("Art. 3 Frase D.", _meta_doc(3, 2, 3)), ("Art. 4 Frase E.", _meta_doc(4, 3, 4)),
                      ("Art. 5 Frase F.", _meta_doc(5, 3, 5))]
        self.recuperador = rec.Recuperador(modelo=object(), colecao=_ColecaoFalsa(fragmentos))

    def _trecho(self, indice, similaridade):
        meta = _meta_doc(indice, 1, indice + 1)
        return rec.Trecho(id_fragmento("doc.pdf", indice), "", meta, similaridade)

    def test_vizinhos_sao_unidos_sem_repetir_a_sobreposicao(self):
        passagens = self.recuperador.montar_passagens([self._trecho(2, 0.7)], janela=1)
        self.assertEqual(len(passagens), 1)
        self.assertEqual(passagens[0].texto, "Art. 2 Frase X. Frase B. Frase C.\nArt. 3 Frase D.")
        self.assertEqual((passagens[0].pagina_inicio, passagens[0].pagina_fim), (1, 2))
        self.assertEqual((passagens[0].artigo_inicio, passagens[0].artigo_fim), (2, 3))

    def test_passagens_separadas_em_ordem_de_relevancia(self):
        passagens = self.recuperador.montar_passagens([self._trecho(0, 0.4), self._trecho(5, 0.9)], janela=1)
        self.assertEqual([p.numero for p in passagens], [1, 2])
        self.assertAlmostEqual(passagens[0].similaridade, 0.9)   # a mais relevante primeiro
        self.assertEqual(passagens[0].texto, "Art. 4 Frase E.\nArt. 5 Frase F.")
        self.assertEqual(passagens[1].texto, "Art. 1 Frase A.\nArt. 2 Frase X. Frase B.")

    def test_janelas_que_se_tocam_viram_uma_passagem(self):
        passagens = self.recuperador.montar_passagens([self._trecho(0, 0.4), self._trecho(2, 0.5)], janela=1)
        self.assertEqual(len(passagens), 1)          # janelas 0-1 e 1-3 se sobrepõem
        self.assertAlmostEqual(passagens[0].similaridade, 0.5)
        self.assertEqual(passagens[0].texto,
                         "Art. 1 Frase A.\nArt. 2 Frase X. Frase B. Frase C.\nArt. 3 Frase D.")

    def test_sem_vizinhos(self):
        passagens = self.recuperador.montar_passagens([self._trecho(3, 0.6)], janela=0)
        self.assertEqual(passagens[0].texto, "Art. 3 Frase D.")

    def test_ordem_das_passagens_segue_o_ranking_no_empate(self):
        # fusão: b#10 = 1/62 + 1/62; a#0 e b#0 empatam em 1/61, e o ranking já pôs a#0 antes.
        # As passagens seguem o ranking, e não o agrupamento por documento.
        def meta(fonte, indice, n):
            return {"fonte": fonte, "documento": fonte, "indice": indice, "n_fragmentos": n, "pagina": 1,
                    "pagina_fim": 1, "localizacao": "", "secao": "", "sobreposicao_chars": 0,
                    "separador_anterior": "\n"}
        fragmentos = [("Texto a0.", meta("a.pdf", 0, 1)), ("Texto b0.", meta("b.pdf", 0, 11)),
                      ("Texto b10.", meta("b.pdf", 10, 11))]
        recuperador = rec.Recuperador(modelo=object(), colecao=_ColecaoFalsa(fragmentos), titulos={})
        ranking = [rec.Trecho("b.pdf#00010", "", meta("b.pdf", 10, 11), 0.80, nota=2 / 62),
                   rec.Trecho("a.pdf#00000", "", meta("a.pdf", 0, 1), 0.90, nota=1 / 61),
                   rec.Trecho("b.pdf#00000", "", meta("b.pdf", 0, 11), 0.55, nota=1 / 61)]
        passagens = recuperador.montar_passagens(ranking, janela=0)
        self.assertEqual([p.texto for p in passagens], ["Texto b10.", "Texto a0.", "Texto b0."])

    def test_titulo_do_arquivo_de_titulos_vai_para_o_prompt(self):
        recuperador = rec.Recuperador(modelo=object(), colecao=self.recuperador.colecao,
                                      titulos={"doc.pdf": "Resolução nº 1/2026: normas de teste"})
        passagens = recuperador.montar_passagens([self._trecho(3, 0.6)], janela=0)
        self.assertEqual(passagens[0].documento, "Resolução nº 1/2026: normas de teste")
        # sem título no arquivo: fica o título extraído do PDF (metadado "documento")
        sem = rec.Recuperador(modelo=object(), colecao=self.recuperador.colecao, titulos={})
        self.assertEqual(sem.montar_passagens([self._trecho(3, 0.6)], janela=0)[0].documento, "Documento")

    def test_carregar_titulos(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "titulos.json"
            arquivo.write_text(json.dumps({"_leia_me": "x", "titulos": {"a.pdf": " Título A ", "b.pdf": ""}}),
                               encoding="utf-8")
            self.assertEqual(vetorial.carregar_titulos(arquivo), {"a.pdf": "Título A"})
            self.assertEqual(vetorial.carregar_titulos(Path(pasta) / "nao_existe.json"), {})
            arquivo.write_text("{ quebrado", encoding="utf-8")
            with mock.patch("builtins.print"):
                self.assertEqual(vetorial.carregar_titulos(arquivo), {})

    def test_arquivo_de_titulos_do_projeto_e_valido(self):
        titulos = vetorial.carregar_titulos()
        self.assertTrue(titulos, "data/titulos_documentos.json vazio ou ausente")
        for nome, titulo in titulos.items():
            self.assertTrue(nome.endswith(".pdf"), nome)
            self.assertNotIn("\u2014", titulo, nome)      # sem travessão longo
            self.assertLessEqual(len(titulo), 200, nome)

    def test_limite_de_contexto(self):
        grandes = [rec.Passagem(i, "d.pdf", "D", "x" * 9000, 1, 1, None, None, "", "", 0.5)
                   for i in range(1, 5)]
        for janela_do_llm in (2048, 8192):          # a janela do LLM não muda nada
            with configuracao(CONTEXTO_MAX_CARACTERES=20000, OLLAMA_NUM_CTX=janela_do_llm):
                selecionadas = rec.Recuperador._limitar_contexto(grandes)
            self.assertEqual(len(selecionadas), 2)     # 18.000 cabem em 20.000; 27.000 não


# ===========================================================================
# Recuperador no ChromaDB real (modelo de embeddings falso)
# ===========================================================================
class TestRecuperadorNoChroma(unittest.TestCase):
    PERGUNTA = "Qual a carga horária do estágio curricular obrigatório?"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        raiz = Path(cls._tmp.name)
        documentos = raiz / "documentos"
        documentos.mkdir()
        criar_ppc_sintetico(documentos / "ppc.pdf")
        cls.modelo = ModeloEmbeddingsFalso()
        cls.cliente = vetorial.abrir_cliente(raiz / "chroma")
        ingestao.ingerir(pasta=documentos, modelo=cls.modelo, cliente=cls.cliente,
                         pasta_relatorios=raiz / "relatorios", saida=_silencioso)
        cls.colecao = vetorial.obter_colecao(cls.cliente, vetorial.nome_colecao(cls.modelo.nome))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.recuperador = rec.Recuperador(modelo=self.modelo, colecao=self.colecao, titulos={})

    def test_busca_densa_igual_a_consulta_direta_ao_chroma(self):
        trechos = self.recuperador.buscar(self.PERGUNTA, n=4, modo="densa")
        direto = self.colecao.query(query_embeddings=[self.modelo.codificar_consulta(self.PERGUNTA)],
                                    n_results=self.colecao.count(), include=["distances"])
        # ranking completo do ChromaDB, com empate desfeito pelo id (o modelo falso gera empates)
        esperado = sorted(zip(direto["ids"][0], direto["distances"][0]), key=lambda par: (par[1], par[0]))[:4]
        self.assertEqual([t.id for t in trechos], [i for i, _ in esperado])
        for trecho, (_, distancia) in zip(trechos, esperado):
            self.assertAlmostEqual(trecho.similaridade, 1 - distancia, places=6)
        # a ordem não depende de quantos resultados se pede
        self.assertEqual([t.id for t in self.recuperador.buscar(self.PERGUNTA, n=2, modo="densa")],
                         [t.id for t in trechos[:2]])

    def test_hibrida_de_ponta_a_ponta(self):
        with configuracao(SIMILARIDADE_MINIMA=0.05):
            contexto = self.recuperador.recuperar(self.PERGUNTA, modo="hibrida")
        self.assertFalse(contexto.abstencao_previa)
        self.assertIn("180 horas", contexto.passagens[0].texto)
        self.assertEqual(len(self.recuperador.indice_bm25), self.colecao.count())
        # a similaridade de cada candidato é o cosseno com o vetor guardado no ChromaDB
        vetor = np.asarray(self.modelo.codificar_consulta(self.PERGUNTA))
        guardados = self.colecao.get(ids=[t.id for t in contexto.recuperados], include=["embeddings"])
        cosseno = {i: float(np.dot(vetor, e)) for i, e in zip(guardados["ids"], guardados["embeddings"])}
        for trecho in contexto.recuperados:
            self.assertAlmostEqual(trecho.similaridade, cosseno[trecho.id], places=5)


# ===========================================================================
# A busca não depende da geração
# ===========================================================================
class TestIndependencia(unittest.TestCase):
    def _geracao_carregada(self, modulo: str) -> str:
        codigo = (f"import sys; import {modulo}; "
                  "print(','.join(m for m in ('consulta', 'ollama') if m in sys.modules))")
        resultado = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True,
                                   text=True, timeout=300)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return resultado.stdout.strip()

    def test_busca_nao_carrega_a_geracao(self):
        self.assertEqual(self._geracao_carregada("recuperacao"), "")

    def test_avaliacao_da_busca_nao_carrega_a_geracao(self):
        self.assertEqual(self._geracao_carregada("avaliar_recuperacao"), "")


if __name__ == "__main__":
    unittest.main()
