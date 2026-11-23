"""Fase de indexação (Fase 3 da metodologia; RF01 da Seção 5.2).

Fluxo: PDFs de data/documentos -> processamento (limpeza, estrutura,
fragmentos) -> embeddings -> ChromaDB. Rode sempre que adicionar, trocar ou
remover documentos:

    python ingestao.py              # indexa só o que mudou
    python ingestao.py --completo   # reconstrói a base inteira

Regras de sincronização (RF01: reindexar substitui, sem duplicar):
* documento novo ou alterado (conteúdo diferente) -> os fragmentos antigos
  dele são apagados e os novos gravados;
* documento sem alteração -> nada é refeito (a verificação usa o hash SHA-256
  do arquivo, não a data);
* documento que saiu da pasta -> seus fragmentos saem da base;
* mudança de modelo de embeddings ou de parâmetro de segmentação -> a base é
  reconstruída do zero, porque os fragmentos antigos deixam de ser comparáveis.

Para cada documento processado, um relatório legível com todos os fragmentos
é gravado em data/relatorios_indexacao/.
"""
from __future__ import annotations

import argparse
import hashlib
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import config
import processamento
from vetorial import (COLECAO_LEGADA, ErroEmbeddings, ModeloEmbeddings, abrir_cliente,
                      assinatura, carregar_titulos, criar_colecao, id_fragmento, nome_colecao,
                      obter_colecao, opcoes_processamento, parametros_indice, remover_colecao)


@dataclass
class ResumoIndexacao:
    indexados: list[str] = field(default_factory=list)
    inalterados: list[str] = field(default_factory=list)
    removidos: list[str] = field(default_factory=list)
    com_erro: list[str] = field(default_factory=list)
    sem_texto: list[str] = field(default_factory=list)
    base_reconstruida: bool = False
    total_fragmentos: int = 0


def hash_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def listar_pdfs(pasta: Path) -> list[Path]:
    return sorted((p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
                  key=lambda p: p.name.lower())


def documentos_indexados(colecao) -> dict[str, dict]:
    """Situação de cada documento já presente na base.

    Um documento só é considerado completo se todos os seus fragmentos têm o
    mesmo hash e a quantidade bate com a registrada: assim uma indexação
    interrompida no meio é refeita na próxima execução.
    """
    dados = colecao.get(include=["metadatas"])
    docs: dict[str, dict] = {}
    for meta in dados["metadatas"] or []:
        info = docs.setdefault(meta["fonte"], {"hashes": set(), "n": 0,
                                               "esperado": meta.get("n_fragmentos", -1)})
        info["hashes"].add(meta.get("hash_arquivo", ""))
        info["n"] += 1
    return docs


def _metadados_fragmento(doc, fragmento, indice: int, hash_doc: str) -> dict:
    """Metadados guardados com cada fragmento (rastreabilidade, RNF03).

    O ChromaDB não aceita None: campos vazios são omitidos.
    """
    meta = {
        "fonte": doc.nome,
        "documento": doc.titulo,
        "indice": indice,
        "n_fragmentos": len(doc.fragmentos),
        "pagina": fragmento.pagina_inicio,          # mantido por compatibilidade
        "pagina_fim": fragmento.pagina_fim,
        "localizacao": fragmento.localizacao,
        "secao": fragmento.secao_nome,
        "n_tokens": fragmento.n_tokens,
        "sobreposicao_chars": fragmento.sobreposicao_chars,
        "separador_anterior": fragmento.separador_anterior,
        "hash_arquivo": hash_doc,
    }
    if fragmento.artigo_inicio is not None:
        meta["artigo_inicio"] = fragmento.artigo_inicio
        meta["artigo_fim"] = fragmento.artigo_fim
    return meta


def escrever_relatorio(doc, parametros: dict, pasta: Path, titulo_exibido: str | None = None) -> Path:
    """Relatório legível do que foi indexado: diagnósticos e todos os fragmentos."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{Path(doc.nome).stem}.txt"
    tokens = [f.n_tokens for f in doc.fragmentos] or [0]
    linhas = [
        f"Relatório de indexação: {doc.nome}",
        f"Gerado em: {datetime.now():%d/%m/%Y %H:%M}",
        f"Título detectado: {doc.titulo}",
        "Título no chat: " + (titulo_exibido or f"o detectado (o arquivo não está em {config.ARQUIVO_TITULOS.name})"),
        f"Páginas: {doc.n_paginas}"
        + (f" (sem texto: {', '.join(map(str, doc.paginas_sem_texto))})" if doc.paginas_sem_texto else ""),
    ]
    if doc.paginas_ocr:
        linhas.append(f"Texto de OCR (PDF digitalizado) em {len(doc.paginas_ocr)} página(s): erros de "
                      "reconhecimento podem ter ficado; confira no PDF os trechos importantes.")
    linhas += [
        f"Modelo de embeddings: {parametros['modelo_embeddings']} "
        f"(janela de {parametros['janela_modelo']} tokens)",
        f"Limite por fragmento: {parametros['limite_fragmento_tokens']} tokens; "
        f"sobreposição: até {parametros['sobreposicao_tokens']} tokens",
        "",
        "Linhas removidas como cabeçalho/rodapé:",
    ]
    numeros = [l for l in doc.linhas_removidas if l.strip("-\N{EN DASH}\N{EM DASH} ").isdigit()]
    outras = [l for l in doc.linhas_removidas if l not in numeros]
    linhas += [f"  - {l}" for l in outras] or ["  (nenhuma)"]
    if numeros:
        linhas.append(f"  - números de página ({len(numeros)} ocorrências)")
    if doc.linhas_sumario:
        linhas.append(f"Linhas de sumário ou de lista de figuras/tabelas removidas: {doc.linhas_sumario}")
    linhas += ["", f"Corpo de letra do texto principal: {doc.corpo_texto:g} pt; "
               f"tabelas lidas: {doc.n_tabelas}; hifenização silábica: "
               f"{'sim' if doc.hifenizacao_silabica else 'não'}"]
    if doc.paginas_ilegiveis:
        linhas.append(f"Páginas com muitos caracteres ilegíveis (fonte sem mapeamento Unicode): "
                      f"{', '.join(map(str, doc.paginas_ilegiveis))}")
    linhas += ["", f"Texto riscado descartado (redação revogada): {len(doc.trechos_riscados)} trecho(s)"]
    for d in doc.trechos_riscados:
        linhas.append(f"  - p. {d['pagina']}: {d['texto']}")
    linhas += ["", f"Redações alteradas descartadas pela anotação: {len(doc.redacoes_descartadas)}"]
    for n, d in enumerate(doc.redacoes_descartadas, 1):
        linhas += [f"  {n}. p. {d['pagina_inicio']}: {d['anotacao']}",
                   f"     Texto descartado: {d['texto']}"]
    linhas += ["", f"Dispositivos descartados por nota de revogação em bloco: {len(doc.revogados_em_bloco)}"]
    for d in doc.revogados_em_bloco:
        linhas.append(f"  - p. {d['pagina']}: {d['texto']}")
    linhas += ["", "Anotações de alteração sem nova redação do mesmo dispositivo logo depois "
               f"(em geral é a própria redação vigente; conferir): {len(doc.anotacoes_nao_resolvidas)}"]
    for d in doc.anotacoes_nao_resolvidas:
        linhas.append(f"  - p. {d['pagina']}: {d['anotacao']} | {d['texto']}")
    linhas += ["",
               f"Fragmentos: {len(doc.fragmentos)} (tokens: mín. {min(tokens)}, "
               f"média {statistics.mean(tokens):.0f}, máx. {max(tokens)})",
               "Formato: #índice | páginas | artigos | tokens | localização. "
               "A primeira linha de cada fragmento é o cabeçalho de contexto, quando houver.",
               ""]
    for i, f in enumerate(doc.fragmentos):
        paginas = f"p. {f.pagina_inicio}" + (f"-{f.pagina_fim}" if f.pagina_fim != f.pagina_inicio else "")
        artigos = "-" if f.artigo_inicio is None else (
            f"Art. {f.artigo_inicio}" + (f" a {f.artigo_fim}" if f.artigo_fim != f.artigo_inicio else ""))
        linhas += [f"#{i:04d} | {paginas} | {artigos} | {f.n_tokens} tokens | {f.localizacao}",
                   f.texto_embedding, ""]
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def ingerir(completo: bool = False, pasta: Path | None = None, modelo: ModeloEmbeddings | None = None,
            cliente=None, pasta_relatorios: Path | None = None, saida=print) -> ResumoIndexacao:
    """Sincroniza a base vetorial com os PDFs da pasta de documentos."""
    pasta = Path(pasta or config.DOCS_DIR)
    pasta_relatorios = Path(pasta_relatorios or config.RELATORIOS_DIR)
    resumo = ResumoIndexacao()
    pasta.mkdir(parents=True, exist_ok=True)
    pdfs = listar_pdfs(pasta)
    if not pdfs:
        saida(f"Nenhum PDF encontrado em {pasta}.")
        saida("Coloque os documentos institucionais nessa pasta e rode de novo.")
        return resumo

    modelo = modelo or ModeloEmbeddings()
    saida(f"Carregando o modelo de embeddings ({modelo.nome})...")
    parametros = parametros_indice(modelo)
    if modelo.limite_conteudo < config.CHUNK_MAX_TOKENS:
        saida(f"  O modelo lê no máximo {modelo.janela_tokens} tokens por texto; os fragmentos serão "
              f"limitados a {parametros['limite_fragmento_tokens']} tokens para não haver truncamento.")

    cliente = cliente or abrir_cliente()
    if remover_colecao(cliente, COLECAO_LEGADA):
        saida(f"Coleção da versão anterior ('{COLECAO_LEGADA}') removida: a base será refeita.")

    nome = nome_colecao(modelo.nome)
    colecao = obter_colecao(cliente, nome)
    assinatura_atual = assinatura(parametros)
    if colecao is not None and (completo or (colecao.metadata or {}).get("assinatura") != assinatura_atual):
        motivo = "pedido de reconstrução completa" if completo else "parâmetros de indexação mudaram"
        saida(f"Reconstruindo a base do zero ({motivo}).")
        remover_colecao(cliente, nome)
        colecao = None
        resumo.base_reconstruida = True
    if colecao is None:
        colecao = criar_colecao(cliente, nome, {**_parametros_para_metadados(parametros),
                                                "assinatura": assinatura_atual})

    existentes = documentos_indexados(colecao)
    nomes_na_pasta = {p.name for p in pdfs}
    for fonte in sorted(set(existentes) - nomes_na_pasta):
        colecao.delete(where={"fonte": fonte})
        resumo.removidos.append(fonte)
        saida(f"Removido da base (não está mais na pasta): {fonte}")

    titulos = carregar_titulos()
    lote = min(1000, getattr(cliente, "get_max_batch_size", lambda: 1000)())
    for pdf in pdfs:
        hash_doc = hash_arquivo(pdf)
        info = existentes.get(pdf.name)
        if info and info["hashes"] == {hash_doc} and info["n"] == info["esperado"]:
            resumo.inalterados.append(pdf.name)
            saida(f"Sem alterações: {pdf.name}")
            continue

        saida(f"Processando: {pdf.name}")
        inicio = time.perf_counter()
        try:
            doc = processamento.processar_pdf(pdf, modelo.contar_tokens, opcoes_processamento(parametros))
        except processamento.ErroExtracao as erro:
            resumo.com_erro.append(pdf.name)
            saida(f"  ERRO: {erro}. O arquivo foi ignorado.")
            continue

        if doc.paginas_sem_texto:
            saida(f"  Aviso: {len(doc.paginas_sem_texto)} página(s) sem texto extraível "
                  f"({', '.join(map(str, doc.paginas_sem_texto[:10]))}"
                  f"{'...' if len(doc.paginas_sem_texto) > 10 else ''}). "
                  "Se o PDF for digitalizado (imagem), passe-o antes por um programa de OCR "
                  "(por exemplo, o OCRmyPDF) para criar a camada de texto.")
        if doc.paginas_ocr:
            saida(f"  Aviso: texto de OCR em {len(doc.paginas_ocr)} página(s) (PDF digitalizado); erros de "
                  "reconhecimento podem ter ficado. Confira o relatório.")
        if doc.paginas_ilegiveis:
            saida(f"  Aviso: páginas com texto ilegível (fonte sem mapeamento Unicode): "
                  f"{', '.join(map(str, doc.paginas_ilegiveis[:10]))}. Confira o relatório.")
        colecao.delete(where={"fonte": pdf.name})   # nada de fragmentos órfãos (RF01)
        if not doc.fragmentos:
            resumo.sem_texto.append(pdf.name)
            saida("  Nenhum texto aproveitável: o documento não foi indexado.")
            continue

        vetores = modelo.codificar_documentos([f.texto_embedding for f in doc.fragmentos],
                                              mostrar_progresso=len(doc.fragmentos) > 200)
        ids = [id_fragmento(doc.nome, i) for i in range(len(doc.fragmentos))]
        metadados = [_metadados_fragmento(doc, f, i, hash_doc) for i, f in enumerate(doc.fragmentos)]
        textos = [f.texto for f in doc.fragmentos]
        for j in range(0, len(ids), lote):
            colecao.add(ids=ids[j:j + lote], embeddings=vetores[j:j + lote],
                        documents=textos[j:j + lote], metadatas=metadados[j:j + lote])

        relatorio = escrever_relatorio(doc, parametros, pasta_relatorios, titulos.get(pdf.name))
        tokens = [f.n_tokens for f in doc.fragmentos]
        resumo.indexados.append(pdf.name)
        saida(f"  -> {len(doc.fragmentos)} fragmentos ({min(tokens)} a {max(tokens)} tokens), "
              f"{doc.n_paginas} páginas, em {time.perf_counter() - inicio:.1f} s")
        if doc.linhas_removidas:
            exemplo = next((l for l in doc.linhas_removidas if not l.strip("-\N{EN DASH}\N{EM DASH} ").isdigit()), None)
            if exemplo:
                saida(f"  -> cabeçalho/rodapé removido: \"{exemplo}\"")
        if doc.trechos_riscados:
            saida(f"  -> {len(doc.trechos_riscados)} trecho(s) de texto riscado (redação revogada) "
                  "descartado(s) (ver relatório)")
        if doc.redacoes_descartadas:
            saida(f"  -> {len(doc.redacoes_descartadas)} redação(ões) alterada(s) descartada(s) pela anotação "
                  "(ver relatório)")
        if doc.n_tabelas:
            saida(f"  -> {doc.n_tabelas} tabela(s) lida(s) linha a linha")
        if doc.revogados_em_bloco:
            saida(f"  -> {len(doc.revogados_em_bloco)} resto(s) de dispositivo revogado em bloco descartado(s) "
                  "(ver relatório)")
        if doc.anotacoes_nao_resolvidas:
            saida(f"  -> {len(doc.anotacoes_nao_resolvidas)} anotação(ões) de alteração sem nova redação logo "
                  "depois (em geral é a redação vigente; confira no relatório)")
        saida(f"  -> relatório: {relatorio}")

    colecao.modify(metadata={**_parametros_para_metadados(parametros), "assinatura": assinatura_atual,
                             "atualizado_em": datetime.now().isoformat(timespec="seconds")})
    resumo.total_fragmentos = colecao.count()
    sem_titulo = [p.name for p in pdfs if p.name not in titulos]
    if sem_titulo:
        saida("")
        saida(f"Aviso: {len(sem_titulo)} PDF(s) sem título em {config.ARQUIVO_TITULOS} "
              "(o chat usa o título extraído do PDF, que pode não dizer o assunto nem a versão):")
        for nome_pdf in sem_titulo[:15]:
            saida(f"  - {nome_pdf}")
        if len(sem_titulo) > 15:
            saida(f"  ... e mais {len(sem_titulo) - 15}")
    saida("")
    saida(f"Concluído. Base com {resumo.total_fragmentos} fragmentos "
          f"({len(resumo.indexados)} documento(s) indexado(s), {len(resumo.inalterados)} sem alteração, "
          f"{len(resumo.removidos)} removido(s), {len(resumo.com_erro)} com erro).")
    saida(f"Base vetorial: {config.CHROMA_DIR} (coleção '{nome}')")
    return resumo


def _parametros_para_metadados(parametros: dict) -> dict:
    """O ChromaDB guarda só str/int/float/bool; strings vazias viram '-'."""
    return {k: (v if not isinstance(v, str) or v else "-") for k, v in parametros.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indexa os PDFs de data/documentos na base vetorial.")
    parser.add_argument("--completo", action="store_true", help="reconstrói a base inteira")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        ingerir(completo=args.completo)
    except ErroEmbeddings as erro:
        print(f"\nERRO: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
