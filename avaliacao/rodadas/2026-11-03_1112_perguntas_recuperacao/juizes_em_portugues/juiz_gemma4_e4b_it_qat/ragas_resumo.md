# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juiz: gemma4:e4b-it-qat (temperatura 0, janela de 8192 tokens). Calculado em 2026-11-15T19:13:40.

Juiz em português: os exemplos dos prompts do RAGAS em português e a instrução de escrever a saída em português (prompts_em_portugues.py).

Cobertura dos trechos (a mesma para todos os modelos): média 0,79, mediana 1,00, em 53 perguntas; 6 com nota zero.

| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção | Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |
|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,38 | 0,38 | 52 | 17 | 0,62 | 0,66 | 0,74 | 54 | 0 |
| Qwen 3.8 27B | 0,67 | 0,67 | 52 | 3 | 0,74 | 1,00 | 0,98 | 52 | 0 |
| Phi-4-mini 3.8B | 0,53 | 0,57 | 49 | 11 | 0,51 | 0,50 | 0,83 | 49 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu no ragas_<modelo>.jsonl.

## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,24, p = 0,000
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,012
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,14, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,07, p = 0,036
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,249
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,11, p = 0,076
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,011
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
