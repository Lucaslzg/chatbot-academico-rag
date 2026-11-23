"""Testes dos problemas encontrados ao processar o corpus real (61 PDFs).

Cada teste reproduz, com dados sintéticos, um defeito visto num documento
de verdade e confere a correção. O nome do documento está no comentário.

Rodar da pasta do projeto:  python -m unittest discover -s testes -v
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from utilitarios import PDFSintetico, contar_tokens_aproximado

import processamento as pr

OPCOES = pr.OpcoesProcessamento(limite_tokens=126, sobreposicao_tokens=25)


def _linha(texto, pagina=1, y=100.0, x=72.0, bloco=0, tamanho=11.0, negrito=False, x1=None, ocr=False):
    fim = x1 if x1 is not None else x + 6.0 * len(texto)
    return pr.LinhaVisual(texto, pagina, bloco, x, y, y + 12.0, tamanho, negrito, fim, ocr)


def _peca(texto, x0, x1, y=300.0, bloco=0, ordem=0, sobrescrito=False, tamanho=12.0):
    """Pedaço de linha com os caracteres distribuídos de x0 a x1."""
    passo = (x1 - x0) / max(1, len(texto))
    chars = [(c, x0 + passo * (i + 0.5)) for i, c in enumerate(texto)]
    span = pr._Span(chars, tamanho, False, False, sobrescrito)
    return pr._Peca(ordem, bloco, x0, y, x1, y + 12.0, [span], True)


def _texto_das_linhas(pecas):
    return [pr._texto_da_linha(grupo)[0] for grupo in pr._agrupar_linhas_visuais(pecas)]


class TestLinhasVisuais(unittest.TestCase):
    def test_linha_em_faixas_emendada_sem_repetir_caractere(self):
        # Res. 300/2020, 1ª página: cada linha vem em 3 faixas, em blocos
        # diferentes, e o caractere da emenda aparece nas duas faixas
        pecas = [_peca("pelo art. 10", 57, 218, bloco=2, ordem=0),
                 _peca("0 da Resolução nº 33, de 29 de setembro", 212, 433, bloco=157, ordem=1),
                 _peca("o de 2011 (Regimento do", 427, 564, bloco=178, ordem=2)]
        self.assertEqual(_texto_das_linhas(pecas),
                         ["pelo art. 10 da Resolução nº 33, de 29 de setembro de 2011 (Regimento do"])

    def test_colunas_afastadas_continuam_separadas(self):
        pecas = [_peca("texto da coluna da esquerda", 57, 280, bloco=1, ordem=0),
                 _peca("texto da coluna da direita", 310, 540, bloco=2, ordem=1)]
        self.assertEqual(_texto_das_linhas(pecas), ["texto da coluna da esquerda", "texto da coluna da direita"])

    def test_numero_da_nota_junto_do_texto(self):
        # PPC 2023, p. 33: o número da nota ("6") e o texto vêm em pedaços separados
        pecas = [_peca(" https://cursos.unipampa.edu.br", 125, 300, y=774, bloco=3, ordem=0, tamanho=10),
                 _peca("6", 120, 125, y=773, bloco=3, ordem=1, tamanho=8)]
        self.assertEqual(_texto_das_linhas(pecas), ["6 https://cursos.unipampa.edu.br"])

    def test_ordinal_sobrescrito(self):
        # PPC 2019 (LaTeX): "n" + "o" sobrescrito é "nº"
        pecas = [_peca("Lei n", 100, 130, ordem=0), _peca("o", 130, 135, ordem=1, sobrescrito=True),
                 _peca(" 11.640", 135, 170, ordem=2)]
        self.assertEqual(_texto_das_linhas(pecas), ["Lei nº 11.640"])


class TestCaracteresDoCorpus(unittest.TestCase):
    def test_ligaduras_da_calibri_e_marcador_da_symbol(self):
        # IN 05/2021: "ti" e "tt" da Calibri vêm como "\u019f" e "\u01a9";
        # Res. 204/2018: o traço de lista da fonte Symbol vem como U+F02D
        self.assertEqual(pr.limpar_linha("Portaria Norma\u019fva sobre a Pol\u00ed\u019fca, h\u01a9ps://sei"),
                         "Portaria Normativa sobre a Política, https://sei")
        self.assertEqual(pr.limpar_linha("\uf02d Ata ou documento equivalente"), "- Ata ou documento equivalente")


class TestCabecalhosDoCorpus(unittest.TestCase):
    def test_marcas_do_navegador_em_documento_de_uma_pagina(self):
        # Termo de Apostilamento 01 (impresso do SEI): data e hora no topo,
        # endereço encurtado e "1/1" na base
        pagina = pr.PaginaExtraida(1, 842, [
            _linha("06/05/2022 13:06 SEI/UNIPAMPA - 0803102 - Termo de Apostilamento GR", y=15, tamanho=8),
            _linha("Texto do termo de apostilamento.", y=300),
            _linha("https://sei.unipampa.edu.br/sei/controlador.php?acao=x&infra_\N{HORIZONTAL ELLIPSIS}",
                   y=818, tamanho=8),
            _linha("1/1", y=818, x=557, tamanho=8)])
        pr.remover_cabecalhos_rodapes([pagina])
        self.assertEqual([l.visivel for l in pagina.linhas], ["Texto do termo de apostilamento."])

    def test_documento_curto_exige_todas_as_paginas(self):
        # Portaria 618/2026: "Leia-se:" abre as páginas 2 e 3 e é conteúdo
        paginas = []
        for n in range(1, 4):
            linhas = [_linha("Corpo da página.", n, y=300),
                      _linha(f"Portaria GR 618 (2012066) SEI 23100.012163/2025-79 / pg. {n}", n, y=821)]
            if n > 1:
                linhas.append(_linha("Leia-se:", n, y=68))
            paginas.append(pr.PaginaExtraida(n, 842, linhas))
        removidas = pr.remover_cabecalhos_rodapes(paginas)
        self.assertTrue(all("Portaria GR 618" in r for r in removidas))
        self.assertIn("Leia-se:", [l.visivel for l in paginas[1].linhas])

    def test_rodape_encurtado_de_jeitos_diferentes(self):
        # IN 05/2022: o navegador encurta o endereço de um jeito nas páginas 1-9
        # e de outro nas páginas 10-24
        paginas = []
        for n in range(1, 13):
            fim = "&infra_\N{HORIZONTAL ELLIPSIS}" if n < 10 else "&infr\N{HORIZONTAL ELLIPSIS}"
            paginas.append(pr.PaginaExtraida(n, 842, [
                _linha("Conteúdo.", n, y=300),
                _linha(f"https://sei.unipampa.edu.br/sei/controlador.php?acao=documento_imprimir_web{fim} {n}/12",
                       n, y=818, tamanho=8)]))
        pr.remover_cabecalhos_rodapes(paginas)
        self.assertTrue(all([l.visivel for l in p.linhas] == ["Conteúdo."] for p in paginas))

    def test_sumario_removido(self):
        # Manuais de Normalização e Regimento Geral
        linhas = [_linha("SUMÁRIO", y=80),
                  _linha("1 INTRODUÇÃO .................................................. 7", y=110),
                  _linha("4.5.4 Documento em que a editora é a mesma pessoa física ou jurídica que o", y=130),
                  _linha("autor ........................................................... 24", y=145),
                  _linha("TÍTULO I - DAS DISPOSIÇÕES PRELIMINARES ....................... 5", y=160),
                  _linha("Figura 1 - Organograma ....................................... 12", y=175)]
        linhas.append(_linha("1 INTRODUÇÃO", y=300))
        pagina = pr.PaginaExtraida(1, 842, linhas)
        # sai também o título "SUMÁRIO" (logo antes de uma linha de sumário)
        self.assertEqual(pr.remover_sumarios([pagina]), 6)
        self.assertEqual([l.visivel for l in pagina.linhas], ["1 INTRODUÇÃO"])


    def test_sumario_com_numero_na_linha_de_baixo(self):
        # PPC 2023: o número da página caiu na linha de baixo e as subseções
        # não têm pontilhado
        linhas = [_linha("SUMÁRIO", y=80),
                  _linha("1 CONTEXTUALIZAÇÃO ................................................ 15", y=110),
                  _linha("1.1 Contextualização da UNIPAMPA ................................", y=140),
                  _linha("15", y=156),
                  _linha("1.3.1 Justificativa 25", y=180),
                  _linha("1.3.2 Histórico do Curso 27", y=200),
                  _linha("1.4 Apresentação do Curso ........................................", y=220),
                  _linha("30", y=236)]
        pagina = pr.PaginaExtraida(9, 842, linhas)
        self.assertEqual(pr.remover_sumarios([pagina]), 8)
        self.assertEqual(pagina.linhas, [])


class TestParagrafosDoCorpus(unittest.TestCase):
    def test_espacamento_misto_nao_parte_a_frase(self):
        # Manual de Referências: exemplos em espaço simples e texto em 1,5; a
        # linha em 1,5 parecia parágrafo novo
        linhas = [_linha("RIO GRANDE DO SUL. Secretaria da Justiça. Cartilha. 2000.", y=100),
                  _linha("BRASIL. Ministério da Saúde. Guia de bolso. Brasília, 2010.", y=113),
                  _linha("BIBLIOTECA NACIONAL. Inventário. Lisboa, 1996.", y=126),
                  _linha("Para instituição governamental, o nome da instituição deve ser", y=160, x1=520),
                  _linha("precedido pelo nome do órgão superior.", y=185)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        self.assertIn("Para instituição governamental, o nome da instituição deve ser precedido pelo nome "
                      "do órgão superior.", [u.texto for u in unidades])

    def test_frase_interrompida_por_figura_e_religada(self):
        # PPC 2019: figura com "Fonte: NDE (2016)" no meio da frase, com o
        # hífen de separação silábica do LaTeX ("do-" + "centes")
        unidades = [pr.Unidade("texto", "As discussões envolveram os do-", [(0, 19)]),
                    pr.Unidade("texto", "Figura 2 - Histórico do curso", [(0, 19)]),
                    pr.Unidade("texto", "Fonte: NDE (2016)", [(0, 19)]),
                    pr.Unidade("texto", "centes concursados em 2007.", [(0, 20)])]
        r = pr._religar_continuacoes(unidades, silabica=True)
        self.assertEqual([u.texto for u in r], ["As discussões envolveram os docentes concursados em 2007.",
                                                "Figura 2 - Histórico do curso", "Fonte: NDE (2016)"])
        self.assertEqual((r[0].pagina_inicio, r[0].pagina_fim), (19, 20))

    def test_legenda_no_alto_da_pagina_nao_entra_no_paragrafo(self):
        # PPC 2019, p. 18-19: a frase para em "do-" e a p. 19 abre com a figura;
        # a legenda entrava no meio do parágrafo ("do- Figura 3 ... centes")
        paginas = [pr.PaginaExtraida(18, 842, [_linha("A partir da entrada de mais do-", 18, y=770)]),
                   pr.PaginaExtraida(19, 842, [
                       _linha("Figura 3 \N{EN DASH} Histórico da procura no processo seletivo", 19, y=86),
                       _linha("Fonte: NDE (2016)", 19, y=334, tamanho=9.5),
                       _linha("centes concursados em 2007.", 19, y=388)])]
        unidades, _ = pr.montar_unidades(paginas, 11.0, True)
        self.assertEqual([u.texto for u in unidades], [
            "A partir da entrada de mais docentes concursados em 2007.",
            "Figura 3 \N{EN DASH} Histórico da procura no processo seletivo", "Fonte: NDE (2016)"])

    def test_nome_de_capitulo_que_termina_em_preposicao(self):
        # Res. 480/2026: "... COMPONENTE CURRICULAR PARA" + "DISCENTE PROVÁVEL FORMANDO"
        linhas = [_linha("CAPÍTULO II", y=100, bloco=1),
                  _linha("DA MODALIDADE ESPECIAL DE OFERTA PARA", y=113, bloco=1),
                  _linha("DISCENTE PROVÁVEL FORMANDO", y=150, bloco=2),
                  _linha("Art. 16 A oferta na modalidade especial é destinada ao provável formando.", y=180, bloco=3)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        self.assertEqual(unidades[0].texto,
                         "CAPÍTULO II DA MODALIDADE ESPECIAL DE OFERTA PARA DISCENTE PROVÁVEL FORMANDO")
        pr.anotar_contexto(unidades)
        self.assertEqual(unidades[1].secao_nome, "Da modalidade especial de oferta para discente provável formando")

    def test_paragrafo_em_negrito_nao_vira_titulo(self):
        # Guia de elementos obrigatórios: parágrafo em negrito que quebra de linha
        linhas = [_linha("Converse com seu orientador! Juntos, vocês vão definir o formato mais", y=100,
                         negrito=True),
                  _linha("adequado à sua pesquisa.", y=113, negrito=True)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        self.assertEqual([(u.tipo, u.texto) for u in unidades], [
            ("texto", "Converse com seu orientador! Juntos, vocês vão definir o formato mais adequado à sua "
                      "pesquisa.")])

    def test_inciso_que_ficou_so_com_o_marcador_sai(self):
        # Res. 29/2011 consolidada: texto do inciso riscado, sobrou "III. ."
        linhas = [_linha("Art. 62 A integralização observa:", y=100),
                  _linha("III.", y=113), _linha(f" {pr.RISCO} ", y=126), _linha(".", y=139)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        self.assertEqual([u.texto for u in unidades], ["Art. 62 A integralização observa:"])


class TestArtigoDasUnidades(unittest.TestCase):
    def test_paragrafo_unico_com_maiuscula(self):
        # IN 05/2021, IN 05/2022 e anexos do PPC 2019 escrevem "Parágrafo Único -"
        # e "Parágrafo Único:"; só "Parágrafo único." era reconhecido
        for texto in ("Parágrafo Único - Demais atribuições estarão previstas nos editais.",
                      "Parágrafo Único: É permitido o registro de discussões não presenciais.",
                      "PARÁGRAFO ÚNICO. O prazo é de dez dias."):
            self.assertEqual(pr._classificar(texto)[:2], ("paragrafo", "único"), texto)

    def test_itens_logo_abaixo_do_artigo_pertencem_a_ele(self):
        # Norma de Láurea da EC: os critérios do Art. 3 vêm numa lista com "•"
        linhas = [_linha("Art. 3 \N{EN DASH} São considerados os seguintes critérios:", y=100, bloco=1),
                  _linha("\N{BULLET} média aritmética das notas;", y=113, bloco=2),
                  _linha("\N{BULLET} aspectos formativos, como assiduidade.", y=126, bloco=3),
                  _linha("ANEXO I", y=160, bloco=4, negrito=True),
                  _linha("Texto do anexo, que não faz parte do artigo.", y=190, bloco=5)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        pr.anotar_contexto(unidades)
        self.assertEqual([(u.tipo, u.artigo) for u in unidades],
                         [("artigo", 3), ("item", 3), ("item", 3), ("cabecalho", None), ("texto", None)])

    def test_tabela_depois_do_ultimo_artigo_nao_herda(self):
        # Calendário 2026: o calendário inteiro vem depois do Art. 10 da portaria
        tabela = pr.Tabela(1, 150, 190, [], ["12 e 13/01 | OFERTA PLE-I: registro da oferta."],
                           [["12 e 13/01", "OFERTA PLE-I: registro da oferta."]], 2)
        linhas = [_linha("Art. 10 Esta Portaria entra em vigor na data de sua publicação.", y=100, bloco=1),
                  tabela, _linha("Abandono: discente que não efetuou a matrícula.", y=220, bloco=3)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        pr.anotar_contexto(unidades)
        self.assertEqual([u.artigo for u in unidades], [10, None, None])


def _u(tipo, texto, rotulo="", marcador=0):
    return pr.Unidade(tipo, texto, [(0, 1)], rotulo=rotulo, tamanho_marcador=marcador)


def _frase(n_palavras, palavra="informação"):
    return " ".join([palavra] * n_palavras) + "."


class TestSegmentacaoDoCorpus(unittest.TestCase):
    def _segmentar(self, unidades):
        pr.anotar_contexto(unidades)
        return [f.texto for f in pr.segmentar(unidades, contar_tokens_aproximado, 126, 25)]

    def test_numero_de_item_nao_vira_frase_sozinho(self):
        # PPC 2019, p. 26: "6." ficava num fragmento só dele
        texto = "6. Lei nº 11.645/2008, que estabelece as diretrizes e bases da educação nacional."
        pedacos = pr._dividir_em_pedacos(texto, contar_tokens_aproximado, 126)
        self.assertEqual([texto[a:b].strip() for a, b in pedacos], [texto])

    def test_introducao_curta_vai_para_o_fragmento_seguinte(self):
        # resoluções: "RESOLVE:" logo antes do TÍTULO I
        textos = self._segmentar([_u("texto", _frase(60)), _u("texto", "RESOLVE:"),
                                  _u("titulo", "TÍTULO I DAS DISPOSIÇÕES PRELIMINARES", "I"),
                                  _u("artigo", "Art. 1º Esta norma trata das disposições gerais.", "1", 7)])
        self.assertNotIn("RESOLVE:", textos)
        self.assertTrue(any(t.startswith("RESOLVE:\nTÍTULO I") for t in textos), textos)

    def test_trecho_curto_volta_para_o_fragmento_anterior(self):
        # PPC: "Pré-requisitos" + "Não há." entre dois títulos da ementa
        textos = self._segmentar([_u("cabecalho", "Ementa"), _u("texto", _frase(40)),
                                  _u("cabecalho", "Pré-requisitos"), _u("texto", "Não há."),
                                  _u("cabecalho", "Objetivos"), _u("texto", _frase(40, "objetivo"))])
        self.assertEqual(len(textos), 2, textos)
        self.assertTrue(textos[0].endswith("Pré-requisitos\nNão há."), textos)
        self.assertTrue(textos[1].startswith("Objetivos"), textos)

    def test_titulos_seguidos_ficam_juntos(self):
        # anexos do PPC: três linhas de título antes de um parágrafo longo
        textos = self._segmentar([_u("cabecalho", "UNIVERSIDADE FEDERAL DO PAMPA"),
                                  _u("cabecalho", "COMISSÃO DE CURSO DE ENGENHARIA DE COMPUTAÇÃO"),
                                  _u("cabecalho", "CAMPUS BAGÉ"), _u("texto", _frase(110))])
        self.assertEqual(textos[0], "UNIVERSIDADE FEDERAL DO PAMPA\nCOMISSÃO DE CURSO DE ENGENHARIA DE "
                                    "COMPUTAÇÃO\nCAMPUS BAGÉ")

    def test_frase_longa_sem_pontuacao_dividida_por_igual(self):
        texto = " ".join(["informação"] * 150)          # 300 "tokens" sem pontuação
        blocos = pr._dividir_por_palavras(texto, 0, len(texto), contar_tokens_aproximado, 126)
        tamanhos = [contar_tokens_aproximado(texto[a:b]) for a, b in blocos]
        self.assertEqual(len(blocos), 3)
        self.assertLessEqual(max(tamanhos) - min(tamanhos), 4, tamanhos)


def _pdf_com_risco_parcial(caminho: Path, linhas: list[tuple[str, str, bool]]) -> Path:
    """Cada linha: (texto, trecho a riscar, deixar uma falha no meio do risco)."""
    import fitz
    doc = fitz.open()
    pagina = doc.new_page(width=595, height=842)
    y = 120.0
    for texto, riscar, falha in linhas:
        pagina.insert_text((72, y), texto, fontname="helv", fontsize=11)
        if riscar:
            inicio = 72 + fitz.get_text_length(texto[:texto.index(riscar)], fontname="helv", fontsize=11)
            fim = inicio + fitz.get_text_length(riscar, fontname="helv", fontsize=11)
            meio = y - 11 * 0.3
            if falha:        # o traço falha numa letra no meio (fonte trocada no PDF)
                corte = (inicio + fim) / 2
                pagina.draw_line((inicio, meio), (corte - 2, meio), width=0.8)
                pagina.draw_line((corte + 2, meio), (fim, meio), width=0.8)
            else:
                pagina.draw_line((inicio, meio), (fim, meio), width=0.8)
        y += 16
    doc.save(caminho)
    doc.close()
    return caminho


class TestRiscoPorCaractere(unittest.TestCase):
    def test_risco_so_numa_parte_do_trecho(self):
        # Res. 29/2011 consolidada, incisos do estágio: o fim do texto revogado
        # (riscado) e a anotação (sem risco) vêm no mesmo trecho do PDF
        with tempfile.TemporaryDirectory() as pasta:
            pdf = _pdf_com_risco_parcial(Path(pasta) / "r.pdf", [
                ("Art. 135 Compete à Coordenação de Estágios:", "", False),
                ("I. elaborar e comunicar as regras do estágio com o PPC; (Revogado pela Resolução 329)",
                 "elaborar e comunicar as regras do estágio com o PPC;", False),
                ("II. manter contato com os supervisores de estágio.", "", False)])
            doc = pr.processar_pdf(pdf, contar_tokens_aproximado, OPCOES)
        textos = [u.texto for u in doc.unidades]
        self.assertEqual(textos, ["Art. 135 Compete à Coordenação de Estágios:",
                                  "II. manter contato com os supervisores de estágio."])

    def test_falha_curta_no_risco_nao_deixa_sobra(self):
        # Res. 208/2018: o traço falha no "í" de "política" (letra de outra fonte)
        with tempfile.TemporaryDirectory() as pasta:
            pdf = _pdf_com_risco_parcial(Path(pasta) / "r.pdf", [
                ("APROVAR as normas da politica institucional de fomento.",
                 "APROVAR as normas da politica institucional de fomento.", True),
                ("APROVAR as normas da nova política institucional de fomento.", "", False)])
            doc = pr.processar_pdf(pdf, contar_tokens_aproximado, OPCOES)
        self.assertEqual([u.texto for u in doc.unidades],
                         ["APROVAR as normas da nova política institucional de fomento."])


class TestRevogacaoEmBloco(unittest.TestCase):
    def test_resto_de_artigo_revogado_em_bloco_sai(self):
        # Res. 29/2011 consolidada até a Res. 480/2026: o início do Art. 45
        # ficou sem risco, mas a nota diz que os Arts. 40 a 48 foram revogados
        linhas = [_linha("Art. 45 A prioridade de matrícula em componentes curriculares obedece:", y=100),
                  _linha("(Do Art. 40 ao Art. 48 - Revogados pela Resolução 480, de 20/08/2026)", y=126, bloco=1),
                  _linha("Art. 49 São consideradas atividades de ensino os componentes curriculares.", y=152,
                         bloco=2)]
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(1, 842, linhas)], corpo=11.0)
        pr.anotar_contexto(unidades)
        mantidas, descartadas = pr.descartar_revogados_em_bloco(unidades)
        self.assertEqual([d["texto"][:7] for d in descartadas], ["Art. 45"])
        self.assertEqual([u.texto[:8] for u in mantidas], ["(Do Art.", "Art. 49 "])


class TestTitulosDoCorpus(unittest.TestCase):
    def test_titulo_pela_identificacao_do_ato(self):
        # Várias resoluções: a identificação tem o mesmo corpo de letra do texto
        paginas = [pr.PaginaExtraida(1, 842, [
            _linha("Ministério da Educação", y=90), _linha("Universidade Federal do Pampa", y=103),
            _linha("RESOLUÇÃO CONSUNI/UNIPAMPA Nº 300, DE 10 DE DEZEMBRO DE 2020", y=140),
            _linha("Estabelece o Programa Institucional de acompanhamento da evasão.", y=170)])]
        self.assertEqual(pr.titulo_do_documento("Res_300-2020.pdf", paginas, 11.0),
                         "Resolução CONSUNI/UNIPAMPA nº 300, de 10 de dezembro de 2020")

    def test_titulo_curto_demais_usa_o_nome_do_arquivo(self):
        # Guia de elementos: a maior letra da capa é "UNIPAMPA • 2026"
        paginas = [pr.PaginaExtraida(1, 842, [_linha("UNIPAMPA \N{BULLET} 2026", y=90, tamanho=20),
                                              _linha("Texto do guia.", y=200)])]
        self.assertEqual(pr.titulo_do_documento("Guia_Elementos_2026.pdf", paginas, 11.0), "Guia Elementos 2026")


class TestTabelasDoCorpus(unittest.TestCase):
    def test_tabela_de_datas_sem_cabecalho(self):
        # Calendário 2026: a primeira linha é dado, não nome de coluna
        with tempfile.TemporaryDirectory() as pasta:
            pdf = PDFSintetico()
            pdf.escrever("CALENDÁRIO ACADÊMICO DA GRADUAÇÃO 2026", negrito=True)
            pdf.tabela([["02 a 16/03", "NOTAS PLE-I: registro das notas pelo docente."],
                        ["02 a 06/03", "FORMAÇÃO PEDAGÓGICA: formação organizada pelos cursos."],
                        ["03 a 09/03", "REGIME ESPECIAL: solicitação junto à Secretaria Acadêmica."]], [90, 350])
            doc = pr.processar_pdf(pdf.salvar(Path(pasta) / "cal.pdf"), contar_tokens_aproximado, OPCOES)
        linhas = [u.texto for u in doc.unidades if u.tipo in ("tabela", "linha_tabela")]
        self.assertEqual(linhas[1], "02 a 06/03 | FORMAÇÃO PEDAGÓGICA: formação organizada pelos cursos.")
        self.assertFalse(any("NOTAS PLE-I" in l for l in linhas[1:]))

    def test_celula_mesclada_na_vertical_e_repetida(self):
        # Portaria 618/2026: "Semestre Letivo 2026/1" mesclado em várias linhas
        celulas = [["Semestre Letivo 2026/1", "21/04/2026", "Feriado nacional"],
                   [None, "04/06/2026", "Ponto facultativo"],
                   [None, "20/06/2026", "Feriado municipal"]]
        linhas = [SimpleNamespace(bbox=(0, 100 + 20 * i, 500, 120 + 20 * i),
                                  cells=[(0, 100, 100, 160) if i == 0 else None, (100, 0, 200, 0), (200, 0, 500, 0)])
                  for i in range(3)]
        colunas = pr._preencher_mescladas(SimpleNamespace(rows=linhas), celulas)
        self.assertEqual(colunas, {0})
        self.assertEqual([l[0] for l in celulas], ["Semestre Letivo 2026/1"] * 3)

    def test_coluna_de_grupo_preenchida_e_continuada(self):
        # Matriz curricular do PPC 2023: o semestre aparece só na 1ª linha do grupo
        parte1 = [["1", "1", "Elementos de Matemática", "4"], ["", "2", "Química Geral Básica", "4"]]
        grupo = pr._preencher_coluna_de_grupo(parte1)
        self.assertEqual((parte1[1][0], grupo), ("1", "1"))
        parte2 = [["", "3", "Elementos de Física", "2"], [None, "4", "Fundamentos de Hardware", "6"],
                  ["2", "7", "Projeto Digital I", "6"], ["", "8", "Algoritmos", "6"]]
        pr._preencher_coluna_de_grupo(parte2, anterior=grupo)
        self.assertEqual([l[0] for l in parte2], ["1", "1", "2", "2"])

    def test_so_a_primeira_coluna_e_de_grupo(self):
        # coluna de pré-requisito vazia quer dizer "não tem": não herda o valor de cima
        celulas = [["BA01", "Cálculo I", ""], ["BA02", "Cálculo II", "BA01"], ["BA03", "Física I", ""]]
        pr._preencher_coluna_de_grupo(celulas)
        self.assertEqual([l[2] for l in celulas], ["", "BA01", ""])

    def test_linha_de_titulo_e_legenda(self):
        cabecalho = ["S", "N", "Componente", "CH"]
        linhas = pr._linearizar(cabecalho, [["JANEIRO/2026", None, None, None], ["1", "1", "Cálculo I", "60"]])
        self.assertEqual(linhas, ["JANEIRO/2026", "S: 1; N: 1; Componente: Cálculo I; CH: 60"])

    def test_linha_so_com_omissao_sai(self):
        # Portaria 618/2026 (retifica o calendário): as linhas que não mudaram
        # aparecem como "(...)" em todas as colunas
        cabecalho = ["Período Letivo", "Data", "Tipo"]
        linhas = pr._linearizar(cabecalho, [["(...)", "(...)", "(...)"],
                                            ["Semestre Letivo 2026/1", "(...)", "(...)"],
                                            ["Semestre Letivo 2026/1", "04/06/2026", "Ponto facultativo"]])
        self.assertEqual(linhas, ["Período Letivo: Semestre Letivo 2026/1; Data: 04/06/2026; Tipo: Ponto facultativo"])

    def test_cabecalho_em_dois_niveis(self):
        # Tabelas de ACG dos PPCs 2019 e 2023: "CH máxima" mesclada na
        # horizontal sobre "por atividade" e "por tipo de atividade"
        celulas = [["Atividade", "CH máxima", None, "Comprovante"],
                   ["Atividade", "por atividade", "por tipo de atividade", "Comprovante"],
                   ["Monitoria", "CH semanal/semestre", "60", "Certificado"]]
        celulas_pdf = [[(0, 0, 1, 1), (1, 0, 2, 1), None, (3, 0, 4, 1)],
                       [None, (1, 0, 2, 1), (2, 0, 3, 1), None],
                       [(0, 0, 1, 1)] * 4]
        t = SimpleNamespace(rows=[SimpleNamespace(bbox=(0, 10 * k, 500, 10 * k + 10), cells=c)
                                  for k, c in enumerate(celulas_pdf)])
        with mock.patch.object(pr, "_fracao_negrito", side_effect=[1.0, 1.0, 0.0]):
            nomes = pr._cabecalho_em_dois_niveis(None, t, celulas, 0)
        self.assertEqual(nomes, ["Atividade", "CH máxima por atividade", "CH máxima por tipo de atividade",
                                 "Comprovante"])
        self.assertEqual(pr._nomes_das_colunas(t, celulas, 0), ["Atividade", "CH máxima", "CH máxima",
                                                                "Comprovante"])

    def test_continuacao_que_repete_so_o_primeiro_nivel(self):
        # PPC 2023, p. 409-410: a continuação repete só "Atividade | CH máxima | Comprovante"
        completo = ["Atividade", "CH máxima por atividade", "CH máxima por tipo de atividade", "Comprovante"]
        t1 = pr.Tabela(1, 600, 780, completo, ["..."], [["Monitoria", "CH semanal", "60", "Certificado"]], 4)
        t2 = pr.Tabela(2, 80, 200, ["Atividade", "CH máxima", "CH máxima", "Comprovante"], ["..."],
                       [["Representação em órgãos colegiados", "1h / ata", "20h", "Atas das reuniões"]], 4)
        paginas = [pr.PaginaExtraida(1, 842, [t1]), pr.PaginaExtraida(2, 842, [t2])]
        self.assertEqual(pr._continuar_cabecalhos(paginas, 11.0), 1)
        self.assertEqual(t2.linhas, ["Atividade: Representação em órgãos colegiados; CH máxima por atividade: "
                                     "1h / ata; CH máxima por tipo de atividade: 20h; Comprovante: Atas das reuniões"])

    def test_cabecalho_herdado_na_pagina_seguinte(self):
        # Calendário 2026, p. 9: a tabela continua sem repetir o cabeçalho
        cab = ["Período", "Data", "Tipo"]
        t1 = pr.Tabela(1, 600, 780, cab, ["Período: 2026/1; Data: 21/04/2026; Tipo: Feriado"],
                       [["2026/1", "21/04/2026", "Feriado"]], 3)
        t2 = pr.Tabela(2, 80, 200, [], ["2026/1 | 04/06/2026 | Ponto facultativo"],
                       [["2026/1", "04/06/2026", "Ponto facultativo"]], 3)
        paginas = [pr.PaginaExtraida(1, 842, [_linha("Tabela 1 - Feriados", y=580), t1]),
                   pr.PaginaExtraida(2, 842, [t2])]
        self.assertEqual(pr._continuar_cabecalhos(paginas, 11.0), 1)
        self.assertEqual(t2.linhas, ["Período: 2026/1; Data: 04/06/2026; Tipo: Ponto facultativo"])


class TestCorrecoesDeOCR(unittest.TestCase):
    def test_erros_tipicos_do_tesseract(self):
        # IN PROGRAD 01/2018 e Res. 433/2025, digitalizadas e passadas por OCR
        textos = ["Art. 4o Disciplinar o aproveitamento.", "Art, 2o O Programa integra a política.",
                  "Art. 32 A extensão universitária é um processo.", "Il - técnicos Administrativos;",
                  "HI - discentes; e", "CAPÍTULO |", "S 1o Para o aproveitamento da carga horária.",
                  "Art. 6o desta Instrução Normativa, citado no texto.", "pela Resolução no 05, de 2010."]
        linhas = [_linha(t, y=100 + 20 * i, ocr=True) for i, t in enumerate(textos)]
        comum = _linha("Il - linha de PDF digital fica como está.", y=400)
        pagina = pr.PaginaExtraida(1, 842, linhas + [comum])
        pr.corrigir_ocr([pagina])
        self.assertEqual([l.texto for l in pagina.linhas], [
            "Art. 1º Disciplinar o aproveitamento.", "Art. 2º O Programa integra a política.",
            "Art. 3º A extensão universitária é um processo.", "II - técnicos Administrativos;",
            "III - discentes; e", "CAPÍTULO I", "§ 1º Para o aproveitamento da carga horária.",
            "Art. 6o desta Instrução Normativa, citado no texto.", "pela Resolução nº 05, de 2010.",
            "Il - linha de PDF digital fica como está."])

    def test_pdf_com_camada_de_ocr(self):
        # camada de texto invisível (como a que o OCRmyPDF cria sobre a imagem):
        # é lida, corrigida e marcada para o aviso do relatório
        import fitz
        with tempfile.TemporaryDirectory() as pasta:
            documento = fitz.open()
            pagina = documento.new_page()
            pagina.insert_text((72, 100), "Art. 1o Esta Instrução Normativa disciplina o aproveitamento.",
                               fontsize=11, render_mode=3)
            pagina.insert_text((72, 130), "Art. 2o O Programa integra a política institucional.",
                               fontsize=11, render_mode=3)
            caminho = Path(pasta) / "digitalizado.pdf"
            documento.save(caminho)
            documento.close()
            doc = pr.processar_pdf(caminho, contar_tokens_aproximado, OPCOES)
        self.assertEqual(doc.paginas_ocr, [1])
        self.assertEqual([u.texto[:8] for u in doc.unidades], ["Art. 1º ", "Art. 2º "])

    def test_paragrafo_lido_como_8_ou_cifrao(self):
        # Res. 433/2025: o OCR leu o "§" como "8" (19 vezes) ou "$" (2 vezes)
        textos = ["8 1o A definição das áreas temáticas possibilita a organização.",
                  "$ 2o As ações de extensão serão avaliadas pelas Comissões.",
                  "84o O Prêmio só poderá ser concedido uma vez.",
                  "8 1o semestre de 2025, com minúscula depois, fica como está."]
        linhas = [_linha(t, y=100 + 20 * i, ocr=True) for i, t in enumerate(textos)]
        pagina = pr.PaginaExtraida(1, 842, linhas)
        pr.corrigir_ocr([pagina])
        self.assertEqual([l.texto for l in pagina.linhas], [
            "§ 1º A definição das áreas temáticas possibilita a organização.",
            "§ 2º As ações de extensão serão avaliadas pelas Comissões.",
            "§ 4º O Prêmio só poderá ser concedido uma vez.",
            "8 1o semestre de 2025, com minúscula depois, fica como está."])


class TestTitulosFalsos(unittest.TestCase):
    """Versão 6: linhas em destaque que viravam título de seção por engano e
    davam nome errado ao cabeçalho de contexto de todos os fragmentos
    seguintes (ERROS_CORRIGIDOS.md, erro 3.1)."""

    def _unidades(self, linhas, pagina=1):
        unidades, _ = pr.montar_unidades([pr.PaginaExtraida(pagina, 842, linhas)], corpo=11.0)
        pr.anotar_contexto(unidades)
        return unidades

    def test_item_numerado_em_fonte_normal_nao_vira_titulo(self):
        # PPC 2019, p. 45: o item 5 (fonte normal) tem número e a 1ª linha termina
        # em "nos"; virava título e dava nome a 40 fragmentos (p. 45 a 51)
        unidades = self._unidades([
            _linha("2.3.1 Integralização curricular", y=100, negrito=True),
            _linha("Para colar grau, o discente deve:", y=130),
            _linha("5. Obter validação em 120 horas de atividades complementares, nos", y=160, bloco=1),
            _linha("termos da normativa específica, apresentada no Apêndice D.", y=173, bloco=1),
            _linha("O estágio tem supervisão de um professor do curso.", y=203, bloco=2)], pagina=45)
        self.assertEqual([u.tipo for u in unidades], ["cabecalho", "texto", "item", "texto"])
        self.assertEqual(unidades[-1].secao_nome, "Integralização curricular")

    def test_observacao_em_negrito_nao_vira_titulo(self):
        # guia de matrícula, p. 4: a observação em negrito era o título de 9 fragmentos
        unidades = self._unidades([
            _linha("Exemplos de Solicitação:", y=100, tamanho=16.0, negrito=True),
            _linha("Observação: Aluno eventualmente pode não conseguir vaga em Cálculo I na turma", y=140,
                   negrito=True),
            _linha("EC11, mas sim na EC12. Idem para Laboratório de Física I.", y=153, negrito=True),
            _linha("Abaixo segue um exemplo visual com os três passos.", y=190)], pagina=4)
        self.assertEqual([u.tipo for u in unidades], ["cabecalho", "texto", "texto"])
        self.assertTrue(unidades[1].texto.startswith("Observação: Aluno"))
        self.assertTrue(unidades[1].texto.endswith("Idem para Laboratório de Física I."))
        # o título verdadeiro (16 pt, com dois-pontos) agora vale para as páginas de exemplos
        self.assertEqual(unidades[-1].secao_nome, "Exemplos de Solicitação")

    def test_dois_pontos_so_com_letra_maior(self):
        unidades = self._unidades([_linha("Dicas:", y=100, negrito=True),
                                   _linha("Equilibre os créditos do semestre.", y=130)])
        self.assertNotIn("cabecalho", [u.tipo for u in unidades])

    def test_inicio_em_negrito_que_para_em_preposicao_e_paragrafo(self):
        # PPC 2019, p. 66: o nome do programa, em negrito, abre o parágrafo
        unidades = self._unidades([
            _linha("Programa Institucional de Bolsas de Iniciação em Desenvolvimento Tecnológico e", y=100,
                   negrito=True),
            _linha("Inovação (PROBITI) oferece bolsas para participação em projetos.", y=113)], pagina=66)
        self.assertEqual([(u.tipo, u.texto) for u in unidades], [
            ("texto", "Programa Institucional de Bolsas de Iniciação em Desenvolvimento Tecnológico e "
                      "Inovação (PROBITI) oferece bolsas para participação em projetos.")])

    def test_titulo_da_obra_nas_referencias_nao_vira_secao(self):
        # PPC 2019, p. 76: o título da obra (negrito, pela ABNT) era seção de 17 fragmentos
        unidades = self._unidades([
            _linha("REFERÊNCIAS", y=100, negrito=True),
            _linha("ACM/IEEE. Computing Curricula.", y=130),
            _linha("The Overview Report covering undergraduate degree programs", y=160, negrito=True),
            _linha("Software Engineering. IEEE Press, 2005.", y=173),
            _linha("APÊNDICE A", y=220, negrito=True),
            _linha("Texto do apêndice.", y=250)], pagina=76)
        self.assertEqual([u.texto for u in unidades if u.tipo == "cabecalho"], ["REFERÊNCIAS", "APÊNDICE A"])
        self.assertEqual(unidades[-1].secao_nome, "Apêndice a")

    def test_numeracao_com_parentese_e_item(self):
        # guia de matrícula: "2) Atentar para os prazos..." (negrito) é dica, não seção
        unidades = self._unidades([_linha("2) Atentar para os prazos da matrícula via WEB", y=100, negrito=True),
                                   _linha("Os prazos estão no calendário acadêmico.", y=130)])
        self.assertEqual([u.tipo for u in unidades], ["item", "texto"])

    def test_sinais_de_frase_e_abreviacoes(self):
        self.assertTrue(pr._parece_frase_ou_lista("Pense no TCC como uma sequência de blocos. Os itens"))
        self.assertTrue(pr._parece_frase_ou_lista("1. Auxílio Moradia 2. Alojamento 3. Vaga na Moradia"))
        self.assertTrue(pr._parece_frase_ou_lista("Observação: Aluno pode não conseguir vaga"))
        self.assertFalse(pr._parece_frase_ou_lista("Coordenação do Prof. Dr. Fulano de Tal"))
        self.assertFalse(pr._parece_frase_ou_lista("2.4.4.2 Atividades Complementares de Graduação"))
        # título montado que termina em ponto: frase (salvo em maiúsculas, como ementas)
        self.assertFalse(pr._titulo_montado_valido("Obter validação em 120 horas, apresentada no Apêndice D."))
        self.assertTrue(pr._titulo_montado_valido("FIXAR O TEMPO MÁXIMO DE INTEGRALIZAÇÃO DOS CURSOS."))

    def test_nome_de_secao_cortado_no_fim_da_palavra(self):
        # até a versão 5 o corte era em 80 caracteres, no meio da palavra ("..., nos t")
        nome = ("Normas para aproveitamento de atividades complementares de graduação no curso de "
                "Engenharia de Computação")
        self.assertEqual(pr._encurtar(nome, pr.LIMITE_NOME_SECAO), nome)
        longo = nome + " do Campus Bagé da Universidade Federal do Pampa"
        curto = pr._encurtar(longo, pr.LIMITE_NOME_SECAO)
        self.assertLessEqual(len(curto), pr.LIMITE_NOME_SECAO)
        self.assertEqual(longo[len(curto)], " ")                # corte entre palavras
        self.assertFalse(pr._termina_com_conector(curto))      # sem "do" solto no fim
        self.assertEqual(curto, nome)


if __name__ == "__main__":
    unittest.main()
