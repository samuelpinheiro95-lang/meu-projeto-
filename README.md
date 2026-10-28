# ✂️ Cortador IA

App para cortar vídeos com inteligência artificial. Ele roda no seu computador e abre no navegador.

- **IA que encontra os melhores momentos**: o Claude lê a transcrição do vídeo e escolhe os trechos com mais potencial (ganchos, histórias, piadas, dicas, frases de impacto). Você pode dizer o que procurar, por exemplo "momentos engraçados".
- **Legenda automática**: transcreve a fala com o Whisper, direto no seu computador e sem custo. A legenda pode ser gravada no vídeo (3 estilos) ou salva como arquivo `.srt`.
- **Exportação em 1080p, 1440p (2K) ou 4K**, nos formatos original, vertical 9:16 (Reels, Shorts, TikTok), quadrado 1:1, 4:5 ou 16:9.
- **Vídeos grandes**: o envio é feito em partes e continua de onde parou se a conexão cair. Tudo fica salvo no seu disco, então o limite é o espaço do seu HD. Você pode usar um HD externo.
- Edição manual: marque início e fim na linha do tempo (atalhos `I` e `O`), ajuste os tempos de cada corte, exporte um arquivo por corte ou junte tudo em um vídeo só.

## 1. O que instalar (só na primeira vez)

### Python 3.10 ou mais novo
- **Windows**: baixe em https://www.python.org/downloads/. Na instalação, **marque "Add Python to PATH"**.
- **Mac**: `brew install python`, ou baixe no site acima.
- **Linux**: já costuma vir instalado (`python3 --version`).

### FFmpeg (é ele que processa os vídeos)
- **Windows**: abra o "Prompt de Comando" e rode:
  ```bash
  winget install Gyan.FFmpeg
  ```
  Depois feche e abra o terminal de novo.
- **Mac**:
  ```bash
  brew install ffmpeg
  ```
- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt install ffmpeg
  ```

## 2. Baixar o app

No GitHub, clique em **Code → Download ZIP** e extraia o arquivo. Se preferir usar git:

```bash
git clone https://github.com/samuelpinheiro95-lang/meu-projeto-.git
```

## 3. Abrir o app

- **Windows**: dê dois cliques em `iniciar.bat`.
- **Mac/Linux**: no terminal, dentro da pasta do projeto, rode:
  ```bash
  ./iniciar.sh
  ```

Na primeira vez, ele instala tudo sozinho, o que leva alguns minutos. Depois o navegador abre em **http://localhost:8000**.

> A primeira legenda demora um pouco mais, porque o app baixa o modelo de transcrição (cerca de 500 MB no modo "small"). Isso só acontece uma vez.

## 4. Ativar a IA do Claude (recomendado)

Sem a chave, o app funciona em **modo automático**: escolhe os momentos pelo volume do áudio e pela quantidade de fala. Com a chave, a IA entende o conteúdo e escolhe muito melhor.

1. Crie uma chave em https://console.anthropic.com/settings/keys.
2. Abra o arquivo `.env` na pasta do projeto (ele é criado na primeira execução) e preencha:
   ```
   ANTHROPIC_API_KEY=sua-chave-aqui
   ```
3. Feche e abra o app de novo.

O custo é por uso. Analisar um vídeo de 1 hora custa em torno de US$ 0,10 a 0,30. **Nunca coloque a chave no GitHub**: o arquivo `.env` já fica fora do repositório.

## 5. Mais espaço para vídeos grandes

No arquivo `.env`, aponte a pasta de dados para um disco maior ou para um HD externo:

```
# Windows
PASTA_DADOS=D:\Videos\CortadorIA
# Mac
PASTA_DADOS=/Volumes/HD Externo/CortadorIA
```

O espaço livre e o espaço usado aparecem no topo do app.

## Como usar

1. **Envie um vídeo**: arraste o arquivo para a área "Enviar vídeo".
2. **✨ Melhores momentos**: escolha quantos cortes quer e a duração de cada um, e clique em *Encontrar melhores momentos*. Clique em um corte para assistir. Você pode ajustar os tempos, desmarcar cortes ou adicionar os seus pela linha do tempo.
3. **💬 Legendas**: gere a legenda, confira o texto e baixe o `.srt` se quiser. A legenda também é gerada automaticamente quando você busca momentos ou exporta com legenda.
4. **🎬 Exportar**: escolha resolução, formato, qualidade e legenda, e clique em *Exportar*.
5. **📁 Cortes prontos**: assista e baixe os vídeos.

### Atalhos de teclado
| Tecla | Ação |
|---|---|
| `Espaço` | tocar ou pausar |
| `I` / `O` | marcar início / fim do corte |
| `←` / `→` | voltar / avançar 5 s (com `Shift`: 1 s) |

### Dicas
- **4K** demora mais para exportar. Use a qualidade "Rápida" para testar e "Máxima" para a versão final.
- Exportar em resolução maior que a do original (ex.: vídeo 1080p exportado em 4K) aumenta o tamanho da imagem, mas não cria detalhes novos. O app avisa quando isso acontece.
- Se você tem placa de vídeo NVIDIA com CUDA, coloque `USAR_GPU=1` no `.env` para a transcrição ficar bem mais rápida.
- Para legendas mais precisas, escolha a precisão "Ótima" ou "Máxima" na aba Legendas. Elas são mais lentas.

## Configurações (`.env`)

| Variável | Para que serve | Padrão |
|---|---|---|
| `ANTHROPIC_API_KEY` | chave da IA do Claude | vazio (modo automático) |
| `PASTA_DADOS` | onde os vídeos ficam salvos | `./dados` |
| `MODELO_WHISPER` | precisão da transcrição: `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `USAR_GPU` | `1` para usar placa NVIDIA na transcrição | `0` |
| `PORTA` | porta no navegador | `8000` |

## Para desenvolvedores

```
app/
  main.py         API (FastAPI) e servidor da interface
  video.py        FFmpeg: leitura, prévia, energia do áudio, exportação (recorte/escala/legenda)
  transcricao.py  legenda automática (faster-whisper)
  momentos.py     seleção dos melhores momentos (Claude + modo automático)
  legendas.py     montagem das legendas (SRT/estilo)
  jobs.py         tarefas em segundo plano com progresso
  storage.py      pastas e arquivos de cada vídeo
  static/         interface (HTML/CSS/JS puro)
tests/            testes (pytest)
```

Rodar os testes:

```bash
pip install -r requirements.txt pytest httpx
```

```bash
python -m pytest
```
