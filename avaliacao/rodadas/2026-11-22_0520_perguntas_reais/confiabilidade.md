# Confiabilidade da rodada 2026-11-22_0520_perguntas_reais

Perguntas: perguntas_reais.csv (assinatura 6f256815ebe4), 19 na rodada. Código da rodada: versão 16. Calculada em 2026-11-22T14:31:31.

| Modelo | Perguntas respondidas pelo modelo | Com resposta nos documentos | Respondeu | Abstenção pelo limiar | Abstenção do modelo | Abstenção com acréscimo | Respondeu, das que chegaram ao modelo | Sem resposta nos documentos | Absteve-se pelo limiar | Absteve-se o modelo | Respondeu sem base (perigoso) | Absteve-se, das que chegaram ao modelo | Respostas vazias | Respostas mistas | Respostas sem citação | Cortadas no limite de tokens | Raciocinou mesmo desligado | Tempo médio (s) | Tempo mediano (s) | Escrita (tokens/s) | Correção (F1) média (juízes) | Completude média (juízes) | Fidelidade média (juízes) |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 19 | 15 | 15 | 0 | 0 | 0 | 100% | 4 | 1 | 0 | 3 | 0% | 0 | 3 | 0 | 0 | 0 | 96,2 | 84,8 | 6,1 | 0,25 | 0,26 | 0,76 |
| Qwen 3.8 27B | 19 | 15 | 13 | 0 | 2 | 0 | 87% | 4 | 1 | 2 | 1 | 67% | 0 | 2 | 0 | 0 | 0 | 244,2 | 242,4 | 3,4 | 0,44 | 0,49 | 0,86 |
| Phi-4-mini 3.8B | 19 | 15 | 13 | 0 | 2 | 0 | 87% | 4 | 1 | 0 | 3 | 0% | 0 | 1 | 0 | 0 | 0 | 29,9 | 26,0 | 10,9 | 0,23 | 0,15 | 0,66 |

Respondeu sem base = respondeu (ou se absteve acrescentando algo sem citar) a uma pergunta que os documentos não respondem: o caso que o requisito do trabalho quer evitar. Abstenção pelo limiar = nenhum trecho passou na similaridade mínima (0,50); é igual para todos os modelos, porque os trechos estão congelados, e por isso as taxas contam só as perguntas que chegaram ao modelo. A classificação das respostas é automática; o revisar.csv lista as que merecem conferência à mão, e a decisão escrita na coluna "sua conferência" passa a valer aqui.

As médias dos juízes são as dos juízes em português (os exemplos dos prompts do RAGAS em português, versão 15).

Classificação conferida à mão (coluna "sua conferência" do revisar.csv): 2 resposta(s) mudaram de categoria (Phi-4-mini 3.8B P007, de abstenção com acréscimo para abstenção; Qwen 3.8 27B P004, de mista para abstenção); 13 ficaram como o programa classificou. As contagens e as comparações usam a categoria conferida; o arquivo de respostas não muda.

Atenção: decisões do revisar.csv que não valeram ou pedem cuidado: Phi-4-mini 3.8B P007: está no piloto (P06), e com a decisão deixa de ter nota dos juízes; o piloto passa a ter uma resposta a menos.

## Comparação dos modelos (McNemar exato)

- Llama 3.1 8B x Qwen 3.8 27B, absteve-se nas perguntas sem resposta (4 perguntas): só o Llama 3.1 8B: 0; só o Qwen 3.8 27B: 2 (P004, P017); p = 0,500
- Llama 3.1 8B x Qwen 3.8 27B, respondeu as perguntas com resposta (15 perguntas): só o Llama 3.1 8B: 2 (P005, P008); só o Qwen 3.8 27B: 0; p = 0,500
- Llama 3.1 8B x Phi-4-mini 3.8B, absteve-se nas perguntas sem resposta (4 perguntas): só o Llama 3.1 8B: 0; só o Phi-4-mini 3.8B: 0; p = 1,000
- Llama 3.1 8B x Phi-4-mini 3.8B, respondeu as perguntas com resposta (15 perguntas): só o Llama 3.1 8B: 2 (P005, P007); só o Phi-4-mini 3.8B: 0; p = 0,500
- Qwen 3.8 27B x Phi-4-mini 3.8B, absteve-se nas perguntas sem resposta (4 perguntas): só o Qwen 3.8 27B: 2 (P004, P017); só o Phi-4-mini 3.8B: 0; p = 0,500
- Qwen 3.8 27B x Phi-4-mini 3.8B, respondeu as perguntas com resposta (15 perguntas): só o Qwen 3.8 27B: 1 (P007); só o Phi-4-mini 3.8B: 1 (P008); p = 1,000
