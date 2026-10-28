"""Montagem de legendas (SRT) a partir das palavras transcritas, com tempos ajustados a cada corte."""

import math

PONTUACAO_FINAL = (".", "!", "?", "…")

# Estilos de legenda gravada na imagem (formato ASS do libass: cores em &HAABBGGRR).
# Os tamanhos são relativos à altura do vídeo, então funcionam igual em 1080p e 4K.
ESTILOS = {
    "padrao": "FontName=Arial,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1.6,Shadow=0.6",
    "destaque": "FontName=Arial,Bold=1,PrimaryColour=&H0000E5FF,OutlineColour=&H00000000,BorderStyle=1,Outline=2.2,Shadow=1",
    "caixa": "FontName=Arial,Bold=1,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=3,Outline=0.8,Shadow=0",
}


def estilo_ass(nome: str, vertical: bool) -> str:
    base = ESTILOS.get(nome, ESTILOS["padrao"])
    if vertical:
        return f"{base},Fontsize=13,Alignment=2,MarginV=70"
    return f"{base},Fontsize=16,Alignment=2,MarginV=18"


def agrupar(palavras: list[dict], inicio: float = 0.0, fim: float = math.inf, vertical: bool = False) -> list[dict]:
    """Junta palavras em blocos curtos de legenda dentro do intervalo [inicio, fim], com tempos relativos a `inicio`."""
    max_caracteres = 18 if vertical else 40
    max_duracao = 2.2 if vertical else 3.5

    blocos: list[dict] = []
    atual: list[dict] = []

    def fechar():
        if atual:
            blocos.append({
                "inicio": max(0.0, atual[0]["inicio"] - inicio),
                "fim": min(fim, atual[-1]["fim"]) - inicio,
                "texto": " ".join(p["texto"] for p in atual),
            })
            atual.clear()

    for palavra in palavras:
        if palavra["fim"] <= inicio or palavra["inicio"] >= fim:
            continue
        if atual:
            texto_junto = len(" ".join(p["texto"] for p in atual)) + 1 + len(palavra["texto"])
            pausa = palavra["inicio"] - atual[-1]["fim"]
            longo = palavra["fim"] - atual[0]["inicio"] > max_duracao
            if texto_junto > max_caracteres or pausa > 0.7 or longo:
                fechar()
        atual.append(palavra)
        if palavra["texto"].endswith(PONTUACAO_FINAL):
            fechar()
    fechar()

    # Evita que um bloco fique na tela por cima do próximo.
    for anterior, proximo in zip(blocos, blocos[1:]):
        anterior["fim"] = min(anterior["fim"], proximo["inicio"])
    return [b for b in blocos if b["fim"] - b["inicio"] > 0.05]


def _tempo_srt(segundos: float) -> str:
    milis = int(round(segundos * 1000))
    horas, milis = divmod(milis, 3_600_000)
    minutos, milis = divmod(milis, 60_000)
    seg, milis = divmod(milis, 1000)
    return f"{horas:02d}:{minutos:02d}:{seg:02d},{milis:03d}"


def gerar_srt(palavras: list[dict], inicio: float = 0.0, fim: float = math.inf, vertical: bool = False) -> str:
    blocos = agrupar(palavras, inicio, fim, vertical)
    return "".join(
        f"{i}\n{_tempo_srt(b['inicio'])} --> {_tempo_srt(b['fim'])}\n{b['texto']}\n\n"
        for i, b in enumerate(blocos, start=1)
    )


def gerar_srt_de_trechos(palavras: list[dict], trechos: list[dict], vertical: bool = False) -> str:
    """SRT para um vídeo formado por vários trechos emendados (os tempos continuam de um trecho para o outro)."""
    blocos = []
    deslocamento = 0.0
    for trecho in trechos:
        for bloco in agrupar(palavras, trecho["inicio"], trecho["fim"], vertical):
            blocos.append({**bloco, "inicio": bloco["inicio"] + deslocamento, "fim": bloco["fim"] + deslocamento})
        deslocamento += trecho["fim"] - trecho["inicio"]
    return "".join(
        f"{i}\n{_tempo_srt(b['inicio'])} --> {_tempo_srt(b['fim'])}\n{b['texto']}\n\n"
        for i, b in enumerate(blocos, start=1)
    )
