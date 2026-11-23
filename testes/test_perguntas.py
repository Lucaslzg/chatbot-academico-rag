"""Testes do conjunto de perguntas trocável (perguntas.py)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from utilitarios import RAIZ, configuracao  # noqa: F401  (ajusta o sys.path)

import config
import perguntas as pg
from perguntas import ErroPerguntas, carregar_perguntas

DOCUMENTOS = ["Res_480-2026_Normas_dos_Processos_Academicos_da_Graduacao.pdf",
              "PPC_Engenharia_de_Computacao_2023.pdf"]

CABECALHO = "id;pergunta;resposta_correta;sem_resposta;fonte;observacao"


class _ComPasta(unittest.TestCase):
    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)

    def tearDown(self):
        self._pasta.cleanup()

    def escrever(self, nome: str, texto: str, codificacao: str = "utf-8") -> Path:
        caminho = self.pasta / nome
        caminho.write_bytes(texto.encode(codificacao))
        return caminho

    def carregar(self, nome: str, texto: str, codificacao: str = "utf-8", documentos=DOCUMENTOS):
        return carregar_perguntas(self.escrever(nome, texto, codificacao), documentos=documentos)


class TestLeituraCSV(_ComPasta):
    def test_excel_em_portugues_ponto_e_virgula_e_windows_1252(self):
        texto = (f"{CABECALHO}\r\n"
                 ";Quantas vezes posso trancar a matrícula?;No máximo quatro vezes.;não;;\r\n"
                 ";Qual o cardápio do RU hoje?;;sim;;\r\n")
        conjunto = self.carregar("reais.csv", texto, "cp1252")
        self.assertEqual(conjunto.codificacao, "Windows-1252")
        self.assertEqual([p["pergunta"] for p in conjunto.perguntas],
                         ["Quantas vezes posso trancar a matrícula?", "Qual o cardápio do RU hoje?"])
        self.assertEqual(conjunto.perguntas[0]["resposta_correta"], "No máximo quatro vezes.")
        self.assertEqual([p["sem_resposta"] for p in conjunto.perguntas], [False, True])
        self.assertEqual(conjunto.erros, [])

    def test_google_planilhas_virgula_e_utf8_com_bom(self):
        texto = ("pergunta,resposta_correta\n"
                 "\"Posso trancar uma disciplina, depois de iniciada?\",\"Sim, até a data do calendário.\"\n")
        conjunto = self.carregar("reais.csv", texto, "utf-8-sig")
        self.assertEqual(conjunto.codificacao, "UTF-8")
        self.assertEqual(conjunto.perguntas[0]["pergunta"], "Posso trancar uma disciplina, depois de iniciada?")
        self.assertEqual(conjunto.perguntas[0]["resposta_correta"], "Sim, até a data do calendário.")
        self.assertFalse(conjunto.perguntas[0]["sem_resposta"])

    def test_nomes_de_coluna_com_maiusculas_acentos_e_sinonimos(self):
        texto = ("Pergunta;Resposta correta;Sem resposta?;Documento;Observação;Carimbo de data/hora\n"
                 "como tranco a matricula;Pelo sistema acadêmico.;;;coletada em 10/11;10/11/2026\n")
        conjunto = self.carregar("form.csv", texto)
        item = conjunto.perguntas[0]
        self.assertEqual(item["pergunta"], "como tranco a matricula")      # como foi escrita
        self.assertEqual(item["resposta_correta"], "Pelo sistema acadêmico.")
        self.assertEqual(item["observacao"], "coletada em 10/11")
        self.assertTrue(any("Carimbo de data/hora" in p.mensagem for p in conjunto.avisos))

    def test_valores_de_sem_resposta(self):
        linhas = [f";P{n}?;resposta;{valor};;" for n, valor in enumerate(["sim", "Sim", "X", "s", "1"])]
        linhas += [f";Q{n}?;resposta;{valor};;" for n, valor in enumerate(["", "não", "Nao", "n", "0"])]
        conjunto = self.carregar("v.csv", CABECALHO + "\n" + "\n".join(linhas) + "\n")
        self.assertEqual([p["sem_resposta"] for p in conjunto.perguntas], [True] * 5 + [False] * 5)
        invalido = self.carregar("w.csv", f"{CABECALHO}\n;P?;resposta;talvez;;\n")
        self.assertEqual(len(invalido.erros), 1)
        self.assertEqual(invalido.erros[0].linha, 2)
        self.assertIn("talvez", invalido.erros[0].mensagem)

    def test_ids_numerados_pela_ordem_e_linhas_vazias_ignoradas(self):
        texto = f"{CABECALHO}\n;Primeira?;r;;;\n;;;;;\n\n;Segunda?;r;;;\n"
        conjunto = self.carregar("ids.csv", texto)
        self.assertEqual([p["id"] for p in conjunto.perguntas], ["P001", "P002"])
        self.assertEqual([p["linha"] for p in conjunto.perguntas], [2, 5])     # linha do Excel
        self.assertTrue(any("sem id" in p.mensagem for p in conjunto.avisos))

    def test_id_repetido_e_erro_pergunta_repetida_e_aviso(self):
        texto = f"{CABECALHO}\nA1;Posso trancar?;r;;;\nA1;Outra coisa?;r;;;\nA3;posso  TRANCAR;r;;;\n"
        conjunto = self.carregar("rep.csv", texto)
        self.assertEqual([(p.linha, p.mensagem) for p in conjunto.erros], [(3, "id repetido")])
        self.assertTrue(any(p.linha == 4 and "igual à de A1" in p.mensagem for p in conjunto.avisos))

    def test_id_automatico_que_coincide_com_id_escrito_e_erro(self):
        conjunto = self.carregar("c.csv", f"{CABECALHO}\nP002;Primeira?;r;;;\n;Segunda?;r;;;\n")
        self.assertEqual([p.mensagem for p in conjunto.erros], ["id repetido"])

    def test_pergunta_vazia_com_resposta_e_erro(self):
        conjunto = self.carregar("vazia.csv", f"{CABECALHO}\n;;uma resposta sem pergunta;;;\n")
        self.assertEqual([p.mensagem for p in conjunto.erros], ["pergunta vazia"])

    def test_respondivel_sem_resposta_correta_e_aviso(self):
        conjunto = self.carregar("a.csv", f"{CABECALHO}\n;Pergunta sem gabarito?;;;;\n")
        self.assertEqual(conjunto.erros, [])
        self.assertTrue(any("sem resposta correta" in p.mensagem for p in conjunto.avisos))
        self.assertEqual(conjunto.resumo()["sem_resposta_correta"], 1)

    def test_sem_resposta_com_resposta_escrita_e_aviso(self):
        conjunto = self.carregar("b.csv", f"{CABECALHO}\n;Cardápio?;algo;sim;;\n")
        self.assertTrue(any("ignorada" in p.mensagem for p in conjunto.avisos))

    def test_linha_de_exemplo_da_planilha_modelo_e_aviso(self):
        conjunto = self.carregar("e.csv", f"{CABECALHO}\n;Pergunta?;r;;;exemplo: apague esta linha\n")
        self.assertTrue(any("exemplo" in p.mensagem for p in conjunto.avisos))

    def test_artigos_e_paginas(self):
        texto = ("pergunta;resposta_correta;fonte;artigos;paginas\n"
                 f"A?;r;{DOCUMENTOS[0]};37; \n"
                 f"B?;r;{DOCUMENTOS[0]};37 e 38;\n"
                 f"C?;r;{DOCUMENTOS[1]};;406-410\n"
                 f"D?;r;{DOCUMENTOS[1]};;12\n"
                 f"E?;r;{DOCUMENTOS[1]};;\"406 a 410 e 500\"\n"
                 f"F?;r;{DOCUMENTOS[0]};nenhum;\n")
        conjunto = self.carregar("local.csv", texto)
        itens = conjunto.perguntas
        self.assertEqual(itens[0]["artigos"], [37])
        self.assertEqual(itens[1]["artigos"], [37, 38])
        self.assertEqual(itens[2]["paginas"], [406, 410])
        self.assertEqual(itens[3]["paginas"], [12, 12])
        self.assertEqual(sorted(p.linha for p in conjunto.erros), [6, 7])

    def test_paginas_invertidas_e_erro(self):
        conjunto = self.carregar("inv.csv", f"pergunta;resposta_correta;fonte;paginas\nA?;r;{DOCUMENTOS[1]};410-406\n")
        self.assertEqual(len(conjunto.erros), 1)

    def test_fonte_inexistente_sugere_o_nome_mais_parecido(self):
        conjunto = self.carregar("f.csv", f"{CABECALHO}\n;A?;r;;Res_480-2026_Normas_dos_Processos.pdf;\n")
        self.assertEqual(len(conjunto.erros), 1)
        self.assertIn(DOCUMENTOS[0], conjunto.erros[0].mensagem)

    def test_fonte_sem_extensao_ou_com_outras_maiusculas_e_ajustada(self):
        conjunto = self.carregar("g.csv", f"{CABECALHO}\n;A?;r;;ppc_engenharia_de_computacao_2023;\n")
        self.assertEqual(conjunto.erros, [])
        self.assertEqual(conjunto.perguntas[0]["fonte"], DOCUMENTOS[1])

    def test_sem_lista_de_documentos_a_fonte_nao_e_conferida(self):
        with configuracao(DOCS_DIR=self.pasta / "nao_existe"):
            conjunto = carregar_perguntas(self.escrever("h.csv", f"{CABECALHO}\n;A?;r;;qualquer.pdf;\n"))
        self.assertEqual(conjunto.erros, [])
        self.assertTrue(any("não foi conferida" in p.mensagem for p in conjunto.avisos))

    def test_documentos_lidos_da_pasta_da_base(self):
        pasta_docs = self.pasta / "documentos"
        pasta_docs.mkdir()
        (pasta_docs / DOCUMENTOS[0]).write_bytes(b"%PDF")
        with configuracao(DOCS_DIR=pasta_docs):
            self.assertEqual(pg.documentos_disponiveis(), [DOCUMENTOS[0]])

    def test_sem_coluna_pergunta_o_arquivo_nao_e_lido(self):
        with self.assertRaises(ErroPerguntas):
            self.carregar("x.csv", "questao_numero;texto\n1;algo\n".replace("questao_numero", "numero"))

    def test_arquivo_vazio_ou_so_com_cabecalho(self):
        with self.assertRaises(ErroPerguntas):
            self.carregar("vazio.csv", "")
        with self.assertRaises(ErroPerguntas):
            self.carregar("cab.csv", CABECALHO + "\n")


class TestLeituraJSON(_ComPasta):
    def test_formato_do_conjunto_gerado(self):
        dados = {"descricao": "teste", "perguntas": [
            {"id": "R01", "pergunta": "Quantos trancamentos?", "fonte": DOCUMENTOS[0], "artigos": [37],
             "resposta_correta": "Quatro."},
            {"id": "N01", "pergunta": "Valor da bolsa?", "sem_resposta": True}]}
        conjunto = self.carregar("g.json", json.dumps(dados, ensure_ascii=False))
        self.assertEqual(conjunto.descricao, "teste")
        self.assertEqual(conjunto.perguntas[0]["artigos"], [37])
        self.assertEqual(conjunto.perguntas[1]["resposta_correta"], "")
        self.assertEqual(conjunto.erros, [])
        self.assertEqual(conjunto.nome, "g")

    def test_lista_simples_e_alternativas(self):
        dados = [{"pergunta": "Frequência mínima?", "resposta_correta": "75%.",
                  "alternativas": [{"fonte": DOCUMENTOS[0], "artigos": [50]}, {"fonte": "errado.pdf"}]}]
        conjunto = self.carregar("l.json", json.dumps(dados))
        self.assertEqual(conjunto.perguntas[0]["id"], "P001")
        self.assertEqual(len(conjunto.erros), 1)            # o documento da 2ª alternativa não existe

    def test_json_invalido(self):
        with self.assertRaises(ErroPerguntas):
            self.carregar("ruim.json", "{ isto não é json")
        with self.assertRaises(ErroPerguntas):
            self.carregar("outro.json", json.dumps({"itens": []}))

    def test_extensao_nao_aceita(self):
        with self.assertRaises(ErroPerguntas):
            self.carregar("perguntas.xlsx", "qualquer coisa")


class TestAssinaturaEUso(_ComPasta):
    def test_assinatura_muda_com_qualquer_caractere(self):
        a = self.carregar("a.csv", f"{CABECALHO}\n;Pergunta?;r;;;\n")
        b = self.carregar("b.csv", f"{CABECALHO}\n;Pergunta?;r;;;\n")
        c = self.carregar("c.csv", f"{CABECALHO}\n;Pergunta!;r;;;\n")
        self.assertEqual(a.assinatura, b.assinatura)
        self.assertNotEqual(a.assinatura, c.assinatura)
        self.assertEqual(len(a.assinatura), 12)
        self.assertEqual(a.identificacao(), {"arquivo": "a.csv", "assinatura": a.assinatura, "total": 1})

    def test_local_da_resposta(self):
        self.assertFalse(pg.tem_local({"pergunta": "?"}))
        self.assertTrue(pg.tem_local({"fonte": "x.pdf"}))
        self.assertTrue(pg.tem_local({"alternativas": [{"fonte": "x.pdf"}]}))
        self.assertTrue(pg.so_documento({"fonte": "x.pdf"}))
        self.assertFalse(pg.so_documento({"fonte": "x.pdf", "artigos": [3]}))

    def test_para_busca_separa_as_respondiveis_sem_local(self):
        itens = [{"id": "A", "sem_resposta": False, "fonte": "x.pdf"},
                 {"id": "B", "sem_resposta": False},
                 {"id": "C", "sem_resposta": True}]
        dentro, fora = pg.para_busca(itens)
        self.assertEqual([i["id"] for i in dentro], ["A", "C"])
        self.assertEqual(fora, ["B"])

    def test_arquivo_padrao_e_o_do_config(self):
        caminho = self.escrever("ativo.csv", f"{CABECALHO}\n;Pergunta?;r;;;\n")
        with configuracao(ARQUIVO_PERGUNTAS=caminho):
            self.assertEqual(carregar_perguntas(documentos=[]).arquivo, caminho)

    def test_arquivo_inexistente(self):
        with self.assertRaises(ErroPerguntas):
            carregar_perguntas(self.pasta / "nao_existe.csv")


class TestConferenciaPelaLinhaDeComando(_ComPasta):
    def _rodar(self, caminho: Path) -> tuple[int, str]:
        saida = io.StringIO()
        with redirect_stdout(saida), configuracao(DOCS_DIR=self.pasta / "sem_docs"):
            codigo = pg.main([str(caminho)])
        return codigo, saida.getvalue()

    def test_arquivo_sem_erros_devolve_zero(self):
        codigo, texto = self._rodar(self.escrever("ok.csv", f"{CABECALHO}\n;Pergunta?;Resposta.;;;\n"))
        self.assertEqual(codigo, 0)
        self.assertIn("1 perguntas", texto)
        self.assertIn("com resposta correta: 1", texto)

    def test_arquivo_com_erro_devolve_um(self):
        codigo, texto = self._rodar(self.escrever("erro.csv", f"{CABECALHO}\nA;P1?;r;;;\nA;P2?;r;;;\n"))
        self.assertEqual(codigo, 1)
        self.assertIn("id repetido", texto)
        self.assertIn("Corrija os erros", texto)

    def test_avisos_iguais_viram_uma_linha(self):
        linhas = "\n".join(f";Pergunta {n}?;;;;" for n in range(30))
        codigo, texto = self._rodar(self.escrever("muitos.csv", f"{CABECALHO}\n{linhas}\n"))
        self.assertEqual(codigo, 0)
        self.assertEqual(texto.count("sem resposta correta: fica fora"), 1)
        self.assertIn("30 perguntas", texto)
        self.assertIn("e mais 10", texto)

    def test_arquivo_que_nao_pode_ser_lido_devolve_um(self):
        codigo, texto = self._rodar(self.pasta / "nao_existe.csv")
        self.assertEqual(codigo, 1)
        self.assertIn("não encontrado", texto)


class TestArquivosDoProjeto(unittest.TestCase):
    """A planilha modelo e o conjunto gerado precisam abrir sem erros."""

    def test_planilha_modelo(self):
        conjunto = carregar_perguntas(config.AVALIACAO_DIR / "modelo_perguntas.csv", documentos=[])
        self.assertEqual(conjunto.erros, [])
        self.assertEqual(conjunto.codificacao, "UTF-8")
        self.assertTrue(any(p["sem_resposta"] for p in conjunto.perguntas))
        self.assertTrue(any(not p["sem_resposta"] and p["resposta_correta"] for p in conjunto.perguntas))
        self.assertTrue(all("exemplo" in p["observacao"] for p in conjunto.perguntas))

    def test_conjunto_gerado(self):
        conjunto = carregar_perguntas(config.AVALIACAO_DIR / "perguntas_recuperacao.json", documentos=[])
        self.assertEqual(conjunto.erros, [])
        resumo = conjunto.resumo()
        self.assertEqual((resumo["total"], resumo["sem_resposta_nos_documentos"]), (61, 8))
        self.assertEqual(resumo["com_resposta_correta"], 53)


if __name__ == "__main__":
    unittest.main()
