# Avaliação com o RAGAS da rodada 2026-11-22_0520_perguntas_reais

Juiz: ministral-3:8b (temperatura 0, janela de 8192 tokens). Calculado em 2026-11-22T13:15:11.

Juiz em português: os exemplos dos prompts do RAGAS em português e a instrução de escrever a saída em português (prompts_em_portugues.py).

Cobertura dos trechos (a mesma para todos os modelos): média 0,58, mediana 0,50, em 15 perguntas; 2 com nota zero.

| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção | Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |
|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,22 | 0,24 | 15 | 5 | 0,28 | 0,17 | 0,73 | 18 | 0 |
| Qwen 3.8 27B | 0,45 | 0,44 | 13 | 0 | 0,49 | 0,43 | 0,80 | 14 | 0 |
| Phi-4-mini 3.8B | 0,25 | 0,29 | 13 | 4 | 0,15 | 0,00 | 0,58 | 16 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu no ragas_<modelo>.jsonl.

## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 13 perguntas, mediana da diferença -0,20, p = 0,005
- completude, Llama 3.1 8B x Qwen 3.8 27B: 13 perguntas, mediana da diferença -0,10, p = 0,150
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 14 perguntas, mediana da diferença -0,12, p = 0,110
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,00, p = 1,000
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,12, p = 0,078
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 16 perguntas, mediana da diferença 0,09, p = 0,173
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 12 perguntas, mediana da diferença 0,17, p = 0,034
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 12 perguntas, mediana da diferença 0,28, p = 0,016
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 13 perguntas, mediana da diferença 0,17, p = 0,110
