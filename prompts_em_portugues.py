"""Os prompts do RAGAS em português, para o juiz em português (versão 13).

Os prompts do RAGAS vêm em inglês, com exemplos em inglês, e os juízes
escrevem cerca de metade das afirmações em inglês, às vezes traduzindo errado
(na avaliação de 04/11/2026, "Você tem 8 dias de licença" virou "The employee
is entitled...", e a fidelidade de uma resposta certa foi a zero). O juiz em
português usa os mesmos prompts com duas mudanças:

1. os exemplos em português: é o que o método adapt do RAGAS faz (troca cada
   texto dos exemplos pela tradução e deixa a instrução em inglês), só que a
   tradução fica fixa aqui, a mesma para os dois juízes, em vez de ser feita
   por um modelo de linguagem a cada execução. Os nomes próprios ficam como
   estão, e os valores "low" e "high" (o nível de detalhe pedido na divisão em
   afirmações) também, porque são opções do RAGAS e não texto;
2. uma frase no fim da instrução pedindo a saída em português
   (INSTRUCAO_EM_PORTUGUES).

Os prompts das quatro notas estão aqui: correção, completude e fidelidade
(versão 13) e a cobertura dos trechos (versão 15).

Se uma versão nova do RAGAS mudar algum exemplo, em_portugues avisa qual texto
ficou sem tradução, em vez de mandar ao juiz um exemplo metade em inglês.
"""
from __future__ import annotations

import copy

INSTRUCAO_EM_PORTUGUES = ("The input is in Brazilian Portuguese. Write every statement, claim and reason of the output "
                          "in Brazilian Portuguese, as in the examples, and do not translate anything into English.")

# Opções do RAGAS que aparecem nos exemplos e não são texto para traduzir.
NAO_TRADUZIR = {"low", "high"}

# Cada texto dos exemplos do RAGAS 0.4.3 (Factual Correctness e Faithfulness) e a tradução dele.
TRADUCOES = {
    # Divisão em afirmações (correção e completude)
    "Charles Babbage was a French mathematician, philosopher, and food critic.":
        "Charles Babbage foi um matemático, filósofo e crítico gastronômico francês.",
    "Charles Babbage was a mathematician and philosopher.":
        "Charles Babbage foi matemático e filósofo.",
    "Albert Einstein was a German theoretical physicist. He developed the theory of relativity and also contributed to "
    "the development of quantum mechanics.":
        "Albert Einstein foi um físico teórico alemão. Ele desenvolveu a teoria da relatividade e também contribuiu para "
        "o desenvolvimento da mecânica quântica.",
    "Albert Einstein was a German physicist.":
        "Albert Einstein foi um físico alemão.",
    "Albert Einstein developed relativity and contributed to quantum mechanics.":
        "Albert Einstein desenvolveu a relatividade e contribuiu para a mecânica quântica.",
    # (os outros níveis de detalhe da divisão em afirmações, que o projeto não usa, mas o prompt carrega)
    "Albert Einstein was a German theoretical physicist.":
        "Albert Einstein foi um físico teórico alemão.",
    "Albert Einstein developed the theory of relativity and also contributed to the development of quantum mechanics.":
        "Albert Einstein desenvolveu a teoria da relatividade e também contribuiu para o desenvolvimento da mecânica "
        "quântica.",
    "Charles Babbage was a mathematician.":
        "Charles Babbage foi matemático.",
    "Charles Babbage was a philosopher.":
        "Charles Babbage foi filósofo.",
    "Charles Babbage was a food critic.":
        "Charles Babbage foi crítico gastronômico.",
    "Charles Babbage was French.":
        "Charles Babbage era francês.",
    "Albert Einstein developed the theory of relativity.":
        "Albert Einstein desenvolveu a teoria da relatividade.",
    "Albert Einstein contributed to the development of quantum mechanics.":
        "Albert Einstein contribuiu para o desenvolvimento da mecânica quântica.",
    # Conferência das afirmações contra um texto (correção, completude e fidelidade)
    "John is a student at XYZ University. He is pursuing a degree in Computer Science. He is enrolled in several "
    "courses this semester, including Data Structures, Algorithms, and Database Management. John is a diligent student "
    "and spends a significant amount of time studying and completing assignments. He often stays late in the library "
    "to work on his projects.":
        "John é estudante da Universidade XYZ. Ele cursa Ciência da Computação. Neste semestre, está matriculado em "
        "várias disciplinas, entre elas Estruturas de Dados, Algoritmos e Gerenciamento de Banco de Dados. John é um "
        "estudante aplicado e passa bastante tempo estudando e fazendo os trabalhos. Muitas vezes, fica até tarde na "
        "biblioteca trabalhando nos seus projetos.",
    "John is majoring in Biology.":
        "John cursa Biologia.",
    "John is taking a course on Artificial Intelligence.":
        "John está fazendo uma disciplina de Inteligência Artificial.",
    "John is a dedicated student.":
        "John é um estudante dedicado.",
    "John has a part-time job.":
        "John tem um emprego de meio período.",
    "John's major is explicitly stated as Computer Science, not Biology.":
        "O contexto diz explicitamente que John cursa Ciência da Computação, e não Biologia.",
    "The context mentions courses in Data Structures, Algorithms, and Database Management, but does not mention "
    "Artificial Intelligence.":
        "O contexto menciona as disciplinas de Estruturas de Dados, Algoritmos e Gerenciamento de Banco de Dados, mas "
        "não menciona Inteligência Artificial.",
    "The context states that John is a diligent student who spends a significant amount of time studying and "
    "completing assignments.":
        "O contexto diz que John é um estudante aplicado, que passa bastante tempo estudando e fazendo os trabalhos.",
    "There is no information in the context about John having a part-time job.":
        "Não há informação no contexto sobre John ter um emprego de meio período.",
    # Divisão da resposta em afirmações (fidelidade)
    "Who was Albert Einstein and what is he best known for?":
        "Quem foi Albert Einstein e pelo que ele é mais conhecido?",
    "He was a German-born theoretical physicist, widely acknowledged to be one of the greatest and most influential "
    "physicists of all time. He was best known for developing the theory of relativity, he also made important "
    "contributions to the development of the theory of quantum mechanics.":
        "Ele foi um físico teórico nascido na Alemanha, amplamente reconhecido como um dos maiores e mais influentes "
        "físicos de todos os tempos. Ele ficou mais conhecido por desenvolver a teoria da relatividade e também deu "
        "contribuições importantes para o desenvolvimento da teoria da mecânica quântica.",
    "Albert Einstein was a German-born theoretical physicist.":
        "Albert Einstein foi um físico teórico nascido na Alemanha.",
    "Albert Einstein is recognized as one of the greatest and most influential physicists of all time.":
        "Albert Einstein é reconhecido como um dos maiores e mais influentes físicos de todos os tempos.",
    "Albert Einstein was best known for developing the theory of relativity.":
        "Albert Einstein ficou mais conhecido por desenvolver a teoria da relatividade.",
    "Albert Einstein made important contributions to the development of the theory of quantum mechanics.":
        "Albert Einstein deu contribuições importantes para o desenvolvimento da teoria da mecânica quântica.",
    # Cobertura dos trechos (versão 15)
    "What can you tell me about Albert Einstein?":
        "O que você pode me dizer sobre Albert Einstein?",
    "Albert Einstein (14 March 1879 - 18 April 1955) was a German-born theoretical physicist, widely held to be one "
    "of the greatest and most influential scientists of all time. Best known for developing the theory of relativity, "
    "he also made important contributions to quantum mechanics, and was thus a central figure in the revolutionary "
    "reshaping of the scientific understanding of nature that modern physics accomplished in the first decades of the "
    "twentieth century. His mass-energy equivalence formula E = mc2, which arises from relativity theory, has been "
    "called 'the world's most famous equation'. He received the 1921 Nobel Prize in Physics 'for his services to "
    "theoretical physics, and especially for his discovery of the law of the photoelectric effect', a pivotal step in "
    "the development of quantum theory. His work is also known for its influence on the philosophy of science. In a "
    "1999 poll of 130 leading physicists worldwide by the British journal Physics World, Einstein was ranked the "
    "greatest physicist of all time. His intellectual achievements and originality have made Einstein synonymous with "
    "genius.":
        "Albert Einstein (14 de março de 1879 - 18 de abril de 1955) foi um físico teórico nascido na Alemanha, "
        "amplamente considerado um dos maiores e mais influentes cientistas de todos os tempos. Mais conhecido por "
        "desenvolver a teoria da relatividade, ele também deu contribuições importantes para a mecânica quântica e "
        "foi, assim, uma figura central na reformulação revolucionária da compreensão científica da natureza que a "
        "física moderna realizou nas primeiras décadas do século XX. A sua fórmula da equivalência entre massa e "
        "energia, E = mc2, que decorre da teoria da relatividade, foi chamada de 'a equação mais famosa do mundo'. "
        "Ele recebeu o Prêmio Nobel de Física de 1921 'por seus serviços à física teórica e, especialmente, pela "
        "descoberta da lei do efeito fotoelétrico', um passo decisivo no desenvolvimento da teoria quântica. O seu "
        "trabalho também é conhecido pela influência na filosofia da ciência. Numa pesquisa de 1999 com 130 físicos "
        "de destaque do mundo todo, feita pela revista britânica Physics World, Einstein foi apontado como o maior "
        "físico de todos os tempos. As suas realizações intelectuais e a sua originalidade fizeram de Einstein "
        "sinônimo de genialidade.",
    "Albert Einstein, born on 14 March 1879, was a German-born theoretical physicist, widely held to be one of the "
    "greatest and most influential scientists of all time. He received the 1921 Nobel Prize in Physics for his "
    "services to theoretical physics. He published 4 papers in 1905. Einstein moved to Switzerland in 1895.":
        "Albert Einstein, nascido em 14 de março de 1879, foi um físico teórico nascido na Alemanha, amplamente "
        "considerado um dos maiores e mais influentes cientistas de todos os tempos. Ele recebeu o Prêmio Nobel de "
        "Física de 1921 por seus serviços à física teórica. Ele publicou 4 artigos em 1905. Einstein se mudou para a "
        "Suíça em 1895.",
    "Albert Einstein, born on 14 March 1879, was a German-born theoretical physicist, widely held to be one of the "
    "greatest and most influential scientists of all time.":
        "Albert Einstein, nascido em 14 de março de 1879, foi um físico teórico nascido na Alemanha, amplamente "
        "considerado um dos maiores e mais influentes cientistas de todos os tempos.",
    "The date of birth of Einstein is mentioned clearly in the context.":
        "A data de nascimento de Einstein está clara no contexto.",
    "He received the 1921 Nobel Prize in Physics for his services to theoretical physics.":
        "Ele recebeu o Prêmio Nobel de Física de 1921 por seus serviços à física teórica.",
    "The exact sentence is present in the given context.":
        "A mesma frase está no contexto dado.",
    "He published 4 papers in 1905.":
        "Ele publicou 4 artigos em 1905.",
    "There is no mention about papers he wrote in the given context.":
        "O contexto dado não menciona artigos que ele escreveu.",
    "Einstein moved to Switzerland in 1895.":
        "Einstein se mudou para a Suíça em 1895.",
    "There is no supporting evidence for this in the given context.":
        "Nada no contexto dado sustenta isso.",
    "who won 2020 icc world cup?":
        "quem ganhou a copa do mundo da icc de 2020?",
    "The 2022 ICC Men's T20 World Cup, held from October 16 to November 13, 2022, in Australia, was the eighth "
    "edition of the tournament. Originally scheduled for 2020, it was postponed due to the COVID-19 pandemic. England "
    "emerged victorious, defeating Pakistan by five wickets in the final to clinch their second ICC Men's T20 World "
    "Cup title.":
        "A Copa do Mundo Masculina de T20 da ICC de 2022, disputada de 16 de outubro a 13 de novembro de 2022, na "
        "Austrália, foi a oitava edição do torneio. Prevista inicialmente para 2020, ela foi adiada por causa da "
        "pandemia de COVID-19. A Inglaterra foi a campeã, ao vencer o Paquistão por cinco wickets na final e "
        "conquistar o seu segundo título da Copa do Mundo Masculina de T20 da ICC.",
    "England":
        "Inglaterra",
    "The context clarifies that England won the 2022 edition (which was originally scheduled for 2020).":
        "O contexto esclarece que a Inglaterra venceu a edição de 2022 (que estava prevista inicialmente para 2020).",
    "What is the tallest mountain in the world?":
        "Qual é a montanha mais alta do mundo?",
    "The Andes is the longest continental mountain range in the world, located in South America. It stretches across "
    "seven countries and features many of the highest peaks in the Western Hemisphere. The range is known for its "
    "diverse ecosystems, including the high-altitude Andean Plateau and the Amazon rainforest.":
        "Os Andes são a cordilheira continental mais longa do mundo, na América do Sul. Eles se estendem por sete "
        "países e têm muitos dos picos mais altos do Hemisfério Ocidental. A cordilheira é conhecida pela diversidade "
        "dos seus ecossistemas, entre eles o Altiplano Andino e a floresta amazônica.",
    "Mount Everest.":
        "Monte Everest.",
    "The provided context discusses the Andes mountain range, which does not include Mount Everest or directly relate "
    "to the world's tallest mountain.":
        "O contexto fala da cordilheira dos Andes, que não inclui o Monte Everest nem trata diretamente da montanha "
        "mais alta do mundo.",
}


class TraducaoIncompleta(ValueError):
    """Um texto dos exemplos do RAGAS instalado não tem tradução em TRADUCOES."""


def _conjuntos_de_exemplos(prompt) -> list:
    """Os exemplos do prompt e, na divisão em afirmações, os de cada nível de detalhe (_all_examples), que o
    prompt troca na hora de montar o texto."""
    todos = getattr(prompt, "_all_examples", None)
    return [prompt.examples] + (list(todos.values()) if isinstance(todos, dict) else [])


def textos_dos_exemplos(prompt) -> list[str]:
    """Os textos dos exemplos de um prompt do RAGAS, sem repetir, na ordem em que aparecem."""
    from ragas.prompt.utils import get_all_strings
    textos = [t for conjunto in _conjuntos_de_exemplos(prompt) for t in get_all_strings(conjunto)]
    return [t for t in dict.fromkeys(textos) if t not in NAO_TRADUZIR]


def em_portugues(prompt):
    """Uma cópia do prompt do RAGAS com os exemplos em português e a frase que pede a saída em português.

    O prompt original não muda (os exemplos são da classe, compartilhados por
    todas as métricas), e a troca dos textos usa a mesma função do adapt do
    RAGAS (update_strings), que mantém a estrutura dos exemplos.
    """
    from ragas.prompt.utils import update_strings
    textos = textos_dos_exemplos(prompt)
    faltam = [t for t in textos if t not in TRADUCOES]
    if faltam:
        raise TraducaoIncompleta(
            f"o exemplo do prompt {type(prompt).__name__} desta versão do RAGAS tem texto sem tradução "
            f"(prompts_em_portugues.TRADUCOES): {faltam[0][:120]!r}" + (f" e mais {len(faltam) - 1}" if len(faltam) > 1
                                                                        else ""))
    traducao = [TRADUCOES[t] for t in textos]
    novo = copy.deepcopy(prompt)
    novo.examples = update_strings(obj=prompt.examples, old_strings=textos, new_strings=traducao)
    todos = getattr(prompt, "_all_examples", None)
    if isinstance(todos, dict):
        novo._all_examples = {nivel: update_strings(obj=exemplos, old_strings=textos, new_strings=traducao)
                              for nivel, exemplos in todos.items()}
    novo.instruction = prompt.instruction.rstrip() + "\n" + INSTRUCAO_EM_PORTUGUES
    novo.language = "portuguese"
    return novo
