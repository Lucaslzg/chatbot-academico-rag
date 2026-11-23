# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juiz: ministral-3:8b (temperatura 0, janela de 8192 tokens). Calculado em 2026-11-04T23:37:06.

Cobertura dos trechos (a mesma para todos os modelos): média 0,81, mediana 1,00, em 53 perguntas; 5 com nota zero.

| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção | Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |
|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,36 | 0,34 | 52 | 16 | 0,52 | 0,50 | 0,71 | 54 | 0 |
| Qwen 3.8 27B | 0,59 | 0,60 | 52 | 7 | 0,69 | 0,78 | 0,88 | 53 | 0 |
| Phi-4-mini 3.8B | 0,46 | 0,46 | 49 | 10 | 0,49 | 0,43 | 0,73 | 50 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu no ragas_<modelo>.jsonl.

## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,14, p = 0,000
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,002
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 52 perguntas, mediana da diferença -0,18, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,224
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,582
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença -0,07, p = 0,342
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,08, p = 0,053
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,023
