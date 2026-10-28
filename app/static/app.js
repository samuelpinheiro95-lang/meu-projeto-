// Interface do Cortador IA (JavaScript puro, sem dependências).

const $ = (seletor) => document.querySelector(seletor);
const TAMANHO_PARTE = 32 * 1024 * 1024; // envio em partes de 32 MB

const estado = {
  video: null,        // detalhes do vídeo aberto
  momentos: [],       // cortes sugeridos/manuais
  selecao: { inicio: null, fim: null },
  pararEm: null,      // ao tocar um corte, pausa no fim dele
  tocandoIndice: null,
};

// ---------- utilitários ----------

async function api(metodo, url, corpo) {
  const resposta = await fetch(url, {
    method: metodo,
    headers: corpo ? { "Content-Type": "application/json" } : {},
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (!resposta.ok) {
    let mensagem = `Erro ${resposta.status}`;
    try {
      const dados = await resposta.json();
      mensagem = typeof dados.detail === "string" ? dados.detail : JSON.stringify(dados.detail);
    } catch {}
    throw new Error(mensagem);
  }
  return resposta.json();
}

function tempo(segundos, decimal = false) {
  if (segundos == null || isNaN(segundos)) return "–";
  const negativo = segundos < 0;
  segundos = Math.abs(segundos);
  const h = Math.floor(segundos / 3600);
  const m = Math.floor((segundos % 3600) / 60);
  const s = segundos % 60;
  const ss = decimal ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return (negativo ? "-" : "") + (h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`);
}

function lerTempo(texto) {
  // aceita "75", "1:15", "1:15.5", "1:01:15"
  const partes = String(texto).trim().replace(",", ".").split(":").map(Number);
  if (partes.some(isNaN)) return null;
  return partes.reduce((total, p) => total * 60 + p, 0);
}

function bytes(n) {
  if (!n && n !== 0) return "";
  const unidades = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < unidades.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i > 1 ? 1 : 0)} ${unidades[i]}`;
}

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function avisar(texto, tipo = "") {
  const el = document.createElement("div");
  el.className = `aviso-flutuante ${tipo}`;
  el.textContent = texto;
  $("#avisos").append(el);
  setTimeout(() => el.remove(), tipo === "erro" ? 9000 : 5000);
}

function mostrarProgresso(caixa, fracao, texto) {
  caixa.hidden = false;
  caixa.querySelector("div").style.width = `${Math.round(fracao * 100)}%`;
  caixa.querySelector("span").textContent = texto;
}

// Acompanha uma tarefa em segundo plano até terminar.
async function acompanhar(tarefaId, caixa) {
  while (true) {
    let t;
    try {
      t = await api("GET", `/api/tarefas/${tarefaId}`);
    } catch {
      if (caixa) caixa.hidden = true;
      return null; // servidor reiniciado: a tarefa se perdeu
    }
    if (caixa) mostrarProgresso(caixa, t.progresso, `${t.mensagem} ${Math.round(t.progresso * 100)}%`);
    if (t.status === "concluida") { if (caixa) caixa.hidden = true; return t; }
    if (t.status === "erro") { if (caixa) caixa.hidden = true; throw new Error(t.erro); }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

// ---------- status e biblioteca ----------

async function carregarStatus() {
  try {
    const s = await api("GET", "/api/status");
    const chipIa = $("#chip-ia");
    chipIa.textContent = s.claude ? "IA Claude: ativa" : "IA Claude: sem chave (modo automático)";
    chipIa.className = `chip ${s.claude ? "ok" : "alerta"}`;
    chipIa.title = s.claude ? "" : "Coloque ANTHROPIC_API_KEY no arquivo .env para usar a IA";
    $("#chip-disco").textContent = `Disco livre: ${bytes(s.disco.livre)} · usado pelo app: ${bytes(s.disco.usado_pelo_app)}`;
    $("#chip-disco").title = `Pasta dos dados: ${s.pasta_dados}`;
    $("#m-ia").checked = s.claude;
    $("#m-ia").disabled = !s.claude;
  } catch {}
}

async function carregarLista() {
  const videos = await api("GET", "/api/videos");
  const lista = $("#lista-videos");
  lista.innerHTML = videos.length ? "" : `<li class="vazio-lista">Nenhum vídeo ainda</li>`;
  for (const v of videos) {
    const li = document.createElement("li");
    li.dataset.id = v.id;
    if (estado.video?.id === v.id) li.classList.add("ativo");
    const detalhe = v.status === "enviando" ? "envio incompleto" :
      v.status === "erro" ? "erro ao ler" :
      `${tempo(v.duracao)} · ${v.largura}×${v.altura} · ${bytes(v.tamanho)}`;
    li.innerHTML = `
      <img src="/api/videos/${v.id}/miniatura" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'sem-miniatura'}))">
      <div><div class="nome" title="${escapar(v.nome)}">${escapar(v.nome)}</div><small>${detalhe}</small></div>`;
    li.onclick = () => v.status === "pronto" ? abrirVideo(v.id) : avisar("Envie este arquivo de novo para terminar o envio.");
    lista.append(li);
  }
}

// ---------- envio de arquivos grandes (em partes, com retomada) ----------

function chaveEnvio(arquivo) {
  return `envio:${arquivo.name}:${arquivo.size}:${arquivo.lastModified}`;
}

async function enviarArquivo(arquivo) {
  const el = document.createElement("div");
  el.className = "envio";
  el.innerHTML = `<div class="nome">${escapar(arquivo.name)}</div><div class="progresso"><div></div><span>Preparando…</span></div>`;
  $("#envios").append(el);
  const barra = el.querySelector(".progresso");

  try {
    // Retoma um envio interrompido do mesmo arquivo, se houver.
    let id = null, recebido = 0;
    const chave = chaveEnvio(arquivo);
    try {
      id = localStorage.getItem(chave);
      if (id) recebido = (await api("GET", `/api/videos/${id}/envio`)).recebido;
    } catch { id = null; recebido = 0; }
    if (!id) {
      ({ id, recebido } = await api("POST", "/api/videos", { nome: arquivo.name, tamanho: arquivo.size }));
      try { localStorage.setItem(chave, id); } catch {}
    }
    carregarLista();

    const inicio = performance.now();
    const recebidoInicial = recebido;
    let falhas = 0;
    while (recebido < arquivo.size) {
      const parte = arquivo.slice(recebido, recebido + TAMANHO_PARTE);
      try {
        const r = await fetch(`/api/videos/${id}/envio?offset=${recebido}`, { method: "PUT", body: parte });
        if (!r.ok) throw new Error(`Erro ${r.status}`);
        recebido = (await r.json()).recebido;
        falhas = 0;
      } catch (erro) {
        if (++falhas > 8) throw erro;
        mostrarProgresso(barra, recebido / arquivo.size, `Conexão falhou, tentando de novo (${falhas})…`);
        await new Promise((r) => setTimeout(r, 1000 * 2 ** Math.min(falhas, 5)));
        recebido = (await api("GET", `/api/videos/${id}/envio`).catch(() => ({ recebido }))).recebido;
        continue;
      }
      const segundos = (performance.now() - inicio) / 1000;
      const velocidade = (recebido - recebidoInicial) / Math.max(segundos, 0.1);
      const restante = (arquivo.size - recebido) / Math.max(velocidade, 1);
      mostrarProgresso(barra, recebido / arquivo.size,
        `${bytes(recebido)} de ${bytes(arquivo.size)} · ${bytes(velocidade)}/s · falta ${tempo(restante)}`);
    }

    mostrarProgresso(barra, 1, "Lendo o vídeo…");
    await api("POST", `/api/videos/${id}/envio/concluir`);
    try { localStorage.removeItem(chave); } catch {}
    el.remove();
    avisar(`"${arquivo.name}" enviado!`, "ok");
    await carregarLista();
    await abrirVideo(id);
  } catch (erro) {
    mostrarProgresso(barra, 0, `Falhou: ${erro.message}. Envie o mesmo arquivo de novo para continuar de onde parou.`);
    setTimeout(() => el.remove(), 15000);
  }
}

// ---------- abrir vídeo ----------

async function abrirVideo(id) {
  const v = await api("GET", `/api/videos/${id}`);
  const trocouDeVideo = estado.video?.id !== id;
  estado.video = v;
  estado.momentos = v.momentos;
  if (trocouDeVideo) {
    estado.selecao = { inicio: null, fim: null };
    estado.pararEm = null;
    estado.tocandoIndice = null;
    $("#player").src = `/api/videos/${id}/assistir`;
  }

  $("#editor").classList.remove("vazio");
  document.querySelectorAll("#lista-videos li").forEach((li) => li.classList.toggle("ativo", li.dataset.id === id));
  $("#nome-video").textContent = v.nome;
  $("#nome-video").title = v.nome;
  $("#detalhes-video").textContent =
    `${tempo(v.duracao)} · ${v.largura}×${v.altura} · ${v.fps} fps · ${bytes(v.tamanho)}${v.tem_audio ? "" : " · sem áudio"}`;
  $("#tempo-total").textContent = tempo(v.duracao);

  renderizarMomentos();
  renderizarTranscricao();
  renderizarCortes();
  atualizarSelecao();
  atualizarAvisoResolucao();

  // Retoma o acompanhamento de tarefas que ainda estão rodando.
  for (const t of v.tarefas) {
    if (t.status === "concluida" || t.status === "erro") continue;
    if (trocouDeVideo || !estado.acompanhando?.has(t.id)) acompanharTarefaDoVideo(t);
  }
}

estado.acompanhando = new Set();
async function acompanharTarefaDoVideo(t) {
  if (estado.acompanhando.has(t.id)) return;
  estado.acompanhando.add(t.id);
  const caixas = {
    previa: $("#aviso-previa"),
    transcricao: $("#progresso-legendas"),
    momentos: $("#progresso-momentos"),
    exportacao: $("#progresso-exportar"),
  };
  const videoId = t.video_id;
  try {
    if (t.tipo === "previa") {
      const aviso = $("#aviso-previa");
      aviso.hidden = false;
      while (true) {
        const atual = await api("GET", `/api/tarefas/${t.id}`).catch(() => null);
        if (!atual || atual.status === "concluida" || atual.status === "erro") break;
        aviso.querySelector("span").textContent = `${Math.round(atual.progresso * 100)}%`;
        await new Promise((r) => setTimeout(r, 1500));
      }
      aviso.hidden = true;
      if (estado.video?.id === videoId) $("#player").src = `/api/videos/${videoId}/assistir`;
      return;
    }
    const resultado = await acompanhar(t.id, estado.video?.id === videoId ? caixas[t.tipo] : null);
    if (!resultado) return;
    if (t.tipo === "momentos") avisar(`${resultado.resultado.quantidade} momentos encontrados${resultado.resultado.fonte === "ia" ? " pela IA" : ""}!`, "ok");
    if (t.tipo === "transcricao") avisar("Legenda pronta!", "ok");
    if (t.tipo === "exportacao") {
      avisar("Exportação concluída! Veja em “Cortes prontos”.", "ok");
      trocarAba("cortes");
    }
    if (estado.video?.id === videoId) await abrirVideo(videoId);
    carregarStatus();
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    estado.acompanhando.delete(t.id);
  }
}

// ---------- player e linha do tempo ----------

const player = $("#player");

player.addEventListener("timeupdate", () => {
  const atual = player.currentTime;
  $("#tempo-atual").textContent = tempo(atual);
  const duracao = estado.video?.duracao || player.duration || 1;
  $("#cabeca").style.left = `${(atual / duracao) * 100}%`;

  if (estado.pararEm != null && atual >= estado.pararEm) {
    player.pause();
    estado.pararEm = null;
  }

  const segmentos = estado.video?.transcricao?.segmentos || [];
  const seg = segmentos.find((s) => atual >= s.inicio && atual <= s.fim);
  $("#legenda-ao-vivo").textContent = seg ? seg.texto : "";
  document.querySelectorAll("#lista-transcricao li").forEach((li) => {
    li.classList.toggle("atual", seg && Number(li.dataset.inicio) === seg.inicio);
  });
});

$("#linha-tempo").addEventListener("click", (e) => {
  const caixa = e.currentTarget.getBoundingClientRect();
  const fracao = (e.clientX - caixa.left) / caixa.width;
  estado.pararEm = null;
  player.currentTime = fracao * (estado.video?.duracao || player.duration || 0);
});

function renderizarLinhaDoTempo() {
  const linha = $("#linha-tempo");
  linha.querySelectorAll(".bloco").forEach((b) => b.remove());
  const duracao = estado.video?.duracao || 1;
  estado.momentos.forEach((m, i) => {
    const bloco = document.createElement("div");
    bloco.className = `bloco ${m.selecionado !== false ? "marcado" : ""}`;
    bloco.style.left = `${(m.inicio / duracao) * 100}%`;
    bloco.style.width = `${((m.fim - m.inicio) / duracao) * 100}%`;
    bloco.textContent = i + 1;
    bloco.title = m.titulo;
    bloco.onclick = (e) => { e.stopPropagation(); tocarMomento(i); };
    linha.insertBefore(bloco, $("#cabeca"));
  });
}

function atualizarSelecao() {
  const { inicio, fim } = estado.selecao;
  const el = $("#selecao");
  const duracao = estado.video?.duracao || 1;
  if (inicio != null) {
    const f = fim ?? inicio;
    el.hidden = false;
    el.style.left = `${(Math.min(inicio, f) / duracao) * 100}%`;
    el.style.width = `${(Math.abs(f - inicio) / duracao) * 100}%`;
  } else {
    el.hidden = true;
  }
  $("#texto-selecao").textContent = inicio != null
    ? `Seleção: ${tempo(inicio, true)} → ${fim != null ? tempo(fim, true) : "?"}${fim != null ? ` (${(fim - inicio).toFixed(1)}s)` : ""}`
    : "";
  $("#botao-adicionar").disabled = !(inicio != null && fim != null && fim > inicio);
}

$("#botao-inicio").onclick = () => { estado.selecao.inicio = player.currentTime; if (estado.selecao.fim != null && estado.selecao.fim <= player.currentTime) estado.selecao.fim = null; atualizarSelecao(); };
$("#botao-fim").onclick = () => { estado.selecao.fim = player.currentTime; if (estado.selecao.inicio == null || estado.selecao.inicio >= player.currentTime) estado.selecao.inicio = Math.max(0, player.currentTime - 15); atualizarSelecao(); };
$("#botao-adicionar").onclick = async () => {
  const { inicio, fim } = estado.selecao;
  estado.momentos.push({ inicio: +inicio.toFixed(2), fim: +fim.toFixed(2), titulo: `Corte manual ${estado.momentos.length + 1}`, motivo: "", nota: 0, fonte: "manual", selecionado: true });
  estado.momentos.sort((a, b) => a.inicio - b.inicio);
  estado.selecao = { inicio: null, fim: null };
  atualizarSelecao();
  await salvarMomentos();
  renderizarMomentos();
  trocarAba("momentos");
};

document.addEventListener("keydown", (e) => {
  if (!estado.video || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  if (e.key === "i" || e.key === "I") $("#botao-inicio").click();
  else if (e.key === "o" || e.key === "O") $("#botao-fim").click();
  else if (e.key === " ") { e.preventDefault(); player.paused ? player.play() : player.pause(); }
  else if (e.key === "ArrowLeft") player.currentTime -= e.shiftKey ? 1 : 5;
  else if (e.key === "ArrowRight") player.currentTime += e.shiftKey ? 1 : 5;
});

// ---------- melhores momentos ----------

function tocarMomento(i) {
  const m = estado.momentos[i];
  estado.tocandoIndice = i;
  estado.pararEm = m.fim;
  player.currentTime = m.inicio;
  player.play();
  document.querySelectorAll(".momento").forEach((el, j) => el.classList.toggle("tocando", i === j));
}

let temporizadorSalvar;
function salvarMomentosDepois() {
  clearTimeout(temporizadorSalvar);
  temporizadorSalvar = setTimeout(salvarMomentos, 500);
}

async function salvarMomentos() {
  if (!estado.video) return;
  try {
    estado.momentos = await api("PUT", `/api/videos/${estado.video.id}/momentos`, { momentos: estado.momentos });
  } catch (erro) {
    avisar(erro.message, "erro");
  }
  renderizarLinhaDoTempo();
  atualizarResumoExportar();
}

function renderizarMomentos() {
  const lista = $("#lista-momentos");
  lista.innerHTML = "";
  if (!estado.momentos.length) {
    lista.innerHTML = `<li class="vazio-lista">Clique em “Encontrar melhores momentos” ou marque um trecho na linha do tempo e clique em “Adicionar corte”.</li>`;
  }
  estado.momentos.forEach((m, i) => {
    const li = document.createElement("li");
    li.className = "momento";
    const fonte = { ia: "🤖 IA", automatico: "📊 automático", manual: "✋ manual" }[m.fonte] || "";
    li.innerHTML = `
      <input type="checkbox" ${m.selecionado !== false ? "checked" : ""} title="Incluir na exportação">
      <div>
        <div class="titulo">${i + 1}. ${escapar(m.titulo)}</div>
        ${m.motivo ? `<div class="motivo">${escapar(m.motivo)}</div>` : ""}
        <div class="tempos">
          <input class="t-inicio" value="${tempo(m.inicio, true)}" title="Início">
          →
          <input class="t-fim" value="${tempo(m.fim, true)}" title="Fim">
          <span class="detalhes">${(m.fim - m.inicio).toFixed(1)}s</span>
          <span class="fonte">${fonte}</span>
        </div>
      </div>
      <div class="acoes">
        ${m.nota ? `<span class="nota" title="Potencial de engajamento">${m.nota}</span>` : ""}
        <button class="botao mini" data-acao="tocar" title="Assistir">▶</button>
        <button class="botao mini" data-acao="ajustar" title="Usar a seleção atual da linha do tempo">⇤⇥</button>
        <button class="botao mini perigo" data-acao="remover" title="Remover">✕</button>
      </div>`;
    li.querySelector("input[type=checkbox]").onchange = (e) => { m.selecionado = e.target.checked; salvarMomentosDepois(); };
    li.querySelector(".titulo").onclick = () => tocarMomento(i);
    li.querySelector("[data-acao=tocar]").onclick = () => tocarMomento(i);
    li.querySelector("[data-acao=remover]").onclick = async () => { estado.momentos.splice(i, 1); await salvarMomentos(); renderizarMomentos(); };
    li.querySelector("[data-acao=ajustar]").onclick = async () => {
      const { inicio, fim } = estado.selecao;
      if (inicio == null || fim == null) return avisar("Marque início e fim na linha do tempo primeiro.");
      Object.assign(m, { inicio: +inicio.toFixed(2), fim: +fim.toFixed(2) });
      await salvarMomentos(); renderizarMomentos();
    };
    for (const [classe, campo] of [[".t-inicio", "inicio"], [".t-fim", "fim"]]) {
      li.querySelector(classe).onchange = async (e) => {
        const valor = lerTempo(e.target.value);
        if (valor == null) return avisar("Tempo inválido. Use o formato 1:23.5");
        m[campo] = valor;
        if (m.fim <= m.inicio) return avisar("O fim precisa ser depois do início.", "erro");
        await salvarMomentos(); renderizarMomentos();
      };
    }
    lista.append(li);
  });
  $("#marcar-todos").checked = estado.momentos.length > 0 && estado.momentos.every((m) => m.selecionado !== false);
  renderizarLinhaDoTempo();
  atualizarResumoExportar();
}

$("#marcar-todos").onchange = (e) => {
  estado.momentos.forEach((m) => (m.selecionado = e.target.checked));
  renderizarMomentos();
  salvarMomentosDepois();
};

$("#botao-momentos").onclick = async () => {
  if (estado.momentos.length && !confirm("Isso substitui os cortes da lista atual. Continuar?")) return;
  const botao = $("#botao-momentos");
  botao.disabled = true;
  try {
    const { tarefa, usando_ia } = await api("POST", `/api/videos/${estado.video.id}/momentos`, {
      quantidade: Number($("#m-quantidade").value),
      duracao_min: Number($("#m-min").value),
      duracao_max: Number($("#m-max").value),
      instrucoes: $("#m-instrucoes").value,
      usar_ia: $("#m-ia").checked,
    });
    if (!usando_ia) avisar("Usando o modo automático (sem IA).");
    await acompanharTarefaDoVideo({ id: tarefa, tipo: "momentos", video_id: estado.video.id });
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    botao.disabled = false;
  }
};

// ---------- legendas ----------

function renderizarTranscricao() {
  const t = estado.video?.transcricao;
  const lista = $("#lista-transcricao");
  $("#botao-baixar-srt").hidden = !t;
  $("#botao-baixar-srt").href = t ? `/api/videos/${estado.video.id}/legenda.srt` : "#";
  $("#botao-transcrever").textContent = t ? "🔁 Gerar legenda de novo" : "💬 Gerar legenda automática";
  if (!t) {
    lista.innerHTML = `<li class="vazio-lista">${estado.video?.tem_audio ? "Ainda não há legenda. A legenda também é criada automaticamente quando você busca os melhores momentos ou exporta com legenda." : "Este vídeo não tem áudio."}</li>`;
    return;
  }
  lista.innerHTML = "";
  for (const s of t.segmentos) {
    const li = document.createElement("li");
    li.dataset.inicio = s.inicio;
    li.innerHTML = `<span class="t">${tempo(s.inicio)}</span><span>${escapar(s.texto)}</span>`;
    li.onclick = () => { estado.pararEm = null; player.currentTime = s.inicio; player.play(); };
    lista.append(li);
  }
}

$("#botao-transcrever").onclick = async () => {
  const botao = $("#botao-transcrever");
  botao.disabled = true;
  try {
    const { tarefa } = await api("POST", `/api/videos/${estado.video.id}/transcrever`, {
      idioma: $("#l-idioma").value || null,
      modelo: $("#l-modelo").value || null,
    });
    await acompanharTarefaDoVideo({ id: tarefa, tipo: "transcricao", video_id: estado.video.id });
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    botao.disabled = false;
  }
};

// ---------- exportar ----------

function selecionados() {
  return estado.momentos.filter((m) => m.selecionado !== false);
}

function atualizarResumoExportar() {
  const lista = selecionados();
  const total = lista.reduce((s, m) => s + (m.fim - m.inicio), 0);
  $("#resumo-exportar").textContent = lista.length
    ? `${lista.length} corte(s) selecionado(s) · ${tempo(total)} no total.`
    : "Nenhum corte selecionado. Escolha os cortes na aba “Melhores momentos”.";
  $("#botao-exportar").disabled = !lista.length;
}

function atualizarAvisoResolucao() {
  const v = estado.video;
  const aviso = $("#aviso-upscale");
  const alvo = { "1080p": 1080, "1440p": 1440, "4k": 2160 }[$("#e-resolucao").value];
  const ladoMenor = v ? Math.min(v.largura, v.altura) : 0;
  aviso.hidden = !(alvo && ladoMenor && alvo > ladoMenor);
  aviso.textContent = `Atenção: o vídeo original tem ${v?.largura}×${v?.altura}. Exportar em resolução maior aumenta o tamanho da imagem, mas não cria detalhes que não existem.`;
}
$("#e-resolucao").onchange = atualizarAvisoResolucao;

$("#botao-exportar").onclick = async () => {
  const botao = $("#botao-exportar");
  botao.disabled = true;
  try {
    const { tarefa } = await api("POST", `/api/videos/${estado.video.id}/exportar`, {
      trechos: selecionados(),
      modo: $("#e-modo").value,
      resolucao: $("#e-resolucao").value,
      formato: $("#e-formato").value,
      qualidade: $("#e-qualidade").value,
      legenda: $("#e-legenda").value,
      estilo_legenda: $("#e-estilo").value,
    });
    await acompanharTarefaDoVideo({ id: tarefa, tipo: "exportacao", video_id: estado.video.id });
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    botao.disabled = false;
    atualizarResumoExportar();
  }
};

// ---------- cortes prontos ----------

function renderizarCortes() {
  const cortes = estado.video?.cortes || [];
  const videos = cortes.filter((c) => c.nome.endsWith(".mp4"));
  $("#contador-cortes").textContent = videos.length ? `(${videos.length})` : "";
  const lista = $("#lista-cortes");
  lista.innerHTML = cortes.length ? "" : `<li class="vazio-lista">Os vídeos exportados aparecem aqui.</li>`;
  for (const c of cortes) {
    const url = `/api/videos/${estado.video.id}/cortes/${encodeURIComponent(c.nome)}`;
    const li = document.createElement("li");
    li.innerHTML = `
      <div><div class="nome">${escapar(c.nome)}</div><small>${bytes(c.tamanho)}</small></div>
      <div class="acoes">
        ${c.nome.endsWith(".mp4") ? `<button class="botao mini" data-acao="ver">▶ Ver</button>` : ""}
        <a class="botao mini" href="${url}?baixar=true">⬇ Baixar</a>
        <button class="botao mini perigo" data-acao="apagar">✕</button>
      </div>`;
    li.querySelector("[data-acao=ver]")?.addEventListener("click", () => {
      const existente = li.querySelector("video");
      if (existente) return existente.remove();
      const v = document.createElement("video");
      v.src = url; v.controls = true; v.autoplay = true;
      li.append(v);
    });
    li.querySelector("[data-acao=apagar]").onclick = async () => {
      if (!confirm(`Apagar ${c.nome}?`)) return;
      await api("DELETE", url);
      await abrirVideo(estado.video.id);
      carregarStatus();
    };
    lista.append(li);
  }
}

// ---------- abas, apagar vídeo, arrastar e soltar ----------

function trocarAba(nome) {
  document.querySelectorAll(".aba").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === nome));
  document.querySelectorAll(".conteudo-aba").forEach((c) => (c.hidden = c.dataset.aba !== nome));
}
document.querySelectorAll(".aba").forEach((a) => (a.onclick = () => trocarAba(a.dataset.aba)));

$("#botao-apagar-video").onclick = async () => {
  if (!confirm(`Apagar "${estado.video.nome}" e todos os cortes dele? Isso não pode ser desfeito.`)) return;
  await api("DELETE", `/api/videos/${estado.video.id}`);
  estado.video = null;
  player.removeAttribute("src");
  $("#editor").classList.add("vazio");
  carregarLista();
  carregarStatus();
};

$("#entrada-arquivo").onchange = (e) => {
  for (const arquivo of e.target.files) enviarArquivo(arquivo);
  e.target.value = "";
};
const area = $("#area-envio");
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); area.classList.add("arrastando"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop" || !e.relatedTarget) area.classList.remove("arrastando"); }));
document.addEventListener("drop", (e) => {
  for (const arquivo of e.dataTransfer.files) enviarArquivo(arquivo);
});

// ---------- início ----------

carregarStatus();
carregarLista();
