"""Armazenamento em disco: cada vídeo tem sua própria pasta com o original e os arquivos gerados.

dados/videos/<id>/
    original.<ext>     vídeo enviado
    info.json          metadados (nome, duração, resolução...)
    transcricao.json   legenda com tempos por palavra
    momentos.json      melhores momentos sugeridos
    cortes/            vídeos exportados
"""

import json
import re
import shutil
import uuid
from pathlib import Path

from .config import PASTA_VIDEOS

_ID_VALIDO = re.compile(r"^[a-f0-9]{32}$")


def novo_id() -> str:
    return uuid.uuid4().hex


def pasta_video(video_id: str) -> Path:
    if not _ID_VALIDO.match(video_id):
        raise ValueError("id de vídeo inválido")
    return PASTA_VIDEOS / video_id


def ler_json(video_id: str, nome: str, padrao=None):
    caminho = pasta_video(video_id) / nome
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_json(video_id: str, nome: str, dados) -> None:
    caminho = pasta_video(video_id) / nome
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def arquivo_original(video_id: str) -> Path | None:
    for caminho in pasta_video(video_id).glob("original.*"):
        if not caminho.name.endswith(".parcial"):
            return caminho
    return None


def listar_videos() -> list[dict]:
    videos = []
    for pasta in PASTA_VIDEOS.iterdir():
        info_arquivo = pasta / "info.json"
        if pasta.is_dir() and info_arquivo.exists():
            videos.append(json.loads(info_arquivo.read_text(encoding="utf-8")))
    return sorted(videos, key=lambda v: v.get("criado_em", 0), reverse=True)


def apagar_video(video_id: str) -> None:
    shutil.rmtree(pasta_video(video_id), ignore_errors=True)


def nome_seguro(nome: str) -> str:
    nome = re.sub(r"[^\w\-. ]", "_", nome).strip() or "video"
    return nome[:120]


def espaco_em_disco() -> dict:
    uso = shutil.disk_usage(PASTA_VIDEOS)
    usado_pelo_app = sum(f.stat().st_size for f in PASTA_VIDEOS.rglob("*") if f.is_file())
    return {"total": uso.total, "livre": uso.free, "usado_pelo_app": usado_pelo_app}
