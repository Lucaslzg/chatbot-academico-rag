"""Testes do processamento de texto (extração, limpeza, estrutura, fragmentos).

Rodar da pasta do projeto:  python -m unittest discover -s testes -v
"""
import re
import tempfile
import unittest
from pathlib import Path

from utilitarios import (PDF_EXEMPLO, contar_tokens_aproximado, criar_pdf_hifenizado,
                         criar_pdf_sem_texto, criar_ppc_sintetico)

import processamento as pr

OPCOES = pr.OpcoesProcessamento(limite_tokens=126, sobreposicao_tokens=25)


def _linha(texto, pagina=1, y=100.0, x=72.0, bloco=0, tamanho=11.0, negrito=False):
    return pr.LinhaVisual(texto, pagina, bloco, x, y, y + 12.0, tamanho, negrito)


def _paginas(*listas_de_linhas):
    """Páginas a partir de listas de textos; cada linha 13 pt abaixo da anterior."""
    paginas = []
    for n, textos in enumerate(listas_de_linhas, 1):
        linhas = [_linha(t, n, 100 + 13 * i) for i, t in enumerate(textos)]
        paginas.append(pr.PaginaExtraida(n, 842, linhas))
    return paginas


def _normal(texto):
    return re.sub(r"\s+", " ", texto).strip()


class TestLimpeza(unittest.TestCase):
    def test_remove_invisiveis_e_mantem_ordinal(self):
        self.assertEqual(pr.limpar_linha("matr\N{RIGHT-TO-LEFT MARK}ícula Art. 1º"), "matrícula Art. 1º")

    def test_espacos_especiais_e_ligaduras(self):
        self.assertEqual(pr.limpar_linha("a\N{NO-BREAK SPACE}b \N{LATIN SMALL LIGATURE FI}m"), "a b fim")

    def test_hifen_de_palavra_composta_e_mantido(self):
        texto, _ = pr._juntar_linhas([("pode transferir-", 1), ("se para outro curso", 1)], silabica=False)
        self.assertEqual(texto, "pode transferir-se para outro curso")

    def test_hifenizacao_silabica(self):
        linhas = [("a infor-", 1), ("mação e a documen-", 1), ("tação; encaminhá-", 1), ("lo ao pré-", 1),
                  ("requisito", 1)]
        texto, _ = pr._juntar_linhas(linhas, silabica=True)
        self.assertEqual(texto, "a informação e a documentação; encaminhá-lo ao pré-requisito")

    def test_marcas_de_pagina(self):
        texto, marcas = pr._juntar_linhas([("Art. 20 A reprovação é considerada no", 5),
                                           ("cômputo do tempo máximo.", 6)], silabica=False)
        unidade = pr.Unidade("artigo", texto, marcas, "20")
        self.assertEqual((unidade.pagina_inicio, unidade.pagina_fim), (5, 6))
        self.assertEqual(unidade.pagina_em(texto.index("cômputo")), 6)


class TestCabecalhosRodapes(unittest.TestCase):
    def test_remove_repetidos_na_borda_e_preserva_corpo(self):
        paginas = []
        for n in range(1, 6):
            linhas = [_linha("Resolução nº 29, de 28 de abril de 2011", n, y=780),   # rodapé
                      _linha(str(n), n, y=800),                                        # nº da página
                      _linha("Texto do corpo da página.", n, y=300)]
            if n == 3:   # a mesma frase no corpo deve ficar
                linhas.append(_linha("Resolução nº 29, de 28 de abril de 2011", n, y=400))
            paginas.append(pr.PaginaExtraida(n, 842, linhas))
        removidas = pr.remover_cabecalhos_rodapes(paginas)
        self.assertIn("Resolução nº 29, de 28 de abril de 2011", removidas)
        textos_p3 = [l.visivel for l in paginas[2].linhas]
        self.assertEqual(textos_p3, ["Texto do corpo da página.", "Resolução nº 29, de 28 de abril de 2011"])
        self.assertTrue(all(l.visivel == "Texto do corpo da página." for p in paginas if p.numero != 3
                            for l in p.linhas))

    def test_cabecalho_com_numero_variavel(self):
        paginas = [pr.PaginaExtraida(n, 842, [_linha(f"PPC Engenharia - página {n}", n, y=30),
                                              _linha("Conteúdo.", n, y=300)]) for n in range(1, 5)]
        pr.remover_cabecalhos_rodapes(paginas)
        self.assertTrue(all([l.visivel for l in p.linhas] == ["Conteúdo."] for p in paginas))


class TestEstrutura(unittest.TestCase):
    def _unidades(self, *paginas):
        unidades, _ = pr.montar_unidades(_paginas(*paginas), corpo=11.0)
        return unidades

    def test_marcador_sozinho_recebe_o_texto_da_linha_seguinte(self):
        u = self._unidades(["§1º", "O Calendário é publicado até 31 de outubro."])
        self.assertEqual([(x.tipo, x.rotulo, x.texto) for x in u],
                         [("paragrafo", "1", "§1º O Calendário é publicado até 31 de outubro.")])

    def test_artigo_atravessa_a_pagina(self):
        u = self._unidades(["Art. 20 A reprovação ou abandono é considerada no"],
                           ["cômputo do tempo máximo de permanência.", "Art. 21. O discente não pode trancar."])
        self.assertEqual(len(u), 2)
        self.assertEqual((u[0].pagina_inicio, u[0].pagina_fim), (1, 2))
        self.assertTrue(u[0].texto.endswith("de permanência."))

    def test_citacao_a_artigo_no_inicio_da_linha_nao_abre_artigo(self):
        u = self._unidades(["Art. 84 O discente pode solicitar licença para as atividades do",
                            "Art. 81, instruído de documento comprobatório."])
        self.assertEqual(len(u), 1)

    def test_titulo_com_nome_em_duas_linhas(self):
        u = self._unidades(["CAPÍTULO IV", "DA TRANSFERÊNCIA COMPULSÓRIA", "(TRANSFERÊNCIA EX-OFFICIO)",
                            "Art. 13 A Transferência Compulsória é a forma de ingresso."])
        self.assertEqual(u[0].tipo, "capitulo")
        self.assertEqual(u[0].texto, "CAPÍTULO IV DA TRANSFERÊNCIA COMPULSÓRIA (TRANSFERÊNCIA EX-OFFICIO)")
        pr.anotar_contexto(u)
        self.assertEqual(u[1].secao_nome, "Da transferência compulsória (transferência ex-officio)")
        self.assertEqual(u[1].localizacao, "CAPÍTULO IV")
        self.assertEqual(u[1].artigo, 13)

    def test_texto_riscado_e_descartado_com_a_anotacao(self):
        # "II." sem risco, texto riscado, anotação e a redação nova (caso real do Art. 8º)
        risco = pr.RISCO
        linhas = [_linha("II.", 1, 100), _linha(f" {risco} ", 1, 113),
                  _linha("(Alterado pela Resolução 225, de 25 de outubro de 2018)", 1, 126),
                  _linha("II. as vagas são oferecidas nas categorias novas;", 1, 139)]
        u, n = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        self.assertEqual([x.texto for x in u], ["II. as vagas são oferecidas nas categorias novas;"])

    def test_nota_de_rodape_nao_corta_o_paragrafo(self):
        # Parágrafo que continua na página 2 e duas notas de rodapé (letra
        # menor, no pé da página 1): o parágrafo fica inteiro e cada nota vira
        # uma unidade própria, logo depois dele.
        p1 = [_linha("O estágio obrigatório deve ser realizado em empresa conveniada", 1, 700),
              _linha("1 Conforme a Lei nº 11.788, de 25 de setembro de 2008.", 1, 760, tamanho=8.0),
              _linha("2 Ver também o PPC do curso.", 1, 770, tamanho=8.0)]
        p2 = [_linha("e supervisionado por um profissional da área.", 2, 100),
              _linha("O relatório final é entregue em até 30 dias.", 2, 113, bloco=1)]
        u, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, p1), pr.PaginaExtraida(2, 842, p2)], corpo=11.0)
        self.assertEqual([x.texto for x in u], [
            "O estágio obrigatório deve ser realizado em empresa conveniada e supervisionado por um "
            "profissional da área.",
            "1 Conforme a Lei nº 11.788, de 25 de setembro de 2008.",
            "2 Ver também o PPC do curso.",
            "O relatório final é entregue em até 30 dias."])
        self.assertEqual((u[0].pagina_inicio, u[0].pagina_fim), (1, 2))
        self.assertEqual((u[1].pagina_inicio, u[2].pagina_inicio), (1, 1))

    def test_letra_menor_sem_numero_nao_e_nota(self):
        # Citação longa em letra menor no pé da página, continuando na seguinte:
        # não começa com número de nota, então segue o fluxo normal do texto.
        p1 = [_linha("Conforme o regulamento:", 1, 400),
              _linha("O estágio é ato educativo escolar supervisionado,", 1, 700, tamanho=10.0),
              _linha("desenvolvido no ambiente de trabalho,", 1, 713, tamanho=10.0)]
        p2 = [_linha("que visa à preparação para o trabalho produtivo.", 2, 100, tamanho=10.0)]
        u, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, p1), pr.PaginaExtraida(2, 842, p2)], corpo=11.0)
        self.assertEqual([x.texto for x in u], [
            "Conforme o regulamento:",
            "O estágio é ato educativo escolar supervisionado, desenvolvido no ambiente de trabalho, "
            "que visa à preparação para o trabalho produtivo."])


class TestRedacaoAlterada(unittest.TestCase):
    def _u(self, tipo, rotulo, texto):
        return pr.Unidade(tipo, texto, [(0, 1)], rotulo)

    def test_inciso_artigo_e_paragrafo(self):
        unidades = [
            self._u("artigo", "9", "Art. 9º Para o ingresso é considerada a seguinte prioridade:"),
            self._u("inciso", "I", "I. Reingresso;"),
            self._u("inciso", "II", "II. Portador de Diploma. (Alterado pela Resolução 225, de 25 de outubro de 2018)"),
            self._u("artigo", "9", "Art. 9º Para o ingresso é considerada a seguinte prioridade:"),
            self._u("inciso", "I", "I. Segundo Ciclo de Formação;"),
            self._u("paragrafo", "2", "§2º Regra antiga. (Alterado pela Resolução 78, de 26 de agosto de 2014)"),
            self._u("paragrafo", "2", "§2º Regra nova."),
            self._u("paragrafo", "4", "§4º Regra incluída. (Incluído pela Resolução 225, de 2018)"),
        ]
        mantidas, descartadas, nao_resolvidas = pr.descartar_redacoes_alteradas(unidades)
        self.assertEqual([u.texto for u in mantidas],
                         ["Art. 9º Para o ingresso é considerada a seguinte prioridade:",
                          "I. Segundo Ciclo de Formação;", "§2º Regra nova.",
                          "§4º Regra incluída. (Incluído pela Resolução 225, de 2018)"])
        self.assertEqual(len(descartadas), 2)
        self.assertEqual(nao_resolvidas, [])

    def test_fora_do_padrao_e_mantido_e_reportado(self):
        unidades = [self._u("texto", "", "Texto qualquer. (Alterado pela Resolução 1, de 2020)"),
                    self._u("texto", "", "Outro parágrafo.")]
        mantidas, descartadas, nao_resolvidas = pr.descartar_redacoes_alteradas(unidades)
        self.assertEqual(len(mantidas), 2)
        self.assertEqual(descartadas, [])
        self.assertEqual(len(nao_resolvidas), 1)


class TestSegmentacao(unittest.TestCase):
    def _fragmentos(self, unidades, limite=60, sobreposicao=12):
        pr.anotar_contexto(unidades)
        return pr.segmentar(unidades, contar_tokens_aproximado, limite, sobreposicao)

    def _unidades_longas(self):
        u = [pr.Unidade("capitulo", "CAPÍTULO I DO TRANCAMENTO DE MATRÍCULA", [(0, 1)], "I")]
        for n in range(1, 6):
            texto = (f"Art. {n} " + " ".join(f"Frase número {k} do artigo {n} sobre trancamento de matrícula."
                                                for k in range(1, 7)))
            u.append(pr.Unidade("artigo", texto, [(0, n)], str(n), tamanho_marcador=len(f"Art. {n} ")))
            u.append(pr.Unidade("paragrafo", f"Parágrafo único. Regra complementar do artigo {n}.", [(0, n)],
                                "único", tamanho_marcador=len("Parágrafo único. ")))
        return u

    def test_limite_de_tokens_respeitado(self):
        for f in self._fragmentos(self._unidades_longas()):
            self.assertLessEqual(f.n_tokens, 60)
            self.assertEqual(f.n_tokens, contar_tokens_aproximado(f.texto_embedding))

    def test_reconstrucao_sem_perda(self):
        unidades = self._unidades_longas()
        fr = self._fragmentos(unidades)
        texto = pr.juntar_fragmentos_consecutivos([f.texto for f in fr], [f.sobreposicao_chars for f in fr],
                                                  [f.separador_anterior for f in fr])
        self.assertEqual(_normal(texto), _normal("\n".join(u.texto for u in unidades)))

    def test_sobreposicao_so_dentro_do_mesmo_artigo(self):
        # cada frase tem cerca de 16 "tokens": a sobreposição de 20 comporta uma frase
        fr = self._fragmentos(self._unidades_longas(), limite=60, sobreposicao=20)
        self.assertTrue(any(f.sobreposicao_chars for f in fr))
        for anterior, f in zip(fr, fr[1:]):
            if f.sobreposicao_chars:
                self.assertTrue(anterior.texto.endswith(f.texto[:f.sobreposicao_chars]))
                self.assertEqual(f.artigo_inicio, anterior.artigo_fim)

    def test_marcador_nao_fica_separado_do_texto(self):
        for f in self._fragmentos(self._unidades_longas()):
            self.assertNotRegex(f.texto.splitlines()[-1].strip(), r"^(Parágrafo único\.|Art\. \d+)$")

    def test_nenhum_fragmento_termina_com_titulo(self):
        for f in self._fragmentos(self._unidades_longas()):
            self.assertFalse(f.texto.splitlines()[-1].startswith("CAPÍTULO"))

    def test_cabecalho_de_contexto_no_embedding(self):
        fr = self._fragmentos(self._unidades_longas())
        meio = [f for f in fr if not f.texto.startswith(("Art.", "CAPÍTULO"))]
        self.assertTrue(meio)
        self.assertTrue(meio[0].texto_embedding.startswith("Do trancamento de matrícula - Art."))
        self.assertFalse(meio[0].texto.startswith("Do trancamento"))   # o texto guardado não muda

    def test_frase_gigante_e_dividida(self):
        texto = "Art. 1 " + " ".join(f"palavra{k}" for k in range(400))
        u = [pr.Unidade("artigo", texto, [(0, 1)], "1", tamanho_marcador=7)]
        fr = self._fragmentos(u)
        self.assertGreater(len(fr), 1)
        self.assertTrue(all(f.n_tokens <= 60 for f in fr))


class TestFormatosVariados(unittest.TestCase):
    """PDFs sintéticos com formatos diferentes do documento de exemplo."""

    @classmethod
    def setUpClass(cls):
        cls.pasta = tempfile.TemporaryDirectory()
        cls.ppc = pr.processar_pdf(criar_ppc_sintetico(Path(cls.pasta.name) / "ppc.pdf"),
                                   contar_tokens_aproximado, OPCOES)

    @classmethod
    def tearDownClass(cls):
        cls.pasta.cleanup()

    def test_titulo_da_capa(self):
        self.assertEqual(self.ppc.titulo, "Projeto pedagógico do curso de engenharia de computação")

    def test_cabecalho_e_numero_de_pagina_removidos(self):
        todo = "\n".join(f.texto for f in self.ppc.fragmentos)
        self.assertNotIn("Página 2 de 9", todo)
        self.assertEqual(todo.count("Projeto Pedagógico do Curso"), 0)

    def test_titulos_por_estilo_e_numeracao(self):
        titulos = [u.texto for u in self.ppc.unidades if u.tipo == "cabecalho"]
        for esperado in ("1 APRESENTAÇÃO", "1.1 Objetivos do curso", "2 MATRIZ CURRICULAR",
                         "3 TRABALHO DE CONCLUSÃO DE CURSO"):
            self.assertIn(esperado, titulos)

    def test_paragrafos_sem_linha_em_branco(self):
        textos = [u.texto for u in self.ppc.unidades if u.tipo == "texto"]
        self.assertTrue(any(t.startswith("O curso de Engenharia") and t.endswith("semestres letivos.")
                            for t in textos))
        self.assertTrue(any(t.startswith("O estágio curricular") for t in textos))

    def test_lista(self):
        itens = [u for u in self.ppc.unidades if u.tipo == "item"]
        self.assertEqual(len(itens), 3)
        self.assertEqual(itens[0].secao_nome, "Objetivos do curso")

    def test_tabela_linha_a_linha_depois_do_titulo(self):
        tipos = [u.tipo for u in self.ppc.unidades]
        i = [u.texto for u in self.ppc.unidades].index("2 MATRIZ CURRICULAR")
        self.assertEqual(tipos[i + 1], "tabela")
        linhas = [u.texto for u in self.ppc.unidades if u.tipo == "linha_tabela"]
        self.assertIn("Código: BA000001; Componente curricular: Cálculo I; Semestre: 1; CH: 60", linhas)

    def test_texto_riscado_e_anotacao_descartados(self):
        todo = " ".join(u.texto for u in self.ppc.unidades)
        self.assertNotIn("defesa fechada", todo)
        self.assertNotIn("Revogado", todo)
        self.assertEqual(len(self.ppc.trechos_riscados), 1)

    def test_paragrafo_entre_paginas(self):
        u = next(u for u in self.ppc.unidades if u.texto.startswith("A banca avaliadora"))
        self.assertTrue(u.texto.endswith("nota final do trabalho."))
        self.assertEqual((u.pagina_inicio, u.pagina_fim), (2, 3))

    def test_nota_de_rodape_depois_do_paragrafo(self):
        # a página 2 tem uma nota de rodapé embaixo do parágrafo que continua na página 3
        textos = [u.texto for u in self.ppc.unidades]
        i = next(i for i, t in enumerate(textos) if t.startswith("A banca avaliadora"))
        self.assertEqual(textos[i + 1], "1 O regulamento do TCC é aprovado pela Comissão de Curso.")
        self.assertEqual(self.ppc.unidades[i + 1].pagina_inicio, 2)

    def test_hifenizacao_silabica_detectada(self):
        with tempfile.TemporaryDirectory() as pasta:
            doc = pr.processar_pdf(criar_pdf_hifenizado(Path(pasta) / "h.pdf"), contar_tokens_aproximado, OPCOES)
        self.assertTrue(doc.hifenizacao_silabica)
        texto = doc.unidades[0].texto
        self.assertIn("informação institucional", texto)
        self.assertIn("transferir-se", texto)
        self.assertIn("regulamento vigente", texto)

    def test_pdf_sem_texto(self):
        with tempfile.TemporaryDirectory() as pasta:
            doc = pr.processar_pdf(criar_pdf_sem_texto(Path(pasta) / "v.pdf"), contar_tokens_aproximado, OPCOES)
        self.assertEqual(doc.paginas_sem_texto, [1])
        self.assertEqual(doc.fragmentos, [])

    def test_arquivo_que_nao_e_pdf(self):
        with tempfile.TemporaryDirectory() as pasta:
            falso = Path(pasta) / "falso.pdf"
            falso.write_text("isto não é um PDF", encoding="utf-8")
            with self.assertRaises(pr.ErroExtracao):
                pr.processar_pdf(falso, contar_tokens_aproximado, OPCOES)


@unittest.skipUnless(PDF_EXEMPLO.exists(), "PDF de exemplo ausente")
class TestDocumentoExemplo(unittest.TestCase):
    """Resolução nº 29/2011 (documento de exemplo em data/documentos)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = pr.processar_pdf(PDF_EXEMPLO, contar_tokens_aproximado, OPCOES)

    def test_todos_os_artigos_uma_vez(self):
        artigos = [int(u.rotulo) for u in self.doc.unidades if u.tipo == "artigo"]
        self.assertEqual(sorted(artigos), list(range(1, 152)))

    def test_redacoes_revogadas_fora(self):
        todo = "\n".join(f.texto for f in self.doc.fragmentos)
        self.assertNotIn("Código Internacional da Doença", todo)      # Art. 97, I antigo
        self.assertNotIn("Alterado pela", todo)
        self.assertEqual(self.doc.anotacoes_nao_resolvidas, [])

    def test_versao_vigente_do_art_45(self):
        incisos = [u.texto for u in self.doc.unidades if u.artigo == 45 and u.tipo == "inciso"]
        self.assertEqual(len(incisos), 9)
        self.assertEqual(incisos[0], "I. discentes com deficiência;")

    def test_rodape_removido(self):
        self.assertIn("Resolução nº 29, de 28 de abril de 2011", self.doc.linhas_removidas)
        todo = "\n".join(f.texto for f in self.doc.fragmentos)
        self.assertNotIn("Resolução nº 29, de 28 de abril de 2011", todo)

    def test_limite_e_reconstrucao(self):
        fr = self.doc.fragmentos
        self.assertTrue(all(f.n_tokens <= 126 for f in fr))
        texto = pr.juntar_fragmentos_consecutivos([f.texto for f in fr], [f.sobreposicao_chars for f in fr],
                                                  [f.separador_anterior for f in fr])
        self.assertEqual(_normal(texto), _normal("\n".join(u.texto for u in self.doc.unidades)))

    def test_art_48_inteiro_apesar_da_quebra_de_pagina(self):
        paginas = {(f.pagina_inicio, f.pagina_fim) for f in self.doc.fragmentos
                   if f.artigo_inicio and f.artigo_inicio <= 48 <= f.artigo_fim}
        self.assertIn(11, {p for par in paginas for p in par})
        todo = "\n".join(f.texto for f in self.doc.fragmentos)
        self.assertIn("devendo ser:\na) realizado semestralmente;", todo)


if __name__ == "__main__":
    unittest.main()
