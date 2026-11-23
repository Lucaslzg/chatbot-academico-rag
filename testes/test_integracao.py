"""Testes de ponta a ponta: indexação no ChromaDB real + consulta com Ollama simulado.

Usam um modelo de embeddings falso (sem rede neural) e um servidor que imita
a API do Ollama, então rodam em segundos e sem internet. O que se testa aqui é
o encadeamento (sincronização da base, metadados, busca, contexto, streaming,
citações, abstenção, erros), não a qualidade semântica das respostas.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ollama_falso import OllamaFalso
from utilitarios import ModeloEmbeddingsFalso, PDFSintetico, configuracao, criar_ppc_sintetico

import config
import consulta
import ingestao
import vetorial


def _silencioso(*_args, **_kwargs):
    pass


def _criar_norma(caminho: Path, versao: int = 1) -> Path:
    pdf = PDFSintetico(rodape="Resolução de teste")
    pdf.escrever("CAPÍTULO I", tamanho=11)
    pdf.escrever("DO TRANCAMENTO DE MATRÍCULA", tamanho=11)
    pdf.escrever("Art. 1º O discente pode solicitar trancamento total da matrícula uma vez por semestre.")
    pdf.escrever("§1º O número máximo de trancamentos totais é 4 (quatro).")
    if versao == 2:
        pdf.escrever("§2º O trancamento parcial exige parecer da coordenação do curso.")
        pdf.escrever("Art. 2º A frequência mínima para aprovação é de 75% da carga horária.")
    pdf.nova_pagina()
    pdf.escrever("Art. 3º Os casos omissos são decididos pela Comissão de Curso.")
    return pdf.salvar(caminho)


class TestIndexacaoEConsulta(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        raiz = Path(self._tmp.name)
        self.docs = raiz / "documentos"
        self.docs.mkdir()
        self.relatorios = raiz / "relatorios"
        self.modelo = ModeloEmbeddingsFalso()
        self.cliente = vetorial.abrir_cliente(raiz / "chroma")
        self._config = configuracao(REGISTROS_DIR=raiz / "registros", SIMILARIDADE_MINIMA=0.05)
        self._config.__enter__()
        _criar_norma(self.docs / "norma.pdf")
        criar_ppc_sintetico(self.docs / "ppc.pdf")

    def tearDown(self):
        self._config.__exit__(None, None, None)
        self._tmp.cleanup()

    def _ingerir(self, **kwargs):
        return ingestao.ingerir(pasta=self.docs, modelo=self.modelo, cliente=self.cliente,
                                pasta_relatorios=self.relatorios, saida=_silencioso, **kwargs)

    def _colecao(self):
        return vetorial.obter_colecao(self.cliente, vetorial.nome_colecao(self.modelo.nome))

    def _ids_do_documento(self, nome):
        return self._colecao().get(where={"fonte": nome}, include=[])["ids"]

    def test_indexacao_inicial_metadados_e_relatorio(self):
        resumo = self._ingerir()
        self.assertEqual(sorted(resumo.indexados), ["norma.pdf", "ppc.pdf"])
        colecao = self._colecao()
        self.assertEqual(colecao.count(), resumo.total_fragmentos)
        meta = colecao.get(where={"fonte": "norma.pdf"}, include=["metadatas"])["metadatas"][0]
        for chave in ("documento", "indice", "n_fragmentos", "pagina", "pagina_fim", "localizacao",
                      "n_tokens", "hash_arquivo", "artigo_inicio"):
            self.assertIn(chave, meta)
        self.assertIn("assinatura", colecao.metadata)
        self.assertTrue((self.relatorios / "norma.txt").exists())
        # PDF fora de data/titulos_documentos.json: o relatório avisa que o chat usa o título detectado
        self.assertIn("Título no chat: o detectado", (self.relatorios / "norma.txt").read_text(encoding="utf-8"))

    def test_reindexacao_incremental_sem_orfaos(self):
        self._ingerir()
        n_antes = len(self._ids_do_documento("norma.pdf"))
        resumo = self._ingerir()
        self.assertEqual(sorted(resumo.inalterados), ["norma.pdf", "ppc.pdf"])
        _criar_norma(self.docs / "norma.pdf", versao=2)          # documento alterado
        resumo = self._ingerir()
        self.assertEqual(resumo.indexados, ["norma.pdf"])
        ids = self._ids_do_documento("norma.pdf")
        metas = self._colecao().get(ids=ids, include=["metadatas"])["metadatas"]
        self.assertEqual(len(ids), metas[0]["n_fragmentos"])      # nenhum fragmento órfão
        self.assertEqual(len({m["hash_arquivo"] for m in metas}), 1)
        self.assertGreaterEqual(len(ids), n_antes)

    def test_documento_removido_sai_da_base(self):
        self._ingerir()
        (self.docs / "ppc.pdf").unlink()
        resumo = self._ingerir()
        self.assertEqual(resumo.removidos, ["ppc.pdf"])
        self.assertEqual(self._ids_do_documento("ppc.pdf"), [])

    def test_mudanca_de_parametro_reconstroi_a_base(self):
        self._ingerir()
        with configuracao(CHUNK_SOBREPOSICAO=0.1):
            resumo = self._ingerir()
        self.assertTrue(resumo.base_reconstruida)
        self.assertEqual(sorted(resumo.indexados), ["norma.pdf", "ppc.pdf"])

    def test_colecao_da_versao_anterior_e_removida(self):
        self.cliente.create_collection(vetorial.COLECAO_LEGADA, embedding_function=None)
        self._ingerir()
        nomes = [c.name for c in self.cliente.list_collections()]
        self.assertNotIn(vetorial.COLECAO_LEGADA, nomes)

    def test_pdf_invalido_nao_interrompe_a_indexacao(self):
        (self.docs / "quebrado.pdf").write_text("não é PDF", encoding="utf-8")
        resumo = self._ingerir()
        self.assertEqual(resumo.com_erro, ["quebrado.pdf"])
        self.assertEqual(sorted(resumo.indexados), ["norma.pdf", "ppc.pdf"])

    def test_consulta_completa_com_ollama_simulado(self):
        self._ingerir()
        with OllamaFalso() as endereco, configuracao(OLLAMA_HOST=endereco):
            assistente = consulta.AssistenteRAG(modelo=self.modelo, colecao=self._colecao())
            self.assertEqual(assistente.verificar_base(), [])
            assistente.verificar_ollama()
            assistente.aquecer()
            recebidos = []
            resposta = assistente.responder("Qual a carga horária do estágio curricular obrigatório?",
                                            ao_receber=recebidos.append)
            self.assertIn("180 horas", resposta.passagens[0].texto)    # busca achou o trecho certo
            self.assertEqual("".join(recebidos).strip(), resposta.texto)   # streaming
            # o servidor falso cita [1] e [2]; só valem números de trechos que existem
            self.assertEqual(resposta.citadas, [n for n in (1, 2) if n <= len(resposta.passagens)])
            self.assertFalse(resposta.abstencao)
            self.assertTrue(all(p.fonte == "ppc.pdf" or p.fonte == "norma.pdf" for p in resposta.fontes()))
            self.assertIn("prompt_eval_count", resposta.estatisticas_llm)

            # abstenção decidida pelo modelo (o servidor falso abstém com "desconhecido")
            resposta = assistente.responder("trancamento desconhecido")
            self.assertTrue(resposta.abstencao)
            self.assertEqual(resposta.motivo_abstencao, "modelo")
            self.assertEqual(resposta.fontes(), [])

        registros = (config.REGISTROS_DIR / "interacoes.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(registros), 2)
        self.assertIn("passagens", json.loads(registros[0]))
        self.assertIn("resposta_mista", json.loads(registros[0]))

    def test_abstencao_por_similaridade_nao_chama_o_llm(self):
        self._ingerir()
        with configuracao(SIMILARIDADE_MINIMA=0.99):
            assistente = consulta.AssistenteRAG(modelo=self.modelo, colecao=self._colecao(),
                                                cliente_llm=None)   # sem Ollama nenhum
            resposta = assistente.responder("Qual é a capital da França?")
        self.assertTrue(resposta.abstencao)
        self.assertEqual(resposta.motivo_abstencao, "similaridade_baixa")
        self.assertFalse(resposta.gerada_pelo_llm)
        self.assertEqual(resposta.texto, config.MENSAGEM_ABSTENCAO)

    def test_erros_do_ollama_viram_mensagens_claras(self):
        self._ingerir()
        with OllamaFalso(modelos=("outro:1b",)) as endereco, configuracao(OLLAMA_HOST=endereco):
            assistente = consulta.AssistenteRAG(modelo=self.modelo, colecao=self._colecao())
            with self.assertRaisesRegex(consulta.ErroOllama, "ollama pull"):
                assistente.verificar_ollama()
            with self.assertRaisesRegex(consulta.ErroOllama, "ollama pull"):
                assistente.responder("trancamento de matrícula")
        with configuracao(OLLAMA_HOST="http://127.0.0.1:9"):   # porta sem servidor
            assistente = consulta.AssistenteRAG(modelo=self.modelo, colecao=self._colecao())
            with self.assertRaisesRegex(consulta.ErroOllama, "Não foi possível conectar"):
                assistente.verificar_ollama()
            with self.assertRaisesRegex(consulta.ErroOllama, "Não foi possível conectar"):
                assistente.responder("trancamento de matrícula")

    def test_base_vazia(self):
        assistente = consulta.AssistenteRAG(modelo=ModeloEmbeddingsFalso(nome="teste/sem-base"))
        with configuracao(CHROMA_DIR=Path(self._tmp.name) / "vazia"):
            with self.assertRaises(consulta.ErroBaseVazia):
                _ = assistente.colecao


class TestRodadaDePontaAPonta(unittest.TestCase):
    """Base real (ChromaDB), busca real (Recuperador), Ollama simulado: a rodada inteira."""

    # a mesma base de teste da classe acima, sem herdar (e repetir) os testes dela
    setUp = TestIndexacaoEConsulta.setUp
    tearDown = TestIndexacaoEConsulta.tearDown
    _ingerir = TestIndexacaoEConsulta._ingerir
    _colecao = TestIndexacaoEConsulta._colecao

    def test_rodada_completa_com_a_busca_de_verdade(self):
        import io
        from contextlib import redirect_stdout

        import avaliar_respostas
        import gerar_respostas as gr
        from perguntas import carregar_perguntas
        from recuperacao import Recuperador

        self._ingerir()
        raiz = Path(self._tmp.name)
        arquivo = raiz / "perguntas.csv"
        arquivo.write_text("id;pergunta;resposta_correta;sem_resposta\n"
                           "E1;Qual a carga horária do estágio curricular obrigatório?;180 horas.;não\n"
                           "E2;Quantos trancamentos totais posso fazer?;Quatro.;não\n"
                           "E3;Qual é a capital da França?;;sim\n", encoding="utf-8")
        modelos = {"modelo-a:1b": {"rotulo": "A", "raciocinio": False, "tempo_limite": 30},
                   "modelo-b:2b": {"rotulo": "B", "raciocinio": True, "tempo_limite": 30}}
        servidor = OllamaFalso(modelos=tuple(modelos), placa=1.0)
        with servidor as endereco, configuracao(OLLAMA_HOST=endereco, AVALIACAO_DIR=raiz / "avaliacao",
                                               MODELOS=modelos, MODELOS_COMPARACAO=list(modelos), TOP_K=4,
                                               MODO_BUSCA="hibrida", DOCS_DIR=self.docs), \
                redirect_stdout(io.StringIO()):
            conjunto = carregar_perguntas(arquivo)
            self.assertEqual(conjunto.erros, [])
            recuperador = Recuperador(modelo=self.modelo, colecao=self._colecao())
            pasta = gr.criar_rodada(conjunto, list(modelos), recuperador)
            gr.executar(pasta, list(modelos))
            resultado = avaliar_respostas.avaliar_rodada(pasta)
        contextos = json.loads((pasta / "contextos.json").read_text(encoding="utf-8"))
        estagio = next(c["contexto"] for c in contextos if c["id"] == "E1")
        self.assertIn("180 horas", " ".join(p["texto"] for p in estagio["passagens"]))
        self.assertEqual(estagio["configuracao"]["modo_busca"], "hibrida")
        configuracao_rodada = json.loads((pasta / "configuracao.json").read_text(encoding="utf-8"))
        self.assertEqual(configuracao_rodada["busca"]["top_k"], 4)
        # os dois modelos receberam exatamente as mesmas mensagens, só no processador
        pedidos = [p for p in servidor.requisicoes if p.get("messages")]
        por_modelo = {}
        for p in pedidos:
            por_modelo.setdefault(p["model"], []).append(p["messages"])
            self.assertEqual(p["options"]["num_gpu"], 0)
        self.assertEqual(por_modelo["modelo-a:1b"], por_modelo["modelo-b:2b"])
        self.assertEqual({t["modelo"]: t["respondidas"] for t in resultado["tabela"]},
                         {"modelo-a:1b": 3, "modelo-b:2b": 3})


if __name__ == "__main__":
    unittest.main()
