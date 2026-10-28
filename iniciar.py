"""Inicia o Cortador IA e abre o navegador em http://localhost:8000."""

import threading
import webbrowser

import uvicorn

from app import config, video


def main():
    video.verificar_ffmpeg()
    endereco = f"http://localhost:{config.PORTA}"
    print(f"\n  Cortador IA rodando em {endereco}")
    print(f"  Vídeos salvos em: {config.PASTA_DADOS}")
    print("  Para fechar, pressione Ctrl+C nesta janela.\n")
    threading.Timer(1.5, lambda: webbrowser.open(endereco)).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=config.PORTA, log_level="warning")


if __name__ == "__main__":
    main()
