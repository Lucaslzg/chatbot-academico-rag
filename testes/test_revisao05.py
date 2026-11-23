"""Testes dos problemas apontados na revisão independente da versão 05 (03/11/2026).

Cada classe corresponde a um item da revisão: classificação das respostas,
mudança de configuração entre sessões, abstenções pelo limiar, execuções ao
mesmo tempo, limite de tokens, versão do modelo e local de execução, tipos no
JSON das perguntas, arquivos de respostas e criação da rodada.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from ollama_falso import OllamaFalso
from test_rodada import MODELOS_TESTE, _ComRodada
from utilitarios import configuracao

import avaliar_respostas
import config
import consulta
import gerar_respostas as gr
from perguntas import carregar_perguntas

M = config.MENSAGEM_ABSTENCAO


class TestClassificacaoDasRespostas(unittest.TestCase):
    def c(self, texto):
        return consulta.classificar_resposta(texto, 6)

    def test_abstencao_pura(self):
        self.assertEqual(self.c(M), "abstencao")
        self.assertEqual(self.c(M + " [1]"), "abstencao")                     # citação solta não muda nada
        self.assertEqual(self.c("Os trechos fornecidos não informam o cardápio do restaurante."), "abstencao")
        self.assertEqual(self.c("Não encontrei essa informação nos trechos enviados."), "abstencao")
        self.assertEqual(self.c("Não há informação sobre isso nos trechos. Procure a secretaria acadêmica."),
                         "abstencao")

    def test_abstencao_com_acrescimo_nao_e_abstencao(self):
        texto = ("Não encontrei essa informação nos documentos disponíveis. Em geral, o cardápio do RU é "
                 "divulgado no site e custa R$ 3,00.")
        self.assertEqual(self.c(texto), "abstencao_com_acrescimo")
        self.assertFalse(consulta.eh_abstencao(texto, []))

    def test_respostas(self):
        self.assertEqual(self.c("São 4 trancamentos [1]."), "resposta")
        self.assertEqual(self.c("Não encontrei o valor da taxa, mas o prazo é de 5 dias [1]."), "resposta")
        self.assertEqual(self.c("O prazo é de 5 dias úteis."), "resposta")
        self.assertEqual(self.c("São 120 horas [1]. " + M), "mista")
        self.assertEqual(self.c("   "), "vazia")

    def test_intervalo_de_citacoes(self):
        self.assertEqual(consulta.extrair_citacoes("Veja [1-3] e [5].", 6), [1, 2, 3, 5])
        self.assertEqual(consulta.extrair_citacoes("Veja [2 a 4].", 6), [2, 3, 4])

    def test_raciocinio_no_texto_sai_da_resposta(self):
        self.assertEqual(consulta.separar_raciocinio("<think>vou ler</think>São 4 [1]."),
                         ("São 4 [1].", "<think>vou ler</think>"))
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), resposta_texto="<think>pensando...</think>São 4 [1].")
        passagem = consulta.Passagem(1, "n.pdf", "Norma", "Art. 1 ...", 1, 1, 1, 1, "", "", 0.7)
        contexto = consulta.Contexto("Quantos?", [passagem], [], 0.7, False, {})
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco, MODELOS=MODELOS_TESTE):
            resposta = consulta.AssistenteRAG(recuperador=None, modelo_llm="modelo-a:1b").responder_com_contexto(
                contexto, registrar=False)
        self.assertEqual(resposta.texto, "São 4 [1].")
        self.assertGreater(resposta.estatisticas_llm["raciocinio_caracteres"], 0)

    def test_resposta_cortada_no_limite_fica_marcada(self):
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), motivo_fim="length")
        passagem = consulta.Passagem(1, "n.pdf", "Norma", "Art. 1 ...", 1, 1, 1, 1, "", "", 0.7)
        contexto = consulta.Contexto("Quantos?", [passagem], [], 0.7, False, {})
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco, MODELOS=MODELOS_TESTE):
            resposta = consulta.AssistenteRAG(recuperador=None, modelo_llm="modelo-a:1b").responder_com_contexto(
                contexto, registrar=False)
        self.assertEqual(resposta.estatisticas_llm["motivo_fim"], "length")
        self.assertIn("cortada", resposta.estatisticas_llm["aviso"])
        self.assertEqual(servidor.requisicoes[-1]["options"]["num_predict"], config.OLLAMA_NUM_PREDICT)


class TestRodadaProtegida(_ComRodada):
    def test_configuracao_mudou_entre_sessoes(self):
        pasta, _ = self.rodar(modelos=["modelo-a:1b"])
        with configuracao(TEMPERATURA=0.7):
            with self.assertRaises(gr.ErroRodada) as erro:
                self.rodar(pasta_rodada=pasta, modelos=["modelo-a:1b", "modelo-b:2b"])
        self.assertIn("opções de geração", str(erro.exception))
        with configuracao(MENSAGEM_ABSTENCAO="Outra frase."):
            with self.assertRaises(gr.ErroRodada):
                self.rodar(pasta_rodada=pasta)

    def test_versao_do_modelo_mudou(self):
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), digests={"modelo-a:1b": "aaa111"})
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco), redirect_stdout(io.StringIO()):
            pasta = gr.criar_rodada(self.conjunto, ["modelo-a:1b"], self.recuperador, 2)
            gr.executar(pasta, ["modelo-a:1b"])
        gravado = json.loads((pasta / "configuracao.json").read_text(encoding="utf-8"))["modelos"][0]
        self.assertEqual(gravado["digest"], "aaa111")
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        arquivo.write_text(arquivo.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), digests={"modelo-a:1b": "bbb222"})
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco), redirect_stdout(io.StringIO()):
            with self.assertRaises(gr.ErroRodada) as erro:
                gr.executar(pasta, ["modelo-a:1b"])
        self.assertIn("mudou desde o início", str(erro.exception))

    def test_modelo_na_placa_de_video_para_a_rodada(self):
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), ignora_num_gpu=("modelo-a:1b",))
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco), redirect_stdout(io.StringIO()):
            pasta = gr.criar_rodada(self.conjunto, ["modelo-a:1b"], self.recuperador, 1)
            with self.assertRaises(gr.ErroRodada) as erro:
                gr.executar(pasta, ["modelo-a:1b"])
        self.assertIn("placa de vídeo", str(erro.exception))
        self.assertEqual(gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b")), [])
        self.assertFalse((pasta / gr.ARQUIVO_TRAVA).exists())            # a trava sai mesmo com erro

    def test_duas_execucoes_ao_mesmo_tempo(self):
        pasta, _ = self.rodar(limite=1)
        (pasta / gr.ARQUIVO_TRAVA).write_text("outro processo", encoding="utf-8")
        with self.assertRaises(gr.ErroRodada) as erro:
            self.rodar(pasta_rodada=pasta)
        self.assertIn(".em_uso", str(erro.exception))

    def test_contextos_perdidos_nao_sao_buscados_de_novo(self):
        pasta, _ = self.rodar(limite=1)
        (pasta / "contextos.json").unlink()
        with self.assertRaises(gr.ErroRodada) as erro:
            self.rodar(pasta_rodada=pasta)
        self.assertIn("rodada nova", str(erro.exception))

    def test_resposta_vazia_e_tentada_de_novo_e_marcada(self):
        servidor = OllamaFalso(modelos=tuple(MODELOS_TESTE), resposta_texto="")
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco), redirect_stdout(io.StringIO()):
            pasta = gr.criar_rodada(self.conjunto, ["modelo-a:1b"], self.recuperador, 1)
            gr.executar(pasta, ["modelo-a:1b"])
        linha = gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b"))[0]
        self.assertEqual(linha["categoria"], "vazia")
        self.assertEqual(len([p for p in servidor.requisicoes if p.get("messages")]), 2)

    def test_linha_sem_quebra_no_fim_nao_gruda_na_proxima(self):
        pasta, _ = self.rodar(modelos=["modelo-a:1b"])
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        primeira = arquivo.read_text(encoding="utf-8").splitlines()[0]
        arquivo.write_text(primeira, encoding="utf-8")                   # sem "\n" no fim
        antes = arquivo.read_bytes()
        gr.ler_respostas(arquivo)
        self.assertEqual(arquivo.read_bytes(), antes)                    # só ler não altera o arquivo
        self.rodar(pasta_rodada=pasta, modelos=["modelo-a:1b"])
        self.assertEqual([r["id"] for r in gr.ler_respostas(arquivo)], ["P1", "P2", "P3"])

    def test_cada_resposta_grava_opcoes_e_codigo_das_mensagens(self):
        pasta, _ = self.rodar()
        a = gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b"))
        b = gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-b:2b"))
        self.assertEqual(a[0]["codigo_mensagens"], b[0]["codigo_mensagens"])   # mesmas mensagens nos dois
        self.assertIsNone(a[1]["codigo_mensagens"])                             # parou no limiar
        self.assertEqual(a[0]["opcoes"]["num_gpu"], 0)
        self.assertEqual(a[0]["versao_chatbot"], config.VERSAO_CHATBOT)

    def test_criacao_que_falha_nao_deixa_pasta(self):
        class _Quebrado(type(self.recuperador)):
            def recuperar(self, pergunta, k=None, modo=None):
                raise RuntimeError("base vazia")
        with self.assertRaises(RuntimeError), redirect_stdout(io.StringIO()):
            gr.criar_rodada(self.conjunto, list(MODELOS_TESTE), _Quebrado())
        self.assertEqual(list(gr.pasta_das_rodadas().glob("*")) if gr.pasta_das_rodadas().exists() else [], [])

    def test_mais_recente_pela_data_e_nao_pela_copia(self):
        pasta, _ = self.rodar(agora=datetime(2026, 11, 20, 9, 0))
        import shutil
        shutil.copytree(pasta, pasta.parent / (pasta.name + " - Copia"))
        self.assertEqual(gr.rodada_mais_recente(), pasta)
        nova, _ = self.rodar(agora=datetime(2026, 11, 22, 9, 0))
        self.assertEqual(gr.rodada_mais_recente(), nova)


class TestTabelaComCasosDificeis(_ComRodada):
    def _reescrever(self, pasta, modelo, mudar):
        arquivo = gr.arquivo_respostas(pasta, modelo)
        linhas = gr.ler_respostas(arquivo)
        mudar(linhas)
        arquivo.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")

    def test_abstencao_com_acrescimo_conta_como_sem_base_e_vai_para_revisao(self):
        pasta, _ = self.rodar()
        texto = M + " Em geral, a bolsa é de R$ 700,00."

        def mudar(linhas):
            linhas[2].update(resposta=texto, categoria="abstencao_com_acrescimo", abstencao=False)
        self._reescrever(pasta, "modelo-a:1b", mudar)
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        linha = next(t for t in resultado["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual((linha["absteve_modelo_certo"], linha["respondeu_sem_base"]), (0, 1))
        revisar = {(r["modelo"], r["id"]): r for r in resultado["revisar"]}
        self.assertEqual(revisar[("modelo-a:1b", "P3")]["categoria"], "abstencao_com_acrescimo")

    def test_linhas_repetidas_contam_uma_vez_e_sao_avisadas(self):
        pasta, _ = self.rodar()
        arquivo = gr.arquivo_respostas(pasta, "modelo-a:1b")
        arquivo.write_text(arquivo.read_text(encoding="utf-8") * 2, encoding="utf-8")
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        linha = next(t for t in resultado["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual(linha["respondidas"], 3)
        self.assertEqual(resultado["linhas_repetidas"], {"modelo-a:1b": 3})
        self.assertIn("repetidas", avaliar_respostas.texto_markdown(resultado))

    def test_limiar_da_rodada_com_duas_casas(self):
        pasta, _ = self.rodar()
        with configuracao(SIMILARIDADE_MINIMA=0.99):          # o config mudou depois: vale o da rodada
            resultado = avaliar_respostas.avaliar_rodada(pasta)
        self.assertEqual(resultado["limiar"], 0.5)
        self.assertIn("(0,50)", avaliar_respostas.texto_markdown(resultado))

    def test_revisar_csv(self):
        pasta, _ = self.rodar()
        with redirect_stdout(io.StringIO()):
            avaliar_respostas.main(["--rodada", str(pasta)])
        texto = (pasta / "revisar.csv").read_text(encoding="utf-8-sig")
        self.assertTrue(texto.startswith("modelo;id;pergunta;sem_resposta;categoria;motivo;resposta"))
        self.assertIn("Qual o valor da bolsa?", texto)


class TestPerguntasJSONECSV(unittest.TestCase):
    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)

    def tearDown(self):
        self._pasta.cleanup()

    def _json(self, perguntas):
        caminho = self.pasta / "p.json"
        caminho.write_text(json.dumps({"perguntas": perguntas}, ensure_ascii=False), encoding="utf-8")
        return carregar_perguntas(caminho, documentos=[])

    def _csv(self, texto, codificacao="utf-8"):
        caminho = self.pasta / "p.csv"
        caminho.write_bytes(texto.encode(codificacao))
        return carregar_perguntas(caminho, documentos=[])

    def test_sem_resposta_em_texto_no_json(self):
        conjunto = self._json([{"pergunta": "A?", "resposta_correta": "r", "sem_resposta": "não"},
                               {"pergunta": "B?", "sem_resposta": "sim"},
                               {"pergunta": "C?", "resposta_correta": "r", "sem_resposta": "false"}])
        self.assertEqual([p["sem_resposta"] for p in conjunto.perguntas], [False, True, False])
        ruim = self._json([{"pergunta": "A?", "resposta_correta": "r", "sem_resposta": "talvez"}])
        self.assertEqual(len(ruim.erros), 1)

    def test_tipos_no_json(self):
        conjunto = self._json([{"pergunta": None, "resposta_correta": "r"},
                               {"pergunta": "B?", "resposta_correta": "r", "fonte": "x.pdf", "artigos": "37"},
                               {"pergunta": "C?", "resposta_correta": "r", "fonte": "x.pdf", "paginas": [3]}])
        mensagens = " | ".join(p.mensagem for p in conjunto.erros)
        self.assertIn("pergunta vazia", mensagens)
        self.assertIn("artigos", mensagens)
        self.assertIn("paginas", mensagens)

    def test_artigos_em_intervalo_e_datas_do_excel(self):
        conjunto = self._csv("pergunta;resposta_correta;fonte;artigos;paginas\n"
                             "A?;r;x.pdf;37 a 40;\nB?;r;x.pdf;37-38;\nC?;r;x.pdf;;01/mar\nD?;r;x.pdf;mar-37;\n")
        self.assertEqual(conjunto.perguntas[0]["artigos"], [37, 38, 39, 40])
        self.assertEqual(conjunto.perguntas[1]["artigos"], [37, 38])
        self.assertEqual(sorted(p.linha for p in conjunto.erros), [4, 5])

    def test_codificacao_misturada_e_avisada(self):
        texto = "pergunta;resposta_correta\nComo faÃ§o a rematrícula?;r\n"
        conjunto = self._csv(texto, "cp1252")
        self.assertTrue(any("codificações" in p.mensagem for p in conjunto.avisos))


if __name__ == "__main__":
    unittest.main()
