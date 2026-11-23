# Piloto dos juízes da rodada 2026-11-03_1112_perguntas_recuperacao

30 respostas sorteadas (semente 20261104). As notas dos juízes viram níveis pelos cortes fixados antes do piloto. Correção (F1 e completude): abaixo de 0,25, incorreta; a partir de 0,75, correta; entre os dois, parcial. Fidelidade: abaixo de 0,50, infiel; só 1,00 (todas as afirmações nos trechos), fiel; entre os dois, parcial. Calculado em 2026-11-14T04:19:24.

Cada juiz aparece duas vezes: em inglês, com os prompts do RAGAS como vêm, e em português (versão 13), com os exemplos dos prompts em português e a instrução de escrever a saída em português. A média de cada língua é a dos juízes daquela língua.

| Avaliação humana | Nota do juiz | Avaliador | Respostas | Kappa ponderado (IC 95%) | Spearman (IC 95%) | Concordância exata |
|-|-|-|-|-|-|-|
| correção | correção (F1) | Ministral 3 8B, em inglês | 30 | 0,23 (0,05 a 0,44) | 0,60 (0,36 a 0,77) | 0,40 |
| correção | correção (F1) | Ministral 3 8B, em português | 30 | 0,19 (0,04 a 0,38) | 0,59 (0,35 a 0,76) | 0,33 |
| correção | correção (F1) | Gemma 4 E4B, em inglês | 30 | 0,27 (0,09 a 0,46) | 0,63 (0,39 a 0,79) | 0,47 |
| correção | correção (F1) | Gemma 4 E4B, em português | 30 | 0,36 (0,12 a 0,60) | 0,61 (0,36 a 0,78) | 0,57 |
| correção | correção (F1) | média dos juízes, em inglês | 30 | 0,29 (0,08 a 0,49) | 0,64 (0,40 a 0,79) | 0,43 |
| correção | correção (F1) | média dos juízes, em português | 30 | 0,28 (0,07 a 0,49) | 0,62 (0,36 a 0,79) | 0,43 |
| correção | completude | Ministral 3 8B, em inglês | 30 | 0,20 (-0,02 a 0,43) | 0,49 (0,15 a 0,73) | 0,40 |
| correção | completude | Ministral 3 8B, em português | 30 | 0,20 (-0,10 a 0,50) | 0,37 (0,01 a 0,65) | 0,50 |
| correção | completude | Gemma 4 E4B, em inglês | 30 | 0,30 (0,02 a 0,58) | 0,36 (-0,03 a 0,65) | 0,60 |
| correção | completude | Gemma 4 E4B, em português | 30 | 0,32 (0,02 a 0,60) | 0,43 (0,06 a 0,71) | 0,60 |
| correção | completude | média dos juízes, em inglês | 30 | 0,27 (0,00 a 0,54) | 0,46 (0,13 a 0,71) | 0,53 |
| correção | completude | média dos juízes, em português | 30 | 0,32 (0,02 a 0,60) | 0,42 (0,07 a 0,68) | 0,60 |
| fidelidade | fidelidade | Ministral 3 8B, em inglês | 30 | 0,04 (0,00 a 0,17) | 0,21 | 0,50 |
| fidelidade | fidelidade | Ministral 3 8B, em português | 30 | 0,04 (0,00 a 0,14) | 0,14 | 0,43 |
| fidelidade | fidelidade | Gemma 4 E4B, em inglês | 30 | 0,08 (0,00 a 0,27) | 0,11 | 0,63 |
| fidelidade | fidelidade | Gemma 4 E4B, em português | 30 | 0,14 (0,00 a 0,44) | 0,23 | 0,73 |
| fidelidade | fidelidade | média dos juízes, em inglês | 30 | 0,04 (0,00 a 0,14) | 0,17 | 0,43 |
| fidelidade | fidelidade | média dos juízes, em português | 30 | 0,04 (0,00 a 0,14) | 0,14 | 0,40 |

Kappa ponderado (linear): 1 é concordância total e 0 é o que o acaso daria; discordar por um nível conta metade. Referência usual (Landis e Koch, 1977): de 0,41 a 0,60, moderada; de 0,61 a 0,80, substancial; acima de 0,80, quase perfeita. Spearman: se as notas sobem e descem juntas, sem depender dos cortes; com três níveis do lado da pessoa, ele não chega a 1 nem com a ordem toda certa (no máximo cerca de 0,94 com os níveis divididos por igual). IC 95%: intervalo de confiança de 95% por bootstrap (2000 reamostras das respostas, com a semente do sorteio). Com cerca de 30 respostas, o intervalo do kappa costuma ter perto de 0,5 de largura: diferenças menores que isso podem ser só acaso. Sem intervalo: poucas respostas, ou reamostras demais em que a medida não sai. "Um nível só de um lado": a pessoa ou o juiz deu o mesmo nível a todas as respostas, e aí o kappa não mede concordância (dá 0 ou não sai).

## Diferenças, nas mesmas respostas

| Comparação | Avaliador | Respostas | No kappa (IC 95%) | No Spearman (IC 95%) |
|-|-|-|-|-|
| português menos inglês: correção (F1) | Ministral 3 8B | 30 | -0,04 (-0,13 a 0,03) | -0,01 (-0,16 a 0,14) |
| português menos inglês: completude | Ministral 3 8B | 30 | 0,00 (-0,17 a 0,13) | -0,12 (-0,39 a 0,03) |
| português menos inglês: fidelidade | Ministral 3 8B | 30 | -0,01 (-0,05 a 0,02) | -0,07 |
| português menos inglês: correção (F1) | Gemma 4 E4B | 30 | +0,09 (-0,06 a 0,28) | -0,03 (-0,15 a 0,06) |
| português menos inglês: completude | Gemma 4 E4B | 30 | +0,02 (0,00 a 0,06) | +0,07 (0,00 a 0,19) |
| português menos inglês: fidelidade | Gemma 4 E4B | 30 | +0,06 (0,00 a 0,19) | +0,12 |
| português menos inglês: correção (F1) | média dos juízes | 30 | -0,01 (-0,07 a 0,04) | -0,02 (-0,12 a 0,07) |
| português menos inglês: completude | média dos juízes | 30 | +0,04 (0,00 a 0,12) | -0,04 (-0,12 a 0,00) |
| português menos inglês: fidelidade | média dos juízes | 30 | 0,00 (-0,03 a 0,03) | -0,02 |
| F1 menos completude | Ministral 3 8B, em inglês | 30 | +0,03 (-0,10 a 0,18) | +0,11 (-0,10 a 0,41) |
| F1 menos completude | Ministral 3 8B, em português | 30 | -0,01 (-0,21 a 0,21) | +0,22 (-0,07 a 0,55) |
| F1 menos completude | Gemma 4 E4B, em inglês | 30 | -0,03 (-0,26 a 0,18) | +0,28 (-0,01 a 0,63) |
| F1 menos completude | Gemma 4 E4B, em português | 30 | +0,04 (-0,19 a 0,29) | +0,18 (-0,07 a 0,52) |
| F1 menos completude | média dos juízes, em inglês | 30 | +0,01 (-0,16 a 0,18) | +0,18 (-0,02 a 0,46) |
| F1 menos completude | média dos juízes, em português | 30 | -0,04 (-0,23 a 0,15) | +0,20 (-0,01 a 0,49) |
| juiz menos a média: correção (F1) | Ministral 3 8B, em inglês | 30 | não se aplica | -0,04 (-0,15 a 0,03) |
| juiz menos a média: completude | Ministral 3 8B, em inglês | 30 | não se aplica | +0,03 (0,00 a 0,10) |
| juiz menos a média: fidelidade | Ministral 3 8B, em inglês | 30 | não se aplica | +0,05 |
| juiz menos a média: correção (F1) | Ministral 3 8B, em português | 30 | não se aplica | -0,03 (-0,15 a 0,06) |
| juiz menos a média: completude | Ministral 3 8B, em português | 30 | não se aplica | -0,05 (-0,21 a 0,05) |
| juiz menos a média: fidelidade | Ministral 3 8B, em português | 30 | não se aplica | +0,00 |
| juiz menos a média: correção (F1) | Gemma 4 E4B, em inglês | 30 | não se aplica | -0,01 (-0,06 a 0,03) |
| juiz menos a média: completude | Gemma 4 E4B, em inglês | 30 | não se aplica | -0,11 (-0,26 a 0,01) |
| juiz menos a média: fidelidade | Gemma 4 E4B, em inglês | 30 | não se aplica | -0,06 |
| juiz menos a média: correção (F1) | Gemma 4 E4B, em português | 30 | não se aplica | -0,02 (-0,11 a 0,07) |
| juiz menos a média: completude | Gemma 4 E4B, em português | 30 | não se aplica | +0,01 (-0,07 a 0,07) |
| juiz menos a média: fidelidade | Gemma 4 E4B, em português | 30 | não se aplica | +0,08 |

Positivo: a primeira nota concorda mais com a pessoa. Se o intervalo passa pelo zero, estas respostas não bastam para dizer qual das duas concorda mais; quando ele não passa, a tabela diz "todo acima de zero" ou "todo abaixo de zero", conferido nos valores sem arredondar (um limite muito perto de zero aparece com mais casas). Na comparação de cada juiz com a média, só o Spearman, que não depende dos cortes: com o corte de fiel em 1, a média só é fiel quando os dois juízes dão 1, o que puxaria o kappa da média para baixo. São várias comparações ao mesmo tempo, então um intervalo que não passa pelo zero ainda pode ser acaso; valem as que as regras combinadas antes do piloto mandam olhar.

Português menos inglês: o mesmo juiz (ou a média) com os prompts em português e em inglês, nas respostas que as duas versões avaliaram; positivo quando a versão em português concorda mais com a pessoa. Aqui o kappa também vale, porque as duas notas passam pelos mesmos cortes. O F1 contra a completude e cada juiz contra a média são comparados dentro de cada língua.

## Por modelo: nível do juiz menos o da pessoa, em média (média dos juízes, em inglês; média dos juízes, em português)

| Comparação | Llama 3.1 8B | Phi-4-mini 3.8B | Qwen 3.8 27B |
|-|-|-|-|
| correção x correção (F1) (média dos juízes, em inglês) | -0,70 (10) | -0,60 (10) | -0,50 (10) |
| correção x correção (F1) (média dos juízes, em português) | -0,60 (10) | -0,60 (10) | -0,60 (10) |
| correção x completude (média dos juízes, em inglês) | -0,20 (10) | -0,90 (10) | -0,40 (10) |
| correção x completude (média dos juízes, em português) | -0,20 (10) | -0,80 (10) | -0,30 (10) |
| fidelidade x fidelidade (média dos juízes, em inglês) | -0,80 (10) | -0,70 (10) | -0,60 (10) |
| fidelidade x fidelidade (média dos juízes, em português) | -0,70 (10) | -0,70 (10) | -0,50 (10) |

Positivo: o juiz deu níveis mais altos que a pessoa nas respostas daquele modelo (entre parênteses, quantas respostas). Com cerca de 10 respostas por modelo, só diferenças grandes dizem alguma coisa.

## Quantas vezes cada nível coincidiu (linhas: a pessoa; colunas: a média dos juízes)

**correção x correção (F1) (média dos juízes, em inglês)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 2 | 0 | 0 |
| parcial | 3 | 1 | 0 |
| correta | 1 | 13 | 10 |

**correção x correção (F1) (média dos juízes, em português)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 2 | 0 | 0 |
| parcial | 2 | 2 | 0 |
| correta | 1 | 14 | 9 |

**correção x completude (média dos juízes, em inglês)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 2 | 0 | 0 |
| parcial | 1 | 2 | 1 |
| correta | 3 | 9 | 12 |

**correção x completude (média dos juízes, em português)**

| | incorreta | parcial | correta |
|-|-|-|-|
| incorreta | 2 | 0 | 0 |
| parcial | 0 | 3 | 1 |
| correta | 3 | 8 | 13 |

**fidelidade x fidelidade (média dos juízes, em inglês)**

| | infiel | parcial | fiel |
|-|-|-|-|
| infiel | 0 | 0 | 0 |
| parcial | 0 | 1 | 0 |
| fiel | 4 | 13 | 12 |

**fidelidade x fidelidade (média dos juízes, em português)**

| | infiel | parcial | fiel |
|-|-|-|-|
| infiel | 0 | 0 | 0 |
| parcial | 0 | 1 | 0 |
| fiel | 1 | 17 | 11 |

