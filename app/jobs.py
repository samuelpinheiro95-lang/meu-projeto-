"""Fila simples de tarefas em segundo plano (transcrição, análise, exportação) com progresso."""

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_executor = ThreadPoolExecutor(max_workers=2)
_tarefas: dict[str, dict] = {}
_trava = threading.Lock()


class Tarefa:
    """Passada para a função de trabalho para ela informar o progresso."""

    def __init__(self, tarefa_id: str):
        self.id = tarefa_id

    def progresso(self, fracao: float, mensagem: str | None = None) -> None:
        with _trava:
            estado = _tarefas[self.id]
            estado["progresso"] = max(0.0, min(1.0, fracao))
            if mensagem:
                estado["mensagem"] = mensagem


def iniciar(tipo: str, video_id: str, funcao: Callable[[Tarefa], dict | None]) -> str:
    tarefa_id = uuid.uuid4().hex
    with _trava:
        _tarefas[tarefa_id] = {
            "id": tarefa_id,
            "tipo": tipo,
            "video_id": video_id,
            "status": "na_fila",
            "progresso": 0.0,
            "mensagem": "Aguardando...",
            "resultado": None,
            "erro": None,
            "criado_em": time.time(),
        }

    def executar():
        with _trava:
            _tarefas[tarefa_id]["status"] = "executando"
        try:
            resultado = funcao(Tarefa(tarefa_id))
            with _trava:
                _tarefas[tarefa_id].update(status="concluida", progresso=1.0, resultado=resultado, mensagem="Pronto")
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira erro visível na interface
            traceback.print_exc()
            with _trava:
                _tarefas[tarefa_id].update(status="erro", erro=str(erro), mensagem="Falhou")

    _executor.submit(executar)
    return tarefa_id


def obter(tarefa_id: str) -> dict | None:
    with _trava:
        estado = _tarefas.get(tarefa_id)
        return dict(estado) if estado else None


def do_video(video_id: str) -> list[dict]:
    with _trava:
        return [dict(t) for t in _tarefas.values() if t["video_id"] == video_id]
