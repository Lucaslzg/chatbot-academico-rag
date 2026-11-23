# Avaliação com o RAGAS da rodada 2026-11-22_0520_perguntas_reais

Juízes em português: Ministral 3 8B (Mistral (Mistral AI)), Gemma 4 E4B (Gemma (Google)). A nota de cada resposta é a média dos juízes; entram só as respostas que todos avaliaram. Calculado em 2026-11-22T14:00:54.

Cobertura dos trechos (a mesma para todos os modelos): média dos juízes 0,54, em 15 perguntas (Ministral 3 8B: 0,58; Gemma 4 E4B: 0,51).

| Modelo | Correção (F1) (média dos juízes) | Respostas | Correção (F1), Ministral 3 8B | Correção (F1), Gemma 4 E4B | Completude (média dos juízes) | Respostas | Completude, Ministral 3 8B | Completude, Gemma 4 E4B | Fidelidade (média dos juízes) | Respostas | Fidelidade, Ministral 3 8B | Fidelidade, Gemma 4 E4B | Erros dos juízes |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,25 | 15 | 0,22 | 0,28 | 0,26 | 15 | 0,28 | 0,24 | 0,76 | 18 | 0,73 | 0,79 | 0 |
| Qwen 3.8 27B | 0,44 | 13 | 0,45 | 0,43 | 0,49 | 13 | 0,49 | 0,49 | 0,86 | 14 | 0,80 | 0,92 | 0 |
| Phi-4-mini 3.8B | 0,23 | 13 | 0,25 | 0,22 | 0,15 | 13 | 0,15 | 0,15 | 0,66 | 16 | 0,58 | 0,74 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu por cada juiz na pasta dele (juiz_<nome>/ragas_<modelo>.jsonl).

## Concordância entre os juízes

- correção (F1), Ministral 3 8B x Gemma 4 E4B: 41 notas dos dois, correlação de Pearson 0,60, diferença média 0,15
- completude, Ministral 3 8B x Gemma 4 E4B: 41 notas dos dois, correlação de Pearson 0,95, diferença média 0,06
- fidelidade, Ministral 3 8B x Gemma 4 E4B: 48 notas dos dois, correlação de Pearson 0,54, diferença média 0,19
- cobertura dos trechos, Ministral 3 8B x Gemma 4 E4B: 15 notas dos dois, correlação de Pearson 0,59, diferença média 0,22

## Comparação dos modelos (Wilcoxon pareado, na média dos juízes, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 13 perguntas, mediana da diferença -0,18, p = 0,017
- completude, Llama 3.1 8B x Qwen 3.8 27B: 13 perguntas, mediana da diferença -0,10, p = 0,067
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 14 perguntas, mediana da diferença -0,09, p = 0,135
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,02, p = 0,750
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,06, p = 0,055
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 16 perguntas, mediana da diferença 0,09, p = 0,193
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 12 perguntas, mediana da diferença 0,24, p = 0,027
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 12 perguntas, mediana da diferença 0,25, p = 0,004
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,09, p = 0,042
