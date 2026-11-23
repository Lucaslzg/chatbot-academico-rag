"""Testes estatísticos das comparações (buscas e modelos), sem bibliotecas extras.

* mcnemar_exato: duas buscas ou dois modelos nas mesmas perguntas, com um
  resultado de sim ou não por pergunta (pôs o trecho certo no contexto? se
  absteve quando devia?). Olha só as perguntas em que os dois discordam.
* wilcoxon_pareado: dois modelos nas mesmas perguntas, com uma nota por
  pergunta (a correção ou a fidelidade do RAGAS, de 0 a 1). Olha a diferença
  de nota pergunta a pergunta, sem supor que as notas sigam a curva normal;
* concordancia_de_notas: dois juízes nas mesmas respostas: quanto as notas
  andam juntas (correlação de Pearson) e quanto diferem, em média;
* kappa_ponderado e spearman (versão 12, piloto dos juízes): uma pessoa e um
  juiz nas mesmas respostas. O kappa mede a concordância nos níveis
  (correta, parcial, incorreta) descontando a que aconteceria por acaso; o
  Spearman, se as notas sobem e descem juntas, sem depender de cortes;
* intervalo_bootstrap (versão 12): o intervalo de confiança de qualquer uma
  dessas medidas, sorteando de novo as respostas com reposição.
"""
from __future__ import annotations

import math
import random


def mcnemar_exato(b: int, c: int) -> float:
    """Teste de McNemar exato (bilateral) para duas buscas (ou dois modelos) nas mesmas perguntas.

    b = perguntas em que só a primeira acerta; c = só a segunda. As perguntas
    em que as duas acertam ou as duas erram não dizem nada sobre a diferença.
    Se as buscas fossem equivalentes, cada discordância cairia para um lado ou
    outro com chance de 1/2: o p é a chance de um desequilíbrio igual ou maior
    que o observado (binomial com n = b + c e p = 1/2). Ex.: 16 x 3 dá
    p ≈ 0,004 (diferença real); 8 x 7 dá p = 1 (empate).
    """
    n = b + c
    if n == 0:
        return 1.0
    cauda = sum(math.comb(n, x) for x in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * cauda)


def _postos(valores: list[float]) -> list[float]:
    """Postos de 1 a n, com a média dos postos para valores empatados."""
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    postos = [0.0] * len(valores)
    i = 0
    while i < len(ordem):
        j = i
        while j + 1 < len(ordem) and valores[ordem[j + 1]] == valores[ordem[i]]:
            j += 1
        for k in range(i, j + 1):
            postos[ordem[k]] = (i + j) / 2 + 1
        i = j + 1
    return postos


def wilcoxon_pareado(a: list[float], b: list[float]) -> dict:
    """Teste dos postos sinalizados de Wilcoxon (bilateral), exato.

    `a[i]` e `b[i]` são as notas dos dois modelos na mesma pergunta. As
    perguntas com diferença zero saem (método de Wilcoxon). As diferenças
    restantes são ordenadas pelo tamanho; W+ soma os postos das diferenças a
    favor do primeiro modelo. O p é exato: conta, entre os 2^n jeitos de
    trocar os sinais (o que aconteceria se os modelos fossem equivalentes),
    quantos dão um W+ tão desequilibrado quanto o observado. Os empates de
    tamanho recebem a média dos postos (múltiplos de 0,5), e a contagem é
    feita com os postos dobrados, que são inteiros.

    Devolve n (perguntas com diferença), w_mais, mediana_diferenca e p.
    Ex.: cinco perguntas, todas a favor do primeiro: p = 2/32 = 0,0625.
    """
    if len(a) != len(b):
        raise ValueError("as duas listas precisam ter o mesmo tamanho (uma nota por pergunta)")
    diferencas = [x - y for x, y in zip(a, b)]
    nao_nulas = [d for d in diferencas if abs(d) > 1e-12]
    ordenadas = sorted(diferencas)
    meio = len(ordenadas) // 2
    mediana = (0.0 if not ordenadas else ordenadas[meio] if len(ordenadas) % 2
               else (ordenadas[meio - 1] + ordenadas[meio]) / 2)
    n = len(nao_nulas)
    if n == 0:
        return {"n": 0, "w_mais": 0.0, "mediana_diferenca": mediana, "p": 1.0}
    postos = _postos([abs(d) for d in nao_nulas])
    w_mais = sum(r for r, d in zip(postos, nao_nulas) if d > 0)
    dobrados = [int(round(2 * r)) for r in postos]
    contagem = [0] * (sum(dobrados) + 1)
    contagem[0] = 1
    for r in dobrados:                         # quantos subconjuntos de postos somam cada valor
        for soma in range(len(contagem) - 1, r - 1, -1):
            contagem[soma] += contagem[soma - r]
    total = 2 ** n
    alvo = int(round(2 * w_mais))
    abaixo = sum(contagem[:alvo + 1]) / total
    acima = sum(contagem[alvo:]) / total
    return {"n": n, "w_mais": w_mais, "mediana_diferenca": mediana, "p": min(1.0, 2 * min(abaixo, acima))}


def concordancia_de_notas(pares: list[tuple[float, float]]) -> dict:
    """Concordância entre dois juízes nas mesmas respostas, com uma nota de 0 a 1 de cada um.

    Devolve n (respostas com nota dos dois), pearson (de -1 a 1: 1 quando um
    juiz dá nota alta exatamente onde o outro dá; None com menos de 3 pares
    ou quando um juiz deu a mesma nota a todas) e diferenca_media (a média da
    diferença absoluta entre as duas notas; 0 é concordância total).
    """
    n = len(pares)
    if n == 0:
        return {"n": 0, "pearson": None, "diferenca_media": None}
    diferenca = sum(abs(a - b) for a, b in pares) / n
    pearson = None
    if n >= 3:
        media_a = sum(a for a, _ in pares) / n
        media_b = sum(b for _, b in pares) / n
        cov = sum((a - media_a) * (b - media_b) for a, b in pares)
        var_a = sum((a - media_a) ** 2 for a, _ in pares)
        var_b = sum((b - media_b) ** 2 for _, b in pares)
        if var_a > 0 and var_b > 0:
            pearson = cov / math.sqrt(var_a * var_b)
    return {"n": n, "pearson": None if pearson is None else round(pearson, 3),
            "diferenca_media": round(diferenca, 3)}


def kappa_ponderado(pares: list[tuple[int, int]], categorias: int, pesos: str = "linear") -> float | None:
    """Kappa de Cohen ponderado entre dois avaliadores, com níveis ordenados de 0 a categorias - 1.

    Cada par é (nível do primeiro, nível do segundo) na mesma resposta. Com
    pesos lineares, discordar por um nível (correta x parcial) vale metade da
    concordância, e por dois (correta x incorreta), nada; com pesos="nenhum",
    é o kappa simples, em que só o nível igual conta. O kappa compara a
    concordância observada com a esperada se cada avaliador distribuísse os
    seus níveis ao acaso: 1 é concordância total, 0 é o que o acaso daria.
    None sem pares ou quando os dois deram o mesmo nível a todas as respostas
    (aí o acaso já explica tudo); se só um deles fez isso, o kappa é 0.
    Ex.: (0,0), (0,1), (1,1), (1,2), (2,2), (2,2) dá 0,625 (linear) e 0,5 (simples).
    """
    if not pares:
        return None
    if pesos not in ("linear", "nenhum"):
        raise ValueError("pesos deve ser \"linear\" ou \"nenhum\"")
    k = categorias
    if any(not (0 <= a < k and 0 <= b < k) for a, b in pares):
        raise ValueError(f"os níveis precisam estar entre 0 e {k - 1}")

    def peso(i: int, j: int) -> float:
        if pesos == "nenhum" or k == 1:
            return 1.0 if i == j else 0.0
        return 1 - abs(i - j) / (k - 1)
    n = len(pares)
    margem_a = [sum(1 for a, _ in pares if a == i) / n for i in range(k)]
    margem_b = [sum(1 for _, b in pares if b == j) / n for j in range(k)]
    observada = sum(peso(a, b) for a, b in pares) / n
    esperada = sum(peso(i, j) * margem_a[i] * margem_b[j] for i in range(k) for j in range(k))
    if 1 - esperada < 1e-12:
        return None
    return round((observada - esperada) / (1 - esperada), 3)


def spearman(pares: list[tuple[float, float]]) -> float | None:
    """Correlação de Spearman: a de Pearson calculada sobre os postos (empates com a média dos postos).

    Não depende de cortes: mede se, onde um avaliador dá nota maior, o outro
    também dá. None com menos de 3 pares ou quando um dos lados não varia.
    """
    if len(pares) < 3:
        return None
    postos_a = _postos([a for a, _ in pares])
    postos_b = _postos([b for _, b in pares])
    return concordancia_de_notas(list(zip(postos_a, postos_b)))["pearson"]


def _percentil(ordenados: list[float], q: float) -> float:
    """O percentil q (de 0 a 1) de valores já ordenados, com interpolação linear (o padrão do NumPy)."""
    posicao = q * (len(ordenados) - 1)
    baixo = math.floor(posicao)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (posicao - baixo)


def intervalo_bootstrap(itens: list, medida, reamostras: int = 2000, semente: int = 0,
                        nivel: float = 0.95) -> tuple[float, float] | None:
    """Intervalo de confiança de uma medida pelo bootstrap percentil.

    Sorteia, com reposição, tantos itens quantos há (cada item é uma resposta,
    com as notas que entram na conta), calcula a medida nessa amostra e repete
    reamostras vezes; o intervalo de 95% vai do percentil 2,5 ao 97,5 dos
    valores obtidos. Mostra quanto a medida mudaria com outras respostas do
    mesmo tipo: com 30 respostas, um kappa de 0,6 pode estar, na verdade,
    entre cerca de 0,35 e 0,8. As reamostras em que a medida não pode ser
    calculada (o kappa quando os dois avaliadores dão o mesmo nível a tudo,
    por exemplo) são puladas; se forem mais de 10%, o intervalo não seria
    confiável, e a função devolve None, como também com menos de 2 itens.
    A mesma semente dá sempre o mesmo intervalo.
    """
    n = len(itens)
    if n < 2:
        return None
    sorteio = random.Random(semente)
    valores = []
    for _ in range(reamostras):
        valor = medida([itens[sorteio.randrange(n)] for _ in range(n)])
        if valor is not None:
            valores.append(valor)
    if not valores or len(valores) < 0.9 * reamostras:
        return None
    valores.sort()
    cauda = (1 - nivel) / 2
    return round(_percentil(valores, cauda), 3), round(_percentil(valores, 1 - cauda), 3)
