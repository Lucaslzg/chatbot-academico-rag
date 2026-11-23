# Piloto dos juízes da rodada 2026-11-22_0520_perguntas_reais

42 respostas sorteadas (semente 20261104). As notas dos juízes viram níveis pelos cortes fixados antes do piloto. Correção (F1 e completude): abaixo de 0,25, incorreta; a partir de 0,75, correta; entre os dois, parcial. Fidelidade: abaixo de 0,50, infiel; só 1,00 (todas as afirmações nos trechos), fiel; entre os dois, parcial. Calculado em 2026-11-22T14:32:08.

Juízes em inglês, com os prompts do RAGAS como vêm: nenhum. Em português (versão 13), com os exemplos dos prompts em português e a instrução de escrever a saída em português: Ministral 3 8B e Gemma 4 E4B.

Atenção: os juízes não são os mesmos nas duas línguas (em inglês: nenhum; em português: Ministral 3 8B e Gemma 4 E4B). A comparação entre as línguas vale só para o juiz que está nas duas, e a regra da língua, que usa a média dos juízes, não pode ser aplicada. Para ela, os dois juízes precisam ter avaliado nas duas línguas: rode até o fim o avaliar-ragas.bat e o juizes-em-portugues.bat (sem --juiz) e o avaliar-piloto.bat de novo.

| Avaliação humana | Nota do juiz | Avaliador | Respostas | Kappa ponderado (IC 95%) | Spearman (IC 95%) | Concordância exata |
|-|-|-|-|-|-|-|
| correção | correção (F1) | Ministral 3 8B, em português | 36 | 0,22 (0,07 a 0,38) | 0,50 (0,20 a 0,74) | 0,39 |
| correção | correção (F1) | Gemma 4 E4B, em português | 36 | 0,12 (-0,02 a 0,26) | 0,42 (0,09 a 0,69) | 0,25 |
| correção | correção (F1) | média dos juízes, em português | 36 | 0,20 (0,05 a 0,36) | 0,51 (0,18 a 0,74) | 0,33 |
| correção | completude | Ministral 3 8B, em português | 36 | 0,29 (0,12 a 0,48) | 0,48 (0,17 a 0,69) | 0,44 |
| correção | completude | Gemma 4 E4B, em português | 36 | 0,31 (0,15 a 0,50) | 0,47 (0,16 a 0,69) | 0,44 |
| correção | completude | média dos juízes, em português | 36 | 0,25 (0,10 a 0,44) | 0,48 (0,17 a 0,70) | 0,42 |
| fidelidade | fidelidade | Ministral 3 8B, em português | 36 | 0,01 (-0,15 a 0,14) | 0,15 (-0,36 a 0,54) | 0,11 |
| fidelidade | fidelidade | Gemma 4 E4B, em português | 36 | 0,12 (-0,10 a 0,35) | 0,16 (-0,21 a 0,50) | 0,53 |
| fidelidade | fidelidade | média dos juízes, em português | 36 | 0,00 (-0,16 a 0,14) | 0,16 (-0,36 a 0,55) | 0,11 |

Kappa ponderado (linear): 1 é concordância total e 0 é o que o acaso daria; discordar por um nível conta metade. Referência usual (Landis e Koch, 1977): de 0,41 a 0,60, moderada; de 0,61 a 0,80, substancial; acima de 0,80, quase perfeita. Spearman: se as notas sobem e descem juntas, sem depender dos cortes; com três níveis do lado da pessoa, ele não chega a 1 nem com a ordem toda certa (no máximo cerca de 0,94 com os níveis divididos por igual). IC 95%: intervalo de confiança de 95% por bootstrap (2000 reamostras das respostas, com a semente do sorteio). Com cerca de 30 respostas, o intervalo do kappa costuma ter perto de 0,5 de largura: diferenças menores que isso podem ser só acaso. Sem intervalo: poucas respostas, ou reamostras demais em que a medida não sai. "Um nível só de um lado": a pessoa ou o juiz deu o mesmo nível a todas as respostas, e aí o kappa não mede concordância (dá 0 ou não sai).

## Diferenças, nas mesmas respostas

| Comparação | Avaliador | Respostas | No kappa (IC 95%) | No Spearman (IC 95%) |
|-|-|-|-|-|
| F1 menos completude | Ministral 3 8B, em português | 36 | -0,08 (-0,25 a 0,11) | +0,03 (-0,25 a 0,29) |
| F1 menos completude | Gemma 4 E4B, em português | 36 | -0,18 (-0,35 a -0,04; todo abaixo de zero) | -0,05 (-0,34 a 0,24) |
| F1 menos completude | média dos juízes, em português | 36 | -0,05 (-0,22 a 0,11) | +0,02 (-0,23 a 0,26) |
| juiz menos a média: correção (F1) | Ministral 3 8B, em português | 36 | não se aplica | 0,00 (-0,17 a 0,18) |
| juiz menos a média: completude | Ministral 3 8B, em português | 36 | não se aplica | -0,01 (-0,07 a 0,05) |
| juiz menos a média: fidelidade | Ministral 3 8B, em português | 36 | não se aplica | -0,01 (-0,05 a 0,02) |
| juiz menos a média: correção (F1) | Gemma 4 E4B, em português | 36 | não se aplica | -0,09 (-0,22 a 0,06) |
| juiz menos a média: completude | Gemma 4 E4B, em português | 36 | não se aplica | -0,02 (-0,09 a 0,04) |
| juiz menos a média: fidelidade | Gemma 4 E4B, em português | 36 | não se aplica | +0,01 (-0,21 a 0,17) |

Positivo: a primeira nota concorda mais com a pessoa. Se o intervalo passa pelo zero, estas respostas não bastam para dizer qual das duas concorda mais; quando ele não passa, a tabela diz "todo acima de zero" ou "todo abaixo de zero", conferido nos valores sem arredondar (um limite muito perto de zero aparece com mais casas). Na comparação de cada juiz com a média, só o Spearman, que não depende dos cortes: com o corte de fiel em 1, a média só é fiel quando os dois juízes dão 1, o que puxaria o kappa da média para baixo. São várias comparações ao mesmo tempo, então um intervalo que não passa pelo zero ainda pode ser acaso; valem as que as regras combinadas antes do piloto mandam olhar.

## Por modelo: nível do juiz menos o da pessoa, em média (média dos juízes, em português)

| Comparação | Llama 3.1 8B | Phi-4-mini 3.8B | Qwen 3.8 27B |
|-|-|-|-|
| correção x correção (F1) | -0,69 (13) | -0,58 (12) | -1,00 (11) |
| correção x completude | -0,62 (13) | -0,83 (12) | -0,73 (11) |
| fidelidade x fidelidade | -1,08 (13) | -0,67 (12) | -0,91 (11) |

Positivo: o juiz deu níveis mais altos que a pessoa nas respostas daquele modelo (entre parênteses, quantas respostas). Com cerca de 10 respostas por modelo, só diferenças grandes dizem alguma coisa.

Notas em branco na planilha (com o motivo na observação): correção: P06, P17, P18, P19, P28, P29; fidelidade: P06, P17, P18, P19, P28, P29

Respostas sem nota de um juiz (ficam fora da comparação com ele): Ministral 3 8B, em português: P06; Gemma 4 E4B, em português: P06; média dos juízes, em português: P06

## Quantas vezes cada nível coincidiu (linhas: a pessoa; colunas: a média dos juízes)

**correção x correção (F1) (média dos juízes, em português)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 6 | 1 | 0 |
| parcial | 3 | 5 | 0 |
| correta | 5 | 15 | 1 |

**correção x completude (média dos juízes, em português)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 6 | 1 | 0 |
| parcial | 4 | 4 | 0 |
| correta | 7 | 9 | 5 |

**fidelidade x fidelidade (média dos juízes, em português)**

| | infiel | parcial | fiel |
|-|-|-|-|
| infiel | 1 | 0 | 1 |
| parcial | 1 | 0 | 0 |
| fiel | 3 | 27 | 3 |

