"""Testes da versão 10 (03/11/2026): o que os juízes recebem e como as notas são contadas.

Cada classe corresponde a um item da versão, aprovado depois do teste com os
dois juízes em 3 perguntas:

a) as marcas de citação saem do texto que vai para os juízes;
b) a completude, tirada dos veredictos que o juiz já deu na correção;
c) a recusa com outras palavras e uma citação solta é abstenção, também nas
   respostas já gravadas (a categoria é refeita sobre o texto);
d) as notas de um método anterior ficam no arquivo, são refeitas e não
   entram nas médias.

Os textos de exemplo vêm da rodada de teste de 03/11/2026.
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from test_ragas import JUIZ_FALSO, _AvaliadorFalso, _do_juiz
from test_rodada import _ComRodada

import avaliar_ragas as ar
import avaliar_respostas
import config
import consulta
import gerar_respostas as gr

M = config.MENSAGEM_ABSTENCAO
# Phi-4-mini, R03: a busca não trouxe o trecho certo, e ele disse que não encontrou, com um "[1]" no fim
RECUSA_DO_PHI = "Não foi encontrada na informação fornecida quantas vezes você pode trancar a mesma disciplina. [1]"
TEXTO_DO_MODELO_FALSO = "Conforme o documento, a regra está descrita no trecho [1]. Veja também [2]."


def _detalhes(lado_da_resposta, lado_da_resposta_correta):
    """O que o juiz devolve na correção do RAGAS: os dois lados, cada um com as afirmações e os veredictos."""
    saida = []
    for veredictos in (lado_da_resposta, lado_da_resposta_correta):
        afirmacoes = [f"afirmação {i}" for i in range(len(veredictos))]
        saida.append({"etapa": "ClaimDecompositionOutput", "saida": {"claims": afirmacoes}})
        if afirmacoes:
            saida.append({"etapa": "NLIStatementOutput", "saida": {"statements": [
                {"statement": a, "reason": "", "verdict": int(v)} for a, v in zip(afirmacoes, veredictos)]}})
    return saida


class _AvaliadorQueGuarda(_AvaliadorFalso):
    """Guarda o texto que o juiz recebeu e devolve, na correção, os dois lados da conta do RAGAS."""

    def __init__(self, *args, lados=((False,), (True, False)), **kwargs):
        super().__init__(*args, **kwargs)
        self.textos = []
        self.lados = lados

    def correcao(self, pergunta, resposta, referencia):
        self.textos.append(("correcao", resposta))
        valor, _ = self._nota("correcao", pergunta, self.notas["correcao"])
        return valor, _detalhes(*self.lados)

    def fidelidade(self, pergunta, resposta, trechos):
        self.textos.append(("fidelidade", resposta))
        return super().fidelidade(pergunta, resposta, trechos)


def _reescrever(pasta, modelo, mudar):
    arquivo = gr.arquivo_respostas(pasta, modelo)
    linhas = gr.ler_respostas(arquivo)
    mudar({l["id"]: l for l in linhas})
    arquivo.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas), encoding="utf-8")


class TestMarcasDeCitacaoForaDoTextoJulgado(unittest.TestCase):
    """Item a."""

    def test_marcas_saem_e_o_resto_fica(self):
        casos = {
            "São 4 trancamentos [1].": "São 4 trancamentos.",
            "De acordo com o documento [1], Art. 37, é permitido.": "De acordo com o documento, Art. 37, é permitido.",
            "Não é concedido aos ingressantes [2][3].": "Não é concedido aos ingressantes.",
            "O prazo é de 5 dias [1, 4].": "O prazo é de 5 dias.",
            "São duas etapas [1-3].": "São duas etapas.",
            "Conforme o inciso II [8, II], o prazo é de 5 dias.": "Conforme o inciso II, o prazo é de 5 dias.",
            "Conforme o Art. 37, § 1º [1].": "Conforme o Art. 37, § 1º.",
            "Pode solicitar:\n* 2 trancamentos [1];\n* 4 trancamentos [1].": "Pode solicitar:\n* 2 trancamentos;\n* 4 trancamentos.",
            RECUSA_DO_PHI: RECUSA_DO_PHI[:-4],
            "O prazo é de 5 dias [1] .": "O prazo é de 5 dias.",
        }
        for original, esperado in casos.items():
            self.assertEqual(ar.texto_para_o_juiz(original), esperado, original)

    def test_colchetes_que_nao_sao_citacao_ficam(self):
        self.assertEqual(ar.texto_para_o_juiz("O texto diz [sic] que pode."), "O texto diz [sic] que pode.")
        self.assertEqual(ar.texto_para_o_juiz("Veja a [Resolução 480](https://exemplo.br)."),
                         "Veja a [Resolução 480](https://exemplo.br).")

    def test_o_resto_do_texto_nao_muda(self):
        # revisão independente da versão 10: o recuo das listas (Llama 3.1 8B, R11) e os espaços do texto ficam
        self.assertEqual(ar.texto_para_o_juiz("Desligamento [8]:\n    - abandono [7];\n    - jubilamento [8]."),
                         "Desligamento:\n    - abandono;\n    - jubilamento.")
        self.assertEqual(ar.texto_para_o_juiz("O valor é ( R$ 3,00 )  por refeição [2]."),
                         "O valor é ( R$ 3,00 )  por refeição.")

    def test_so_marcas_vira_texto_vazio(self):
        self.assertEqual(ar.texto_para_o_juiz(" [1] [2] "), "")
        self.assertEqual(ar.texto_para_o_juiz(None), "")


class TestCompletude(unittest.TestCase):
    """Item b."""

    def test_e_o_lado_da_resposta_correta(self):
        # Llama 3.1 8B, R01, juiz Gemma: as três afirmações da resposta rejeitadas por citarem o Art. 37 (F1 zero),
        # e duas das três afirmações da resposta correta achadas na resposta
        self.assertEqual(ar.completude(_detalhes([False, False, False], [True, True, False])),
                         {"valor": 0.6667, "afirmacoes_da_resposta_correta": 3, "conferidas_pelo_juiz": 3,
                          "encontradas_na_resposta": 2})

    def test_juiz_que_devolve_menos_veredictos(self):
        # a conta usa os veredictos, como o RAGAS no F1; os dois números ficam gravados
        detalhes = _detalhes([True], [True, True])
        detalhes[2]["saida"]["claims"].append("afirmação que o juiz não conferiu")
        self.assertEqual(ar.completude(detalhes), {"valor": 1.0, "afirmacoes_da_resposta_correta": 3,
                                                   "conferidas_pelo_juiz": 2, "encontradas_na_resposta": 2})

    def test_resposta_sem_afirmacoes(self):
        # o RAGAS não pede veredicto quando a divisão não rende afirmação: o primeiro lado fica sem ele
        self.assertEqual(ar.completude(_detalhes([], [True, False]))["valor"], 0.5)

    def test_sem_afirmacoes_da_resposta_correta_nao_tem_completude(self):
        self.assertIsNone(ar.completude(_detalhes([True], [])))
        self.assertIsNone(ar.completude([]))
        self.assertIsNone(ar.completude(None))
        self.assertIsNone(ar.completude([{"etapa": "correcao", "saida": {"claims": ["x"]}}]))


class TestRecusaComCitacaoSolta(unittest.TestCase):
    """Item c, na classificação."""

    def c(self, texto):
        return consulta.classificar_resposta(texto, 6)

    def test_recusa_com_outras_palavras_e_citacao_solta_e_abstencao(self):
        self.assertEqual(self.c(RECUSA_DO_PHI), "abstencao")
        self.assertEqual(self.c(RECUSA_DO_PHI.replace(". [1]", " [1].")), "abstencao")
        # Phi-4-mini, N05, e Llama 3.1 8B, N02: perguntas que os documentos não respondem
        self.assertEqual(self.c("A informação sobre o custo da refeição no restaurante universitário não foi "
                                "encontrada nos documentos disponíveis. [1]"), "abstencao")
        self.assertEqual(self.c("Não encontrei informações sobre o cardápio do restaurante universitário nos trechos "
                                "fornecidos [1]. Procure a coordenação do seu curso para obter orientação."), "abstencao")
        self.assertEqual(self.c("Os trechos não trazem o valor da taxa [1]."), "abstencao")
        self.assertEqual(self.c("O documento [1] não informa o valor da taxa."), "abstencao")   # citação no meio
        self.assertEqual(self.c("Não há menção a isso no trecho [2]. " + M), "abstencao")

    def test_recusa_junto_com_informacao_continua_resposta(self):
        self.assertEqual(self.c("Não encontrei o valor da taxa, mas o prazo é de 5 dias [1]."), "resposta")
        self.assertEqual(self.c("O prazo é de 5 dias [1] e não encontrei o valor da taxa."), "resposta")
        # limitação: a recusa com número continua resposta, como antes da versão 10
        self.assertEqual(self.c("Não encontrei no Art. 37 [1] quantas vezes posso trancar."), "resposta")
        self.assertEqual(self.c("Os trechos não informam o valor [2], porém indicam que o pagamento é feito na "
                                "secretaria [3]."), "resposta")
        self.assertEqual(self.c("Não encontrei a informação no trecho [2]; o trecho trata do trancamento total."),
                         "resposta")
        # Llama 3.1 8B, R01: respondeu e depois disse que não encontrou
        self.assertEqual(self.c("De acordo com o documento [1], Art. 37, é permitido solicitar no máximo 2 "
                                "trancamentos. Não encontrei a resposta para a pergunta sobre o total."), "resposta")

    def test_negativa_com_informacao_continua_resposta(self):
        # revisão independente da versão 10: respostas com informação que a primeira regra tomava por abstenção
        casos = [
            "Não há cobrança de taxa para a emissão do documento [1].",
            "Não, não há exigência de documento para o trancamento [1].",
            "O aluno não está obrigado a apresentar documento de identidade [2].",
            "O estudante não está dispensado de entregar os documentos exigidos [1].",
            "Não constam pré-requisitos para essa disciplina no documento [3].",
            "Os documentos não mencionam o trancamento de disciplina, e o trancamento de matrícula pode ser feito até a "
            "metade do semestre [1].",
            "Os trechos não informam o valor da taxa, apenas que ela deve ser paga antes da matrícula [1].",
            "Não encontrei o valor da taxa nos trechos: o documento informa somente que ela é cobrada na matrícula [1].",
            "Não foi encontrada informação sobre trancamentos além do limite de duas vezes por curso [1].",
            "Não foi possível encontrar o prazo, pois o pedido é analisado pela comissão de curso a cada semestre [2].",
            "O prazo é de cinco dias e não encontrei o valor da taxa [1].",
            # encaminhamento que cita um trecho traz um procedimento
            "Não encontrei o prazo. Dirija-se à secretaria acadêmica do campus com o RG e o comprovante de matrícula [1].",
            "Não encontrei o prazo para o pedido. Consulte a coordenação do curso, que é responsável por analisar e "
            "deferir o aproveitamento [1].",
        ]
        for texto in casos:
            self.assertEqual(self.c(texto), "resposta", texto)
        self.assertEqual(self.c("Não encontrei essa informação nos documentos disponíveis sobre a disciplina, que é "
                                "oferecida apenas no primeiro semestre [1]."), "mista")

    def test_segunda_revisao_frases_com_informacao(self):
        # segunda conferência da revisão independente: as palavras da recusa em frases com informação, e a marca que vem
        # depois do ponto num encaminhamento com procedimento
        casos = [
            "O discente que não foi encontrado na lista de matriculados deve procurar a secretaria acadêmica [1].",
            "O atestado médico sem informação do período de afastamento não é aceito [1].",
            "A universidade não divulga nenhuma informação sobre o nome civil do discente [1].",
            "O nome civil não é apresentado nos documentos acadêmicos quando há nome social [1].",
            "A entrega dos documentos não indica deferimento automático do pedido [1].",
            "O histórico escolar não é disponibilizado sem a apresentação de documento com foto [1].",
            "Não é possível informar a nota antes do fechamento do semestre [1].",
            "Não há dados pessoais no atestado de matrícula [1].",
            "Não encontrei restrição para trancar a mesma disciplina mais de uma vez no regulamento [1].",
            "Não encontrei o prazo. Dirija-se à secretaria acadêmica do campus com o formulário preenchido. [1]",
            "Segundo os trechos fornecidos, o discente que não foi encontrado na lista deve procurar a secretaria [1].",
            "De acordo com os trechos fornecidos, não há cobrança de taxa [1].",
        ]
        for texto in casos:
            self.assertEqual(self.c(texto), "resposta", texto)

    def test_outras_formas_de_recusa(self):
        casos = [
            "Infelizmente, não encontrei essa informação nos trechos fornecidos [1].",
            "Com base nos trechos fornecidos, não é possível responder a essa pergunta [1].",
            "Desculpe, mas não encontrei essa informação [1].",
            "Não consegui encontrar essa informação nos trechos fornecidos [1].",
            "A informação não está disponível nos trechos fornecidos [1].",
            "Essa informação não consta nos documentos fornecidos [1].",
            "Os documentos fornecidos não fazem menção a esse assunto [1].",
            "Não há nos trechos informação sobre o cardápio [1].",
            "A pergunta não pode ser respondida com os trechos fornecidos [1].",
            "Não encontrei essa informação nos trechos [1] e [2].",
            "A capital da França não foi mencionada nos trechos fornecidos. [1]",              # Phi-4-mini, N04
        ]
        for texto in casos:
            self.assertEqual(self.c(texto), "abstencao", texto)
        # limitações, como antes da versão 10: recusa com "e", com dois-pontos ou em inglês continua resposta
        self.assertEqual(self.c("Não encontrei informações sobre o valor e o prazo da taxa [1]."), "resposta")
        self.assertEqual(self.c("**Resposta:** Não encontrei essa informação nos trechos fornecidos [1]."), "resposta")

    def test_lista_com_nota_no_fim_e_resposta(self):
        # Llama 3.1 8B, R37 e R50: a lista vem nas quebras de linha, e a nota sobre o que faltou fica no fim
        self.assertEqual(self.c("As modalidades do Processo Seletivo Complementar são:\n\n* Segundo ciclo de "
                                "formação [1]\n* Reingresso [3]\n\nNota: Não foi encontrado o número exato de "
                                "modalidades no trecho [2]."), "resposta")
        self.assertEqual(self.c("Os feriados são:\n\n- Tiradentes [2]\n- Corpus Christi [2]\n\n" + M), "mista")

    def test_mista_continua_mista(self):
        # Llama 3.1 8B, R03: diz que não encontrou, cita um trecho sobre outro assunto e traz a frase padrão
        self.assertEqual(self.c("Não há menção específica sobre trancar disciplinas no texto fornecido. O documento "
                                "trata do Trancamento Total de matrícula, pelo prazo de 1 semestre [1]. " + M), "mista")


class TestCategoriaRefeitaNaAvaliacao(_ComRodada):
    """Item c, nas respostas já gravadas."""

    def test_recusa_gravada_como_resposta_vira_abstencao_e_aparece_na_tabela(self):
        pasta, _ = self.rodar()

        def mudar(linhas):                   # como a versão 09 gravou a resposta do Phi-4-mini à R03
            linhas["P1"].update(resposta=RECUSA_DO_PHI, citadas=[1], citacao_explicita=True, categoria="resposta",
                                abstencao=False)
        _reescrever(pasta, "modelo-a:1b", mudar)
        linha = {l["id"]: l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b"))}["P1"]
        self.assertEqual(avaliar_respostas.categoria_gravada(linha), "resposta")
        self.assertEqual(avaliar_respostas.categoria(linha), "abstencao")
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        tabela = {t["modelo"]: t for t in resultado["tabela"]}
        self.assertEqual((tabela["modelo-a:1b"]["respondeu"], tabela["modelo-a:1b"]["absteve_modelo"]), (0, 1))
        self.assertEqual(resultado["reclassificadas"],
                         [{"modelo": "modelo-a:1b", "id": "P1", "gravada": "resposta", "atual": "abstencao"}])
        revisar = {(r["modelo"], r["id"]): r for r in resultado["revisar"]}
        self.assertIn("outras palavras", revisar[("modelo-a:1b", "P1")]["motivo"])        # para conferir à mão
        markdown = avaliar_respostas.texto_markdown(resultado)
        self.assertIn("Modelo A P1, de resposta para abstenção", markdown)
        self.assertNotIn("\u2014", markdown)
        gravado = gr.arquivo_respostas(pasta, "modelo-a:1b").read_text(encoding="utf-8")
        self.assertIn('"categoria": "resposta"', gravado)                       # o arquivo não muda

    def test_abstencao_pelo_limiar_e_resposta_antiga_sem_citadas(self):
        pasta, _ = self.rodar()
        linhas = {l["id"]: l for l in gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b"))}
        self.assertFalse(linhas["P2"]["gerada_pelo_llm"])                       # parou no limiar
        self.assertEqual(avaliar_respostas.categoria(linhas["P2"]), "abstencao")
        sem_citadas = {k: v for k, v in linhas["P1"].items() if k != "citadas"}
        self.assertEqual(avaliar_respostas.categoria(sem_citadas), "resposta")
        self.assertEqual(avaliar_respostas.avaliar_rodada(pasta)["reclassificadas"], [])

    def test_recusa_gravada_como_resposta_nao_vai_ao_juiz(self):
        pasta, _ = self.rodar()

        def mudar(linhas):
            linhas["P1"].update(resposta=RECUSA_DO_PHI, citadas=[1], categoria="resposta", abstencao=False)
        _reescrever(pasta, "modelo-a:1b", mudar)
        avaliador = _AvaliadorQueGuarda()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        self.assertNotIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)
        linha = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertEqual((linha["categoria"], linha["abstencao"]), ("abstencao", True))
        self.assertIsNone(linha["correcao"])


class TestAvaliacaoDaVersao10(_ComRodada):
    """Itens a, b e d, na avaliação de uma rodada."""

    def test_juiz_recebe_o_texto_sem_marcas_e_a_nota_guarda_o_metodo_e_a_completude(self):
        pasta, _ = self.rodar()
        avaliador = _AvaliadorQueGuarda()
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, ["modelo-a:1b"], avaliador)
        sem_marcas = "Conforme o documento, a regra está descrita no trecho. Veja também."
        self.assertEqual({t for _, t in avaliador.textos}, {sem_marcas})          # correção e fidelidade
        linha = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertEqual(linha["metodo"], ar.VERSAO_DO_METODO)
        self.assertEqual(linha["texto_julgado"], sem_marcas)
        self.assertEqual(linha["completude"], {"valor": 0.5, "afirmacoes_da_resposta_correta": 2,
                                               "conferidas_pelo_juiz": 2, "encontradas_na_resposta": 1})
        respostas = gr.ler_respostas(gr.arquivo_respostas(pasta, "modelo-a:1b"))
        self.assertEqual(respostas[0]["resposta"], TEXTO_DO_MODELO_FALSO)        # a resposta gravada não muda
        tabela = {t["modelo"]: t for t in resumo["tabela"]}
        self.assertEqual(tabela["modelo-a:1b"]["completude"]["media"], 0.5)
        self.assertEqual(tabela["modelo-a:1b"]["completude"]["n"], 1)

    def test_resposta_so_com_marcas_nao_vai_ao_juiz(self):
        pasta, _ = self.rodar()

        def mudar(linhas):
            linhas["P1"].update(resposta="[1] [2]", citadas=[1, 2])
        _reescrever(pasta, "modelo-a:1b", mudar)
        avaliador = _AvaliadorQueGuarda()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], avaliador)
        linha = _do_juiz(pasta, "modelo-a:1b")["P1"]
        self.assertTrue(linha["resposta_vazia"])
        self.assertFalse(linha["tem_erro"])
        self.assertNotIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)

    def test_completude_na_media_dos_juizes_na_concordancia_e_no_csv(self):
        pasta, _ = self.rodar()
        a = _AvaliadorQueGuarda(juiz="a:1b", lados=((False,), (True, True)))       # completude 1
        b = _AvaliadorQueGuarda(juiz="b:1b", lados=((False,), (True, False)))      # completude 0,5
        with redirect_stdout(io.StringIO()):
            resumo = ar.executar(pasta, ["modelo-a:1b", "modelo-b:2b"], [a, b])
        linha = next(t for t in resumo["tabela"] if t["modelo"] == "modelo-a:1b")
        self.assertEqual(linha["completude"]["media"], 0.75)
        self.assertEqual(linha["por_juiz"]["a:1b"]["completude"]["media"], 1.0)
        completude = next(c for c in resumo["concordancia"] if c["metrica"] == "completude")
        self.assertEqual((completude["n"], completude["diferenca_media"]), (2, 0.5))
        self.assertTrue(any(c["metrica"] == "completude" for c in resumo["comparacoes"]))
        cabecalho = (pasta / "ragas_juizes.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
        self.assertIn("completude_media_juizes", cabecalho)
        texto = (pasta / "ragas_juizes.md").read_text(encoding="utf-8")
        self.assertIn("Completude (média dos juízes)", texto)
        self.assertIn("não tira ponto da resposta que diz de onde veio a informação", texto)
        self.assertNotIn("\u2014", texto)
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        self.assertEqual(next(t for t in resultado["tabela"] if t["modelo"] == "modelo-a:1b")["completude_media"],
                         0.75)
        self.assertIn("Completude média (juízes)", avaliar_respostas.texto_markdown(resultado))

    def test_nota_de_metodo_anterior_e_refeita_e_fica_no_arquivo(self):
        pasta, _ = self.rodar()
        destino = ar.pasta_do_juiz(pasta, JUIZ_FALSO)
        destino.mkdir()
        antiga = {"id": "P1", "modelo": "modelo-a:1b", "juiz": JUIZ_FALSO, "sem_resposta": False, "abstencao": False,
                  "correcao": {"valor": 0.0, "detalhes": []}, "fidelidade": {"valor": 0.0, "detalhes": []},
                  "tem_erro": False}                                                 # versão 09: sem "metodo"
        ar.arquivo_ragas(destino, "modelo-a:1b").write_text(json.dumps(antiga) + "\n", encoding="utf-8")
        avaliador = _AvaliadorQueGuarda()
        saida = io.StringIO()
        with redirect_stdout(saida):
            resumo = ar.executar(pasta, ["modelo-a:1b"], avaliador)
        self.assertIn(("correcao", "Quantos trancamentos posso fazer?"), avaliador.chamadas)   # refeita
        self.assertIn(f"método anterior à versão {ar.VERSAO_DO_METODO}", saida.getvalue())
        linhas = gr.ler_respostas(ar.arquivo_ragas(destino, "modelo-a:1b"))
        p1 = [l for l in linhas if l["id"] == "P1"]
        self.assertEqual(len(p1), 2)                                                 # a antiga ficou guardada
        self.assertNotIn("metodo", p1[0])
        self.assertEqual(p1[1]["correcao"]["valor"], 0.75)                           # e a nova é a que vale
        self.assertEqual(next(t for t in resumo["tabela"] if t["modelo"] == "modelo-a:1b")["correcao"]["media"], 0.75)
        segundo = _AvaliadorQueGuarda()
        with redirect_stdout(io.StringIO()):
            ar.executar(pasta, ["modelo-a:1b"], segundo)
        self.assertEqual(segundo.chamadas, [])                                       # não refaz de novo

    def test_notas_de_metodo_anterior_nao_entram_nas_medias(self):
        pasta, _ = self.rodar()
        destino = ar.pasta_do_juiz(pasta, JUIZ_FALSO)
        destino.mkdir()
        (destino / ar.ARQUIVO_CONFIGURACAO_JUIZ).write_text(json.dumps([{"juiz": JUIZ_FALSO}]), encoding="utf-8")
        antiga = {"id": "P1", "modelo": "modelo-a:1b", "juiz": JUIZ_FALSO, "sem_resposta": False, "abstencao": False,
                  "correcao": {"valor": 0.0}, "fidelidade": {"valor": 0.0}, "tem_erro": False}
        ar.arquivo_ragas(destino, "modelo-a:1b").write_text(json.dumps(antiga) + "\n", encoding="utf-8")
        resumo = ar.resumir_juizes(pasta)
        self.assertEqual(resumo["notas_antigas"], {JUIZ_FALSO: 1})
        self.assertEqual(resumo["tabela"], [])
        self.assertIn(f"método anterior à versão {ar.VERSAO_DO_METODO}", ar.texto_markdown_juizes(resumo))
        self.assertEqual(ar.resumir(pasta, destino)["notas_antigas"], 1)
        resultado = avaliar_respostas.avaliar_rodada(pasta)
        self.assertEqual(resultado["notas_antigas_dos_juizes"], 1)
        self.assertIsNone(resultado["tabela"][0]["correcao_media"])
        self.assertIn(f"método anterior à versão {ar.VERSAO_DO_METODO}", avaliar_respostas.texto_markdown(resultado))


if __name__ == "__main__":
    unittest.main()
