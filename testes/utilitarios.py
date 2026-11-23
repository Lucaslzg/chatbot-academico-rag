"""Ferramentas compartilhadas pelos testes (sem internet, sem GPU, sem modelos).

* ModeloEmbeddingsFalso: substitui o ModeloEmbeddings. Conta "tokens" por uma
  regra simples e gera vetores por palavras (hashing), o que já basta para
  testar indexação, busca e montagem de contexto de ponta a ponta.
* PDFSintetico: gera PDFs com formatos variados (títulos em negrito, tabela,
  listas, cabeçalho/rodapé, texto riscado, parágrafo entre páginas...) para
  testar a generalidade do processamento.
* configuracao(): altera valores do config.py temporariamente.
"""
from __future__ import annotations

import hashlib
import math
import re
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import fitz
import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import config  # noqa: E402

# Versão antiga da Res. 29/2011 (alterada até a Res. 225), usada só nos testes: ela saiu do
# corpus porque a versão consolidada até a Res. 480/2026 a substitui.
PDF_EXEMPLO = RAIZ / "testes" / "dados" / "res-29_2011-normas-basicas-de-graduacao-alterada-pela-res-225-1.pdf"

_PALAVRAS_VAZIAS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos",
                    "nas", "um", "uma", "para", "por", "com", "que", "se", "ao", "aos", "qual", "quais",
                    "como", "posso", "pode", "sao", "ser", "ou"}


@contextmanager
def configuracao(**valores):
    """Troca valores do config.py durante um bloco `with`."""
    antigos = {chave: getattr(config, chave) for chave in valores}
    for chave, valor in valores.items():
        setattr(config, chave, valor)
    try:
        yield
    finally:
        for chave, valor in antigos.items():
            setattr(config, chave, valor)


def contar_tokens_aproximado(texto: str) -> int:
    """Aproxima subpalavras: cada palavra vale 1 token a cada 5 letras."""
    return sum(max(1, math.ceil(len(p) / 5)) if p[0].isalnum() else 1
               for p in re.findall(r"\w+|[^\w\s]", texto))


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().lower()


class ModeloEmbeddingsFalso:
    """Mesma interface do vetorial.ModeloEmbeddings, sem rede neural."""

    def __init__(self, nome: str = "teste/modelo-falso", janela: int = 128, dimensao: int = 256):
        self.nome = nome
        self.max_tokens = None
        self.prefixo_consulta = ""
        self.prefixo_documento = ""
        self._janela = janela
        self._dimensao = dimensao
        self.carregado = True

    @property
    def janela_tokens(self) -> int:
        return self._janela

    @property
    def limite_conteudo(self) -> int:
        return self._janela - 2

    @property
    def dimensao(self) -> int:
        return self._dimensao

    def contar_tokens(self, texto: str) -> int:
        return contar_tokens_aproximado(texto)

    def _vetor(self, texto: str) -> list[float]:
        v = np.zeros(self._dimensao)
        for palavra in re.findall(r"\w+", _sem_acento(texto)):
            if palavra in _PALAVRAS_VAZIAS:
                continue
            raiz = palavra[:6]   # "radical" grosseiro: trancamento/trancar/trancamentos
            v[int(hashlib.md5(raiz.encode()).hexdigest(), 16) % self._dimensao] += 1.0
        norma = np.linalg.norm(v)
        if norma == 0:
            v[0], norma = 1.0, 1.0
        return (v / norma).tolist()

    def codificar_documentos(self, textos, mostrar_progresso=False):
        return [self._vetor(t) for t in textos]

    def codificar_consultas(self, perguntas):
        return [self._vetor(p) for p in perguntas]

    def codificar_consulta(self, pergunta):
        return self._vetor(pergunta)


class PDFSintetico:
    """Monta PDFs de teste escrevendo texto em posições controladas."""

    LARGURA, ALTURA, MARGEM = 595, 842, 72

    def __init__(self, cabecalho: str | None = None, rodape: str | None = None, numerar: bool = False):
        self.doc = fitz.open()
        self.cabecalho, self.rodape, self.numerar = cabecalho, rodape, numerar
        self.pagina = None
        self.y = 0.0
        self.nova_pagina()

    def nova_pagina(self) -> None:
        self.pagina = self.doc.new_page(width=self.LARGURA, height=self.ALTURA)
        n = len(self.doc)
        if self.cabecalho:
            self.pagina.insert_text((self.MARGEM, 40), self.cabecalho, fontname="helv", fontsize=8)
        if self.rodape:
            self.pagina.insert_text((self.MARGEM, self.ALTURA - 30), self.rodape, fontname="helv", fontsize=8)
        if self.numerar:
            self.pagina.insert_text((self.LARGURA - self.MARGEM, self.ALTURA - 30), f"Página {n} de 9",
                                    fontname="helv", fontsize=8)
        self.y = 100.0

    def _quebrar(self, texto: str, largura: float, fonte: str, tamanho: float) -> list[str]:
        linhas, atual = [], ""
        for palavra in texto.split():
            tentativa = (atual + " " + palavra).strip()
            if fitz.get_text_length(tentativa, fontname=fonte, fontsize=tamanho) > largura and atual:
                linhas.append(atual)
                atual = palavra
            else:
                atual = tentativa
        if atual:
            linhas.append(atual)
        return linhas

    def escrever(self, texto: str, tamanho: float = 11, negrito: bool = False, recuo: float = 0,
                 espaco_depois: float = 6, riscar: bool = False, linhas: list[str] | None = None) -> None:
        fonte = "hebo" if negrito else "helv"
        largura = self.LARGURA - 2 * self.MARGEM - recuo
        for linha in linhas or self._quebrar(texto, largura, fonte, tamanho):
            if self.y > self.ALTURA - 80:
                self.nova_pagina()
            self.pagina.insert_text((self.MARGEM + recuo, self.y), linha, fontname=fonte, fontsize=tamanho)
            if riscar:
                comprimento = fitz.get_text_length(linha, fontname=fonte, fontsize=tamanho)
                meio = self.y - tamanho * 0.3
                self.pagina.draw_line((self.MARGEM + recuo, meio), (self.MARGEM + recuo + comprimento, meio),
                                      width=0.8)
            self.y += tamanho * 1.25
        self.y += espaco_depois

    def tabela(self, linhas: list[list[str]], larguras: list[float], tamanho: float = 9) -> None:
        altura_linha = tamanho * 2.2
        if self.y + altura_linha * len(linhas) > self.ALTURA - 80:
            self.nova_pagina()
        x0, topo = self.MARGEM, self.y
        xs = [x0]
        for largura in larguras:
            xs.append(xs[-1] + largura)
        for i in range(len(linhas) + 1):
            self.pagina.draw_line((xs[0], topo + i * altura_linha), (xs[-1], topo + i * altura_linha))
        for x in xs:
            self.pagina.draw_line((x, topo), (x, topo + len(linhas) * altura_linha))
        for i, linha in enumerate(linhas):
            for j, celula in enumerate(linha):
                self.pagina.insert_text((xs[j] + 3, topo + i * altura_linha + tamanho * 1.4), celula,
                                        fontname="helv", fontsize=tamanho)
        self.y = topo + len(linhas) * altura_linha + 14

    def salvar(self, caminho: Path) -> Path:
        self.doc.save(caminho)
        self.doc.close()
        return caminho


def criar_ppc_sintetico(caminho: Path) -> Path:
    """PDF no estilo de um PPC: capa, títulos numerados em negrito, parágrafos
    separados só por espaçamento (sem linha em branco), lista, tabela,
    cabeçalho e rodapé repetidos e um parágrafo que atravessa a página, com
    uma nota de rodapé no pé da página em que ele começa."""
    pdf = PDFSintetico(cabecalho="Projeto Pedagógico do Curso de Engenharia de Computação", numerar=True)
    pdf.escrever("UNIVERSIDADE FEDERAL DO PAMPA", tamanho=12, negrito=True)
    pdf.escrever("PROJETO PEDAGÓGICO DO CURSO DE ENGENHARIA DE COMPUTAÇÃO", tamanho=16, negrito=True)
    pdf.escrever("Bagé, 2023", tamanho=11)
    pdf.nova_pagina()
    pdf.escrever("1 APRESENTAÇÃO", tamanho=13, negrito=True)
    pdf.escrever("O curso de Engenharia de Computação forma profissionais para projetar sistemas "
                 "computacionais. A carga horária total do curso é de 3.600 horas, distribuídas em dez "
                 "semestres letivos.", espaco_depois=4)
    pdf.escrever("O estágio curricular obrigatório tem carga horária de 180 horas e é realizado a partir do "
                 "oitavo semestre, sob orientação de um docente do curso.", espaco_depois=4)
    pdf.escrever("1.1 Objetivos do curso", tamanho=12, negrito=True)
    pdf.escrever("São objetivos do curso:", espaco_depois=2)
    pdf.escrever("• formar engenheiros com sólida base em matemática e física;", recuo=12, espaco_depois=1)
    pdf.escrever("• desenvolver a capacidade de projetar hardware e software;", recuo=12, espaco_depois=1)
    pdf.escrever("• estimular a pesquisa e a extensão.", recuo=12, espaco_depois=8)
    pdf.escrever("2 MATRIZ CURRICULAR", tamanho=13, negrito=True)
    pdf.tabela([["Código", "Componente curricular", "Semestre", "CH"],
                ["BA000001", "Cálculo I", "1", "60"],
                ["BA000002", "Algoritmos e Programação", "1", "60"],
                ["BA000150", "Trabalho de Conclusão de Curso II", "10", "60"]], [80, 220, 70, 60])
    pdf.escrever("3 TRABALHO DE CONCLUSÃO DE CURSO", tamanho=13, negrito=True)
    pdf.escrever("A redação antiga desta regra previa defesa fechada ao público.", riscar=True, espaco_depois=2)
    pdf.escrever("(Revogado pela Resolução 99, de 1º de março de 2024)", espaco_depois=6)
    pdf.escrever("O Trabalho de Conclusão de Curso é desenvolvido em duas etapas, TCC I e TCC II, com "
                 "defesa pública perante banca de três avaliadores.")
    # parágrafo que começa no fim de uma página e termina na seguinte
    pdf.y = pdf.ALTURA - 100
    pdf.escrever("", linhas=["A banca avaliadora do TCC é composta pelo orientador e por dois"], espaco_depois=0)
    # nota de rodapé (letra menor, no pé da página, abaixo do texto)
    pdf.pagina.insert_text((pdf.MARGEM, pdf.ALTURA - 52), "1 O regulamento do TCC é aprovado pela Comissão "
                           "de Curso.", fontname="helv", fontsize=8)
    pdf.nova_pagina()
    pdf.escrever("", linhas=["docentes convidados, que atribuem a nota final do trabalho."])
    return pdf.salvar(caminho)


def criar_pdf_hifenizado(caminho: Path) -> Path:
    """Texto com separação silábica no fim das linhas (típico de LaTeX)."""
    pdf = PDFSintetico()
    linhas = []
    for i in range(12):
        linhas += [f"Parágrafo {i} sobre a informação acadêmica e a infor-",
                   "mação institucional, com a documen-",
                   "tação necessária para transferir-",
                   "se de curso conforme o regula-",
                   "mento vigente."]
    pdf.escrever("", linhas=linhas)
    return pdf.salvar(caminho)


def criar_pdf_sem_texto(caminho: Path) -> Path:
    """Página só com um desenho (como um PDF digitalizado sem OCR)."""
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.draw_rect(fitz.Rect(100, 100, 300, 300), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    doc.save(caminho)
    doc.close()
    return caminho
