"""Operações com FFmpeg: leitura de metadados, miniatura, prévia, energia do áudio e exportação dos cortes."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np

from . import legendas

RESOLUCOES = {"1080p": 1080, "1440p": 1440, "4k": 2160}
FORMATOS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5)}
QUALIDADES = {
    # (crf, preset): crf menor = mais qualidade e arquivo maior
    "rapida": (23, "veryfast"),
    "alta": (19, "medium"),
    "maxima": (16, "slow"),
}
CODECS_DO_NAVEGADOR = {"h264", "vp8", "vp9", "av1"}
CONTAINERS_DO_NAVEGADOR = {".mp4", ".m4v", ".webm"}


def verificar_ffmpeg() -> None:
    for programa in ("ffmpeg", "ffprobe"):
        if shutil.which(programa) is None:
            raise RuntimeError(f"'{programa}' não encontrado. Instale o FFmpeg (veja o README).")


def analisar(caminho: Path) -> dict:
    """Retorna duração, resolução, fps e codecs do vídeo."""
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(caminho)],
        capture_output=True, text=True, check=True,
    )
    dados = json.loads(saida.stdout)
    video = next((s for s in dados["streams"] if s.get("codec_type") == "video"), None)
    audio = next((s for s in dados["streams"] if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError("O arquivo não tem uma faixa de vídeo.")

    largura, altura = int(video.get("width", 0)), int(video.get("height", 0))
    rotacao = _rotacao(video)
    if rotacao in (90, 270):
        largura, altura = altura, largura

    fps = 0.0
    if video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = round(int(num) / int(den), 3) if int(den) else 0.0

    return {
        "duracao": float(dados["format"].get("duration") or video.get("duration") or 0),
        "largura": largura,
        "altura": altura,
        "fps": fps,
        "codec_video": video.get("codec_name"),
        "codec_audio": audio.get("codec_name") if audio else None,
        "tem_audio": audio is not None,
        "tamanho": int(dados["format"].get("size") or caminho.stat().st_size),
    }


def _rotacao(stream: dict) -> int:
    rotacao = stream.get("tags", {}).get("rotate")
    if rotacao is None:
        for lado in stream.get("side_data_list", []):
            if "rotation" in lado:
                rotacao = lado["rotation"]
    try:
        return abs(int(float(rotacao or 0))) % 360
    except ValueError:
        return 0


def precisa_previa(caminho: Path, info: dict) -> bool:
    """True quando o navegador provavelmente não consegue tocar o arquivo original."""
    return caminho.suffix.lower() not in CONTAINERS_DO_NAVEGADOR or info["codec_video"] not in CODECS_DO_NAVEGADOR


def gerar_miniatura(caminho: Path, destino: Path, duracao: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{duracao * 0.1:.2f}", "-i", str(caminho),
         "-frames:v", "1", "-vf", "scale=480:-2", str(destino)],
        check=True,
    )


def gerar_previa(caminho: Path, destino: Path, duracao: float, progresso: Callable[[float], None]) -> None:
    """Cria uma versão leve em 720p (H.264) só para assistir e marcar cortes no navegador."""
    comando = [
        "ffmpeg", "-y", "-v", "error", "-i", str(caminho),
        "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destino),
    ]
    _executar_com_progresso(comando, duracao, progresso)


def energia_do_audio(caminho: Path, janela: float = 1.0) -> list[float]:
    """Volume médio (RMS, 0..1) de cada janela de `janela` segundos. Lê o áudio em blocos, sem carregar tudo na memória."""
    taxa = 8000
    amostras_por_janela = int(taxa * janela)
    processo = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(caminho), "-vn", "-ac", "1", "-ar", str(taxa), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE,
    )
    energias = []
    resto = np.empty(0, dtype=np.int16)
    while True:
        bloco = processo.stdout.read(amostras_por_janela * 2 * 60)
        if not bloco:
            break
        amostras = np.concatenate([resto, np.frombuffer(bloco, dtype=np.int16)])
        inteiras = len(amostras) // amostras_por_janela
        if inteiras:
            janelas = amostras[: inteiras * amostras_por_janela].astype(np.float32).reshape(inteiras, -1) / 32768.0
            energias.extend(np.sqrt((janelas ** 2).mean(axis=1)).tolist())
        resto = amostras[inteiras * amostras_por_janela:]
    processo.wait()
    if len(resto):
        energias.append(float(np.sqrt(((resto.astype(np.float32) / 32768.0) ** 2).mean())))
    return energias


def filtro_de_video(info: dict, resolucao: str, formato: str) -> str:
    """Monta o filtro de recorte (formato) + escala (resolução) do FFmpeg."""
    largura, altura = info["largura"], info["altura"]
    filtros = []

    if formato in FORMATOS:
        proporcao_l, proporcao_a = FORMATOS[formato]
        alvo = proporcao_l / proporcao_a
        if largura / altura > alvo:  # mais largo que o desejado: corta as laterais
            nova_largura = _par(altura * alvo)
            filtros.append(f"crop={nova_largura}:{altura}")
            largura = nova_largura
        elif largura / altura < alvo:  # mais alto que o desejado: corta em cima e embaixo
            nova_altura = _par(largura / alvo)
            filtros.append(f"crop={largura}:{nova_altura}")
            altura = nova_altura

    if resolucao in RESOLUCOES:
        # A resolução vale para o lado menor: 1080p = 1920x1080 na horizontal ou 1080x1920 na vertical.
        lado_menor = RESOLUCOES[resolucao]
        if formato in FORMATOS:
            # Usa a proporção exata (ex.: 1080x1920), sem herdar o arredondamento do recorte.
            proporcao_l, proporcao_a = FORMATOS[formato]
            maior = max(proporcao_l, proporcao_a) / min(proporcao_l, proporcao_a)
            lado_maior = _par(lado_menor * maior)
            nova_largura, nova_altura = (lado_maior, lado_menor) if proporcao_l >= proporcao_a else (lado_menor, lado_maior)
        else:
            escala = lado_menor / min(largura, altura)
            nova_largura, nova_altura = _par(largura * escala), _par(altura * escala)
        filtros.append(f"scale={nova_largura}:{nova_altura}:flags=lanczos")

    filtros.append("setsar=1")
    return ",".join(filtros)


def _par(valor: float) -> int:
    return max(2, int(round(valor / 2)) * 2)


def exportar(
    caminho: Path,
    info: dict,
    trechos: list[dict],
    destino: Path,
    *,
    resolucao: str = "1080p",
    formato: str = "original",
    qualidade: str = "alta",
    palavras: list[dict] | None = None,
    estilo_legenda: str = "padrao",
    progresso: Callable[[float], None] = lambda _: None,
) -> None:
    """Exporta um ou mais trechos ({inicio, fim}) num único MP4.

    Com `palavras` (da transcrição), a legenda é gravada na imagem.
    Vários trechos são codificados um a um e depois emendados sem perder qualidade.
    """
    crf, preset = QUALIDADES.get(qualidade, QUALIDADES["alta"])
    filtro_base = filtro_de_video(info, resolucao, formato)
    vertical = formato in ("9:16", "4:5") or (formato == "original" and info["altura"] > info["largura"])
    duracao_total = sum(t["fim"] - t["inicio"] for t in trechos)
    feito = 0.0

    with tempfile.TemporaryDirectory(prefix="corte_") as temp:
        temp = Path(temp)
        partes = []
        for indice, trecho in enumerate(trechos):
            duracao = trecho["fim"] - trecho["inicio"]
            filtro = filtro_base
            if palavras:
                srt = legendas.gerar_srt(palavras, trecho["inicio"], trecho["fim"], vertical=vertical)
                if srt:
                    (temp / f"legenda{indice}.srt").write_text(srt, encoding="utf-8")
                    filtro += f",subtitles=legenda{indice}.srt:force_style='{legendas.estilo_ass(estilo_legenda, vertical)}'"

            parte = temp / f"parte{indice}.mp4"
            comando = ["ffmpeg", "-y", "-v", "error", "-ss", f"{trecho['inicio']:.3f}", "-i", str(caminho)]
            if info["tem_audio"]:
                comando += ["-map", "0:v:0", "-map", "0:a:0"]
            else:
                # Sem áudio no original: adiciona silêncio para os trechos poderem ser emendados.
                comando += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
            comando += [
                "-t", f"{duracao:.3f}",
                "-vf", filtro,
                "-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
                "-r", str(info["fps"] or 30),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(parte),
            ]

            inicio_parte = feito
            _executar_com_progresso(
                comando, duracao, lambda f: progresso((inicio_parte + f * duracao) / duracao_total), cwd=temp,
            )
            feito += duracao
            partes.append(parte)

        if len(partes) == 1:
            shutil.move(partes[0], destino)
        else:
            lista = temp / "lista.txt"
            lista.write_text("".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lista.name,
                 "-c", "copy", "-movflags", "+faststart", str(destino.resolve())],
                check=True, cwd=temp,
            )
    progresso(1.0)


def _executar_com_progresso(comando: list[str], duracao: float, progresso: Callable[[float], None], cwd=None) -> None:
    comando = comando[:1] + ["-progress", "pipe:1", "-nostats"] + comando[1:]
    processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    for linha in processo.stdout:
        if linha.startswith("out_time_us=") and duracao > 0:
            try:
                progresso(min(1.0, int(linha.split("=")[1]) / 1_000_000 / duracao))
            except ValueError:
                pass
    erros = processo.stderr.read()
    if processo.wait() != 0:
        raise RuntimeError(f"FFmpeg falhou: {erros.strip()[-800:]}")
