"""Teste de ponta a ponta: envio em partes -> momentos automáticos -> exportação com legenda em vários formatos."""

import json
import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    os.environ["PASTA_DADOS"] = str(tmp_path_factory.mktemp("dados"))
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def video_teste(tmp_path_factory):
    """Vídeo de 30s, 1280x720, com áudio baixo e um trecho alto entre 18s e 24s."""
    caminho = tmp_path_factory.mktemp("entrada") / "meu video.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
        "-af", "volume='if(between(t,18,24),1.0,0.05)':eval=frame",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(caminho),
    ], check=True)
    return caminho


def esperar(cliente, tarefa_id):
    for _ in range(600):
        t = cliente.get(f"/api/tarefas/{tarefa_id}").json()
        if t["status"] in ("concluida", "erro"):
            assert t["status"] == "concluida", t["erro"]
            return t
        time.sleep(0.2)
    raise TimeoutError


def dimensoes(caminho):
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(caminho)], capture_output=True, text=True, check=True,
    )
    dados = json.loads(saida.stdout)
    return dados["streams"][0]["width"], dados["streams"][0]["height"], float(dados["format"]["duration"])


def test_fluxo_completo(cliente, video_teste):
    conteudo = video_teste.read_bytes()
    r = cliente.post("/api/videos", json={"nome": video_teste.name, "tamanho": len(conteudo)})
    assert r.status_code == 200, r.text
    video_id = r.json()["id"]

    # Envio em 3 partes, incluindo uma parte repetida (simula reenvio após queda de conexão).
    parte = len(conteudo) // 3 + 1
    recebido = 0
    while recebido < len(conteudo):
        r = cliente.put(f"/api/videos/{video_id}/envio?offset={recebido}", content=conteudo[recebido:recebido + parte])
        recebido = r.json()["recebido"]
    r = cliente.put(f"/api/videos/{video_id}/envio?offset=0", content=conteudo[:parte])
    assert r.json() == {"recebido": len(conteudo), "fora_de_ordem": True}

    info = cliente.post(f"/api/videos/{video_id}/envio/concluir").json()
    assert info["status"] == "pronto"
    assert (info["largura"], info["altura"]) == (1280, 720)
    assert info["previa"] == "pronta"

    # Transcrição falsa (o modelo Whisper real é testado à parte) para testar momentos e legendas.
    from app import storage
    palavras = [{"inicio": 18 + i * 0.5, "fim": 18.4 + i * 0.5, "texto": t}
                for i, t in enumerate("Olha que momento incrível aconteceu aqui agora pessoal.".split())]
    storage.salvar_json(video_id, "transcricao.json", {
        "idioma": "pt",
        "segmentos": [{"inicio": 18.0, "fim": 22.0, "texto": " ".join(p["texto"] for p in palavras)}],
        "palavras": palavras,
    })

    r = cliente.post(f"/api/videos/{video_id}/momentos",
                     json={"quantidade": 2, "duracao_min": 4, "duracao_max": 8, "usar_ia": True})
    assert r.json()["usando_ia"] is False  # sem chave: modo automático
    esperar(cliente, r.json()["tarefa"])
    encontrados = cliente.get(f"/api/videos/{video_id}").json()["momentos"]
    assert encontrados, "nenhum momento encontrado"
    melhor = encontrados[0]
    assert 14 <= melhor["inicio"] <= 24, melhor  # o trecho alto (18s-24s) deve ser o escolhido

    # Exporta vertical 1080p com legenda gravada + .srt, juntando dois trechos.
    trechos = [{"inicio": 2, "fim": 5}, {"inicio": 18, "fim": 22}]
    r = cliente.post(f"/api/videos/{video_id}/exportar", json={
        "trechos": trechos, "modo": "juntar", "resolucao": "1080p", "formato": "9:16",
        "qualidade": "rapida", "legenda": "ambas", "estilo_legenda": "destaque",
    })
    arquivos = esperar(cliente, r.json()["tarefa"])["resultado"]["arquivos"]
    pasta = storage.pasta_video(video_id) / "cortes"
    largura, altura, duracao = dimensoes(pasta / arquivos[0])
    assert (largura, altura) == (1080, 1920)
    assert abs(duracao - 7) < 0.3
    srt = (pasta / arquivos[1]).read_text(encoding="utf-8")
    assert "00:00:03,000" in srt  # legenda do 2º trecho começa após os 3s do 1º trecho

    # Exporta em 4K horizontal, um arquivo por corte.
    r = cliente.post(f"/api/videos/{video_id}/exportar", json={
        "trechos": [{"inicio": 0, "fim": 1.5, "titulo": "Início"}], "resolucao": "4k", "qualidade": "rapida",
    })
    arquivos = esperar(cliente, r.json()["tarefa"])["resultado"]["arquivos"]
    assert dimensoes(pasta / arquivos[0])[:2] == (3840, 2160)

    # Baixar, listar e apagar.
    assert cliente.get(f"/api/videos/{video_id}/cortes/{arquivos[0]}?baixar=true").status_code == 200
    assert cliente.get(f"/api/videos/{video_id}/assistir", headers={"Range": "bytes=0-99"}).status_code == 206
    assert len(cliente.get(f"/api/videos/{video_id}").json()["cortes"]) == 3
    assert cliente.delete(f"/api/videos/{video_id}").status_code == 200
    assert cliente.get(f"/api/videos/{video_id}").status_code == 404


def test_id_invalido_nao_acessa_outras_pastas(cliente):
    assert cliente.get("/api/videos/..%2F..%2Fetc").status_code == 404
