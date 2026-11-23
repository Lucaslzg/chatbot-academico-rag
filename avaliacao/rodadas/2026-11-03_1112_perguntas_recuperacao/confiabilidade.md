# Confiabilidade da rodada 2026-11-03_1112_perguntas_recuperacao

Perguntas: perguntas_recuperacao.json (assinatura 646fd8fee83d), 61 na rodada. Código da rodada: versão 08. Calculada em 2026-11-15T20:43:11.

| Modelo | Perguntas respondidas pelo modelo | Com resposta nos documentos | Respondeu | Abstenção pelo limiar | Abstenção do modelo | Abstenção com acréscimo | Respondeu, das que chegaram ao modelo | Sem resposta nos documentos | Absteve-se pelo limiar | Absteve-se o modelo | Respondeu sem base (perigoso) | Absteve-se, das que chegaram ao modelo | Respostas vazias | Respostas mistas | Respostas sem citação | Cortadas no limite de tokens | Raciocinou mesmo desligado | Tempo médio (s) | Tempo mediano (s) | Escrita (tokens/s) | Correção (F1) média (juízes) | Completude média (juízes) | Fidelidade média (juízes) |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| Llama 3.1 8B | 61 | 53 | 52 | 0 | 1 | 0 | 98% | 8 | 3 | 3 | 2 | 60% | 0 | 2 | 3 | 0 | 0 | 64,2 | 63,4 | 6,3 | 0,38 | 0,59 | 0,72 |
| Qwen 3.8 27B | 61 | 53 | 52 | 0 | 1 | 0 | 98% | 8 | 3 | 5 | 0 | 100% | 0 | 1 | 0 | 0 | 0 | 175,1 | 178,6 | 3,7 | 0,61 | 0,70 | 0,92 |
| Phi-4-mini 3.8B | 61 | 53 | 49 | 0 | 4 | 0 | 92% | 8 | 3 | 5 | 0 | 100% | 0 | 3 | 0 | 0 | 0 | 21,9 | 21,8 | 11,4 | 0,49 | 0,49 | 0,78 |

Respondeu sem base = respondeu (ou se absteve acrescentando algo sem citar) a uma pergunta que os documentos não respondem: o caso que o requisito do trabalho quer evitar. Abstenção pelo limiar = nenhum trecho passou na similaridade mínima (0,50); é igual para todos os modelos, porque os trechos estão congelados, e por isso as taxas contam só as perguntas que chegaram ao modelo. A classificação das respostas é automática; o revisar.csv lista as que merecem conferência à mão, e a decisão escrita na coluna "sua conferência" passa a valer aqui.

As médias dos juízes são as dos juízes em português (os exemplos dos prompts do RAGAS em português, versão 15).

Classificação refeita pelas regras da versão 15: 5 resposta(s) mudaram de categoria em relação à gravada na geração (Llama 3.1 8B N02, de resposta para abstenção; Phi-4-mini 3.8B R03, de resposta para abstenção; Phi-4-mini 3.8B R24, de resposta para abstenção; Phi-4-mini 3.8B N04, de resposta para abstenção; Phi-4-mini 3.8B N05, de resposta para abstenção). O arquivo de respostas não muda.

Classificação conferida à mão (coluna "sua conferência" do revisar.csv): 5 resposta(s) mudaram de categoria (Llama 3.1 8B N03, de mista para abstenção; Llama 3.1 8B N04, de abstenção para abstenção com acréscimo; Llama 3.1 8B R11, de abstenção com acréscimo para resposta; Phi-4-mini 3.8B N03, de mista para abstenção; Qwen 3.8 27B N05, de resposta para abstenção); 16 ficaram como o programa classificou. As contagens e as comparações usam a categoria conferida; o arquivo de respostas não muda.

## Comparação dos modelos (McNemar exato)

- Llama 3.1 8B x Qwen 3.8 27B, absteve-se nas perguntas sem resposta (8 perguntas): só o Llama 3.1 8B: 0; só o Qwen 3.8 27B: 2 (N04, N05); p = 0,500
- Llama 3.1 8B x Qwen 3.8 27B, respondeu as perguntas com resposta (53 perguntas): só o Llama 3.1 8B: 1 (R03); só o Qwen 3.8 27B: 1 (R52); p = 1,000
- Llama 3.1 8B x Phi-4-mini 3.8B, absteve-se nas perguntas sem resposta (8 perguntas): só o Llama 3.1 8B: 0; só o Phi-4-mini 3.8B: 2 (N04, N05); p = 0,500
- Llama 3.1 8B x Phi-4-mini 3.8B, respondeu as perguntas com resposta (53 perguntas): só o Llama 3.1 8B: 4 (R03, R07, R09, R24); só o Phi-4-mini 3.8B: 1 (R52); p = 0,375
- Qwen 3.8 27B x Phi-4-mini 3.8B, absteve-se nas perguntas sem resposta (8 perguntas): só o Qwen 3.8 27B: 0; só o Phi-4-mini 3.8B: 0; p = 1,000
- Qwen 3.8 27B x Phi-4-mini 3.8B, respondeu as perguntas com resposta (53 perguntas): só o Qwen 3.8 27B: 3 (R07, R09, R24); só o Phi-4-mini 3.8B: 0; p = 0,250
