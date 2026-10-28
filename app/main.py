"""Servidor do app: API + interface web (http://localhost:8000)."""

import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, jobs, legendas, momentos, storage, transcricao, video

app = FastAPI(title="Cortador de Vídeo com IA")
PASTA_ESTATICA = Path(__file__).parent / "static"

EXTENSOES_ACEITAS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts", ".ts", ".wmv", ".flv", ".3gp"}


# ---------- modelos de requisição ----------

class NovoEnvio(BaseModel):
    nome: str
    tamanho: int = Field(gt=0)


class PedidoTranscricao(BaseModel):
    idioma: str | None = None  # None = detectar automaticamente
    modelo: Literal["tiny", "base", "small", "medium", "large-v3"] | None = None


class PedidoMomentos(BaseModel):
    quantidade: int = Field(5, ge=1, le=30)
    duracao_min: float = Field(15, ge=3)
    duracao_max: float = Field(60, ge=5)
    instrucoes: str = ""
    usar_ia: bool = True


class Trecho(BaseModel):
    inicio: float = Field(ge=0)
    fim: float = Field(gt=0)
    titulo: str = ""
    motivo: str = ""
    nota: int = 0
    fonte: str = "manual"
    selecionado: bool = True


class ListaMomentos(BaseModel):
    momentos: list[Trecho]


class PedidoExportacao(BaseModel):
    trechos: list[Trecho] = Field(min_length=1)
    modo: Literal["separados", "juntar"] = "separados"
    resolucao: Literal["original", "1080p", "1440p", "4k"] = "1080p"
    formato: Literal["original", "16:9", "9:16", "1:1", "4:5"] = "original"
    qualidade: Literal["rapida", "alta", "maxima"] = "alta"
    legenda: Literal["nenhuma", "embutida", "arquivo", "ambas"] = "nenhuma"
    estilo_legenda: Literal["padrao", "destaque", "caixa"] = "padrao"


# ---------- utilitários ----------

def _info(video_id: str) -> dict:
    try:
        info = storage.ler_json(video_id, "info.json")
    except ValueError:
        info = None
    if info is None:
        raise HTTPException(404, "Vídeo não encontrado")
    return info


def _original(video_id: str) -> Path:
    caminho = storage.arquivo_original(video_id)
    if caminho is None:
        raise HTTPException(409, "O envio deste vídeo ainda não terminou")
    return caminho


def _parcial(video_id: str, info: dict) -> Path:
    return storage.pasta_video(video_id) / f"original{info['extensao']}.parcial"


# ---------- status ----------

@app.get("/api/status")
def status():
    return {
        "claude": config.tem_chave_claude(),
        "modelo_whisper": config.MODELO_WHISPER,
        "pasta_dados": str(config.PASTA_DADOS),
        "disco": storage.espaco_em_disco(),
    }


# ---------- envio em partes (aguenta arquivos de dezenas de GB e pode ser retomado) ----------

@app.post("/api/videos")
def iniciar_envio(pedido: NovoEnvio):
    extensao = Path(pedido.nome).suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise HTTPException(400, f"Formato {extensao or 'desconhecido'} não suportado")
    livre = storage.espaco_em_disco()["livre"]
    if pedido.tamanho > livre:
        raise HTTPException(507, "Espaço em disco insuficiente para este vídeo")

    video_id = storage.novo_id()
    storage.pasta_video(video_id).mkdir(parents=True)
    (storage.pasta_video(video_id) / "cortes").mkdir()
    info = {
        "id": video_id,
        "nome": storage.nome_seguro(pedido.nome),
        "extensao": extensao,
        "tamanho": pedido.tamanho,
        "status": "enviando",
        "criado_em": time.time(),
    }
    storage.salvar_json(video_id, "info.json", info)
    _parcial(video_id, info).touch()
    return {"id": video_id, "recebido": 0}


@app.get("/api/videos/{video_id}/envio")
def estado_envio(video_id: str):
    info = _info(video_id)
    parcial = _parcial(video_id, info)
    return {"recebido": parcial.stat().st_size if parcial.exists() else info["tamanho"]}


@app.put("/api/videos/{video_id}/envio")
async def enviar_parte(video_id: str, offset: int, request: Request):
    info = _info(video_id)
    parcial = _parcial(video_id, info)
    if not parcial.exists():
        raise HTTPException(409, "Este envio já foi concluído")
    atual = parcial.stat().st_size
    if offset != atual:
        # O navegador está fora de sincronia (ex.: conexão caiu); ele retoma a partir de `recebido`.
        return {"recebido": atual, "fora_de_ordem": True}
    with parcial.open("ab") as arquivo:
        async for bloco in request.stream():
            arquivo.write(bloco)
    return {"recebido": parcial.stat().st_size}


@app.post("/api/videos/{video_id}/envio/concluir")
def concluir_envio(video_id: str):
    info = _info(video_id)
    parcial = _parcial(video_id, info)
    if not parcial.exists():
        return info
    if parcial.stat().st_size != info["tamanho"]:
        raise HTTPException(409, "O arquivo ainda não chegou completo")

    final = storage.pasta_video(video_id) / f"original{info['extensao']}"
    parcial.rename(final)
    try:
        info.update(video.analisar(final))
    except Exception as erro:
        info.update(status="erro", erro=f"Não consegui ler este vídeo: {erro}")
        storage.salvar_json(video_id, "info.json", info)
        raise HTTPException(400, info["erro"]) from erro

    pasta = storage.pasta_video(video_id)
    try:
        video.gerar_miniatura(final, pasta / "miniatura.jpg", info["duracao"])
    except Exception:  # noqa: BLE001 - miniatura é opcional
        pass

    info["status"] = "pronto"
    info["previa"] = "pronta" if not video.precisa_previa(final, info) else "gerando"
    storage.salvar_json(video_id, "info.json", info)

    if info["previa"] == "gerando":
        def gerar(tarefa: jobs.Tarefa):
            tarefa.progresso(0, "Preparando prévia para o navegador...")
            video.gerar_previa(final, pasta / "previa.mp4", info["duracao"], tarefa.progresso)
            atual = _info(video_id)
            atual["previa"] = "pronta"
            storage.salvar_json(video_id, "info.json", atual)

        jobs.iniciar("previa", video_id, gerar)
    return info


# ---------- vídeos ----------

@app.get("/api/videos")
def listar():
    return storage.listar_videos()


@app.get("/api/videos/{video_id}")
def detalhes(video_id: str):
    info = _info(video_id)
    transcricao_salva = storage.ler_json(video_id, "transcricao.json")
    pasta_cortes = storage.pasta_video(video_id) / "cortes"
    return {
        **info,
        "transcricao": {
            "idioma": transcricao_salva["idioma"],
            "segmentos": transcricao_salva["segmentos"],
        } if transcricao_salva else None,
        "momentos": storage.ler_json(video_id, "momentos.json", []),
        "cortes": [
            {"nome": f.name, "tamanho": f.stat().st_size, "criado_em": f.stat().st_mtime}
            for f in sorted(pasta_cortes.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
            if f.is_file()
        ] if pasta_cortes.exists() else [],
        "tarefas": jobs.do_video(video_id),
    }


@app.delete("/api/videos/{video_id}")
def apagar(video_id: str):
    _info(video_id)
    storage.apagar_video(video_id)
    return {"ok": True}


@app.get("/api/videos/{video_id}/assistir")
def assistir(video_id: str):
    _info(video_id)
    previa = storage.pasta_video(video_id) / "previa.mp4"
    return FileResponse(previa if previa.exists() else _original(video_id))


@app.get("/api/videos/{video_id}/miniatura")
def miniatura(video_id: str):
    _info(video_id)
    caminho = storage.pasta_video(video_id) / "miniatura.jpg"
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho)


# ---------- legenda automática ----------

def _transcrever(video_id: str, tarefa: jobs.Tarefa, idioma=None, modelo=None) -> dict:
    info = _info(video_id)
    resultado = transcricao.transcrever(
        _original(video_id), info["duracao"], idioma, modelo,
        progresso=lambda f, msg: tarefa.progresso(f, msg),
    )
    storage.salvar_json(video_id, "transcricao.json", resultado)
    return resultado


@app.post("/api/videos/{video_id}/transcrever")
def transcrever(video_id: str, pedido: PedidoTranscricao):
    info = _info(video_id)
    if not info.get("tem_audio"):
        raise HTTPException(400, "Este vídeo não tem áudio para transcrever")
    _original(video_id)
    tarefa_id = jobs.iniciar(
        "transcricao", video_id,
        lambda t: {"segmentos": len(_transcrever(video_id, t, pedido.idioma, pedido.modelo)["segmentos"])},
    )
    return {"tarefa": tarefa_id}


@app.get("/api/videos/{video_id}/legenda.srt")
def baixar_legenda(video_id: str):
    info = _info(video_id)
    dados = storage.ler_json(video_id, "transcricao.json")
    if not dados:
        raise HTTPException(404, "Gere a legenda primeiro")
    nome = Path(info["nome"]).stem + ".srt"
    return PlainTextResponse(
        legendas.gerar_srt(dados["palavras"]),
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


# ---------- melhores momentos ----------

@app.post("/api/videos/{video_id}/momentos")
def encontrar_momentos(video_id: str, pedido: PedidoMomentos):
    info = _info(video_id)
    original = _original(video_id)
    if pedido.duracao_max < pedido.duracao_min:
        raise HTTPException(400, "A duração máxima precisa ser maior que a mínima")
    usar_ia = pedido.usar_ia and config.tem_chave_claude()

    def trabalho(tarefa: jobs.Tarefa):
        dados = storage.ler_json(video_id, "transcricao.json")
        if dados is None and info.get("tem_audio"):
            dados = _transcrever(video_id, tarefa)
        segmentos = dados["segmentos"] if dados else []

        tarefa.progresso(0.9 if usar_ia else 0.5, "Analisando o áudio...")
        energia = video.energia_do_audio(original) if info.get("tem_audio") else [0.0] * int(info["duracao"])

        argumentos = dict(
            segmentos=segmentos, energia=energia, duracao=info["duracao"], quantidade=pedido.quantidade,
            duracao_min=pedido.duracao_min, duracao_max=pedido.duracao_max,
        )
        if usar_ia and segmentos:
            tarefa.progresso(0.95, "A IA está assistindo e escolhendo os melhores momentos...")
            encontrados = momentos.com_claude(**argumentos, instrucoes=pedido.instrucoes)
            fonte = "ia"
        else:
            encontrados = momentos.automatico(**argumentos)
            fonte = "automatico"
        for m in encontrados:
            m["fonte"] = fonte
        storage.salvar_json(video_id, "momentos.json", encontrados)
        return {"quantidade": len(encontrados), "fonte": fonte}

    return {"tarefa": jobs.iniciar("momentos", video_id, trabalho), "usando_ia": usar_ia}


@app.put("/api/videos/{video_id}/momentos")
def salvar_momentos(video_id: str, lista: ListaMomentos):
    info = _info(video_id)
    dados = []
    for m in lista.momentos:
        if m.fim <= m.inicio or m.inicio >= info["duracao"]:
            raise HTTPException(400, f"Trecho inválido: {m.inicio:.1f}s a {m.fim:.1f}s")
        dados.append({**m.model_dump(), "fim": min(m.fim, info["duracao"])})
    storage.salvar_json(video_id, "momentos.json", dados)
    return dados


# ---------- exportação ----------

@app.post("/api/videos/{video_id}/exportar")
def exportar(video_id: str, pedido: PedidoExportacao):
    info = _info(video_id)
    original = _original(video_id)
    trechos = [{**t.model_dump(), "fim": min(t.fim, info["duracao"])} for t in pedido.trechos]
    if any(t["fim"] <= t["inicio"] for t in trechos):
        raise HTTPException(400, "Há um trecho com fim antes do início")

    precisa_legenda = pedido.legenda != "nenhuma"
    dados = storage.ler_json(video_id, "transcricao.json")
    if precisa_legenda and dados is None and not info.get("tem_audio"):
        raise HTTPException(400, "Este vídeo não tem áudio para gerar legenda")

    def trabalho(tarefa: jobs.Tarefa):
        transcrito = dados
        if precisa_legenda and transcrito is None:
            transcrito = _transcrever(video_id, tarefa)
        palavras = transcrito["palavras"] if precisa_legenda else None
        embutir = pedido.legenda in ("embutida", "ambas")
        arquivo_srt = pedido.legenda in ("arquivo", "ambas")
        vertical = pedido.formato in ("9:16", "4:5") or (pedido.formato == "original" and info["altura"] > info["largura"])

        grupos = [trechos] if pedido.modo == "juntar" else [[t] for t in trechos]
        base = Path(info["nome"]).stem
        sufixo = f"{pedido.resolucao}{'_' + pedido.formato.replace(':', 'x') if pedido.formato != 'original' else ''}"
        carimbo = time.strftime("%Y%m%d-%H%M%S")
        gerados = []
        for numero, grupo in enumerate(grupos, start=1):
            titulo = storage.nome_seguro(grupo[0]["titulo"])[:40] if len(grupo) == 1 and grupo[0]["titulo"] else ""
            nome = f"{base}_{'juntos' if len(grupo) > 1 else f'corte{numero:02d}'}{'_' + titulo if titulo else ''}_{sufixo}_{carimbo}"
            destino = storage.pasta_video(video_id) / "cortes" / f"{nome}.mp4"

            def progresso(fracao, n=numero):
                tarefa.progresso(((n - 1) + fracao) / len(grupos), f"Exportando corte {n} de {len(grupos)}...")

            video.exportar(
                original, info, grupo, destino,
                resolucao=pedido.resolucao, formato=pedido.formato, qualidade=pedido.qualidade,
                palavras=palavras if embutir else None, estilo_legenda=pedido.estilo_legenda,
                progresso=progresso,
            )
            gerados.append(destino.name)
            if arquivo_srt:
                srt = destino.with_suffix(".srt")
                srt.write_text(legendas.gerar_srt_de_trechos(palavras, grupo, vertical), encoding="utf-8")
                gerados.append(srt.name)
        return {"arquivos": gerados}

    return {"tarefa": jobs.iniciar("exportacao", video_id, trabalho)}


@app.get("/api/videos/{video_id}/cortes/{nome}")
def baixar_corte(video_id: str, nome: str, baixar: bool = False):
    _info(video_id)
    caminho = storage.pasta_video(video_id) / "cortes" / Path(nome).name
    if not caminho.is_file():
        raise HTTPException(404)
    return FileResponse(caminho, filename=caminho.name if baixar else None)


@app.delete("/api/videos/{video_id}/cortes/{nome}")
def apagar_corte(video_id: str, nome: str):
    _info(video_id)
    caminho = storage.pasta_video(video_id) / "cortes" / Path(nome).name
    caminho.unlink(missing_ok=True)
    return {"ok": True}


# ---------- tarefas ----------

@app.get("/api/tarefas/{tarefa_id}")
def tarefa(tarefa_id: str):
    estado = jobs.obter(tarefa_id)
    if estado is None:
        raise HTTPException(404)
    return estado


app.mount("/", StaticFiles(directory=PASTA_ESTATICA, html=True), name="interface")
