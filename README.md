# Chatbot acadêmico com RAG local

Protótipo de chatbot que responde a perguntas sobre documentos institucionais da UNIPAMPA (resoluções, instruções normativas, projetos pedagógicos de curso, calendário e manuais) com Geração Aumentada por Recuperação (RAG). Tudo roda no próprio computador: os modelos de linguagem, pelo [Ollama](https://ollama.com), e o modelo de *embeddings*, pelo sentence-transformers. Nenhuma pergunta ou documento é enviado a serviços externos. É um protótipo acadêmico, e não um serviço oficial da universidade.

Este repositório acompanha o Trabalho de Conclusão de Curso *Proposta e avaliação de um sistema de chatbot com recuperação aumentada (RAG) para acesso à informação institucional universitária*, de Lucas Zerbin Gallert (Engenharia de Computação, UNIPAMPA, 2026). Ele traz o código, os testes, os documentos indexados, as perguntas e os resultados das avaliações relatadas na monografia.

## Como funciona

1. **Indexação.** Os PDFs de `data/documentos` são lidos com a posição e a fonte de cada linha. O programa remove cabeçalhos, rodapés, sumários e texto revogado, divide o conteúdo pela estrutura das normas (artigos, parágrafos, incisos, itens e linhas de tabela) e respeita o limite de entrada do modelo de *embeddings*. Os vetores ficam numa base ChromaDB local.
2. **Consulta.** A pergunta passa por uma busca híbrida, que junta a busca por sentido (densa) e a busca por palavras (BM25) pela fusão RRF. Os seis fragmentos mais bem colocados que passam do limiar de similaridade vão para o modelo de linguagem, com a instrução de responder só com base neles e de citar os trechos usados, como [1] ou [2][3]. Sem trecho relevante, o chatbot se abstém. A lista de fontes exibida depois da resposta é montada pelo programa, com documento, páginas e artigos.
3. **Avaliação.** Cada pergunta é buscada uma vez, e os três modelos comparados respondem com os mesmos trechos, só no processador. As respostas são classificadas (resposta, resposta mista, abstenção), recebem notas de dois LLMs avaliadores pelo RAGAS e podem ser comparadas com notas dadas por uma pessoa, num estudo piloto.

Modelos comparados: Llama 3.1 8B (`llama3.1:8b`, padrão do chat), Qwen 3.8 27B (`qwen3.8:27b`) e Phi-4-mini 3.8B (`phi4-mini`). LLMs avaliadores: Ministral 3 8B (`ministral-3:8b`) e Gemma 4 E4B (`gemma4:e4b-it-qat`). Todos os parâmetros estão em `config.py`.

## Requisitos

- Windows 10 ou 11 para os atalhos `.bat`. Em Linux ou macOS, use os comandos `python` equivalentes (veja abaixo).
- Python 3.10 ou mais novo (testado com o 3.13).
- [Ollama](https://ollama.com) com os modelos:

  ```
  ollama pull llama3.1:8b
  ollama pull qwen3.8:27b
  ollama pull phi4-mini
  ```

  Para a avaliação, também os LLMs avaliadores:

  ```
  ollama pull ministral-3:8b
  ollama pull gemma4:e4b-it-qat
  ```

  O Qwen 3.8 27B ocupa cerca de 18 GB e precisa de cerca de 20 GB de memória. As versões exatas usadas nas medições (o *digest* de cada modelo) estão no `configuracao.json` de cada rodada; uma versão mais nova de um modelo pode dar respostas diferentes.

## Instalação

Na pasta do projeto:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Em Linux ou macOS, a segunda linha é `source .venv/bin/activate`. Na primeira indexação, o modelo de *embeddings* é baixado do Hugging Face uma única vez.

Para a avaliação com o RAGAS, rode também `instalar-avaliacao.bat` (ou `python instalar_avaliacao.py`), uma vez. Não instale o `requirements-avaliacao.txt` direto pelo `pip`: sozinho, ele troca uma dependência do chatbot (o `huggingface-hub`) por uma versão incompatível, e a indexação e o chat param. O instalador mantém os pacotes do chatbot nas versões instaladas e confere, no fim, se o chatbot e o RAGAS funcionam.

PDFs digitalizados, só com imagem, precisam de OCR antes de entrar em `data/documentos`, por exemplo com o [OCRmyPDF](https://ocrmypdf.readthedocs.io): `ocrmypdf -l por entrada.pdf saida.pdf`.

## Uso do chat

1. `indexar.bat`: indexa os PDFs de `data/documentos`. Só os arquivos novos ou alterados são processados; `indexar.bat --completo` refaz a base inteira. Para acrescentar um documento, coloque o PDF na pasta; o título que ele recebe no prompt pode ser definido em `data/titulos_documentos.json`.
2. `iniciar-chat.bat`: abre o chat no terminal, com o Llama 3.1 8B. Para outro modelo, no terminal: `iniciar-chat.bat qwen3.8:27b`.

No chat, `/fontes` mostra o texto dos trechos usados na última resposta, `/ajuda` mostra os comandos e `sair` encerra. Cada interação é gravada em `data/registros`, que não vai para o repositório.

## Avaliação

Os arquivos abaixo seguem a ordem do trabalho. Cada um aceita opções escritas depois do nome, no terminal, e mostra as principais ao terminar.

| Arquivo | O que faz |
|-|-|
| `verificar-modelos.bat` | Confere se os modelos estão instalados, se os comparados rodam só no processador, se os avaliadores usam a placa de vídeo e se o raciocínio dos modelos que pensam está desligado. |
| `validar-perguntas.bat` | Confere o arquivo de perguntas: colunas, repetições e respostas de referência. |
| `avaliar-busca.bat` | Compara as buscas densa, BM25 e híbrida (acerto@k, contexto@k, MRR e teste de McNemar). Não usa modelos de linguagem. |
| `gerar-respostas.bat` | Cria uma rodada em `avaliacao/rodadas`: busca os trechos de cada pergunta uma vez e grava a resposta de cada modelo. `--continuar` retoma uma rodada interrompida. |
| `avaliar-respostas.bat` | Classifica as respostas e grava a tabela de confiabilidade e o `revisar.csv`, com os casos para conferir à mão. A decisão escrita na coluna de conferência passa a valer na tabela. |
| `instalar-avaliacao.bat` | Instala o RAGAS, uma vez. |
| `avaliar-ragas.bat` | Notas dos dois LLMs avaliadores para correção, completude, fidelidade e cobertura dos trechos, com a concordância entre eles e a comparação dos modelos pelo teste de Wilcoxon. |
| `preparar-piloto.bat` | Estudo piloto, passo 1: sorteia respostas, sem o nome do modelo, e grava o caderno de leitura (`piloto_caderno.html`) e a planilha das notas (`piloto_notas.csv`). |
| `juizes-em-portugues.bat` | Estudo piloto, passo 2: notas dos LLMs avaliadores com os exemplos dos prompts do RAGAS traduzidos para o português, só nas respostas sorteadas. |
| `avaliar-piloto.bat` | Estudo piloto, passo 3: compara as notas da planilha com as dos avaliadores (kappa ponderado, correlação de Spearman e concordância exata). |

No código, os LLMs avaliadores aparecem com o nome de juízes: `config.JUIZES`, a opção `--juiz` e as pastas `juiz_<modelo>`.

Comandos equivalentes, para qualquer sistema: `python ingestao.py`, `python consulta.py [modelo]`, `python -m unittest discover -s testes -v`, `python perguntas.py [arquivo]`, `python verificar_modelos.py`, `python avaliar_recuperacao.py --comparar-buscas`, `python gerar_respostas.py`, `python avaliar_respostas.py`, `python avaliar_ragas.py`, `python piloto.py preparar`, `python avaliar_ragas.py --portugues --so-piloto` e `python piloto.py comparar`.

### Arquivo de perguntas

A planilha segue `avaliacao/modelo_perguntas.csv`, com uma pergunta por linha. As colunas `pergunta` e `resposta_correta` são obrigatórias; quando os documentos não respondem à pergunta, a resposta pode ficar vazia e a coluna `sem_resposta` recebe "sim". As colunas `fonte` (nome do PDF), `artigos`, `paginas`, `id` e `observacao` são opcionais. Salve como CSV, com vírgula ou ponto e vírgula, e confira com `validar-perguntas.bat`. O arquivo usado nas rodadas é definido em `ARQUIVO_PERGUNTAS`, no `config.py`, ou pela opção `--arquivo`.

## Dados incluídos

- `data/documentos`: os 60 PDFs indexados, documentos públicos da UNIPAMPA, incluídos para que as medições possam ser reproduzidas. `data/titulos_documentos.json` guarda o título que cada um recebe no prompt.
- `avaliacao/perguntas_recuperacao.json`: 61 perguntas de desenvolvimento (53 com resposta nos documentos e 8 sem), usadas na calibração da busca e na rodada de teste.
- `avaliacao/perguntas_reais.csv`: 19 perguntas reais de estudantes, com as respostas de referência, usadas na medição final.
- `avaliacao/resultados`: as medições da busca usadas na calibração, com a comparação das segmentações e das buscas com quatro e com seis fragmentos.
- `avaliacao/rodadas/2026-11-03_1112_perguntas_recuperacao`: rodada de teste, com as notas dos avaliadores com os prompts em inglês e em português e o estudo piloto.
- `avaliacao/rodadas/2026-11-22_0520_perguntas_reais`: medição final.

Cada rodada traz `configuracao.json` (parâmetros, prompt, modelos e computador usados), `contextos.json` (os trechos recuperados, iguais para os três modelos), `respostas_<modelo>.jsonl`, a tabela de confiabilidade (`confiabilidade.md`, `.csv` e `.json`), o `revisar.csv` com a conferência manual, as notas dos avaliadores e a pasta `piloto`.

As medições foram feitas com este código. Depois delas, mudaram apenas os textos exibidos pelos arquivos `.bat` e pelo chat e este README; prompts, parâmetros e lógica continuam os mesmos.

## Arquivos do código

| Arquivo | Papel |
|-|-|
| `config.py` | Parâmetros: busca, modelos, avaliadores, perguntas, segmentação e limiar. |
| `processamento.py` | Leitura e limpeza dos PDFs e divisão em fragmentos. |
| `vetorial.py` | Modelo de *embeddings* e acesso ao ChromaDB. |
| `ingestao.py` | Indexação: mantém a base igual à pasta de documentos. |
| `recuperacao.py` | Buscas densa, BM25 e híbrida, limiar e montagem do contexto. |
| `modelos.py` | Opções enviadas ao Ollama, iguais para todos os modelos. |
| `consulta.py` | Geração da resposta (prompt, citações, abstenção e registro) e o chat de terminal. |
| `perguntas.py` | Leitura e conferência do arquivo de perguntas. |
| `avaliar_recuperacao.py` | Avaliação da busca. |
| `verificar_modelos.py` | Conferência dos modelos no Ollama. |
| `gerar_respostas.py` | Rodada de avaliação, com os trechos congelados. |
| `avaliar_respostas.py` | Classificação das respostas e tabela de confiabilidade. |
| `avaliar_ragas.py` | Notas dos LLMs avaliadores pelo RAGAS. |
| `prompts_em_portugues.py` | Exemplos dos prompts do RAGAS traduzidos para o português. |
| `piloto.py` | Estudo piloto: sorteio, caderno de leitura, planilha e concordância. |
| `estatistica.py` | Testes de McNemar e de Wilcoxon, kappa ponderado, correlação de Spearman e intervalos por *bootstrap*. |
| `instalar_avaliacao.py` | Instalação do RAGAS sem mudar os pacotes do chatbot. |
| `testes/` | Testes automatizados (unittest). |

## Testes

`testar.bat`, ou `python -m unittest discover -s testes -v`. Os testes não precisam do Ollama nem do modelo de *embeddings*; os que dependem do RAGAS são pulados quando ele não está instalado.

## Uso de inteligência artificial

O Claude (Anthropic) foi usado como assistente de programação no desenvolvimento conduzido pelo autor, com geração e revisão de código, inclusive dos testes automatizados, e identificação e correção de erros. Os requisitos e as decisões de projeto são do autor, que revisou, executou e testou o código. A declaração completa sobre o uso de inteligência artificial está na monografia.
