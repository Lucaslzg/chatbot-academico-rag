# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juízes em português: Ministral 3 8B (Mistral (Mistral AI)), Gemma 4 E4B (Gemma (Google)). A nota de cada resposta é a média dos juízes; entram só as respostas que todos avaliaram. Calculado em 2026-11-15T19:13:40.

Cobertura dos trechos (a mesma para todos os modelos): média dos juízes 0,80, em 53 perguntas (Ministral 3 8B: 0,80; Gemma 4 E4B: 0,79).

| Modelo | Correção (F1) (média dos juízes) | Respostas | Correção (F1), Ministral 3 8B | Correção (F1), Gemma 4 E4B | Completude (média dos juízes) | Respostas | Completude, Ministral 3 8B | Completude, Gemma 4 E4B | Fidelidade (média dos juízes) | Respostas | Fidelidade, Ministral 3 8B | Fidelidade, Gemma 4 E4B | Erros dos juízes |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,38 | 52 | 0,37 | 0,38 | 0,59 | 52 | 0,57 | 0,62 | 0,72 | 54 | 0,69 | 0,74 | 0 |
| Qwen 3.8 27B | 0,61 | 52 | 0,56 | 0,67 | 0,70 | 52 | 0,67 | 0,74 | 0,92 | 52 | 0,85 | 0,98 | 0 |
| Phi-4-mini 3.8B | 0,49 | 49 | 0,45 | 0,53 | 0,49 | 49 | 0,47 | 0,51 | 0,78 | 49 | 0,74 | 0,83 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu por cada juiz na pasta dele (juiz_<nome>/ragas_<modelo>.jsonl).

## Concordância entre os juízes

- correção (F1), Ministral 3 8B x Gemma 4 E4B: 153 notas dos dois, correlação de Pearson 0,79, diferença média 0,16
- completude, Ministral 3 8B x Gemma 4 E4B: 153 notas dos dois, correlação de Pearson 0,85, diferença média 0,12
- fidelidade, Ministral 3 8B x Gemma 4 E4B: 155 notas dos dois, correlação de Pearson 0,49, diferença média 0,17
- cobertura dos trechos, Ministral 3 8B x Gemma 4 E4B: 53 notas dos dois, correlação de Pearson 0,97, diferença média 0,02

## Comparação dos modelos (Wilcoxon pareado, na média dos juízes, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,17, p = 0,000
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,017
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,16, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,09, p = 0,077
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,165
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,11, p = 0,087
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,07, p = 0,012
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,04, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,05, p = 0,005
