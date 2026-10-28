"""Transcrição automática (fala -> texto com tempo de cada palavra) usando faster-whisper, rodando no próprio computador."""

import threading
from pathlib import Path
from typing import Callable

from .config import MODELO_WHISPER, USAR_GPU

_modelos: dict[str, object] = {}
_trava = threading.Lock()


def _carregar_modelo(nome: str):
    with _trava:
        if nome not in _modelos:
            from faster_whisper import WhisperModel

            if USAR_GPU:
                _modelos[nome] = WhisperModel(nome, device="cuda", compute_type="float16")
            else:
                _modelos[nome] = WhisperModel(nome, device="cpu", compute_type="int8")
        return _modelos[nome]


def transcrever(
    caminho: Path,
    duracao: float,
    idioma: str | None = None,
    modelo: str | None = None,
    progresso: Callable[[float, str], None] = lambda *_: None,
) -> dict:
    """Retorna {"idioma", "segmentos": [{inicio, fim, texto}], "palavras": [{inicio, fim, texto}]}."""
    progresso(0.0, "Carregando modelo de transcrição (a primeira vez baixa o modelo)...")
    whisper = _carregar_modelo(modelo or MODELO_WHISPER)

    segmentos_gerados, dados = whisper.transcribe(
        str(caminho),
        language=idioma or None,
        word_timestamps=True,
        vad_filter=True,
    )

    segmentos, palavras = [], []
    for segmento in segmentos_gerados:
        segmentos.append({
            "inicio": round(segmento.start, 3),
            "fim": round(segmento.end, 3),
            "texto": segmento.text.strip(),
        })
        for palavra in segmento.words or []:
            texto = palavra.word.strip()
            if texto:
                palavras.append({"inicio": round(palavra.start, 3), "fim": round(palavra.end, 3), "texto": texto})
        if duracao:
            progresso(segmento.end / duracao, f"Transcrevendo... {_mmss(segmento.end)} de {_mmss(duracao)}")

    return {"idioma": dados.language, "segmentos": segmentos, "palavras": palavras}


def _mmss(segundos: float) -> str:
    segundos = int(segundos)
    horas, resto = divmod(segundos, 3600)
    return f"{horas}:{resto // 60:02d}:{resto % 60:02d}" if horas else f"{resto // 60}:{resto % 60:02d}"
