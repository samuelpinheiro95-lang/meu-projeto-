"""Configuração lida do arquivo .env e de variáveis de ambiente."""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_env(caminho: Path) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        if valor:
            os.environ.setdefault(chave.strip(), valor)


_carregar_env(RAIZ / ".env")

PASTA_DADOS = Path(os.environ.get("PASTA_DADOS", RAIZ / "dados")).expanduser().resolve()
PASTA_VIDEOS = PASTA_DADOS / "videos"
PASTA_VIDEOS.mkdir(parents=True, exist_ok=True)

MODELO_WHISPER = os.environ.get("MODELO_WHISPER", "small")
USAR_GPU = os.environ.get("USAR_GPU", "").lower() in ("1", "sim", "true")
MODELO_CLAUDE =os.environ.get("MODELO_CLAUDE", "claude-opus-5-5")
PORTA = int(os.environ.get("PORTA", "8000"))


def tem_chave_claude() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
