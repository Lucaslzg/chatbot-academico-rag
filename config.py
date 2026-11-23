"""Configurações centrais do chatbot acadêmico (RAG local com Ollama).

Todos os parâmetros de projeto ficam neste arquivo (requisito RNF05 da
monografia, Seção 5.3): para testar outro modelo, outro tamanho de fragmento
ou outro top-k, altera-se um único lugar, e o efeito observado nas métricas
pode ser atribuído a essa variação (Seção 2.2, variáveis independentes).

Cada bloco indica a seção da monografia que fundamenta o valor adotado.
Depois de mudar qualquer parâmetro da seção "Segmentação" ou o modelo de
embeddings, rode a indexação de novo (indexar.bat); o próprio programa
detecta a mudança e reconstrói a base.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Diretórios
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "documentos"           # PDFs institucionais (PPCs, normativas, editais)
CHROMA_DIR = DATA_DIR / "chroma_db"          # base vetorial persistida em disco
RELATORIOS_DIR = DATA_DIR / "relatorios_indexacao"   # o que foi indexado, trecho a trecho
REGISTROS_DIR = DATA_DIR / "registros"       # histórico das consultas (JSONL)
AVALIACAO_DIR = BASE_DIR / "avaliacao"       # perguntas de teste e resultados

# Versão do código (a pasta versoes/ guarda cada uma). Fica gravada em todos os
# resultados, para saber que código produziu cada número.
VERSAO_CHATBOT = "16"

# Conjunto de perguntas das avaliações (avaliar-busca.bat e as rodadas com os
# modelos). Pode ser uma planilha .csv ou um .json; o perguntas.py lê e confere
# (validar-perguntas.bat). Desde a versão 16, a versão congelada da medição
# final, são as perguntas reais: as 19 dúvidas do formulário (fechado em
# 18/11/2026, às 23h59), com as respostas corretas conferidas pelo autor
# (passo a passo em avaliacao/COMO_USAR_PERGUNTAS_REAIS.md). As 61 perguntas
# geradas continuam em perguntas_recuperacao.json: com elas se ajustou o
# programa (rodada de teste); para usá-las de novo, troque o nome nesta linha
# ou passe --arquivo avaliacao\perguntas_recuperacao.json ao .bat.
ARQUIVO_PERGUNTAS = AVALIACAO_DIR / "perguntas_reais.csv"

# Título de cada documento como o LLM o vê ("Documento: ..." no prompt). O
# título extraído do PDF às vezes não diz o assunto ("Resolução nº 29, de 28
# de abril de 2011"), não diferencia versões ("Engenharia de computação" era o
# PPC 2019) ou é só o nome do arquivo. PDF fora da lista usa o título extraído.
# Vale na consulta: mudar um título não exige reindexar.
ARQUIVO_TITULOS = DATA_DIR / "titulos_documentos.json"

# ---------------------------------------------------------------------------
# Embeddings (Seções 3.6 e 5.4)
# ---------------------------------------------------------------------------
# Modelo da família Sentence-BERT (Reimers; Gurevych, 2019), multilíngue.
# Atenção: este modelo lê no máximo 128 tokens por texto (arquivo
# sentence_bert_config.json do próprio modelo). Tudo o que passa disso é
# descartado em silêncio. Por isso a segmentação abaixo mede os fragmentos
# em tokens do próprio modelo.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

# Força outra janela de leitura do modelo (em tokens). None usa a do próprio
# modelo. Só mude para experimentos: o mpnet foi treinado com 128.
EMBEDDING_MAX_TOKENS = None

# "cpu", "cuda" ou None (escolha automática do sentence-transformers). Fica no
# processador, como os modelos de linguagem comparados (SO_PROCESSADOR).
EMBEDDING_DISPOSITIVO = "cpu"

# Alguns modelos exigem um prefixo diferente para pergunta e para documento.
# (prefixo_da_pergunta, prefixo_do_documento). Modelos fora da lista: sem prefixo.
PREFIXOS_EMBEDDINGS = {
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
}

# ---------------------------------------------------------------------------
# Segmentação (Seções 3.5, 3.6 e 5.4)
# ---------------------------------------------------------------------------
# Tamanho-alvo do fragmento, em tokens do modelo de embeddings. 250 tokens
# correspondem a cerca de 1.000 caracteres em português, o valor original da
# monografia. O programa reduz o alvo automaticamente para caber na janela do
# modelo (no mpnet: 126 tokens de conteúdo, cerca de 450 caracteres).
CHUNK_MAX_TOKENS = 250

# Sobreposição entre fragmentos vizinhos, como fração do tamanho efetivo
# (0,2 = 20%, a mesma proporção de 200 em 1.000 caracteres da monografia).
# A sobreposição é feita com frases inteiras e só dentro do mesmo artigo.
CHUNK_SOBREPOSICAO = 0.2

# Acrescenta ao texto vetorizado um cabeçalho curto com o título/capítulo/seção
# e o artigo do fragmento. Ajuda trechos como "I. discentes calouros;" a
# carregarem o assunto de que tratam. O texto guardado e enviado ao LLM não muda.
CONTEXTO_NO_EMBEDDING = True

# Normas consolidadas mantêm a redação revogada no texto, riscada, seguida de
# uma anotação como "(Alterado pela Resolução X...)" e da redação nova.
# Com True, o texto RISCADO no PDF é descartado na indexação, junto com a
# anotação que o acompanha (detecção pelo traço desenhado sobre o texto).
DESCARTAR_TEXTO_RISCADO = True

# Complemento para PDFs que marcam a alteração só com texto, sem risco: a
# redação que termina com "(Alterado pela...)" e é seguida por outra com o
# mesmo identificador (Art., §, inciso) é descartada. Tudo o que for
# descartado fica listado no relatório de indexação.
DESCARTAR_REDACAO_ALTERADA = True

# Tabelas com bordas (matriz curricular de PPC, por exemplo) são lidas linha a
# linha como "Coluna: valor; Coluna: valor". Tabelas sem bordas são lidas como
# texto comum.
EXTRAIR_TABELAS = True

# ---------------------------------------------------------------------------
# Base vetorial (Seção 5.4)
# ---------------------------------------------------------------------------
# Cada modelo de embeddings ganha a própria coleção (vetores de modelos
# diferentes não são comparáveis). O nome final é COLLECTION_NAME + modelo.
COLLECTION_NAME = "documentos"

# ---------------------------------------------------------------------------
# Recuperação (Seções 3.5 e 5.4)
# ---------------------------------------------------------------------------
# Número de fragmentos recuperados por consulta (cada um vem com os vizinhos,
# ver JANELA_VIZINHOS). Era 4. Na comparação de 03/11/2026 (53 perguntas
# respondíveis, busca híbrida), o trecho certo chegou ao modelo em 44
# perguntas com 4 fragmentos e em 48 com 6, sem nenhuma perdida pelo corte;
# a regra decidida antes de medir era passar para 6 com pelo menos 3 a mais.
TOP_K = 6

# Busca usada pelo chat e pela rodada de testes (Seção 5.6 da monografia):
#   "densa"   -> por sentido (embeddings e cosseno), a busca original;
#   "bm25"    -> só por palavras (referência para a avaliação);
#   "hibrida" -> as duas, juntas pela posição de cada fragmento em cada lista.
# Híbrida desde a versão 03, como prevê a monografia. Na comparação de
# 03/11/2026 (avaliar-busca.bat, 53 perguntas respondíveis, 4 fragmentos), ela
# pôs o trecho certo em 1º lugar em 33 perguntas, contra 23 da densa (McNemar
# exato, p = 0,03), e não perdeu nenhuma pelo corte. Com perguntas reais, que
# costumam ter erros de digitação, ela também é mais segura que só o BM25,
# porque a parte por sentido tolera melhor esses erros.
MODO_BUSCA = "hibrida"

# BM25 (Robertson; Zaragoza, 2009), com os valores usuais da literatura,
# fixados antes de medir: ajustá-los nas próprias perguntas de avaliação seria
# escolher no conjunto de teste.
#   BM25_K1: quanto repetir uma palavra no fragmento ainda aumenta a nota;
#   BM25_B:  quanto se desconta dos fragmentos longos (0 = nada, 1 = tudo).
BM25_K1 = 1.2
BM25_B = 0.75

# Fusão das duas listas no modo "hibrida" (Reciprocal Rank Fusion; Cormack;
# Clarke; Büttcher, 2009): cada fragmento soma 1/(RRF_K + posição) em cada
# busca. 60 é o valor do artigo original. Entram na fusão os
# CANDIDATOS_FUSAO primeiros de cada busca.
RRF_K = 60
CANDIDATOS_FUSAO = 50

# Similaridade de cosseno mínima, sempre a da busca densa, em qualquer modo.
# Vale para duas coisas (requisito do trabalho: melhor não responder do que
# responder com base fraca):
#   1. se nem o fragmento mais parecido chega a ela, o sistema se abstém sem
#      consultar o LLM (RF06);
#   2. só entram no contexto fragmentos com pelo menos essa similaridade
#      (corte por trecho); entre eles, os TOP_K mais bem colocados na busca.
# Calibrado com avaliar_recuperacao.py em 21/09/2026 (53 perguntas
# respondíveis e 8 sem resposta, base da versão 5): a maior similaridade de
# cada pergunta respondível ficou entre 0,56 e 0,90, e a das sem resposta,
# entre 0,42 e 0,72. Com 0,50 nenhuma respondível é bloqueada (folga de 0,06)
# e 3 das 8 sem resposta param antes do LLM. O valor 0,55 bloquearia 6 das 8,
# mas com folga de só 0,01, pouco para 53 perguntas. Nenhum limiar separa
# todas: a pergunta sobre nota de corte do SISU chega a 0,72, então a
# abstenção do LLM continua necessária. Era 0,20, que não bloqueava nada.
SIMILARIDADE_MINIMA = 0.50

# Quantos fragmentos vizinhos (antes e depois) acompanham cada fragmento
# recuperado ao montar o contexto do LLM. Como os fragmentos ficaram menores
# para caber na janela do modelo de embeddings, os vizinhos devolvem ao LLM o
# texto em volta (por exemplo, o restante de um artigo). 0 desliga.
JANELA_VIZINHOS = 1

# Limite de texto entregue ao LLM, em caracteres (as passagens menos
# relevantes saem primeiro). É fixo e igual para qualquer LLM: se a janela de
# cada modelo decidisse, modelos diferentes receberiam trechos diferentes. Com
# TOP_K = 4, o contexto real ficava entre 2.200 e 5.000 caracteres (avaliação
# de 21/09/2026); com 6, cerca de metade a mais. O limite é só uma trava de
# segurança. Antes ele era calculado da janela do LLM: (8.192 - 1.500) x 3 =
# 20.076 caracteres.
CONTEXTO_MAX_CARACTERES = 20000

# ---------------------------------------------------------------------------
# LLM via Ollama (Seções 3.4 e 5.4)
# ---------------------------------------------------------------------------
# Endereço do Ollama. None usa a variável de ambiente OLLAMA_HOST ou o padrão
# http://127.0.0.1:11434.
OLLAMA_HOST = None

# Modelo do chat. O iniciar-chat.bat aceita outro na hora, sem mudar esta
# linha:  iniciar-chat.bat qwen3.8:27b
OLLAMA_MODEL = "llama3.1:8b"

# Modelos de linguagem que o programa conhece, com as opções de cada um:
#   "rotulo":       nome nas tabelas e na tela;
#   "familia":      a linha de modelos de cada empresa. Na avaliação, nenhum
#                   modelo (comparado ou juiz) pode repetir a família de outro;
#   "raciocinio":   True para os modelos que "pensam" antes de responder (o
#                   Qwen 3.8 e o Gemma 4). O programa pede think=False ao
#                   Ollama, para que todos respondam direto e os tempos sejam
#                   comparáveis;
#   "tempo_limite": segundos de espera por uma resposta. Só no processador, o
#                   modelo de 27 bilhões de parâmetros leva minutos por pergunta.
# Um modelo fora da lista também funciona, com as opções padrão (sem
# raciocínio e com OLLAMA_TIMEOUT).
MODELOS = {
    "llama3.1:8b": {"rotulo": "Llama 3.1 8B", "familia": "Llama (Meta)", "raciocinio": False, "tempo_limite": 900},
    "qwen3.8:27b": {"rotulo": "Qwen 3.8 27B", "familia": "Qwen (Alibaba)", "raciocinio": True,
                    "tempo_limite": 3600},
    "phi4-mini": {"rotulo": "Phi-4-mini 3.8B", "familia": "Phi (Microsoft)", "raciocinio": False,
                  "tempo_limite": 600},
    # o modelo leve até a versão 08 (fica na lista para as rodadas antigas)
    "llama3.2:3b": {"rotulo": "Llama 3.2 3B", "familia": "Llama (Meta)", "raciocinio": False, "tempo_limite": 600},
    # juízes (versão 09)
    "ministral-3:8b": {"rotulo": "Ministral 3 8B", "familia": "Mistral (Mistral AI)", "raciocinio": False,
                       "tempo_limite": 600},
    "gemma4:e4b-it-qat": {"rotulo": "Gemma 4 E4B", "familia": "Gemma (Google)", "raciocinio": True,
                          "tempo_limite": 600},
}

# Os modelos comparados na avaliação, na ordem em que a rodada gera as
# respostas: o atual, o mais pesado e o mais leve. Regra (decisão do Lucas,
# 03/11/2026): nenhum modelo da avaliação, comparado ou juiz, repete a família
# de outro; o verificar-modelos.bat confere pelo campo "familia" de MODELOS.
# O mais leve é o Phi-4-mini (Microsoft, 3,8 bilhões de parâmetros, 2,5 GB):
# o Sabiá (Rodrigues et al., 2025) recomendou a família Phi para execução
# local, o português está na lista oficial de idiomas e o cartão do modelo o
# põe um pouco acima do Llama 3.2 3B no MMLU multilíngue. Alternativa
# levantada: o Granite 4.0 Micro da IBM (ibm/granite4:micro). Até a versão
# 08, o mais leve era o Llama 3.2 3B, da mesma família do atual.
MODELOS_COMPARACAO = ["llama3.1:8b", "qwen3.8:27b", "phi4-mini"]

# Os modelos comparados e o chat rodam só no processador: o programa pede
# num_gpu = 0 ao Ollama, que então não põe nenhuma parte do modelo na placa de
# vídeo (sem isso, o Ollama usa a placa sempre que pode). Assim todos são
# medidos nas mesmas condições, as de um computador comum. O
# verificar-modelos.bat confere onde cada modelo rodou.
SO_PROCESSADOR = True

# Juízes da avaliação com o RAGAS (versão 09): os modelos que comparam cada
# resposta com a resposta correta e com os trechos. São dois, de famílias
# diferentes entre si e das três comparadas, porque um juiz tende a favorecer
# a própria família (Zheng et al., 2023; Li et al., 2025) e um painel de
# juízes menores de famílias diferentes concordou mais com avaliadores humanos
# do que um juiz grande sozinho (Verga et al., 2024). Cada um avalia a rodada
# inteira, um depois do outro, na placa de vídeo (a Radeon RX 6600, pelo
# Vulkan); a nota de cada resposta é a média dos dois, e a concordância entre
# eles também é relatada. O Gemma 4 vem com o raciocínio ligado e recebe
# think=False, como o Qwen. Para baixar: ollama pull ministral-3:8b e
# ollama pull gemma4:e4b-it-qat.
# "max_tokens": limite de tokens de cada saída do juiz (as listas de
# afirmações do RAGAS); se a saída vier cortada, o programa tenta de novo com
# o dobro. Os juízes usam temperatura 0, a semente e a janela de OLLAMA_NUM_CTX.
JUIZES = [
    {"modelo": "ministral-3:8b", "placa_de_video": True, "tempo_limite": 600, "max_tokens": 2048},
    {"modelo": "gemma4:e4b-it-qat", "placa_de_video": True, "tempo_limite": 600, "max_tokens": 2048},
]

# A língua dos prompts dos juízes na avaliação da rodada inteira (versão 15): "portugues", que o
# piloto de 14/11/2026 escolheu (os exemplos do RAGAS em português, prompts_em_portugues.py), ou
# "ingles", o RAGAS como vem. As notas em português ficam em juizes_em_portugues/ dentro da rodada.
JUIZES_LINGUA = "portugues"

# Piloto dos juízes contra a avaliação humana (piloto.py, versão 12): quantas
# respostas de cada modelo são sorteadas, a semente do sorteio e os cortes que
# convertem as notas dos juízes (de 0 a 1) nos três níveis da avaliação humana:
# abaixo do primeiro, o nível de baixo (incorreta ou infiel); a partir do
# segundo, o de cima (correta ou fiel); entre os dois, parcial. Os cortes da
# correção valem para o F1 e para a completude. Na fidelidade, fiel é só a nota
# 1 (todas as afirmações da resposta estão nos trechos), como na definição que
# a pessoa segue no caderno, e infiel é menos da metade das afirmações nos
# trechos. Os cortes são decididos antes de existirem as notas da pessoa e
# ficam gravados no piloto, para não serem ajustados depois.
# PILOTO_REAMOSTRAS: reamostras do bootstrap dos intervalos de confiança.
# Na rodada de teste, o piloto sorteou 10 respostas de cada modelo. Na medição
# final (versão 16), com 19 perguntas, o autor avalia todas as respostas que
# recebem as notas dos juízes: com 19, nenhum modelo tem mais que isso, e o
# sorteio só embaralha a ordem do caderno.
PILOTO_POR_MODELO = 19
PILOTO_SEMENTE = 20261104
PILOTO_CORTES = {"correcao": (0.25, 0.75), "fidelidade": (0.5, 1.0)}
PILOTO_REAMOSTRAS = 2000

TEMPERATURA = 0.2            # baixa: menos variação e menos "criatividade"

# Janela de contexto do LLM, em tokens (regras + trechos + pergunta + resposta).
# O padrão do Ollama (4.096 tokens, segundo a documentação atual) varia com a
# versão e pode ser menor que o prompt; quando o prompt não cabe, o Ollama
# descarta parte do texto e regras ou trechos podem se perder sem aviso.
# Fixar o valor evita isso. Com o LLaMA 3.1 8B, 8192 tokens de contexto
# ocupam cerca de 1 GB a mais de memória (cache de atenção). O tamanho dos
# trechos enviados não depende deste valor (CONTEXTO_MAX_CARACTERES).
OLLAMA_NUM_CTX = 8192

# Semente fixa: com a mesma pergunta e o mesmo contexto, a resposta se repete,
# o que torna os experimentos reproduzíveis (Seção 2.2). None = aleatória.
OLLAMA_SEED = 42

# Limite de tokens de cada resposta. Sem ele, o padrão do Ollama é não ter
# limite, e um modelo que entra em repetição seguraria a rodada por horas no
# processador. As respostas do chatbot ficam bem abaixo disso; a que bater no
# limite fica marcada como cortada.
OLLAMA_NUM_PREDICT = 1024

# Opções de amostragem fixadas para todos os modelos. Sem elas, cada modelo
# usaria as do próprio Modelfile (o Qwen vem com top_k 20 e top_p 0,95; os
# Llama, com os padrões do Ollama), e a comparação não teria só o modelo
# mudando. Os valores são os padrões do Ollama.
AMOSTRAGEM = {"top_k": 40, "top_p": 0.9, "min_p": 0.0, "repeat_penalty": 1.1, "repeat_last_n": 64}

# Por quanto tempo o Ollama mantém o modelo carregado após a última pergunta.
OLLAMA_KEEP_ALIVE = "30m"

# Tempo máximo de espera por uma resposta do Ollama, em segundos, para um
# modelo fora de MODELOS (os da lista usam o "tempo_limite" de cada um).
OLLAMA_TIMEOUT = 600

# Mensagem padrão de abstenção (RF06). O prompt pede ao modelo que use
# exatamente esta frase quando os trechos não contêm a resposta.
MENSAGEM_ABSTENCAO = (
    "Não encontrei essa informação nos documentos disponíveis. "
    "Procure a coordenação do seu curso para obter orientação."
)

# ---------------------------------------------------------------------------
# Registro das interações (instrumentação para a avaliação, Seção 5.6)
# ---------------------------------------------------------------------------
# Grava pergunta, trechos recuperados, resposta e tempos em
# data/registros/interacoes.jsonl (arquivo local, nada sai da máquina).
REGISTRAR_INTERACOES = True
