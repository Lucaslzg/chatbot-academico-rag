"""Testes do piloto dos juízes (piloto.py, versão 12) e das medidas de concordância dele (estatistica.py).

As rodadas daqui são montadas à mão, com perguntas, trechos, respostas e
notas de juízes de mentira: o piloto só lê arquivos, então não precisa do
Ollama nem do RAGAS.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from utilitarios import configuracao

import avaliar_ragas as ar
import gerar_respostas as gr
import piloto
from estatistica import intervalo_bootstrap, kappa_ponderado, spearman

MODELOS_PILOTO = {"modelo-a:1b": {"rotulo": "Modelo Alfa"}, "modelo-b:2b": {"rotulo": "Modelo Beta"},
                  "juiz-a:1b": {"rotulo": "Juiz Um"}, "juiz-b:1b": {"rotulo": "Juiz Dois"}}
MODELOS = ["modelo-a:1b", "modelo-b:2b"]
JUIZES = ["juiz-a:1b", "juiz-b:1b"]
CORTES = {"correcao": (0.25, 0.75), "fidelidade": (0.5, 1.0)}


def _escrever_json(caminho: Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


class _ComRodadaDoPiloto(unittest.TestCase):
    """Uma rodada com 12 perguntas com resposta (R01 a R12), 2 sem resposta e 2 modelos."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name) / "2026-11-04_0900_teste"
        self.pasta.mkdir()
        self._config = configuracao(MODELOS=MODELOS_PILOTO, JUIZES=[{"modelo": j} for j in JUIZES],
                                    PILOTO_POR_MODELO=5, PILOTO_SEMENTE=7, PILOTO_CORTES=CORTES,
                                    PILOTO_REAMOSTRAS=200)
        self._config.__enter__()
        perguntas = [{"id": f"R{n:02d}", "pergunta": f"Pergunta número {n}?", "resposta_correta": f"Resposta certa {n}.",
                      "sem_resposta": False} for n in range(1, 13)]
        perguntas += [{"id": "N01", "pergunta": "Qual o cardápio?", "resposta_correta": "", "sem_resposta": True},
                      {"id": "N02", "pergunta": "Qual a capital?", "resposta_correta": "", "sem_resposta": True}]
        _escrever_json(self.pasta / gr.ARQUIVO_CONFIGURACAO, {"modelos": [{"modelo": m} for m in MODELOS]})
        _escrever_json(self.pasta / gr.ARQUIVO_PERGUNTAS, perguntas)
        _escrever_json(self.pasta / gr.ARQUIVO_CONTEXTOS, [
            {"id": p["id"], "contexto": {"passagens": [
                {"numero": 1, "fonte": "norma.pdf", "documento": "Resolução de teste", "texto": f"Art. 1 Texto do trecho {p['id']}.",
                 "pagina_inicio": 3, "pagina_fim": 3, "artigo_inicio": 1, "artigo_fim": 1, "localizacao": "", "secao": ""}]}}
            for p in perguntas])
        self.respostas = {}
        for modelo in MODELOS:
            linhas = []
            for p in perguntas:
                texto = f"A resposta do {p['id']} é **esta** [1]."
                linha = {"id": p["id"], "resposta": texto, "categoria": "resposta", "abstencao": False,
                         "gerada_pelo_llm": True, "citadas": [1]}
                if p["id"] == "R12":                       # abstenção do modelo: não recebe nota de correção
                    linha.update(resposta="Não encontrei essa informação nos documentos disponíveis.", categoria="abstencao",
                                 abstencao=True, citadas=[])
                if p["id"] == "R11" and modelo == "modelo-b:2b":     # parou no limiar
                    linha.update(gerada_pelo_llm=False, categoria="abstencao", abstencao=True)
                linhas.append(linha)
            self.gravar_respostas(modelo, linhas)

    def tearDown(self):
        self._config.__exit__(None, None, None)
        self._tmp.cleanup()

    def gravar_respostas(self, modelo, linhas):
        gr.arquivo_respostas(self.pasta, modelo).write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")
        self.respostas[modelo] = linhas

    def preparar(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return piloto.preparar(self.pasta, **kwargs)

    def chave(self):
        return json.loads((piloto.pasta_do_piloto(self.pasta) / piloto.ARQUIVO_CHAVE).read_text(encoding="utf-8"))

    def notas_de_juiz(self, juiz, valores, metodo=ar.VERSAO_DO_METODO):
        """Grava as notas de um juiz: valores = {(modelo, id): (correção, completude, fidelidade)}; None = erro."""
        destino = ar.pasta_do_juiz(self.pasta, juiz)
        destino.mkdir(exist_ok=True)
        _escrever_json(destino / ar.ARQUIVO_CONFIGURACAO_JUIZ, [{"juiz": juiz}])
        for modelo in MODELOS:
            linhas = []
            for (m, i), (c, comp, f) in valores.items():
                if m != modelo:
                    continue
                linhas.append({"id": i, "modelo": m, "juiz": juiz, "metodo": metodo, "correcao": {"valor": c},
                               "completude": {"valor": comp}, "fidelidade": {"valor": f},
                               "tem_erro": None in (c, comp, f)})
            ar.arquivo_ragas(destino, modelo).write_text("".join(json.dumps(l) + "\n" for l in linhas), encoding="utf-8")

    def preencher(self, notas):
        """Preenche a planilha: notas = {código: (correção, fidelidade[, observação])}, como o Excel gravaria."""
        caminho = piloto.pasta_do_piloto(self.pasta) / piloto.ARQUIVO_PLANILHA
        linhas = ["codigo;correcao;fidelidade;observacao"] + [";".join((c, *v, "")[:4]) for c, v in notas.items()]
        caminho.write_text("\ufeff" + "\r\n".join(linhas) + "\r\n", encoding="utf-8")

    def planilha(self):
        return piloto.pasta_do_piloto(self.pasta) / piloto.ARQUIVO_PLANILHA


class TestSorteio(_ComRodadaDoPiloto):
    def test_so_entram_respostas_que_recebem_as_tres_notas(self):
        elegiveis = piloto.elegiveis(self.pasta)
        self.assertEqual(elegiveis["modelo-a:1b"], [f"R{n:02d}" for n in range(1, 12)])     # sem a R12 e sem as N
        self.assertEqual(elegiveis["modelo-b:2b"], [f"R{n:02d}" for n in range(1, 11)])     # e sem o limiar da R11

    def test_estratificado_e_repetivel(self):
        amostra = piloto.sortear(self.pasta)
        self.assertEqual(len(amostra), 10)
        self.assertEqual(sum(a["modelo"] == "modelo-a:1b" for a in amostra), 5)
        self.assertEqual([a["codigo"] for a in amostra], [f"P{n:02d}" for n in range(1, 11)])
        self.assertEqual(piloto.sortear(self.pasta), amostra)                       # mesma semente, mesma amostra
        self.assertNotEqual(piloto.sortear(self.pasta, semente=8), amostra)
        self.assertEqual(len(piloto.sortear(self.pasta, por_modelo=50)), 21)        # menos que o pedido: entram todas

    def test_classificacao_desta_versao(self):
        # uma recusa gravada como resposta (antes da versão 10) não entra no sorteio
        linhas = self.respostas["modelo-a:1b"]
        linhas[0].update(resposta="Não foi encontrada na informação fornecida a resposta para isso. [1]")
        self.gravar_respostas("modelo-a:1b", linhas)
        self.assertNotIn("R01", piloto.elegiveis(self.pasta)["modelo-a:1b"])

    def test_so_perguntas_que_todos_os_modelos_responderam(self):
        # o modelo B parou na R06: as perguntas seguintes diriam que a resposta é do modelo A
        self.gravar_respostas("modelo-b:2b", self.respostas["modelo-b:2b"][:6])
        elegiveis = piloto.elegiveis(self.pasta)
        self.assertEqual(elegiveis["modelo-a:1b"], [f"R{n:02d}" for n in range(1, 7)])
        self.assertEqual(elegiveis["modelo-b:2b"], [f"R{n:02d}" for n in range(1, 7)])
        saida = io.StringIO()
        with redirect_stdout(saida):
            piloto.preparar(self.pasta)
        self.assertIn("Só entram as 6 perguntas com resposta correta que todos os modelos responderam, de 12 "
                      "(Modelo Beta respondeu a 6)", saida.getvalue())
        self.assertIn("--refazer", saida.getvalue())

    def test_avisos_do_sorteio(self):
        self.assertEqual(piloto.avisos_do_sorteio(self.pasta), [])               # os dois responderam a tudo
        # só as perguntas sem resposta faltam: nada que podia ser sorteado se perde, nenhum aviso
        self.gravar_respostas("modelo-b:2b", self.respostas["modelo-b:2b"][:12])
        self.assertEqual(piloto.avisos_do_sorteio(self.pasta), [])
        # o mesmo número de perguntas, mas outras: avisa
        linhas = self.respostas["modelo-a:1b"]
        self.gravar_respostas("modelo-a:1b", linhas[6:])
        self.gravar_respostas("modelo-b:2b", self.respostas["modelo-b:2b"][:6] + linhas[12:])
        avisos = piloto.avisos_do_sorteio(self.pasta)
        self.assertTrue(any("Só entram as 0 perguntas" in a for a in avisos))
        with self.assertRaises(piloto.ErroPiloto) as erro:
            self.preparar()
        self.assertIn("todos os modelos responderam", str(erro.exception))
        # um modelo da configuração sem nenhuma resposta: avisa que fica fora
        gr.arquivo_respostas(self.pasta, "modelo-b:2b").unlink()
        self.assertIn("Modelo Beta não tem respostas nesta rodada e fica fora do piloto.",
                      piloto.avisos_do_sorteio(self.pasta))


class TestMaterial(_ComRodadaDoPiloto):
    def test_caderno_e_planilha_sem_revelar_o_modelo(self):
        destino = self.preparar()
        caderno = (destino / piloto.ARQUIVO_CADERNO).read_text(encoding="utf-8")
        chave = self.chave()
        primeira = chave["amostra"][0]
        self.assertIn(f"Pergunta número {int(primeira['id'][1:])}?", caderno)
        self.assertIn(f"Resposta certa {int(primeira['id'][1:])}.", caderno)
        self.assertIn(f"A resposta do {primeira['id']} é esta [1].", caderno)          # sem o negrito do Markdown
        self.assertIn(f"Texto do trecho {primeira['id']}.", caderno)
        self.assertIn("Resolução de teste | p. 3 | Art. 1", caderno)
        for revelaria in ("Modelo Alfa", "Modelo Beta", "modelo-a", "modelo-b", "Juiz Um"):
            self.assertNotIn(revelaria, caderno)
        self.assertNotIn("\u2014", caderno)
        planilha = self.planilha().read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(planilha[0], "codigo;correcao;fidelidade;observacao")
        self.assertEqual([l.split(";")[0] for l in planilha[1:]], [a["codigo"] for a in chave["amostra"]])
        self.assertNotIn("modelo", "".join(planilha[1:]))
        self.assertEqual((chave["semente"], chave["por_modelo"]), (7, 5))
        self.assertEqual(chave["cortes"], {"correcao": [0.25, 0.75], "fidelidade": [0.5, 1.0]})

    def test_formatacao_que_revelaria_o_modelo(self):
        texto = ("### Prazos\n\nO prazo é **30 dias** [1]:\n\n*   primeiro item;\n  - item de dentro;\n"
                 "    *   também dentro;\n1.  com dois espaços;\n2. outro.   \n\n\n\nFim __aqui__ e ***aqui***.")
        self.assertEqual(piloto.texto_do_caderno(texto),
                         "Prazos\n\nO prazo é 30 dias [1]:\n\n- primeiro item;\n    - item de dentro;\n"
                         "    - também dentro;\n1. com dois espaços;\n2. outro.\n\nFim aqui e aqui.")
        # o que não é marca de formatação fica como está
        for igual in ("O valor é 2 * 3 - 1 = 5.", "+ 10% de acréscimo", "2026) e depois", "a) primeiro caso",
                      "-se o pedido", "Texto com ** solto\nem duas linhas **", "-5 graus"):
            self.assertEqual(piloto.texto_do_caderno(igual), igual)

    def test_nao_grava_por_cima_e_refazer_guarda_o_anterior(self):
        destino = self.preparar()
        (destino / piloto.ARQUIVO_PLANILHA).write_text("codigo;correcao\nP01;correta\n", encoding="utf-8")
        with self.assertRaises(piloto.ErroPiloto) as erro:
            self.preparar()
        self.assertIn("--refazer", str(erro.exception))
        self.preparar(refazer=True, semente=99)
        guardados = [p for p in self.pasta.iterdir() if p.name.startswith("piloto_")]
        self.assertEqual(len(guardados), 1)
        self.assertIn("P01;correta", (guardados[0] / piloto.ARQUIVO_PLANILHA).read_text(encoding="utf-8"))
        self.assertEqual(self.chave()["semente"], 99)
        caderno = (piloto.pasta_do_piloto(self.pasta) / piloto.ARQUIVO_CADERNO).read_text(encoding="utf-8")
        self.assertIn("sorteadas com a semente 99.", caderno)                    # a semente usada, não a do config


class TestPlanilha(_ComRodadaDoPiloto):
    def test_aceita_o_que_o_excel_grava(self):
        self.preparar()
        self.preencher({"P01": ("Correta", "FIEL"), "P02": ("parcial", "0,5"), "P03": ("i", "infiel"),
                        "P04": ("", "fiel"), "P05": ("talvez", "", "não sei")})
        notas, problemas, observacoes, avisos = piloto.ler_planilha(self.planilha())
        self.assertEqual(notas["P01"], {"correcao": 2, "fidelidade": 2})
        self.assertEqual(notas["P02"], {"correcao": 1, "fidelidade": 1})
        self.assertEqual(notas["P03"], {"correcao": 0, "fidelidade": 0})
        self.assertEqual(notas["P04"], {"fidelidade": 2})                           # em branco: nota que falta
        self.assertEqual(notas["P05"], {})
        self.assertEqual(observacoes, {"P05"})
        self.assertEqual(len(problemas), 1)
        self.assertIn("P05", problemas[0])

    def test_separador_vem_do_cabecalho(self):
        # observações com mais vírgulas que os pontos e vírgulas do arquivo inteiro
        self.preparar()
        self.preencher({f"P{n:02d}": ("correta", "fiel", "a, b, c, d, e, f, g, h") for n in range(1, 11)})
        notas, problemas, observacoes, _ = piloto.ler_planilha(self.planilha())
        self.assertEqual(len([c for c, n in notas.items() if n == {"correcao": 2, "fidelidade": 2}]), 10)
        self.assertEqual(problemas, [])

    def test_texto_unicode_e_ansi_do_excel(self):
        self.preparar()
        # "Texto Unicode" do Excel: UTF-16 com tabulação
        self.planilha().write_bytes("codigo\tcorrecao\tfidelidade\tobservacao\r\nP01\tcorreta\tfiel\t\r\n".encode("utf-16"))
        self.assertEqual(piloto.ler_planilha(self.planilha())[0]["P01"], {"correcao": 2, "fidelidade": 2})
        # CSV do Excel em português (ANSI), com o cabeçalho acentuado
        self.planilha().write_bytes("Código;Correção;Fidelidade;Observação\r\nP01;Incorreta;Parcial;não sei\r\n"
                                    .encode("cp1252"))
        notas, _, observacoes, _ = piloto.ler_planilha(self.planilha())
        self.assertEqual(notas["P01"], {"correcao": 0, "fidelidade": 1})
        self.assertEqual(observacoes, {"P01"})
        # UTF-16 sem a marca do começo, e o fim de linha só com CR (Excel de Mac)
        self.planilha().write_bytes("codigo\tcorrecao\tfidelidade\r\nP02\tparcial\tfiel\r\n".encode("utf-16-le"))
        self.assertEqual(piloto.ler_planilha(self.planilha())[0]["P02"], {"correcao": 1, "fidelidade": 2})
        self.planilha().write_bytes(b"codigo;correcao;fidelidade;observacao\rP03;c;f;\rP04;i;i;\r")
        notas = piloto.ler_planilha(self.planilha())[0]
        self.assertEqual((notas["P03"], notas["P04"]), ({"correcao": 2, "fidelidade": 2}, {"correcao": 0, "fidelidade": 0}))

    def test_sem_as_colunas_ou_com_codigo_repetido(self):
        self.preparar()
        self.planilha().write_text("codigo;nota\nP01;correta\n", encoding="utf-8")
        with self.assertRaises(piloto.ErroPiloto) as erro:
            piloto.ler_planilha(self.planilha())
        self.assertIn("correcao, fidelidade", str(erro.exception))
        self.preencher({"P01": ("correta", "")})
        with open(self.planilha(), "a", encoding="utf-8") as arquivo:
            arquivo.write("P01;;fiel;\r\n")
        notas, problemas, _, avisos = piloto.ler_planilha(self.planilha())
        self.assertEqual(notas["P01"], {"correcao": 2, "fidelidade": 2})            # as linhas que concordam se juntam
        self.assertEqual(problemas, [])
        self.assertIn("repetido", avisos[0])
        with open(self.planilha(), "a", encoding="utf-8") as arquivo:
            arquivo.write("P01;incorreta;fiel;\r\n")
        notas, problemas, _, _ = piloto.ler_planilha(self.planilha())
        self.assertEqual(len(problemas), 1)                                          # as que discordam impedem
        self.assertIn("diferente", problemas[0])

    def test_cortes(self):
        correcao, fidelidade = CORTES["correcao"], CORTES["fidelidade"]
        self.assertEqual([piloto.nivel_do_juiz(v, correcao) for v in (0.0, 0.24, 0.25, 0.5, 0.74, 0.75, 1.0)],
                         [0, 0, 1, 1, 1, 2, 2])
        # fiel só com todas as afirmações nos trechos, como no caderno
        self.assertEqual([piloto.nivel_do_juiz(v, fidelidade) for v in (0.0, 0.49, 0.5, 0.75, 0.99, 1.0, 1 / 3 + 2 / 3)],
                         [0, 0, 1, 1, 1, 2, 2])


class TestComparacao(_ComRodadaDoPiloto):
    def _avaliar(self):
        self.preparar()
        amostra = self.chave()["amostra"]
        humanas, valores_a, valores_b = {}, {}, {}
        niveis = [(2, 1.0), (1, 0.5), (0, 0.0)]
        for n, item in enumerate(amostra):
            nivel, nota = niveis[n % 3]
            humanas[item["codigo"]] = (("incorreta", "parcial", "correta")[nivel], ("infiel", "parcial", "fiel")[nivel])
            valores_a[(item["modelo"], item["id"])] = (nota, nota, nota)            # o juiz um concorda em tudo
            valores_b[(item["modelo"], item["id"])] = (1.0, nota, 1.0)              # o dois dá sempre 1 no F1
        humanas[amostra[-1]["codigo"]] = ("", "", "não sei decidir")                 # uma resposta sem nota humana
        sem_juiz = amostra[0]
        del valores_b[(sem_juiz["modelo"], sem_juiz["id"])]                          # uma sem nota do juiz dois
        segunda = amostra[1]
        valores_b[(segunda["modelo"], segunda["id"])] = (1.0, 0.5, None)            # e uma sem a fidelidade dele
        self.notas_de_juiz("juiz-a:1b", valores_a)
        self.notas_de_juiz("juiz-b:1b", valores_b)
        self.preencher(humanas)
        return piloto.comparar(self.pasta), amostra

    def _linha(self, resultado, avaliador, humana, metrica):
        return next(r for r in resultado["resultados"] if r["avaliador"] == avaliador and r["humana"] == humana
                    and r["metrica_do_juiz"] == metrica)

    def test_concordancia_por_juiz_e_metrica(self):
        resultado, amostra = self._avaliar()
        um = self._linha(resultado, "juiz-a:1b", "correcao", "correcao")
        self.assertEqual((um["n"], um["kappa_ponderado"], um["spearman"], um["concordancia_exata"]), (9, 1.0, 1.0, 1.0))
        self.assertEqual(um["kappa_ic95"], (1.0, 1.0))
        dois_f1 = self._linha(resultado, "juiz-b:1b", "correcao", "correcao")
        self.assertEqual(dois_f1["kappa_ponderado"], 0.0)                           # mesmo nível a todas: só o acaso
        self.assertEqual(dois_f1["n"], 8)                                           # uma sem nota humana, uma sem nota dele
        dois_completude = self._linha(resultado, "juiz-b:1b", "correcao", "completude")
        self.assertEqual(dois_completude["kappa_ponderado"], 1.0)
        media = self._linha(resultado, "media_dos_juizes", "fidelidade", "fidelidade")
        self.assertEqual(media["n"], 7)
        self.assertEqual(resultado["notas_que_faltam"]["correcao"], [amostra[-1]["codigo"]])
        self.assertEqual(resultado["sem_nota_do_juiz"]["juiz-b:1b"]["correcao"], [amostra[0]["codigo"]])
        self.assertEqual(resultado["sem_nota_do_juiz"]["juiz-b:1b"]["fidelidade"],
                         sorted([amostra[0]["codigo"], amostra[1]["codigo"]]))
        self.assertEqual(resultado["sem_nota_do_juiz"]["media_dos_juizes"]["correcao"], [amostra[0]["codigo"]])
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        self.assertIn(f"Juiz Dois, fidelidade: {', '.join(sorted([amostra[0]['codigo'], amostra[1]['codigo']]))}", texto)

    def test_diferencas_por_modelo_e_itens(self):
        resultado, amostra = self._avaliar()
        f1_menos = {d["avaliador"]: d for d in resultado["diferencas"] if d["comparacao"] == "F1 menos completude"}
        self.assertEqual((f1_menos["juiz-a:1b"]["kappa"], f1_menos["juiz-a:1b"]["spearman"]), (0.0, 0.0))
        self.assertEqual(f1_menos["juiz-a:1b"]["kappa_ic95"], (0.0, 0.0))            # o F1 e a completude dele são iguais
        self.assertEqual(f1_menos["juiz-b:1b"]["kappa"], -1.0)                       # o F1 dele não acompanha a pessoa
        self.assertIsNone(f1_menos["juiz-b:1b"]["spearman"])                         # F1 constante: o Spearman não sai
        contra_a_media = [d for d in resultado["diferencas"] if d["comparacao"].startswith("juiz menos a média")]
        self.assertTrue(contra_a_media)
        self.assertTrue(all("kappa" not in d and "spearman" in d for d in contra_a_media))   # só pelo Spearman
        self.assertTrue(self._linha(resultado, "juiz-b:1b", "correcao", "correcao")["nivel_unico"])
        dois = self._linha(resultado, "juiz-b:1b", "correcao", "correcao")
        self.assertEqual(set(dois["por_modelo"]), set(MODELOS))
        self.assertTrue(all(v["diferenca_media"] >= 0 for v in dois["por_modelo"].values()))   # sempre 1: generoso
        self.assertEqual([i["codigo"] for i in resultado["itens"]], [a["codigo"] for a in amostra])
        self.assertIn("juiz-a:1b", resultado["itens"][0]["juizes"])
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        for trecho in ("Kappa ponderado (IC 95%)", "F1 menos completude", "Por modelo", "Modelo Alfa"):
            self.assertIn(trecho, texto)

    def test_so_compara_com_a_planilha_terminada(self):
        self.preparar()
        amostra = self.chave()["amostra"]
        self.notas_de_juiz("juiz-a:1b", {(a["modelo"], a["id"]): (1.0, 1.0, 1.0) for a in amostra})
        notas = {a["codigo"]: ("correta", "fiel") for a in amostra}
        notas[amostra[2]["codigo"]] = ("correta", "")                               # sem a fidelidade e sem explicação
        notas[amostra[3]["codigo"]] = ("parcal", "fiel")                            # nota escrita errado
        notas["P99"] = ("correta", "fiel")                                          # código que não existe
        self.preencher(notas)
        with self.assertRaises(piloto.ErroPiloto) as erro:
            piloto.comparar(self.pasta)
        mensagem = str(erro.exception)
        for trecho in (f"falta nota em {amostra[2]['codigo']}, {amostra[3]['codigo']}", "parcal", "P99: código que não está"):
            self.assertIn(trecho, mensagem)
        self.assertFalse((piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").exists())
        del notas["P99"]
        notas[amostra[3]["codigo"]] = ("parcial", "fiel")
        notas[amostra[2]["codigo"]] = ("correta", "", "trechos confusos")             # com o motivo, pode
        self.preencher(notas)
        self.assertEqual(piloto.comparar(self.pasta)["notas_que_faltam"]["fidelidade"], [amostra[2]["codigo"]])

    def test_resultado_gravado_e_notas_antigas_nao_entram(self):
        self.preparar()
        amostra = self.chave()["amostra"]
        self.notas_de_juiz("juiz-a:1b", {(a["modelo"], a["id"]): (0.0, 0.0, 0.0) for a in amostra}, metodo=None)
        self.preencher({a["codigo"]: ("correta", "fiel") for a in amostra})
        resultado = piloto.comparar(self.pasta)
        um = self._linha(resultado, "juiz-a:1b", "correcao", "correcao")
        self.assertEqual(um["n"], 0)                                                # notas de método anterior: fora
        texto = (piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.md").read_text(encoding="utf-8")
        self.assertIn("Kappa ponderado", texto)
        self.assertNotIn("\u2014", texto)
        self.assertTrue((piloto.pasta_do_piloto(self.pasta) / f"{piloto.RESULTADO}.json").exists())

    def test_main_explica_o_que_falta(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = piloto.main(["comparar", "--rodada", str(self.pasta)])
        self.assertEqual(codigo, 1)
        self.assertIn("preparar-piloto.bat", saida.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(piloto.main(["preparar", "--rodada", str(self.pasta)]), 0)
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = piloto.main(["comparar", "--rodada", str(self.pasta)])
        self.assertEqual(codigo, 1)
        self.assertIn("avaliar-ragas.bat", saida.getvalue())                        # nenhum juiz avaliou ainda


class TestEstatisticaDoPiloto(unittest.TestCase):
    def test_kappa_ponderado(self):
        pares = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 2)]
        self.assertEqual(kappa_ponderado(pares, 3), 0.625)                          # conta feita à mão
        self.assertEqual(kappa_ponderado(pares, 3, "nenhum"), 0.5)
        self.assertEqual(kappa_ponderado([(0, 0), (1, 1), (2, 2)], 3), 1.0)
        self.assertIsNone(kappa_ponderado([(2, 2), (2, 2)], 3))                     # um nível só: o acaso explica tudo
        self.assertIsNone(kappa_ponderado([], 3))
        with self.assertRaises(ValueError):
            kappa_ponderado([(0, 3)], 3)

    def test_spearman(self):
        self.assertEqual(spearman([(0, 0.1), (0.5, 0.4), (1, 0.9)]), 1.0)
        self.assertEqual(spearman([(0, 0.9), (0.5, 0.4), (1, 0.1)]), -1.0)
        self.assertIsNone(spearman([(0, 0.1), (1, 0.2)]))
        self.assertIsNone(spearman([(1, 0.1), (1, 0.2), (1, 0.3)]))
        # empates com postos médios: conferido com o scipy.stats.spearmanr (0,082)
        xs = [0.5, 0.5, 1, 0, 0, 1, 1, 0.5, 0, 0, 1, 0.5, 0.5, 0.5, 0.5, 1, 1, 0, 0, 1]
        ys = [0.13, 0.85, 0.76, 0.26, 0.5, 0.45, 0.65, 0.79, 0.09, 0.03, 0.84, 0.43, 0.76, 0.0, 0.45, 0.72, 0.23, 0.95,
              0.9, 0.04]
        self.assertAlmostEqual(spearman(list(zip(xs, ys))), round(_spearman_de_referencia(xs, ys), 3))
        # com três níveis divididos por igual, nem a ordem toda certa chega a 1
        self.assertEqual(spearman([(h / 2, i) for i, h in enumerate([0] * 10 + [1] * 10 + [2] * 10)]), 0.943)

    def test_intervalo_bootstrap(self):
        media = lambda itens: sum(itens) / len(itens)
        valores = [0.1, 0.4, 0.35, 0.8, 0.5, 0.65, 0.2, 0.9, 0.55, 0.3]
        intervalo = intervalo_bootstrap(valores, media, 500, semente=3)
        self.assertLess(intervalo[0], media(valores))
        self.assertGreater(intervalo[1], media(valores))
        self.assertEqual(intervalo_bootstrap(valores, media, 500, semente=3), intervalo)     # mesma semente
        self.assertEqual(intervalo_bootstrap([0.5] * 8, media, 100), (0.5, 0.5))
        self.assertIsNone(intervalo_bootstrap([0.5], media, 100))                            # menos de 2 itens
        self.assertIsNone(intervalo_bootstrap(valores, lambda itens: None, 100))             # medida que não sai
        # kappa de 30 respostas com concordância moderada: o intervalo é largo
        pares = [(0, 0)] * 7 + [(1, 1)] * 6 + [(2, 2)] * 7 + [(0, 1)] * 3 + [(1, 2)] * 3 + [(2, 0)] * 2 + [(1, 0)] * 2
        baixo, alto = intervalo_bootstrap(pares, lambda p: kappa_ponderado(p, 3), 500, semente=1)
        self.assertLess(baixo, kappa_ponderado(pares, 3))
        self.assertGreater(alto, kappa_ponderado(pares, 3))
        self.assertGreater(alto - baixo, 0.3)


def _spearman_de_referencia(xs, ys):
    """Spearman pela definição, com postos médios, calculado de outro jeito (para conferir o do estatistica.py)."""
    def postos(v):
        return [sum(1 for w in v if w < x) + (sum(1 for w in v if w == x) + 1) / 2 for x in v]
    a, b = postos(xs), postos(ys)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5


if __name__ == "__main__":
    unittest.main()
