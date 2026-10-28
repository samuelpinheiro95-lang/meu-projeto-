"""Seleção dos melhores momentos do vídeo.

- Com chave do Claude: a IA lê a transcrição (com tempos e volume) e escolhe os trechos mais interessantes.
- Sem chave (ou sem fala): modo automático que pontua janelas pelo volume do áudio e pela quantidade de fala.
"""

import json

from .config import MODELO_CLAUDE

ESQUEMA = {
    "type": "object",
    "properties": {
        "momentos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "number", "description": "segundo de início no vídeo original"},
                    "fim": {"type": "number", "description": "segundo de fim no vídeo original"},
                    "titulo": {"type": "string", "description": "título curto e chamativo para o corte"},
                    "motivo": {"type": "string", "description": "por que este trecho é bom, em uma frase"},
                    "nota": {"type": "integer", "description": "0 a 100, potencial de engajamento"},
                },
                "required": ["inicio", "fim", "titulo", "motivo", "nota"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["momentos"],
    "additionalProperties": False,
}

SISTEMA = """Você é um editor de vídeo experiente, especialista em encontrar os melhores momentos de vídeos longos \
para virar cortes (Reels, Shorts, TikTok, destaques).

Você recebe a transcrição com tempos em segundos e, em cada linha, o volume relativo do áudio (0 = baixo, 9 = alto; \
picos podem indicar risadas, gritos, aplausos ou empolgação).

Escolha trechos que funcionem sozinhos, sem contexto: começam com um gancho forte, têm uma ideia completa \
(história, piada, revelação, dica útil, opinião polêmica, momento emocionante) e terminam num ponto natural, \
nunca no meio de uma frase. Prefira começar e terminar nos limites das linhas da transcrição. \
Os trechos não podem se sobrepor. Escreva títulos e motivos no idioma da transcrição."""


def _formatar_transcricao(segmentos: list[dict], energia: list[float]) -> str:
    pico = max(energia) if energia else 0
    linhas = []
    for s in segmentos:
        trecho = energia[int(s["inicio"]): max(int(s["fim"]), int(s["inicio"]) + 1)]
        volume = round(9 * (sum(trecho) / len(trecho)) / pico) if trecho and pico else 0
        linhas.append(f"[{s['inicio']:.1f}-{s['fim']:.1f}] (vol {volume}) {s['texto']}")
    return "\n".join(linhas)


def com_claude(
    segmentos: list[dict],
    energia: list[float],
    duracao: float,
    quantidade: int,
    duracao_min: float,
    duracao_max: float,
    instrucoes: str = "",
) -> list[dict]:
    import anthropic

    pedido = (
        f"Duração total do vídeo: {duracao:.0f} segundos.\n"
        f"Encontre os {quantidade} melhores momentos. Cada corte deve ter entre {duracao_min:.0f} e "
        f"{duracao_max:.0f} segundos.\n"
    )
    if instrucoes.strip():
        pedido += f"Pedido do usuário sobre o que procurar: {instrucoes.strip()}\n"
    pedido += "\n<transcricao>\n" + _formatar_transcricao(segmentos, energia) + "\n</transcricao>"

    cliente = anthropic.Anthropic()
    with cliente.beta.messages.stream(
        model=MODELO_CLAUDE,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": ESQUEMA}},
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
    ) as stream:
        resposta = stream.get_final_message()

    if resposta.stop_reason == "refusal":
        raise RuntimeError("A IA recusou analisar este vídeo. Use o modo automático.")
    if resposta.stop_reason == "max_tokens":
        raise RuntimeError("A resposta da IA ficou incompleta. Tente pedir menos momentos.")
    texto = next(b.text for b in resposta.content if b.type == "text")
    momentos = json.loads(texto)["momentos"]
    return ajustar(momentos, segmentos, duracao, duracao_min, duracao_max, quantidade)


def automatico(
    segmentos: list[dict],
    energia: list[float],
    duracao: float,
    quantidade: int,
    duracao_min: float,
    duracao_max: float,
) -> list[dict]:
    """Pontua janelas de tempo por volume, variação de volume e densidade de fala e escolhe as melhores sem sobreposição."""
    total = len(energia)
    if total == 0:
        return []
    tamanho = int(max(1, min((duracao_min + duracao_max) / 2, total)))

    fala = [0.0] * total
    for s in segmentos:
        palavras = max(1, len(s["texto"].split()))
        segundos = range(int(s["inicio"]), min(total, int(s["fim"]) + 1))
        for seg in segundos:
            fala[seg] += palavras / max(1, len(segundos))

    pico_energia = max(energia) or 1.0
    pico_fala = max(fala) or 1.0
    pontos_por_segundo = [0.6 * e / pico_energia + 0.4 * f / pico_fala for e, f in zip(energia, fala)]

    # Soma acumulada para pontuar cada janela rapidamente.
    acumulado = [0.0]
    for p in pontos_por_segundo:
        acumulado.append(acumulado[-1] + p)
    candidatos = []
    for inicio in range(0, total - tamanho + 1):
        media = (acumulado[inicio + tamanho] - acumulado[inicio]) / tamanho
        janela = energia[inicio:inicio + tamanho]
        variacao = (max(janela) - min(janela)) / pico_energia
        candidatos.append((media + 0.15 * variacao, inicio))
    candidatos.sort(reverse=True)

    escolhidos: list[tuple[float, int]] = []
    for pontuacao, inicio in candidatos:
        if all(abs(inicio - outro) >= tamanho for _, outro in escolhidos):
            escolhidos.append((pontuacao, inicio))
        if len(escolhidos) == quantidade:
            break

    melhor = escolhidos[0][0] if escolhidos else 1.0
    momentos = []
    for posicao, (pontuacao, inicio) in enumerate(escolhidos, start=1):
        texto = " ".join(s["texto"] for s in segmentos if s["fim"] > inicio and s["inicio"] < inicio + tamanho)
        momentos.append({
            "inicio": float(inicio),
            "fim": float(inicio + tamanho),
            "titulo": (texto[:60] + "…") if len(texto) > 60 else (texto or f"Momento {posicao}"),
            "motivo": "Trecho com mais energia no áudio e mais fala (modo automático).",
            "nota": int(100 * pontuacao / melhor) if melhor else 0,
        })
    return ajustar(momentos, segmentos, duracao, duracao_min, duracao_max, quantidade)


def ajustar(
    momentos: list[dict],
    segmentos: list[dict],
    duracao: float,
    duracao_min: float,
    duracao_max: float,
    quantidade: int,
) -> list[dict]:
    """Garante tempos válidos, encaixa início/fim no começo/fim das frases e remove sobreposições."""
    inicios = [s["inicio"] for s in segmentos]
    fins = [s["fim"] for s in segmentos]
    resultado: list[dict] = []

    for m in sorted(momentos, key=lambda m: -m.get("nota", 0)):
        inicio = max(0.0, min(float(m["inicio"]), duracao))
        fim = max(0.0, min(float(m["fim"]), duracao))
        if fim <= inicio:
            continue
        inicio = _mais_proximo(inicio, inicios, tolerancia=2.0)
        fim = _mais_proximo(fim, fins, tolerancia=2.0) + 0.25  # pequena folga para a última palavra não ser cortada
        fim = min(fim, duracao)
        if fim - inicio > duracao_max * 1.15:
            fim = inicio + duracao_max
        if fim - inicio < min(duracao_min * 0.5, duracao):
            continue
        if any(inicio < r["fim"] and fim > r["inicio"] for r in resultado):
            continue
        resultado.append({
            "inicio": round(inicio, 2),
            "fim": round(fim, 2),
            "titulo": str(m.get("titulo", "")).strip()[:120],
            "motivo": str(m.get("motivo", "")).strip()[:300],
            "nota": int(max(0, min(100, m.get("nota", 0)))),
        })
        if len(resultado) == quantidade:
            break
    return resultado


def _mais_proximo(valor: float, opcoes: list[float], tolerancia: float) -> float:
    if not opcoes:
        return valor
    melhor = min(opcoes, key=lambda o: abs(o - valor))
    return melhor if abs(melhor - valor) <= tolerancia else valor
