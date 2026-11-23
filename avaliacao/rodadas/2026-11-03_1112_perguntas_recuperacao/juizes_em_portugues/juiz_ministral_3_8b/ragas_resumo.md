# Avaliação com o RAGAS da rodada 2026-11-03_1112_perguntas_recuperacao

Juiz: ministral-3:8b (temperatura 0, janela de 8192 tokens). Calculado em 2026-11-15T17:39:53.

Juiz em português: os exemplos dos prompts do RAGAS em português e a instrução de escrever a saída em português (prompts_em_portugues.py).

Cobertura dos trechos (a mesma para todos os modelos): média 0,80, mediana 1,00, em 53 perguntas; 6 com nota zero.

| Modelo | Correção (F1) média | Correção (F1) mediana | Respostas com correção | Notas zero de correção | Completude média | Completude mediana | Fidelidade média | Respostas com fidelidade | Erros do juiz |
|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 0,37 | 0,30 | 52 | 15 | 0,57 | 0,59 | 0,69 | 54 | 0 |
| Qwen 3.8 27B | 0,56 | 0,61 | 52 | 5 | 0,67 | 0,76 | 0,85 | 52 | 0 |
| Phi-4-mini 3.8B | 0,45 | 0,46 | 49 | 9 | 0,47 | 0,50 | 0,74 | 49 | 0 |

Correção (F1) e completude: só perguntas com resposta nos documentos que o modelo respondeu (as abstenções estão na tabela de confiabilidade). A completude é a parte das afirmações da resposta correta que a resposta traz (um dos dois lados da conta do F1); ela não tira ponto da resposta que diz de onde veio a informação. Uma nota zero pode ser resposta errada ou o juiz não ter achado afirmações: confira o que ele devolveu no ragas_<modelo>.jsonl.

## Comparação dos modelos (Wilcoxon pareado, nas perguntas que os dois têm nota)

- correção (F1), Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,12, p = 0,001
- completude, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença 0,00, p = 0,035
- fidelidade, Llama 3.1 8B x Qwen 3.8 27B: 51 perguntas, mediana da diferença -0,10, p = 0,000
- correção (F1), Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença -0,01, p = 0,244
- completude, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,160
- fidelidade, Llama 3.1 8B x Phi-4-mini 3.8B: 48 perguntas, mediana da diferença 0,00, p = 0,359
- correção (F1), Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,08, p = 0,036
- completude, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,000
- fidelidade, Qwen 3.8 27B x Phi-4-mini 3.8B: 49 perguntas, mediana da diferença 0,00, p = 0,047
