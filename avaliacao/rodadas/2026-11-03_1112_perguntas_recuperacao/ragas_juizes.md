# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juízes: Ministral 3 8B (Mistral (Mistral AI)), Gemma 4 E4B (Gemma (Google)). A nota de cada resposta é a média dos juízes; entram só as respostas que todos avaliaram. Calculado em 2026-11-05T02:21:57.

Cobertura dos trechos (a mesma para todos os modelos): média dos juízes 0,80, em 53 perguntas (Ministral 3 8B: 0,81; Gemma 4 E4B: 0,80).

| Modelo | Correção (F1) (média dos juízes) | Respostas | Correção (F1), Ministral 3 8B | Correção (F1), Gemma 4 E4B | Completude (média dos juízes) | Respostas | Completude, Ministral 3 8B | Completude, Gemma 4 E4B | Fidelidade (média dos juízes) | Respostas | Fidelidade, Ministral 3 8B | Fidelidade, Gemma 4 E4B | Erros dos juízes |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,38 | 52 | 0,36 | 0,40 | 0,57 | 52 | 0,52 | 0,63 | 0,72 | 54 | 0,71 | 0,74 | 0 |
| Qwen 3.8 27B | 0,63 | 52 | 0,59 | 0,68 | 0,71 | 52 | 0,69 | 0,74 | 0,92 | 53 | 0,88 | 0,96 | 0 |
| Phi-4-mini 3.8B | 0,49 | 49 | 0,46 | 0,52 | 0,49 | 49 | 0,49 | 0,50 | 0,75 | 50 | 0,73 | 0,77 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu por cada juiz na pasta dele (juiz_<nome>/ragas_<modelo>.jsonl).

## Concordância entre os juízes

- correção (F1), Ministral 3 8B x Gemma 4 E4B: 153 notas dos dois, correlação de Pearson 0,81, diferença média 0,14
- completude, Ministral 3 8B x Gemma 4 E4B: 153 notas dos dois, correlação de Pearson 0,79, diferença média 0,15
- fidelidade, Ministral 3 8B x Gemma 4 E4B: 157 notas dos dois, correlação de Pearson 0,78, diferença média 0,11
- cobertura dos trechos, Ministral 3 8B x Gemma 4 E4B: 53 notas dos dois, correlação de Pearson 0,86, diferença média 0,05

## Comparação dos modelos (Wilcoxon pareado, na média dos juízes, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,22, p = 0,000
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,001
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 52 perguntas, mediana da diferença -0,16, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,09, p = 0,119
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,287
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença -0,08, p = 0,259
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,07, p = 0,008
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,10, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,005
