# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juiz: gemma4:e4b-it-qat (temperatura 0, janela de 8192 tokens). Calculado em 2026-11-05T02:21:57.

Cobertura dos trechos (a mesma para todos os modelos): média 0,80, mediana 1,00, em 53 perguntas; 7 com nota zero.

| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção | Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |
|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,40 | 0,40 | 52 | 15 | 0,63 | 0,69 | 0,74 | 54 | 0 |
| Qwen 3.8 27B | 0,68 | 0,72 | 52 | 4 | 0,74 | 1,00 | 0,96 | 53 | 0 |
| Phi-4-mini 3.8B | 0,52 | 0,57 | 49 | 10 | 0,50 | 0,50 | 0,77 | 50 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu no ragas_<modelo>.jsonl.

## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,28, p = 0,000
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,027
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 52 perguntas, mediana da diferença -0,16, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,10, p = 0,080
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,118
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,340
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,05, p = 0,003
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
