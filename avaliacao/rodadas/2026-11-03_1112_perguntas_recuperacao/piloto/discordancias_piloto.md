# Discordâncias entre a avaliação humana e os juízes no piloto

Rodada de teste `2026-11-03_1112_perguntas_recuperacao`, 30 respostas do piloto (10 de cada modelo). Análise feita pelo Claude em 14/11/2026, depois do resultado do piloto, para a discussão da monografia.

**De onde vêm os dados.** As notas da avaliação humana e a média dos dois juízes em português estão no `piloto/piloto_resultado.json`. O que cada juiz apontou, com o motivo que ele mesmo escreveu, está nas notas dele (`juizes_em_portugues/juiz_<juiz>/ragas_<modelo>.jsonl`): na completude, as afirmações da resposta de referência que ele não achou na resposta; na fidelidade, as afirmações da resposta que ele não achou nos trechos. Os trechos que o modelo recebeu estão no `contextos.json` da rodada. Os dados extraídos estão em `discordancias_piloto.json`, ao lado deste arquivo, gravado pelo script `Claude outputs\discordancias_piloto.py` (`python discordancias_piloto.py <pasta da rodada> <saída.json>`), que não faz parte do chatbot.

**Como a comparação foi feita.** A média dos dois juízes em português foi convertida nos níveis do caderno pelos cortes fixados antes do piloto: na correção, abaixo de 0,25 é incorreta e a partir de 0,75 é correta; na fidelidade, fiel só com a nota 1, e infiel abaixo de 0,5. A nota de correção usada é a completude, a principal. Há discordância quando o nível dos juízes é outro que o da avaliação humana.

**O que esta análise não faz.** Ela descreve o que os juízes apontaram e o que está nos textos (a resposta, a resposta de referência e os trechos). Ela não avalia as notas humanas. Os tipos de causa foram atribuídos pelo Claude, a partir dos motivos registrados pelos juízes e da conferência nos trechos; um item pode ter mais de uma causa, e a tabela mostra a principal.

## Resumo

| Nota | Juízes abaixo da avaliação humana | Juízes acima | Concordam |
|-|-|-|-|
| Completude | 11 | 1 | 18 |
| Fidelidade | 18 | 0 | 12 |

- **Completude.** Nas 11 respostas em que os juízes ficaram abaixo, todas dadas como corretas pela avaliação humana, a causa principal é uma só em 8: a resposta traz o dado que a pergunta pede, igual ao da resposta de referência, e o juiz aponta detalhes a mais da referência que a resposta não traz. Nas outras 3: a referência enumera casos que a resposta resume numa palavra (1), a resposta não traz um item da referência e um dos juízes errou ao dividir a referência em afirmações (1), e a resposta afirma o contrário da referência (1).
- **Fidelidade.** Nas 18 respostas em que os juízes ficaram abaixo, todas dadas como fiéis pela avaliação humana, só um juiz apontou algo em 11 (o Ministral 3 8B em 10, o Gemma 4 E4B em 1). Com o corte de fiel em 1, uma afirmação apontada por um juiz só basta para a média sair de fiel. Em 6 das 18, o que foi apontado é conteúdo da resposta que contraria os trechos ou não está neles (4) ou a resposta diz que não encontrou uma informação que está nos trechos (2). Nas outras 12, a causa está do lado do juiz ou da métrica: leitura literal de uma paráfrase fiel (5), afirmação reescrita pelo próprio juiz com erro (3), frase de abstenção ou de limite, sem conteúdo a conferir nos trechos (2), e informação que está nos trechos e o juiz não achou (2).

## 1. Completude: onde os juízes ficaram abaixo

Tipos: **A**, a resposta traz o dado que a pergunta pede, igual ao da referência, e o juiz aponta detalhes a mais da referência que ela não traz; **B**, falta um item da referência e um juiz errou na divisão em afirmações; **C**, a referência enumera casos que a resposta resume; **D**, a resposta afirma o contrário da referência.

| Código | Modelo, pergunta | Completude: média (Ministral / Gemma) | O que os juízes não acharam na resposta | Tipo |
|-|-|-|-|-|
| P06 | Phi-4-mini, R46 (tempo máximo do curso) | 0,42 (0,33 / 0,50) | A duração prevista de 10 semestres e que o máximo é o dobro dela. A resposta traz os 20 semestres. | A |
| P23 | Qwen 3.8 27B, R46 (a mesma) | 0,42 (0,33 / 0,50) | O mesmo que na P06. A resposta traz os 20 semestres e a regra geral do tempo mínimo mais 100%. | A |
| P11 | Qwen 3.8 27B, R45 (horas de estágio por semana) | 0,67 (0,67 / 0,67) | Os limites diários (6 horas; 8 horas na jornada de 40). A resposta traz as 30 e as 40 horas semanais. | A |
| P12 | Llama 3.1 8B, R48 (filhos no restaurante universitário) | 0,63 (0,67 / 0,60) | A refeição subsidiada, conforme o orçamento e normas específicas. A resposta traz o sim e a condição do acesso. | A |
| P16 | Phi-4-mini, R29 (disciplinas em outro campus) | 0,17 (0,17 / 0,17) | O limite de 14 componentes e os quatro requisitos (situação regular, plano de atividades, créditos mínimos, prazo do calendário). A resposta traz o sim e a mobilidade intrainstitucional. | A |
| P26 | Phi-4-mini, R42 (créditos de Cálculo I) | 0,50 (0,50 / 0,50) | A carga horária de 60 horas. A resposta traz os 4 créditos. | A |
| P27 | Phi-4-mini, R01 (quantos trancamentos totais) | 0,71 (0,75 / 0,67) | A ressalva "exceto nos casos previstos em legislação". A resposta traz os 2 consecutivos ou 4 intercalados. | A |
| P29 | Qwen 3.8 27B, R20 (TCC com defesa pública) | 0,33 (0,33 / 0,33) | Que, no curso de Engenharia de Computação, a apresentação é num seminário no fim do semestre. A resposta traz o sim e a norma que exige a defesa pública. | A |
| P24 | Phi-4-mini, R34 (o que é preciso para o diploma) | 0,69 (0,67 / 0,71) | Os dois juízes: a colação de grau como condição para o diploma, que a resposta não traz. O Ministral também acrescentou uma sigla errada (ENEM) ao Exame Nacional de Desempenho de Estudantes, na afirmação da referência, e por isso não a achou na resposta, que diz ENADE. | B |
| P19 | Phi-4-mini, R33 (licença por falecimento) | 0,00 (0,00 / 0,00) | A referência lista os parentes (cônjuge, companheiro, pais, avós, irmão, filho e outros), e a resposta diz "um familiar". O Ministral dividiu a referência em 12 afirmações, uma por parente, e não aceitou "familiar" em nenhuma; o Gemma manteve a lista inteira numa afirmação só e também não a achou. A resposta traz os 8 dias consecutivos. | C |
| P10 | Llama 3.1 8B, R02 (ingressante pode trancar) | 0,00 (0,00 / 0,00) | A resposta diz que sim; a referência e o Art. 37, § 1º, dos trechos dizem que não, salvo o serviço militar obrigatório. Os dois juízes registraram a contradição. | D |

Nas 8 do tipo A, o que o juiz aponta de fato não está na resposta: a completude mede quanto da resposta de referência inteira a resposta traz, e as referências das perguntas de teste foram escritas com detalhes além do que a pergunta pede. A avaliação humana registra, numa das observações (P16), que olhou para o que quem perguntou precisaria saber. A diferença, nesses casos, está no critério: cobertura da referência, de um lado; resposta suficiente para a pergunta, do outro.

## 2. Completude: onde os juízes ficaram acima

| Código | Modelo, pergunta | Completude: média (Ministral / Gemma) | F1 (média) | O que explica |
|-|-|-|-|-|
| P02 | Llama 3.1 8B, R14 (prazo do atestado médico) | 0,88 (0,75 / 1,00) | 0,29 | A completude conta só as afirmações da referência que a resposta traz, e esta traz o prazo de 5 dias consecutivos. Ela não desconta o que a resposta acrescenta: aqui, outros prazos misturados (5 dias úteis, de outro tipo de licença). O F1 desconta, e ficou em 0,29. |

## 3. Fidelidade: onde os juízes ficaram abaixo

Tipos: **a1**, a resposta afirma algo que contraria os trechos ou não está neles; **a2**, a resposta diz que não encontrou uma informação que está nos trechos; **b**, frase de abstenção, de limite ou de introdução, sem conteúdo a conferir nos trechos; **c**, o juiz reescreveu a afirmação com erro e julgou a própria reescrita; **d**, leitura literal demais de uma paráfrase fiel; **e**, informação que está nos trechos e o juiz não achou.

| Código | Modelo, pergunta | Fidelidade: média (Ministral / Gemma) | Quem apontou | O que foi apontado | Tipo |
|-|-|-|-|-|-|
| P10 | Llama 3.1 8B, R02 (ingressante pode trancar) | 0,56 (0,40 / 0,71) | os dois | Que o ingressante pode trancar e que isso está no Art. 37, § 1º: o parágrafo diz o contrário. | a1 |
| P25 | Phi-4-mini, R39 (início do semestre 2026/1) | 0,30 (0,40 / 0,20) | os dois | As datas: a resposta dá 19/01, início do Período Letivo Especial I, e 20/07, que pelos trechos é o início do Período Letivo Especial II; pelos trechos, o semestre começa em 09/03/2026. | a1 |
| P05 | Llama 3.1 8B, R24 (aproveitamento na transferência) | 0,65 (0,50 / 0,80) | os dois | A conclusão de que até 50% vale para quem entra por transferência: o trecho que a resposta cita excetua os casos de transferência. O Gemma apontou também a frase "A resposta está no documento...". | a1 |
| P16 | Phi-4-mini, R29 (disciplinas em outro campus) | 0,75 (0,50 / 1,00) | Ministral | O "ou Interinstitucional": pelos trechos, a mobilidade interinstitucional é com outras instituições, não entre campi da UNIPAMPA. | a1 |
| P02 | Llama 3.1 8B, R14 (prazo do atestado médico) | 0,65 (0,40 / 0,90) | os dois | A frase de que não encontrou o prazo da licença maternidade: o Art. 12 está nos trechos. O Ministral apontou também duas frases sobre os prazos misturados. | a2 |
| P09 | Llama 3.1 8B, R41 (horário da biblioteca) | 0,78 (0,80 / 0,75) | os dois | A frase de que não encontrou os horários da Biblioteca Digital: o trecho, e a própria resposta, dizem acesso em tempo integral. | a2 |
| P12 | Llama 3.1 8B, R48 (filhos no restaurante universitário) | 0,90 (0,80 / 1,00) | Ministral | A frase de que não há informação sobre o valor a pagar. | b |
| P30 | Llama 3.1 8B, R21 (quem pode orientar estágio) | 0,50 (0,50 / 0,50) | os dois | A frase padrão de abstenção ("Não encontrei essa informação nos documentos disponíveis. Procure a coordenação do seu curso"). O Ministral também reescreveu "atribuições" do Art. 34 como "requisitos" e rejeitou a reescrita. | b |
| P17 | Llama 3.1 8B, R25 (o que é o reingresso) | 0,83 (0,67 / 1,00) | Ministral | Reescreveu UNIPAMPA como "Universidade da Região da Campanha" e julgou se o reingresso era exclusivo dela; apontou também a frase de que não encontrou a finalidade do reingresso. | c |
| P19 | Phi-4-mini, R33 (licença por falecimento) | 0,75 (1,00 / 0,50) | Gemma | Reescreveu "Você tem 8 dias" como "O funcionário tem 8 dias" e rejeitou porque os trechos falam de estudantes. | c |
| P27 | Phi-4-mini, R01 (quantos trancamentos totais) | 0,90 (0,80 / 1,00) | Ministral | Criou a afirmação "os semestres consecutivos devem ser adjacentes", que a resposta não faz, e a rejeitou. | c |
| P14 | Qwen 3.8 27B, R47 (nome social) | 0,95 (0,91 / 1,00) | Ministral | "Em documento de próprio punho" virou "escrito à mão", rejeitado porque o trecho não diz que é obrigatório escrever à mão. | d |
| P18 | Qwen 3.8 27B, R37 (modalidades do processo seletivo) | 0,95 (0,90 / 1,00) | Ministral | "Poderão ser criadas outras modalidades conforme demandas institucionais" contra "dependem de demandas específicas". | d |
| P22 | Qwen 3.8 27B, R17 (grupos de atividades complementares) | 0,87 (0,88 / 0,86) | os dois | O Gemma apontou a frase de introdução ("Os grupos são os seguintes:"); o Ministral, o nome do Grupo IV no PPC de 2019, embora o próprio motivo dele diga que os trechos não o contrariam. | d |
| P24 | Phi-4-mini, R34 (o que é preciso para o diploma) | 0,96 (0,92 / 1,00) | Ministral | "Quite com as pendências da biblioteca" contra "sem pendências (débitos) com a biblioteca": rejeitou porque o trecho não diz "todas". | d |
| P29 | Qwen 3.8 27B, R20 (TCC com defesa pública) | 0,90 (0,80 / 1,00) | Ministral | Que a Instrução Normativa nº 16/2024 detalha os procedimentos da defesa: rejeitou porque o trecho não diz isso "explicitamente". | d |
| P11 | Qwen 3.8 27B, R45 (horas de estágio por semana) | 0,95 (0,91 / 1,00) | Ministral | A exceção das 40 horas (fora do período letivo ou quando o estágio é o único componente): ela está nos trechos 3 e 5, que a resposta cita. | e |
| P26 | Phi-4-mini, R42 (créditos de Cálculo I) | 0,50 (0,00 / 1,00) | Ministral | Os 4 créditos de Cálculo I: estão no trecho 6, numa tabela de equivalências (a resposta cita o trecho 5). | e |

## 4. O que isso mostra, para a discussão

1. **Na completude, a maior parte da diferença é de critério.** Em 8 das 11 respostas, o juiz aponta corretamente detalhes da referência que a resposta não traz, e a resposta traz o que a pergunta pede. A completude mede a cobertura da resposta de referência inteira, e não se a resposta basta para quem perguntou. Isso pesa na leitura do resultado final, porque as respostas de referência das perguntas reais vão ser escritas pelo Lucas. Ponto a decidir: escrever a referência com o que a pergunta pede (e os detalhes a mais à parte, se houver) ou manter as referências completas e apresentar a completude como cobertura da referência.
2. **O juiz divide e reescreve, e erra ao fazer isso.** Na completude, a divisão da referência em afirmações define a nota: na P19, 12 afirmações, uma por parente, contra uma só no outro juiz. Na fidelidade, 3 das 18 discordâncias vêm de uma reescrita errada do próprio juiz ("o funcionário", "Universidade da Região da Campanha", "adjacentes"), e o mesmo aparece de passagem em outras duas (P24, com "ENEM", e P30, com "requisitos"). Os prompts em português tiraram as afirmações em inglês, mas não esse tipo de erro.
3. **Na fidelidade, o corte em 1 e a média de dois juízes tornam a nota muito sensível a um juiz só.** Em 11 das 18 discordâncias, só um juiz apontou algo, quase sempre o Ministral 3 8B (10), que lê de forma mais literal que o Gemma 4 E4B (os 5 casos do tipo d são dele). Uma afirmação rejeitada entre 11 já tira a resposta de fiel.
4. **As frases de abstenção e de limite contam como afirmações sem apoio.** "Não encontrei essa informação", "procure a coordenação" e frases de introdução não têm o que conferir nos trechos, e a fidelidade do RAGAS as trata como afirmações que os trechos não sustentam. Ponto a decidir antes da medição final: tirar a frase padrão de abstenção do texto que vai ao juiz, como já se faz com as marcas de citação desde a versão 10, ou manter e registrar esse efeito. Quando a resposta diz que não encontrou algo que está nos trechos (P02 e P09), o juiz aponta um problema real.
5. **Onde os juízes apontam problemas de conteúdo.** Em 6 respostas (P02, P05, P09, P10, P16 e P25), o que foi apontado é conteúdo da resposta que contraria os trechos ou não está neles. Nas outras 12 discordâncias de fidelidade, a causa está do lado do juiz ou da métrica.

**Limitações.** São 30 respostas e um avaliador só, que é o autor. Os tipos foram atribuídos pelo Claude e não por uma segunda pessoa. A análise usa só os juízes em português, que ficaram pela regra do piloto; os juízes em inglês têm as próprias falhas, já descritas no item 4.17 do `ERROS_CORRIGIDOS.md`.
