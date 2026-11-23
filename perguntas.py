"""Conjunto de perguntas das avaliações: leitura, conferência e assinatura.

Todos os programas de avaliação leem as perguntas por aqui, então trocar o
conjunto é trocar o arquivo indicado em config.ARQUIVO_PERGUNTAS (passo a
passo em avaliacao/COMO_USAR_PERGUNTAS_REAIS.md). O arquivo pode ser:

* uma planilha CSV, salva pelo Excel ou pelo Google Planilhas, com uma
  pergunta por linha e as colunas da planilha modelo
  (avaliacao/modelo_perguntas.csv);
* um JSON no formato de avaliacao/perguntas_recuperacao.json.

    python perguntas.py                       # confere o arquivo em uso
    python perguntas.py avaliacao\\outro.csv   # confere outro arquivo

Colunas da planilha (o nome pode ter maiúsculas e acentos):

* pergunta (obrigatória): como a pessoa escreveu, com erros de digitação e
  tudo, porque é isso que o chatbot vai enfrentar no uso real;
* resposta_correta: o que os documentos da base dizem; obrigatória, menos
  quando sem_resposta é "sim";
* sem_resposta: "sim" quando os documentos da base não respondem (o certo,
  então, é o chatbot se abster); vazio vale "não";
* fonte: nome do PDF onde está a resposta (opcional);
* artigos e paginas: onde, dentro da fonte (opcionais; "37; 38" e "406-410");
* id: identificador (opcional; vazio, o programa numera P001, P002...);
* observacao: anotações suas; o programa ignora.

Cada pergunta vira um dicionário com id, pergunta, resposta_correta e
sem_resposta, mais os campos de local da resposta que existirem (fonte,
artigos, paginas, trecho ou alternativas, os critérios do
avaliar_recuperacao.py). A assinatura é um código curto calculado do conteúdo
do arquivo: muda se qualquer caractere mudar, e todo resultado a registra
para nunca haver dúvida sobre que perguntas o produziram.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import config

CAMPOS_LOCAL = ("fonte", "artigos", "paginas", "trecho", "alternativas")

# Nome normalizado da coluna -> campo. Aceita variações comuns de planilhas e
# formulários ("Resposta correta", "Sem resposta?", "Documento").
_COLUNAS = {
    "id": "id", "identificador": "id",
    "pergunta": "pergunta", "perguntas": "pergunta", "questao": "pergunta",
    "resposta_correta": "resposta_correta", "resposta": "resposta_correta",
    "resposta_certa": "resposta_correta", "gabarito": "resposta_correta",
    "sem_resposta": "sem_resposta", "sem_resposta_nos_documentos": "sem_resposta",
    "fonte": "fonte", "documento": "fonte", "pdf": "fonte",
    "artigos": "artigos", "artigo": "artigos",
    "paginas": "paginas", "pagina": "paginas",
    "trecho": "trecho",
    "observacao": "observacao", "observacoes": "observacao", "obs": "observacao",
}
_VERDADEIRO = {"sim", "s", "x", "1", "true", "verdadeiro", "yes", "y"}
_FALSO = {"", "nao", "n", "0", "false", "falso", "no"}


class ErroPerguntas(Exception):
    """O arquivo de perguntas não pode ser lido (não existe, formato errado...)."""


@dataclass
class Problema:
    gravidade: str          # "erro" (impede o uso do arquivo) ou "aviso"
    mensagem: str
    linha: int | None = None
    id: str | None = None

    def __str__(self) -> str:
        onde = [f"linha {self.linha}" if self.linha else "", self.id or ""]
        prefixo = ", ".join(x for x in onde if x)
        return f"{self.gravidade.upper()}: " + (f"{prefixo}: " if prefixo else "") + self.mensagem


@dataclass
class ConjuntoPerguntas:
    arquivo: Path
    assinatura: str
    perguntas: list[dict]
    problemas: list[Problema] = field(default_factory=list)
    descricao: str = ""
    codificacao: str = ""

    @property
    def nome(self) -> str:
        """Nome curto do conjunto (o do arquivo, sem extensão), usado nas pastas e nos resultados."""
        return self.arquivo.stem

    @property
    def erros(self) -> list[Problema]:
        return [p for p in self.problemas if p.gravidade == "erro"]

    @property
    def avisos(self) -> list[Problema]:
        return [p for p in self.problemas if p.gravidade == "aviso"]

    def resumo(self) -> dict:
        respondiveis = [p for p in self.perguntas if not p["sem_resposta"]]
        return {
            "total": len(self.perguntas),
            "com_resposta_correta": sum(bool(p.get("resposta_correta")) for p in respondiveis),
            "sem_resposta_correta": sum(not p.get("resposta_correta") for p in respondiveis),
            "sem_resposta_nos_documentos": len(self.perguntas) - len(respondiveis),
            "com_local_da_resposta": sum(tem_local(p) for p in respondiveis),
            "so_documento": sum(tem_local(p) and so_documento(p) for p in respondiveis),
        }

    def identificacao(self) -> dict:
        """O que todo resultado grava sobre as perguntas usadas."""
        return {"arquivo": self.arquivo.name, "assinatura": self.assinatura, "total": len(self.perguntas)}


# Leitura
def assinatura_arquivo(caminho: Path) -> str:
    """Código curto do conteúdo (12 primeiros dígitos do SHA-256 dos bytes)."""
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()[:12]


def _normalizar_nome(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _texto_comparavel(texto: str) -> str:
    """Para achar perguntas repetidas: sem acentos, maiúsculas, pontuação e espaços extras."""
    sem_acento = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento).split())


def _decodificar(dados: bytes) -> tuple[str, str]:
    """UTF-8 (com ou sem BOM, o "CSV UTF-8" do Excel e o do Google Planilhas) ou,
    se não for, Windows-1252 (o "CSV" comum do Excel em português)."""
    try:
        return dados.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace"), "Windows-1252"


def _separador(texto: str) -> str:
    """Ponto e vírgula (Excel em português), vírgula ou tabulação, pelo cabeçalho."""
    cabecalho = next((linha for linha in texto.splitlines() if linha.strip()), "")
    contagem = {sep: cabecalho.count(sep) for sep in (";", ",", "\t")}
    melhor = max(contagem, key=contagem.get)
    return melhor if contagem[melhor] else ";"


def _numeros(texto: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", texto)]


def _sem_letras_estranhas(texto: str) -> bool:
    """Só números, separadores e as palavras "a" e "e" ("37 a 40", "37 e 38").
    Letras a mais costumam ser o Excel trocando "1-3" por uma data ("01/mar")."""
    return not re.search(r"[^\W\d_]", re.sub(r"\b[aAeE]\b", " ", texto))


def _artigos(texto: str) -> list[int] | None:
    """"37", "37; 38", "37 e 38", "37 a 40" ou "37-40" (intervalo: 37, 38, 39 e 40)."""
    if not _sem_letras_estranhas(texto):
        return None
    artigos: list[int] = []
    for parte in re.split(r"[;,]|\be\b", texto):
        numeros = _numeros(parte)
        if len(numeros) == 2 and re.search(r"-|–|\ba\b", parte) and numeros[0] <= numeros[1] <= numeros[0] + 200:
            artigos += list(range(numeros[0], numeros[1] + 1))
        else:
            artigos += numeros
    return artigos or None


_MOJIBAKE = re.compile("Ã[\u0080-\u00bf]")


def _ler_csv(caminho: Path, problemas: list[Problema]) -> tuple[list[dict], str]:
    texto, codificacao = _decodificar(caminho.read_bytes())
    if codificacao == "Windows-1252" and _MOJIBAKE.search(texto):
        problemas.append(Problema("aviso", "o arquivo mistura duas codificações de acentos (parte das linhas deve "
                                           "aparecer como \"faÃ§o\"): salve de novo como \"CSV UTF-8\""))
    leitor = csv.reader(io.StringIO(texto), delimiter=_separador(texto))
    linhas = list(leitor)
    if not linhas:
        raise ErroPerguntas(f"{caminho.name} está vazio.")
    cabecalho = [_normalizar_nome(c) for c in linhas[0]]
    campos = [_COLUNAS.get(c) for c in cabecalho]
    if "pergunta" not in campos:
        raise ErroPerguntas(f"{caminho.name} não tem a coluna \"pergunta\" na primeira linha "
                            f"(colunas encontradas: {', '.join(linhas[0]) or 'nenhuma'}). "
                            "Use a planilha modelo avaliacao/modelo_perguntas.csv.")
    ignoradas = [original for original, campo in zip(linhas[0], campos) if campo is None and original.strip()]
    if ignoradas:
        problemas.append(Problema("aviso", f"coluna(s) ignorada(s): {', '.join(ignoradas)}"))
    itens = []
    for numero, valores in enumerate(linhas[1:], start=2):     # linha 1 é o cabeçalho, como no Excel
        if not any(v.strip() for v in valores):
            continue
        bruto = {}
        for campo, valor in zip(campos, valores):
            if campo and valor.strip() and campo not in bruto:
                bruto[campo] = valor.strip()
        item = {"linha": numero}
        if "id" in bruto:
            item["id"] = bruto["id"]
        item["pergunta"] = bruto.get("pergunta", "")
        item["resposta_correta"] = bruto.get("resposta_correta", "")
        marca = _normalizar_nome(bruto.get("sem_resposta", ""))
        if marca in _VERDADEIRO:
            item["sem_resposta"] = True
        elif marca in _FALSO:
            item["sem_resposta"] = False
        else:
            item["sem_resposta"] = False
            problemas.append(Problema("erro", f"sem_resposta = \"{bruto['sem_resposta']}\": use \"sim\" "
                                              "ou deixe vazio", numero))
        if "fonte" in bruto:
            item["fonte"] = bruto["fonte"]
        if "artigos" in bruto:
            artigos = _artigos(bruto["artigos"])
            if artigos:
                item["artigos"] = artigos
            else:
                problemas.append(Problema("erro", f"artigos = \"{bruto['artigos']}\": use números, como \"37\", "
                                                  "\"37; 38\" ou \"37 a 40\" (formate a coluna como Texto no Excel)",
                                          numero))
        if "paginas" in bruto:
            paginas = _numeros(bruto["paginas"]) if _sem_letras_estranhas(bruto["paginas"]) else []
            if len(paginas) in (1, 2):
                item["paginas"] = [paginas[0], paginas[-1]]
            else:
                problemas.append(Problema("erro", f"paginas = \"{bruto['paginas']}\": use \"12\" ou \"406-410\" "
                                                  "(formate a coluna como Texto no Excel, que troca \"1-3\" por "
                                                  "uma data)", numero))
        if "trecho" in bruto:
            item["trecho"] = bruto["trecho"]
        if "observacao" in bruto:
            item["observacao"] = bruto["observacao"]
        itens.append(item)
    return itens, codificacao


def _ler_json(caminho: Path, problemas: list[Problema]) -> tuple[list[dict], str]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise ErroPerguntas(f"{caminho.name} não é um JSON válido: {erro}") from erro
    descricao = ""
    if isinstance(dados, dict):
        descricao = str(dados.get("descricao", ""))
        dados = dados.get("perguntas")
    if not isinstance(dados, list) or not all(isinstance(i, dict) for i in dados):
        raise ErroPerguntas(f"{caminho.name}: o JSON precisa ser uma lista de perguntas ou ter a "
                            "chave \"perguntas\" com essa lista.")
    itens = []
    for numero, original in enumerate(dados, start=1):
        item = dict(original)
        ident = str(item.get("id") or f"pergunta {numero}")
        pergunta = item.get("pergunta")
        if pergunta is not None and not isinstance(pergunta, str):
            problemas.append(Problema("erro", "a pergunta precisa ser um texto", None, ident))
        item["pergunta"] = pergunta.strip() if isinstance(pergunta, str) else ""
        item["resposta_correta"] = str(item.get("resposta_correta") or "").strip()
        marca = item.get("sem_resposta", False)
        if isinstance(marca, bool):
            item["sem_resposta"] = marca
        elif _normalizar_nome(str(marca)) in _VERDADEIRO:
            item["sem_resposta"] = True
        elif _normalizar_nome(str(marca)) in _FALSO:
            item["sem_resposta"] = False
        else:
            item["sem_resposta"] = False
            problemas.append(Problema("erro", f"sem_resposta = {marca!r}: use true, false, \"sim\" ou \"não\"",
                                      None, ident))
        for criterio in item.get("alternativas") or [item]:
            artigos = criterio.get("artigos")
            if artigos is not None and not (isinstance(artigos, list) and artigos
                                            and all(isinstance(a, int) for a in artigos)):
                problemas.append(Problema("erro", f"artigos = {artigos!r}: use uma lista de números, como [37, 38]",
                                          None, ident))
                criterio.pop("artigos")
            paginas = criterio.get("paginas")
            if paginas is not None and not (isinstance(paginas, list) and len(paginas) == 2
                                            and all(isinstance(x, int) for x in paginas)):
                problemas.append(Problema("erro", f"paginas = {paginas!r}: use [primeira, última]", None, ident))
                criterio.pop("paginas")
        itens.append(item)
    return itens, descricao


def documentos_disponiveis() -> list[str] | None:
    """Nomes dos PDFs de data/documentos (os que estão na base). None quando a
    pasta não existe ou está vazia: aí a coluna fonte não é conferida."""
    if config.DOCS_DIR.is_dir():
        nomes = sorted(p.name for p in config.DOCS_DIR.glob("*.pdf"))
        if nomes:
            return nomes
    return None


def _conferir_fonte(item: dict, chave_valor: dict, documentos: list[str], problemas: list[Problema]) -> None:
    fonte = chave_valor.get("fonte")
    if not fonte or fonte in documentos:
        return
    por_nome = {d.lower(): d for d in documentos}
    candidato = por_nome.get(fonte.lower()) or por_nome.get(fonte.lower() + ".pdf")
    linha, ident = item.get("linha"), item.get("id")
    if candidato:
        chave_valor["fonte"] = candidato
        problemas.append(Problema("aviso", f"fonte \"{fonte}\" lida como \"{candidato}\"", linha, ident))
        return
    parecido = difflib.get_close_matches(fonte, documentos, n=1, cutoff=0.4)
    dica = f" Você quis dizer \"{parecido[0]}\"?" if parecido else ""
    problemas.append(Problema("erro", f"fonte \"{fonte}\" não está entre os documentos da base.{dica}",
                              linha, ident))


def _conferir(itens: list[dict], problemas: list[Problema], documentos: list[str] | None) -> None:
    vistos_id: dict[str, int | None] = {}
    vistas: dict[str, str] = {}
    sem_id = [item for item in itens if not str(item.get("id") or "").strip()]
    if sem_id:
        problemas.append(Problema("aviso", f"{len(sem_id)} pergunta(s) sem id receberam P001, P002... pela "
                                           "ordem das linhas; se for mudar a ordem depois de uma rodada, "
                                           "preencha a coluna id"))
    for numero, item in enumerate(itens, start=1):
        linha = item.get("linha")
        if not str(item.get("id") or "").strip():
            item["id"] = f"P{numero:03d}"
        item["id"] = str(item["id"]).strip()
        ident = item["id"]
        if not item["pergunta"]:
            problemas.append(Problema("erro", "pergunta vazia", linha, ident))
        if ident in vistos_id:
            problemas.append(Problema("erro", "id repetido", linha, ident))
        vistos_id[ident] = linha
        comparavel = _texto_comparavel(item["pergunta"])
        if comparavel and comparavel in vistas:
            problemas.append(Problema("aviso", f"pergunta igual à de {vistas[comparavel]} (conta duas vezes "
                                               "na avaliação)", linha, ident))
        elif comparavel:
            vistas[comparavel] = ident
        if item["sem_resposta"]:
            if item["resposta_correta"]:
                problemas.append(Problema("aviso", "marcada como sem resposta, então a resposta correta "
                                                   "escrita é ignorada", linha, ident))
        elif not item["resposta_correta"]:
            problemas.append(Problema("aviso", "sem resposta correta: fica fora da avaliação das respostas",
                                      linha, ident))
        if str(item.get("observacao", "")).lower().startswith("exemplo"):
            problemas.append(Problema("aviso", "parece ser uma linha de exemplo da planilha modelo",
                                      linha, ident))
        for criterio in item.get("alternativas") or [item]:
            if "paginas" in criterio and (len(criterio["paginas"]) != 2
                                          or criterio["paginas"][0] > criterio["paginas"][1]):
                problemas.append(Problema("erro", f"paginas = {criterio['paginas']}: use [primeira, última]",
                                          linha, ident))
            if documentos:
                _conferir_fonte(item, criterio, documentos, problemas)


def carregar_perguntas(caminho: Path | str | None = None,
                       documentos: list[str] | None = None) -> ConjuntoPerguntas:
    """Lê e confere o conjunto de perguntas (por padrão, config.ARQUIVO_PERGUNTAS).

    Não para nos problemas por pergunta: eles ficam em `problemas` (erro ou
    aviso), e quem chama decide. Levanta ErroPerguntas só quando o arquivo
    inteiro não pode ser lido. `documentos`: nomes dos PDFs para conferir a
    coluna fonte (padrão: documentos_disponiveis()).
    """
    caminho = Path(caminho if caminho is not None else config.ARQUIVO_PERGUNTAS)
    if not caminho.is_absolute() and not caminho.exists():
        caminho = config.BASE_DIR / caminho
    if not caminho.is_file():
        raise ErroPerguntas(f"Arquivo de perguntas não encontrado: {caminho}")
    problemas: list[Problema] = []
    sufixo = caminho.suffix.lower()
    if sufixo == ".csv":
        itens, codificacao = _ler_csv(caminho, problemas)
        descricao = ""
    elif sufixo == ".json":
        itens, descricao = _ler_json(caminho, problemas)
        codificacao = "UTF-8"
    else:
        raise ErroPerguntas(f"{caminho.name}: use uma planilha .csv ou um arquivo .json.")
    if not itens:
        raise ErroPerguntas(f"{caminho.name} não tem nenhuma pergunta.")
    documentos = documentos if documentos is not None else documentos_disponiveis()
    if documentos is None and any(c.get("fonte") for i in itens for c in i.get("alternativas") or [i]):
        problemas.append(Problema("aviso", f"a coluna fonte não foi conferida: não há PDFs em {config.DOCS_DIR}"))
    _conferir(itens, problemas, documentos)
    return ConjuntoPerguntas(caminho, assinatura_arquivo(caminho), itens, problemas, descricao, codificacao)


# Uso pelos programas de avaliação
def tem_local(item: dict) -> bool:
    """A pergunta diz onde está a resposta (critério para medir a busca)?"""
    return any(item.get(c) for c in CAMPOS_LOCAL)


def so_documento(item: dict) -> bool:
    """O local da resposta é só o documento (sem artigo, página ou trecho)."""
    conjuntos = item.get("alternativas") or [item]
    return all(c.get("fonte") and not any(c.get(k) for k in ("artigos", "paginas", "trecho"))
               for c in conjuntos)


def para_busca(itens: list[dict]) -> tuple[list[dict], list[str]]:
    """Perguntas que entram na avaliação da busca: as sem resposta (para o
    limiar) e as respondíveis que dizem onde está a resposta. Devolve também
    os ids das respondíveis que ficam de fora por não terem esse local."""
    dentro = [i for i in itens if i["sem_resposta"] or tem_local(i)]
    fora = [i["id"] for i in itens if not i["sem_resposta"] and not tem_local(i)]
    return dentro, fora


# Conferência pela linha de comando (validar-perguntas.bat)
def agrupar_problemas(problemas: list[Problema]) -> list[str]:
    """Uma linha por problema; os de mesma mensagem viram uma linha só, com a
    lista de onde aparecem (53 perguntas sem resposta correta não ocupam 53 linhas)."""
    grupos: dict[tuple[str, str], list[Problema]] = {}
    for problema in problemas:
        grupos.setdefault((problema.gravidade, problema.mensagem), []).append(problema)
    linhas = []
    for (gravidade, mensagem), lista in grupos.items():
        if len(lista) == 1:
            linhas.append(str(lista[0]))
            continue
        onde = [f"linha {p.linha}" if p.linha else (p.id or "?") for p in lista]
        mostrados = ", ".join(onde[:20]) + (f" e mais {len(onde) - 20}" if len(onde) > 20 else "")
        linhas.append(f"{gravidade.upper()}: {mensagem} ({len(lista)} perguntas: {mostrados})")
    return linhas


def imprimir_conferencia(conjunto: ConjuntoPerguntas) -> None:
    r = conjunto.resumo()
    print(f"Arquivo: {conjunto.arquivo}")
    print(f"Assinatura do conteúdo: {conjunto.assinatura}"
          + (f" | codificação: {conjunto.codificacao}" if conjunto.codificacao else ""))
    if conjunto.descricao:
        print(f"Descrição: {conjunto.descricao[:300]}")
    print(f"\n{r['total']} perguntas:")
    print(f"  com resposta correta: {r['com_resposta_correta']}")
    print(f"  sem resposta nos documentos (o certo é o chatbot se abster): {r['sem_resposta_nos_documentos']}")
    print(f"  ainda sem resposta correta (ficam fora da avaliação das respostas): {r['sem_resposta_correta']}")
    print(f"  dizem onde está a resposta (entram na avaliação da busca): {r['com_local_da_resposta']}"
          + (f", {r['so_documento']} só pelo documento" if r["so_documento"] else ""))
    if not conjunto.problemas:
        print("\nNenhum problema encontrado.")
        return
    print(f"\n{len(conjunto.erros)} erro(s) e {len(conjunto.avisos)} aviso(s):")
    for linha in agrupar_problemas(conjunto.erros + conjunto.avisos):
        print(f"  {linha}")
    if conjunto.erros:
        print("\nCorrija os erros antes de rodar as avaliações. Os avisos não impedem o uso.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        conjunto = carregar_perguntas(argv[0] if argv else None)
    except ErroPerguntas as erro:
        print(f"ERRO: {erro}")
        return 1
    imprimir_conferencia(conjunto)
    return 1 if conjunto.erros else 0


if __name__ == "__main__":
    sys.exit(main())
