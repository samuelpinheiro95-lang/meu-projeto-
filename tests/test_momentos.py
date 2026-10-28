import json
from types import SimpleNamespace

from app import momentos

SEGMENTOS = [
    {"inicio": 0.0, "fim": 9.8, "texto": "Introdução."},
    {"inicio": 10.2, "fim": 24.6, "texto": "A história mais engraçada."},
    {"inicio": 25.0, "fim": 40.0, "texto": "Fim da história."},
]


class StreamFalso:
    def __init__(self, pedido):
        self.pedido = pedido

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        texto = json.dumps({"momentos": [
            {"inicio": 10.5, "fim": 39.0, "titulo": "A história", "motivo": "Engraçado", "nota": 92},
            {"inicio": 20.0, "fim": 30.0, "titulo": "Sobreposto", "motivo": "x", "nota": 50},
        ]})
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=texto)])


def test_com_claude_ajusta_tempos_e_remove_sobreposicao(monkeypatch):
    pedidos = []

    class ClienteFalso:
        def __init__(self):
            self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: pedidos.append(kw) or StreamFalso(kw)))

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", ClienteFalso)

    resultado = momentos.com_claude(SEGMENTOS, [0.1] * 40, 40.0, 3, 10, 40, instrucoes="partes engraçadas")

    assert len(resultado) == 1
    assert resultado[0]["inicio"] == 10.2  # encaixado no começo da frase
    assert resultado[0]["fim"] == 40.0     # encaixado no fim da frase (limitado à duração)
    assert "partes engraçadas" in pedidos[0]["messages"][0]["content"]
    assert pedidos[0]["output_config"]["format"]["type"] == "json_schema"


def test_automatico_sem_transcricao_usa_volume():
    energia = [0.05] * 100
    energia[60:70] = [0.9] * 10
    resultado = momentos.automatico([], energia, 100.0, 1, 8, 12)
    assert 55 <= resultado[0]["inicio"] <= 65
