"""Testes da versão 14: as decisões da coluna "sua conferência" do revisar.csv passam a valer.

Até a versão 13, a tabela de confiabilidade e a escolha do que os juízes
avaliam usavam só a classificação automática, e gerar a tabela de novo
apagava a coluna "sua conferência". Na versão 14, a decisão escrita ali
("manter" ou "corrigir para <categoria>") vale para a resposta daquele modelo
e daquela pergunta, se o texto for o mesmo que estava na planilha; a coluna é
guardada quando o revisar.csv é gerado de novo; e o juiz refaz a nota de uma
resposta cuja categoria a conferência mudou.
"""
from __future__ import annotations

import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_ragas import _AvaliadorFalso, _do_juiz
from test_rodada import MODELOS_TESTE, _ComRodada

import avaliar_ragas as ar
import avaliar_respostas as av
import gerar_respostas as gr

A, B = "modelo-a:1b", "modelo-b:2b"


def _ler_revisar(pasta) -> list[dict]:
    with open(pasta / av.ARQUIVO_REVISAR, encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo, delimiter=";"))


def _gravar_revisar(pasta, linhas, codificacao="utf-8-sig", separador=";"):
    """Grava o revisar.csv como o Excel grava depois que o Lucas escreve as decisões."""
    with open(pasta / av.ARQUIVO_REVISAR, "w", encoding=codificacao, newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]), delimiter=separador)
        escritor.writeheader()
        escritor.writerows(linhas)


def _decidir(pasta, decisoes: dict):
    """Escreve decisões na coluna "sua conferência": {(modelo, id): texto}."""
    linhas = _ler_revisar(pasta)
    for linha in linhas:
        linha[av.COLUNA_CONFERENCIA] = decisoes.get((linha["modelo"], linha["id"]), linha[av.COLUNA_CONFERENCIA])
    _gravar_revisar(pasta, linhas)


def _reescrever(pasta, modelo, i, **campos):
    arquivo = gr.arquivo_respostas(pasta, modelo)
    linhas = gr.ler_respostas(arquivo)
    for linha in linhas:
        if linha["id"] == i:
            linha.update(campos)
    arquivo.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")


def _tabela(resultado, modelo) -> dict:
    return next(l for l in resultado["tabela"] if l["modelo"] == modelo)


def _main(pasta) -> tuple[int, str]:
    saida = io.StringIO()
    with redirect_stdout(saida):
        codigo = av.main(["--rodada", str(pasta)])
    return codigo, saida.getvalue()


class TestInterpretarDecisao(unittest.TestCase):
    def test_formas_aceitas(self):
        casos = {
            "": ("vazia", None),
            "   ": ("vazia", None),
            "manter": ("manter", None),
            "Manter.": ("manter", None),
            "OK": ("manter", None),
            "mantém": ("manter", None),
            "manter (a abstenção está certa)": ("manter", None),
            "corrigir para abstenção": ("corrigir", "abstencao"),
            "Corrigir para ABSTENÇÃO COM ACRÉSCIMO": ("corrigir", "abstencao_com_acrescimo"),
            "corrigir para resposta.": ("corrigir", "resposta"),
            "corrigir para abstenção (acréscimo citado e correto, apresentado como informação adicional)":
                ("corrigir", "abstencao"),
            "corrigir para abstenção com acréscimo (o acréscimo não cita)": ("corrigir", "abstencao_com_acrescimo"),
            "abstenção": ("corrigir", "abstencao"),
            "corrigir: mista": ("corrigir", "mista"),
            "corrigir para abstencao_com_acrescimo": ("corrigir", "abstencao_com_acrescimo"),
            "corrigir para vazia": ("corrigir", "vazia"),
            "Corrigir para: abstenção": ("corrigir", "abstencao"),
            "manter como resposta": ("corrigir", "resposta"),
            "manter, a categoria está certa": ("manter", None),
            "corrigir para abstenção (o acréscimo cita\no trecho certo)": ("corrigir", "abstencao"),
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(av.interpretar_decisao(texto), esperado)

    def test_o_que_nao_vale(self):
        self.assertEqual(av.interpretar_decisao("talvez"), ("invalida", None))
        self.assertEqual(av.interpretar_decisao("corrigir para recusa"), ("invalida", None))
        self.assertEqual(av.interpretar_decisao(f"{av.MARCA_DESATUALIZADA} manter"), ("desatualizada", None))

    def test_categoria_conferida_vem_antes_da_automatica(self):
        linha = {"resposta": "São 4 trancamentos [1].", "citadas": [1], "gerada_pelo_llm": True}
        self.assertEqual(av.categoria(linha), "resposta")
        linha["categoria_conferida"] = "abstencao"
        self.assertEqual((av.categoria(linha), av.categoria_automatica(linha)), ("abstencao", "resposta"))


class TestConferenciaNaTabela(_ComRodada):
    """A decisão vale na tabela e nas comparações, e fica no revisar.csv gerado de novo."""

    def _rodada_com_revisar(self):
        pasta, _ = self.rodar()
        codigo, _ = _main(pasta)              # a primeira tabela: o revisar.csv com a coluna vazia
        self.assertEqual(codigo, 0)
        return pasta

    def test_sem_decisao_nada_muda(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        self.assertEqual([(l["modelo"], l["id"]) for l in linhas], [(A, "P3"), (B, "P3")])
        self.assertTrue(all(l[av.COLUNA_CONFERENCIA] == "" for l in linhas))
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual([resultado["conferencia"][c] for c in ("alteradas", "mantidas", "decisoes", "avisos")],
                         [[], 0, [], []])
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 1)
        self.assertNotIn("conferida à mão", av.texto_markdown(resultado))

    def test_rodada_sem_revisar(self):
        pasta, _ = self.rodar()
        self.assertFalse((pasta / av.ARQUIVO_REVISAR).exists())
        self.assertEqual(av.avaliar_rodada(pasta)["conferencia"]["decisoes"], [])

    def test_decisao_muda_a_tabela_e_fica_guardada(self):
        pasta = self._rodada_com_revisar()
        respostas_antes = gr.arquivo_respostas(pasta, A).read_bytes()
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção (o texto recusa)", (B, "P3"): "manter"})
        resultado = av.avaliar_rodada(pasta)
        a, b = _tabela(resultado, A), _tabela(resultado, B)
        self.assertEqual((a["absteve_modelo_certo"], a["respondeu_sem_base"], a["taxa_abstencao_certa"]), (1, 0, 1.0))
        self.assertEqual((b["absteve_modelo_certo"], b["respondeu_sem_base"]), (0, 1))
        self.assertEqual(resultado["conferencia"]["alteradas"],
                         [{"modelo": A, "id": "P3", "automatica": "resposta", "conferida": "abstencao"}])
        self.assertEqual(resultado["conferencia"]["mantidas"], 1)
        self.assertEqual(resultado["reclassificadas"], [])          # a mudança à mão aparece à parte
        comparacao = next(c for c in resultado["comparacoes"] if c["criterio"].startswith("absteve"))
        self.assertEqual((comparacao["so_a"], comparacao["so_b"]), (["P3"], []))
        # a lista do revisar.csv sai da classificação automática; a decisão fica na coluna dela
        self.assertEqual([(r["modelo"], r["id"], r["categoria"]) for r in resultado["revisar"]],
                         [(A, "P3", "resposta"), (B, "P3", "resposta")])
        planilha = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        codigo, saida = _main(pasta)
        self.assertEqual(codigo, 0)
        self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), planilha)   # as decisões continuam lá
        self.assertEqual(gr.arquivo_respostas(pasta, A).read_bytes(), respostas_antes)
        self.assertIn("2 resposta(s) para conferir à mão em revisar.csv (2 já com decisão)", saida)
        markdown = (pasta / "confiabilidade.md").read_text(encoding="utf-8")
        self.assertIn("Classificação conferida à mão", markdown)
        self.assertIn("Modelo A P3, de resposta para abstenção", markdown)
        self.assertIn("1 ficaram como o programa classificou", markdown)
        self.assertNotIn("\u2014", markdown)
        gravado = json.loads((pasta / "confiabilidade.json").read_text(encoding="utf-8"))
        self.assertEqual([d["situacao"] for d in gravado["conferencia"]["decisoes"]], ["aplicada", "mantida"])

    def test_resposta_que_mudou_pede_conferencia_de_novo(self):
        pasta = self._rodada_com_revisar()
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção"})
        _reescrever(pasta, A, "P3", resposta="Outra resposta, gerada de novo [1].")
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 1)          # a decisão não vale
        self.assertEqual(resultado["conferencia"]["alteradas"], [])
        self.assertTrue(any("a resposta mudou" in aviso for aviso in resultado["conferencia"]["avisos"]))
        codigo, saida = _main(pasta)
        self.assertEqual(codigo, 0)
        self.assertIn("Atenção (revisar.csv)", saida)
        linha = next(l for l in _ler_revisar(pasta) if (l["modelo"], l["id"]) == (A, "P3"))
        self.assertEqual(linha["resposta"], "Outra resposta, gerada de novo [1].")
        self.assertEqual(linha[av.COLUNA_CONFERENCIA], f"{av.MARCA_DESATUALIZADA} corrigir para abstenção")
        _main(pasta)                                                             # gerar de novo não repete a marca
        linha = next(l for l in _ler_revisar(pasta) if (l["modelo"], l["id"]) == (A, "P3"))
        self.assertEqual(linha[av.COLUNA_CONFERENCIA].count(av.MARCA_DESATUALIZADA), 1)
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 1)
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção"})                  # conferida de novo: volta a valer
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)

    def test_manter_vale_para_a_categoria_que_estava_na_planilha(self):
        """Se a classificação automática mudar (uma versão com outras regras), o "manter" pede conferência de novo."""
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0]["categoria"] = "abstencao"           # o que a planilha mostrava quando a decisão foi escrita
        linhas[0][av.COLUNA_CONFERENCIA] = "manter"
        linhas[1][av.COLUNA_CONFERENCIA] = "manter"    # esta continua com a categoria de antes
        _gravar_revisar(pasta, linhas)
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["conferencia"]["mantidas"], 1)
        self.assertTrue(any("a classificação automática mudou depois da conferência (de abstenção para resposta)"
                            in aviso for aviso in resultado["conferencia"]["avisos"]))
        _main(pasta)
        guardadas = {(l["modelo"], l["id"]): l[av.COLUNA_CONFERENCIA] for l in _ler_revisar(pasta)}
        self.assertEqual(guardadas[(A, "P3")], f"{av.MARCA_DESATUALIZADA} manter")
        self.assertEqual(guardadas[(B, "P3")], "manter")

    def test_espacos_e_quebras_de_linha_nao_contam_como_mudanca(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0]["resposta"] = "  " + linhas[0]["resposta"].replace(" ", "\r\n", 1) + " "
        linhas[0][av.COLUNA_CONFERENCIA] = "corrigir para abstenção"
        _gravar_revisar(pasta, linhas)
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)

    def test_decisao_fora_da_lista_vale_e_fica_no_fim(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        p1 = next(l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, A)) if l["id"] == "P1")
        extra = {**linhas[0], "id": "p1", "pergunta": "Quantos trancamentos posso fazer?", "sem_resposta": "não",
                 "categoria": "resposta", "motivo": "", "resposta": p1["resposta"], "resposta_correta": "Quatro.",
                 av.COLUNA_CONFERENCIA: "corrigir para abstenção"}
        _gravar_revisar(pasta, linhas + [extra])
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual((_tabela(resultado, A)["respondeu"], _tabela(resultado, A)["absteve_modelo"]), (0, 1))
        self.assertEqual(resultado["conferencia"]["alteradas"][0]["id"], "P1")     # o id como está na rodada
        _main(pasta)
        novas = _ler_revisar(pasta)
        self.assertEqual([(l["modelo"], l["id"]) for l in novas], [(A, "P3"), (B, "P3"), (A, "P1")])
        self.assertEqual(novas[-1][av.COLUNA_CONFERENCIA], "corrigir para abstenção")

    def test_decisao_que_nao_vale_avisa_e_fica_na_planilha(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "talvez"
        p2 = next(l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, B)) if l["id"] == "P2")
        linhas.append({**linhas[1], "id": "P2", "pergunta": "Qual o cardápio do RU hoje?", "resposta": p2["resposta"],
                       av.COLUNA_CONFERENCIA: "corrigir para resposta"})
        linhas.append({**linhas[1], "modelo": "modelo-c:3b", av.COLUNA_CONFERENCIA: "manter"})
        _gravar_revisar(pasta, linhas)
        resultado = av.avaliar_rodada(pasta)
        avisos = " | ".join(resultado["conferencia"]["avisos"])
        self.assertIn('decisão não reconhecida ("talvez")', avisos)
        self.assertIn("parou no limiar", avisos)
        self.assertIn("não está na rodada", avisos)
        self.assertEqual(resultado["conferencia"]["alteradas"], [])
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 1)
        self.assertIn("decisões do revisar.csv que não valeram", av.texto_markdown(resultado))
        _main(pasta)
        guardadas = {(l["modelo"], l["id"]): l[av.COLUNA_CONFERENCIA] for l in _ler_revisar(pasta)}
        self.assertEqual(guardadas[(A, "P3")], "talvez")
        self.assertEqual(guardadas[("modelo-c:3b", "P3")], "manter")
        self.assertEqual(guardadas[(B, "P2")], "corrigir para resposta")

    def test_planilha_salva_pelo_excel(self):
        """O Excel em português grava o CSV em ANSI (cp1252); em outras línguas, com vírgula."""
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "Corrigir para Abstenção"
        for codificacao, separador in (("cp1252", ";"), ("utf-8-sig", ","), ("cp850", ";"), ("mac_roman", ";"),
                                       ("utf-16", "\t"), ("utf-16-le", ";")):
            with self.subTest(codificacao=codificacao, separador=separador):
                _gravar_revisar(pasta, linhas, codificacao=codificacao, separador=separador)
                self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)
                self.assertEqual(_main(pasta)[0], 0)          # e a decisão sobrevive à planilha gravada de novo
                self.assertEqual(_ler_revisar(pasta)[0][av.COLUNA_CONFERENCIA], "Corrigir para Abstenção")
        # a linha "sep=;" que o Excel aceita no começo do arquivo
        texto = (pasta / av.ARQUIVO_REVISAR).read_text(encoding="utf-8-sig")
        (pasta / av.ARQUIVO_REVISAR).write_text("sep=;\r\n" + texto, encoding="cp1252")
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)

    def test_planilha_aberta_no_excel(self):
        pasta = self._rodada_com_revisar()
        _decidir(pasta, {(A, "P3"): "manter"})
        planilha = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        erro = PermissionError(13, "Permission denied", str(pasta / av.ARQUIVO_REVISAR))
        with mock.patch.object(av, "gravar", side_effect=erro):
            codigo, saida = _main(pasta)
        self.assertEqual(codigo, 1)
        self.assertIn("feche-o", saida)
        self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), planilha)
        with mock.patch.object(av.Path, "read_bytes", side_effect=erro):
            codigo, saida = _main(pasta)
        self.assertEqual(codigo, 1)
        self.assertIn("não consegui ler o revisar.csv", saida)
        self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), planilha)
        # a gravação de verdade, com a troca do arquivo temporário recusada (o Excel com a planilha aberta)
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção"})
        planilha = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        _gravar_revisar(pasta, _ler_revisar(pasta), codificacao="cp1252")          # o Excel salvou em ANSI
        planilha = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        with mock.patch.object(av.os, "replace", side_effect=erro), mock.patch.object(av.time, "sleep"):
            codigo, saida = _main(pasta)
        self.assertEqual(codigo, 1)
        self.assertIn("feche-o", saida)
        self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), planilha)
        self.assertFalse((pasta / (av.ARQUIVO_REVISAR + ".tmp")).exists())


class TestJuizesSeguemAConferencia(_ComRodada):
    def test_nota_refeita_na_categoria_conferida(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorFalso())
            av.main(["--rodada", str(pasta)])
        self.assertIsNotNone(_do_juiz(pasta, A)["P3"]["fidelidade"])           # a resposta sem base tem nota
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção"})
        avaliador, saida = _AvaliadorFalso(), io.StringIO()
        with redirect_stdout(saida):
            ar.executar(pasta, list(MODELOS_TESTE), avaliador)
        self.assertEqual(avaliador.chamadas, [])                 # a P3 do modelo A é refeita como abstenção, sem juiz
        nota = _do_juiz(pasta, A)["P3"]
        self.assertEqual((nota["categoria"], nota["abstencao"], nota["fidelidade"]), ("abstencao", True, None))
        self.assertIn("categoria conferida à mão no revisar.csv em P3", saida.getvalue())
        self.assertEqual(_do_juiz(pasta, B)["P3"]["categoria"], "resposta")    # a do modelo B não muda
        # desfeita a correção, a resposta volta a ter nota
        _decidir(pasta, {(A, "P3"): "manter"})
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), avaliador)
        self.assertEqual(avaliador.chamadas, [("fidelidade", "Qual o valor da bolsa?")])
        self.assertEqual(_do_juiz(pasta, A)["P3"]["categoria"], "resposta")


class TestPlanilhaDeVerdade(_ComRodada):
    """O que a revisão independente da versão 14 achou antes da entrega: nada do que a pessoa escreveu se perde."""

    def _rodada_com_revisar(self):
        pasta, _ = self.rodar()
        self.assertEqual(_main(pasta)[0], 0)
        return pasta

    def test_cabecalho_que_o_programa_nao_reconhece_nao_apaga_nada(self):
        pasta = self._rodada_com_revisar()
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção"})
        texto = (pasta / av.ARQUIVO_REVISAR).read_text(encoding="utf-8-sig")
        for novo in (texto.replace("sua conferência", "decisão"), texto.replace("resposta;resposta_correta", "texto;ref")):
            (pasta / av.ARQUIVO_REVISAR).write_text(novo, encoding="utf-8-sig")
            antes = (pasta / av.ARQUIVO_REVISAR).read_bytes()
            codigo, saida = _main(pasta)
            self.assertEqual(codigo, 1)
            self.assertIn("não reconheci as colunas", saida)
            self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), antes)
        (pasta / av.ARQUIVO_REVISAR).write_bytes(b"PK\x03\x04" + bytes(range(256)) * 4)   # um .xlsx com o nome errado
        self.assertEqual(_main(pasta)[0], 1)
        # o cabeçalho da conferência com outras palavras vale, e volta ao nome do programa
        (pasta / av.ARQUIVO_REVISAR).write_text(texto.replace("sua conferência", "Sua conferência (manter ou corrigir)"),
                                                 encoding="utf-8-sig")
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)
        self.assertEqual(_main(pasta)[0], 0)
        self.assertEqual(_ler_revisar(pasta)[0][av.COLUNA_CONFERENCIA], "corrigir para abstenção")

    def test_colunas_a_mais_da_pessoa_ficam(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        for linha, nota in zip(linhas, ("conferir com o orientador", "")):
            linha["observação"] = nota
        linhas[1][av.COLUNA_CONFERENCIA] = "manter"
        _gravar_revisar(pasta, linhas)
        self.assertEqual(_main(pasta)[0], 0)
        novas = _ler_revisar(pasta)
        self.assertEqual(list(novas[0])[-2:], [av.COLUNA_CONFERENCIA, "observação"])
        self.assertEqual([(l["observação"], l[av.COLUNA_CONFERENCIA]) for l in novas],
                         [("conferir com o orientador", ""), ("", "manter")])

    def test_copia_do_revisar_de_antes_quando_ele_muda(self):
        pasta = self._rodada_com_revisar()
        copias = pasta / av.PASTA_REVISAR_ANTERIORES
        self.assertFalse(copias.exists())                    # gerado de novo igual: nada a guardar
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "manter"
        _gravar_revisar(pasta, linhas, codificacao="cp1252")  # o Excel salvou em ANSI
        antes = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        self.assertEqual(_main(pasta)[0], 0)
        self.assertEqual([c.read_bytes() for c in copias.iterdir()], [antes])
        self.assertEqual(_main(pasta)[0], 0)                 # agora igual: nenhuma cópia nova
        self.assertEqual(len(list(copias.iterdir())), 1)

    def test_notas_dos_juizes_numa_categoria_que_a_conferencia_mudou(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), _AvaliadorFalso())
        self.assertEqual(_main(pasta)[0], 0)
        _decidir(pasta, {(A, "P3"): "corrigir para abstenção", (B, "P3"): "corrigir para mista"})
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["notas_em_categoria_mudada"], 1)   # a P3 do B continua julgada: não conta
        self.assertIn("1 nota(s) dos juízes foram dadas antes da conferência", av.texto_markdown(resultado))
        avaliador = _AvaliadorFalso()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, list(MODELOS_TESTE), avaliador)
        self.assertEqual(avaliador.chamadas, [])      # mista e resposta são julgadas igual: a nota do B fica
        self.assertEqual(_do_juiz(pasta, B)["P3"]["categoria"], "resposta")
        self.assertEqual(av.avaliar_rodada(pasta)["notas_em_categoria_mudada"], 0)

    def test_decisao_fora_da_lista_volta_a_valer(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        extra = {**linhas[0], "id": "P1", "pergunta": "Quantos trancamentos posso fazer?", "sem_resposta": "não",
                 "categoria": "resposta", "resposta": "Um texto que não é mais o da resposta.",
                 av.COLUNA_CONFERENCIA: "corrigir para abstenção"}
        _gravar_revisar(pasta, linhas + [extra])
        self.assertEqual(_main(pasta)[0], 0)
        linha = _ler_revisar(pasta)[-1]
        p1 = next(l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, A)) if l["id"] == "P1")
        self.assertEqual((linha["id"], linha["resposta"]), ("P1", p1["resposta"]))     # o texto de agora
        self.assertEqual(linha[av.COLUNA_CONFERENCIA], f"{av.MARCA_DESATUALIZADA} corrigir para abstenção")
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["absteve_modelo"], 0)
        _decidir(pasta, {(A, "P1"): "corrigir para abstenção"})          # conferida de novo, sem a marca
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["absteve_modelo"], 1)

    def test_linhas_repetidas(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "manter"
        _gravar_revisar(pasta, linhas + [{**linhas[0], av.COLUNA_CONFERENCIA: "corrigir para abstenção"}])
        resultado = av.avaliar_rodada(pasta)
        self.assertTrue(any("linhas com decisões diferentes" in a for a in resultado["conferencia"]["avisos"]))
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 1)               # nenhuma das duas vale
        _main(pasta)
        self.assertEqual([l[av.COLUNA_CONFERENCIA] for l in _ler_revisar(pasta) if l["modelo"] == A],
                         ["manter", "corrigir para abstenção"])                      # as duas ficam
        linhas = _ler_revisar(pasta)                                                  # [A manter, A corrigir, B]
        _gravar_revisar(pasta, [linhas[1], {**linhas[1]}, linhas[2]])                 # repetidas, mas iguais: vale
        self.assertEqual(_tabela(av.avaliar_rodada(pasta), A)["respondeu_sem_base"], 0)

    def test_caractere_que_o_ansi_nao_tem(self):
        pasta, _ = self.rodar()
        _reescrever(pasta, A, "P3", resposta="O valor é ≥ 400 reais [1].")
        self.assertEqual(_main(pasta)[0], 0)
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "corrigir para abstenção"
        linhas[0]["resposta"] = linhas[0]["resposta"].replace("≥", "?")    # o que o Excel grava em ANSI
        _gravar_revisar(pasta, linhas, codificacao="cp1252")
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["conferencia"]["avisos"], [])
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 0)

    def test_pergunta_de_outra_rodada(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0]["pergunta"] = "Outra pergunta, de outra rodada?"
        linhas[0][av.COLUNA_CONFERENCIA] = "corrigir para abstenção"
        _gravar_revisar(pasta, linhas)
        resultado = av.avaliar_rodada(pasta)
        self.assertTrue(any("a pergunta da planilha não é a desta rodada" in a for a in resultado["conferencia"]["avisos"]))
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 1)

    def test_decisao_que_tira_resposta_do_piloto_avisa(self):
        pasta = self._rodada_com_revisar()
        (pasta / "piloto").mkdir()
        (pasta / "piloto" / "piloto_chave.json").write_text(
            json.dumps({"amostra": [{"modelo": A, "id": "P1", "codigo": "P07"}]}), encoding="utf-8")
        linhas = _ler_revisar(pasta)
        p1 = next(l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, A)) if l["id"] == "P1")
        _gravar_revisar(pasta, linhas + [{**linhas[0], "id": "P1", "pergunta": "Quantos trancamentos posso fazer?",
                                          "resposta": p1["resposta"], av.COLUNA_CONFERENCIA: "corrigir para abstenção"}])
        resultado = av.avaliar_rodada(pasta)
        self.assertTrue(any("está no piloto (P07)" in a for a in resultado["conferencia"]["avisos"]))


class TestSegundaRevisao(_ComRodada):
    """O que a segunda conferência da revisão independente achou."""

    def _rodada_com_revisar(self):
        pasta, _ = self.rodar()
        self.assertEqual(_main(pasta)[0], 0)
        return pasta

    def _escrever(self, pasta, linhas_csv: list[list[str]], codificacao="utf-8-sig"):
        with open(pasta / av.ARQUIVO_REVISAR, "w", encoding=codificacao, newline="") as arquivo:
            csv.writer(arquivo, delimiter=";").writerows(linhas_csv)

    def _linhas_csv(self, pasta) -> list[list[str]]:
        with open(pasta / av.ARQUIVO_REVISAR, encoding="utf-8-sig", newline="") as arquivo:
            return list(csv.reader(arquivo, delimiter=";"))

    def test_coluna_sem_nome_com_anotacoes_fica(self):
        pasta = self._rodada_com_revisar()
        linhas = self._linhas_csv(pasta)
        self._escrever(pasta, [linhas[0] + [""], linhas[1] + ["perguntar ao orientador"], linhas[2] + [""]])
        self.assertEqual(_main(pasta)[0], 0)
        novas = self._linhas_csv(pasta)
        self.assertEqual([l[-1] for l in novas], ["", "perguntar ao orientador", ""])
        # e a anotação numa linha mais comprida que o cabeçalho, sem coluna nenhuma no cabeçalho
        self._escrever(pasta, [linhas[0], linhas[1] + ["", "outra anotação"], linhas[2]])
        self.assertEqual(_main(pasta)[0], 0)
        self.assertEqual(self._linhas_csv(pasta)[1][-1], "outra anotação")

    def test_decisao_sem_modelo_ou_id_avisa(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "corrigir para abstenção"
        linhas[0]["id"] = ""
        _gravar_revisar(pasta, linhas)
        resultado = av.avaliar_rodada(pasta)
        self.assertTrue(any("não tem o modelo ou o id" in a for a in resultado["conferencia"]["avisos"]))
        _main(pasta)
        self.assertIn("corrigir para abstenção", [l[av.COLUNA_CONFERENCIA] for l in _ler_revisar(pasta)])

    def test_outra_coluna_com_conferencia_no_nome(self):
        pasta = self._rodada_com_revisar()
        linhas = self._linhas_csv(pasta)
        linhas[1][-1] = "corrigir para abstenção"
        com_outra = [["notas da conferência"] + linhas[0], ["revisto em 14/11"] + linhas[1], [""] + linhas[2]]
        self._escrever(pasta, com_outra)
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["conferencia"]["avisos"], [])
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 0)
        # sem a "sua conferência" e com duas colunas com "conferência" no nome: o programa recusa e diz por quê
        self._escrever(pasta, [[c.replace("sua conferência", "conferência final") for c in l] for l in com_outra])
        antes = (pasta / av.ARQUIVO_REVISAR).read_bytes()
        codigo, saida = _main(pasta)
        self.assertEqual(codigo, 1)
        self.assertIn("2 colunas com \"conferência\" no nome", saida)
        self.assertEqual((pasta / av.ARQUIVO_REVISAR).read_bytes(), antes)
        # a recusa diz qual coluna falta
        self._escrever(pasta, [[c for c in av.CAMPOS_REVISAR if c != "modelo"] + [av.COLUNA_CONFERENCIA]])
        codigo, saida = _main(pasta)
        self.assertIn("falta a coluna modelo", saida)

    def test_arquivo_travado_nao_deixa_copias_repetidas(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "manter"
        _gravar_revisar(pasta, linhas, codificacao="cp1252")
        erro = PermissionError(13, "Permission denied", str(pasta / av.ARQUIVO_REVISAR))
        for _ in range(3):
            with mock.patch.object(av.os, "replace", side_effect=erro), mock.patch.object(av.time, "sleep"):
                self.assertEqual(_main(pasta)[0], 1)
        copias = pasta / av.PASTA_REVISAR_ANTERIORES
        self.assertEqual(list(copias.iterdir()) if copias.exists() else [], [])
        self.assertEqual(_main(pasta)[0], 0)                       # destravado: uma cópia só, a do arquivo de antes
        self.assertEqual(len(list(copias.iterdir())), 1)

    def test_ansi_com_travessao_e_cabecalho_sem_acento(self):
        pasta, _ = self.rodar()
        _reescrever(pasta, A, "P3", resposta="Não há bolsa \u2014 o valor depende do edital \u2014 e o auxílio é outro [1].")
        self.assertEqual(_main(pasta)[0], 0)
        linhas = self._linhas_csv(pasta)
        linhas[0] = [_c.replace("sua conferência", "sua conferencia") for _c in linhas[0]]
        linhas[1][-1] = "corrigir para abstenção"
        self._escrever(pasta, linhas, codificacao="cp1252")
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["conferencia"]["avisos"], [])
        self.assertEqual(_tabela(resultado, A)["respondeu_sem_base"], 0)

    def test_manter_e_corrigir_para_a_mesma_categoria_nao_sao_conflito(self):
        pasta = self._rodada_com_revisar()
        linhas = _ler_revisar(pasta)
        linhas[0][av.COLUNA_CONFERENCIA] = "manter"
        _gravar_revisar(pasta, linhas + [{**linhas[0], av.COLUNA_CONFERENCIA: "corrigir para resposta"}])
        resultado = av.avaliar_rodada(pasta)
        self.assertEqual(resultado["conferencia"]["avisos"], [])
        self.assertEqual(resultado["conferencia"]["mantidas"], 1)


if __name__ == "__main__":
    unittest.main()
