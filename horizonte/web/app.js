/* HORIZONTE — painel (JavaScript puro, sem dependências) */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CAT = { direito: "Direito e Justiça", politica: "Política e Instituições", sociedade: "Sociedade e Cidadania" };
const STAMP = { "VERIFICADA": "VERIFICADA", "EM CONFERÊNCIA": "EM", "CONTROVERSA": "CONTROVERSA", "NÃO PUBLICAR": "NAO" };
const STORY = { selecionada: ["Selecionada", "info"], em_producao: ["Em produção", "info"], pronta: ["Pronta", "ok"], publicada: ["Publicada", "ok"],
  suspensa: ["Suspensa", "bad"], aguardando_ia: ["Aguardando IA local", "warn"], descartada: ["Descartada", ""] };
const LIST = { agendado: ["Agendado", "info"], publicado: ["Publicado", "ok"], publicando: ["Publicando", "info"], falhou: ["Falhou", "bad"],
  suspenso: ["Suspenso", "bad"], verificar: ["Conferir no LinkedIn", "warn"], cancelado: ["Cancelado", ""] };
const XST = { pronto: ["PRONTO PARA PUBLICAR", "warn"], publicado_manual: ["PUBLICADO MANUALMENTE", "ok"], descartado: ["DESCARTADO", ""] };

const fmt = (iso, opt = {}) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", ...opt });
};
const ago = (iso) => {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 1) return "agora";
  if (m < 60) return `há ${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `há ${h} h`;
  return `há ${Math.round(h / 24)} dias`;
};
const stamp = (v) => v ? `<span class="stamp st-${STAMP[v] || "EM"}">${esc(v)}</span>` : "";
const cat = (c) => c ? `<span class="pill cat c-${esc(c)}"><span class="dot"></span>${esc(CAT[c] || c)}</span>` : "";
const state = (map, s) => { const [l, k] = map[s] || [s, ""]; return `<span class="state ${k}">${esc(l)}</span>`; };

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

async function api(path, opts = {}) {
  const init = { credentials: "same-origin", headers: {}, ...opts };
  if (opts.body && !(opts.body instanceof FormData)) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, init);
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("login"); }
  let data = null;
  try { data = await r.json(); } catch (_) { /* sem corpo */ }
  if (!r.ok) throw new Error((data && data.detail) || `Erro ${r.status}`);
  return data;
}

async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (_) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  if (btn) { const o = btn.textContent; btn.textContent = "Copiado"; setTimeout(() => (btn.textContent = o), 1400); }
}

/* ---------------------------------------------------------------- login */
function showLogin() { $("#shell").hidden = true; $("#login").hidden = false; $("#chave").focus(); }
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: { chave: $("#chave").value.trim() } });
    $("#login").hidden = true; $("#shell").hidden = false; route();
  } catch (err) { const el = $("#loginErr"); el.textContent = "Chave incorreta."; el.hidden = false; }
});

/* ---------------------------------------------------------------- roteamento */
const VIEWS = {};
let current = null;
async function route() {
  const v = (location.hash || "#dashboard").slice(1).split("/")[0];
  const view = VIEWS[v] ? v : "dashboard";
  current = view;
  $$("#nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.v === view ? "page" : "false"));
  const main = $("#main");
  try {
    await VIEWS[view](main);
    renderOp();
  } catch (e) {
    if (e.message !== "login") main.innerHTML = `<div class="notice bad">Não foi possível carregar: ${esc(e.message)}</div>`;
  }
}
window.addEventListener("hashchange", route);

async function renderOp() {
  try {
    const s = await api("/api/estado");
    $("#op").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <span class="state ${s.pausado ? "warn" : "ok"}">${s.pausado ? "Pausado" : "Operando"}</span>
        <button class="btn small" id="opToggle">${s.pausado ? "Retomar" : "Pausar"}</button>
      </div>
      <div class="opx muted" style="font-size:12px">Último ciclo: ${s.ultimo_ciclo ? fmt(s.ultimo_ciclo.started_at) : "ainda não rodou"}</div>`;
    $("#opToggle").onclick = async () => { await api("/api/operacao", { method: "POST", body: { pausado: !s.pausado } }); toast(s.pausado ? "Operação retomada." : "Operação pausada."); route(); };
  } catch (_) { /* silencioso */ }
}

/* ---------------------------------------------------------------- dashboard */
VIEWS.dashboard = async (main) => {
  const s = await api("/api/estado");
  const h = s.hoje, li = s.conexoes.linkedin, ia = s.conexoes.ia;
  const pct = (a, b) => Math.min(100, Math.round((a / Math.max(1, b)) * 100));
  main.innerHTML = `
    <div class="page-head">
      <div><h1>Dashboard</h1><p>${s.pausado ? "A operação está pausada: nenhuma rotina automática roda até você retomar." : "O HORIZONTE está operando sozinho dentro das regras editoriais."} Hoje é ${new Date(s.agora).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" })}.</p></div>
      <div class="actions"><button class="btn" id="bRadar">Atualizar radar agora</button><button class="btn primary" id="bCiclo">Rodar ciclo do dia agora</button></div>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="v">${h.noticias}</div><div class="l">notícias monitoradas hoje</div></div>
      <div class="kpi"><div class="v">${h.verificadas}</div><div class="l">fatos verificados (hoje)</div></div>
      <div class="kpi"><div class="v">${h.prontas}<small> / ${Math.max(s.metas.linkedin, s.metas.x)}</small></div><div class="l">pautas prontas</div><div class="bar"><i style="width:${pct(h.prontas, Math.max(s.metas.linkedin, s.metas.x))}%"></i></div></div>
      <div class="kpi"><div class="v">${h.linkedin_publicados}<small> / ${s.metas.linkedin}</small></div><div class="l">publicados no LinkedIn · ${h.linkedin_agendados} agendado(s)</div><div class="bar"><i style="width:${pct(h.linkedin_publicados, s.metas.linkedin)}%"></i></div></div>
      <div class="kpi"><div class="v">${h.x_pendentes}</div><div class="l">conteúdos do X aguardando você · ${h.x_publicados} publicado(s)</div></div>
    </div>
    <div class="grid g3" style="margin-bottom:14px">
      <div class="card"><h2>LinkedIn</h2>
        <p style="margin:0 0 6px">${li.conectado ? `<span class="state ok">Conectado</span> ${esc(li.nome || "")}` : `<span class="state ${li.configurado ? "warn" : "bad"}">${li.configurado ? "Não conectado" : "Não configurado"}</span>`}</p>
        <p class="muted" style="margin:0 0 6px;font-size:13px">${esc(li.mensagem)}</p>
        <p style="margin:0;font-size:13px">Modo automático: <b>${li.modo_auto ? "ligado" : "desligado"}</b>${li.dias_restantes != null ? ` · autorização vence em ${li.dias_restantes} dia(s)` : ""}</p></div>
      <div class="card"><h2>IA local (Ollama)</h2>
        <p style="margin:0 0 6px"><span class="state ${ia.pronto ? "ok" : ia.instalado ? "warn" : "bad"}">${ia.pronto ? "Pronta" : ia.instalado ? "Modelo ausente" : "Não encontrada"}</span> <span class="mono muted">${esc(ia.modelo)}</span></p>
        <p class="muted" style="margin:0;font-size:13px">${esc(ia.mensagem)}${ia.pronto ? "" : " Sem a IA, o radar e a verificação continuam, mas as análises ficam em espera."}</p></div>
      <div class="card"><h2>X</h2>
        <p style="margin:0 0 6px"><span class="state info">Publicação manual</span></p>
        <p class="muted" style="margin:0;font-size:13px">O HORIZONTE prepara os conteúdos; você publica pela <a href="#x">Central do X</a> e marca como publicado.</p></div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Próximas publicações no LinkedIn</h2>
        ${s.proximas_linkedin.length ? `<div class="list">${s.proximas_linkedin.map((p) => `<div class="row"><div class="t">${esc(p.title)}</div><div class="meta">${cat(p.category)}<span class="mono">${fmt(p.scheduled_for)}</span>${li.modo_auto ? "" : '<span class="state warn">aguardando modo automático</span>'}</div></div>`).join("")}</div>` : '<div class="empty">Nada agendado. O ciclo do dia agenda as próximas.</div>'}
      </div>
      <div class="card"><h2>Atividade recente</h2>
        <div>${s.atividade.map((l) => `<div class="log"><span class="faint">${fmt(l.ts)}</span><span class="lv-${l.level}">${esc(l.level)}</span><span class="muted">${esc(l.module)}</span><span class="m">${esc(l.message)}</span></div>`).join("") || '<div class="empty">Sem atividade ainda.</div>'}</div>
      </div>
    </div>
    <p class="faint" style="margin-top:14px;font-size:12px">Fontes ligadas: ${s.fontes.ligadas} (${s.fontes.com_erro} com erro) · Último radar: ${s.ultimo_radar ? ago(s.ultimo_radar.started_at) : "—"} · Agendador: ${s.agendador.ativo ? "ativo" : "parado"}</p>`;
  $("#bRadar").onclick = async () => { const r = await api("/api/radar/atualizar", { method: "POST" }); toast(r.ok ? "Radar em andamento. Atualize em alguns segundos." : r.mensagem); };
  $("#bCiclo").onclick = async () => { const r = await api("/api/ciclo/executar", { method: "POST" }); toast(r.ok ? "Ciclo iniciado. Com a IA local, pode levar alguns minutos." : r.mensagem, 5000); };
};

/* ---------------------------------------------------------------- radar */
const radarF = { categoria: "", regiao: "", fonte: "", status: "", q: "", ordem: "relevancia", desde: "" };
VIEWS.radar = async (main) => {
  const qs = new URLSearchParams(Object.entries(radarF).filter(([, v]) => v)).toString();
  const d = await api("/api/radar?" + qs);
  const chip = (key, val, label) => `<button data-k="${key}" data-v="${val}" aria-pressed="${radarF[key] === val}">${label}</button>`;
  main.innerHTML = `
    <div class="page-head"><div><h1>Radar de Notícias</h1><p>Últimas 72 horas, das fontes ligadas. Cada notícia mostra o status de verificação do fato a que pertence.</p></div>
      <div class="actions"><button class="btn" id="bR">Atualizar agora</button></div></div>
    <div class="filters">
      <span class="chips">${chip("categoria", "", "Todas")}${chip("categoria", "direito", "Direito")}${chip("categoria", "politica", "Política")}${chip("categoria", "sociedade", "Sociedade")}</span>
      <span class="chips">${chip("regiao", "", "Brasil e Pará")}${chip("regiao", "BR", "Brasil")}${chip("regiao", "PA", "Pará")}</span>
      <select id="fFonte" aria-label="Fonte"><option value="">Todas as fontes</option>${d.fontes.map((f) => `<option value="${f.id}" ${String(radarF.fonte) === String(f.id) ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select>
      <select id="fStatus" aria-label="Status"><option value="">Qualquer status</option>${Object.keys(STAMP).map((k) => `<option ${radarF.status === k ? "selected" : ""}>${k}</option>`).join("")}</select>
      <input type="date" id="fDesde" value="${esc(radarF.desde)}" aria-label="Desde">
      <select id="fOrdem" aria-label="Ordem"><option value="relevancia" ${radarF.ordem === "relevancia" ? "selected" : ""}>Mais relevantes</option><option value="data" ${radarF.ordem === "data" ? "selected" : ""}>Mais recentes</option></select>
      <input type="search" id="fQ" placeholder="Buscar no título" value="${esc(radarF.q)}">
    </div>
    <div class="card"><div class="list">${d.itens.map((n) => `
      <div class="row news">
        <div>${stamp(n.verification)}<div class="faint mono" style="font-size:11px;margin-top:4px">${n.n_orgs || 1} veículo(s)</div></div>
        <div style="min-width:0"><a class="t" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>
          <div class="meta">${cat(n.category)}${n.region === "PA" ? '<span class="state info">Pará</span>' : ""}<span>${esc(n.fonte)}</span><span class="mono">${fmt(n.published_at || n.fetched_at)}</span>${n.is_update ? '<span class="state warn">atualização de pauta</span>' : ""}${(n.flags || []).filter((f) => ["acusacao", "proposicao", "decisao_provisoria"].includes(f)).map((f) => `<span class="faint">${{ acusacao: "envolve acusação", proposicao: "proposição", decisao_provisoria: "decisão provisória" }[f]}</span>`).join("")}</div></div>
        <div class="rel">relevância ${n.relevance}<div class="bar"><i style="width:${n.relevance}%"></i></div></div>
      </div>`).join("") || '<div class="empty">Nenhuma notícia com esses filtros. Rode o radar ou amplie os filtros.</div>'}</div></div>`;
  $$(".chips button", main).forEach((b) => (b.onclick = () => { radarF[b.dataset.k] = b.dataset.v; route(); }));
  $("#fFonte").onchange = (e) => { radarF.fonte = e.target.value; route(); };
  $("#fStatus").onchange = (e) => { radarF.status = e.target.value; route(); };
  $("#fOrdem").onchange = (e) => { radarF.ordem = e.target.value; route(); };
  $("#fDesde").onchange = (e) => { radarF.desde = e.target.value; route(); };
  $("#fQ").onkeydown = (e) => { if (e.key === "Enter") { radarF.q = e.target.value.trim(); route(); } };
  $("#bR").onclick = async () => { const r = await api("/api/radar/atualizar", { method: "POST" }); toast(r.ok ? "Radar em andamento." : r.mensagem); setTimeout(() => current === "radar" && route(), 9000); };
};

/* ---------------------------------------------------------------- central editorial */
let storySel = null;
VIEWS.editorial = async (main) => {
  const d = await api("/api/pautas");
  if (!storySel && d.itens.length) storySel = d.itens[0].id;
  const byDay = {};
  d.itens.forEach((s) => (byDay[s.day] = byDay[s.day] || []).push(s));
  main.innerHTML = `
    <div class="page-head"><div><h1>Central Editorial</h1><p>Pautas selecionadas, verificação, análise e os textos de cada rede, com o histórico completo.</p></div></div>
    <div class="split">
      <div class="card" style="padding:8px">${Object.entries(byDay).map(([day, items]) => `
        <div class="faint mono" style="font-size:11px;letter-spacing:.1em;padding:10px 10px 4px">${new Date(day + "T12:00").toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).toUpperCase()}</div>
        ${items.map((s) => `<div class="pick" data-id="${s.id}" aria-current="${s.id === storySel}" tabindex="0">
          <div class="t" style="font-weight:500">${esc(s.title)}</div>
          <div class="meta" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">${cat(s.category)}${state(STORY, s.status)}</div></div>`).join("")}`).join("") || '<div class="empty">Ainda não há pautas. O ciclo diário seleciona as pautas verificadas.</div>'}
      </div>
      <div class="card article" id="storyBox"><div class="empty">Escolha uma pauta.</div></div>
    </div>`;
  $$(".pick", main).forEach((p) => {
    const open = () => { storySel = Number(p.dataset.id); $$(".pick", main).forEach((x) => x.setAttribute("aria-current", x === p)); renderStory(); };
    p.onclick = open; p.onkeydown = (e) => e.key === "Enter" && open();
  });
  if (storySel) renderStory();
};

async function renderStory() {
  const box = $("#storyBox");
  if (!box) return;
  const s = await api(`/api/pautas/${storySel}`);
  const a = s.analysis || {};
  const g = s.grupo || {};
  const list = (arr) => (arr && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : '<p class="muted">—</p>');
  box.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px">${stamp(g.verification)}${cat(s.category)}${state(STORY, s.status)}<span class="faint mono" style="font-size:12px">pauta #${s.id}</span></div>
    <h2 class="headline">${esc(a.titulo || g.title)}</h2>
    <p class="muted" style="font-size:13px">${esc(s.reason || "")}</p>
    <div class="actions" style="margin-top:10px">
      ${["suspensa", "aguardando_ia"].includes(s.status) ? '<button class="btn" id="bProd">Produzir de novo</button>' : ""}
      ${!["suspensa", "publicada"].includes(s.status) ? '<button class="btn danger" id="bSusp">Suspender pauta</button>' : ""}
    </div>
    <section><h4>Verificação</h4>${list(g.verification_notes)}</section>
    ${a.o_que_aconteceu ? `
      <section><h4>O que aconteceu</h4><p>${esc(a.o_que_aconteceu)}</p></section>
      <section><h4>Contexto</h4><p>${esc(a.contexto)}</p></section>
      <section><h4>Fatos confirmados</h4>${list(a.fatos_confirmados)}</section>
      <section><h4>Informações atribuídas</h4>${list(a.informacoes_atribuidas)}</section>
      <section><h4>Relevância</h4><p>${esc(a.relevancia)}</p></section>
      <section><h4>Análise crítica</h4><p>${esc(a.analise_critica)}</p></section>
      <section><h4>Reflexão</h4><p>${esc(a.reflexao)}</p></section>
      <section><h4>Cautelas</h4>${list(a.cautelas)}</section>` : '<section><div class="notice">A análise ainda não foi produzida para esta pauta.</div></section>'}
    <section><h4>Fontes do fato (${s.fontes.length})</h4><div class="list">${s.fontes.map((f) => `<div class="row"><a class="t" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a><div class="meta"><span>${esc(f.fonte)}</span><span class="mono">${fmt(f.published_at)}</span>${f.tier === "primaria" ? '<span class="state ok">fonte primária</span>' : ""}</div></div>`).join("")}</div></section>
    ${s.posts.map((p) => `<section><h4>${p.network === "linkedin" ? "LinkedIn" : "X"} · ${p.network === "linkedin" ? (LIST[p.status] || [p.status])[0] : (XST[p.status] || [p.status])[0]}</h4><div class="post-text">${esc(p.thread && p.thread.length ? p.thread.join("\n\n— — —\n\n") : p.body)}</div></section>`).join("")}
    <section><h4>Histórico</h4><ul class="timeline">${s.historico.map((e) => `<li><span class="mono faint">${fmt(e.ts)}</span> · <b>${esc(e.event)}</b>${e.detail ? ` — <span class="muted">${esc(e.detail)}</span>` : ""}</li>`).join("")}</ul></section>`;
  const bS = $("#bSusp");
  if (bS) bS.onclick = async () => { await api(`/api/pautas/${s.id}/suspender`, { method: "POST", body: {} }); toast("Pauta suspensa."); route(); };
  const bP = $("#bProd");
  if (bP) bP.onclick = async () => { const r = await api(`/api/pautas/${s.id}/produzir`, { method: "POST" }); toast(r.ok ? "Produção iniciada." : r.mensagem); };
}

/* ---------------------------------------------------------------- LinkedIn */
VIEWS.linkedin = async (main) => {
  const d = await api("/api/linkedin");
  const e = d.estado;
  main.innerHTML = `
    <div class="page-head"><div><h1>LinkedIn</h1><p>Publicação automática no seu perfil pela API oficial (OAuth). Sem robôs de navegador e sem serviços pagos.</p></div></div>
    <div class="grid g2" style="margin-bottom:14px">
      <div class="card"><h2>Conta</h2>
        <p style="margin:0 0 8px">${e.conectado ? `<span class="state ok">Conectada</span> <b>${esc(e.nome || "")}</b>` : `<span class="state ${e.configurado ? "warn" : "bad"}">${e.configurado ? "Não conectada" : "App não configurado"}</span>`}</p>
        <p class="muted" style="margin:0 0 10px;font-size:13px">${esc(e.mensagem)}</p>
        <table><tbody>
          <tr><th>Permissões</th><td class="mono">${esc((e.permissoes || []).join(", ") || "—")}</td></tr>
          <tr><th>Autorização vence</th><td>${e.expira_em ? `${fmt(e.expira_em, { year: "numeric" })} (${e.dias_restantes} dias)` : "—"}</td></tr>
          <tr><th>Versão da API</th><td class="mono">${esc(e.versao_api)}</td></tr>
          <tr><th>Endereço de retorno</th><td class="mono" style="overflow-wrap:anywhere">${esc(e.redirect_uri)}</td></tr>
        </tbody></table>
        <div class="actions" style="margin-top:12px">
          ${e.configurado ? `<a class="btn primary" href="/api/linkedin/conectar">${e.conectado ? "Reconectar" : "Conectar conta do LinkedIn"}</a>` : ""}
          ${e.conectado ? '<button class="btn danger" id="bDisc">Desconectar</button>' : ""}
        </div></div>
      <div class="card"><h2>Modo automático</h2>
        <label class="switch"><input type="checkbox" id="auto" ${e.modo_auto ? "checked" : ""} ${e.pode_publicar ? "" : "disabled"}> Publicar sozinho nos horários configurados</label>
        <p class="muted" style="font-size:13px">Ligado, o HORIZONTE publica sem pedir aprovação a cada post. Ele suspende sozinho a pauta que perder a verificação, que tiver risco jurídico ou problema de imagem.</p>
        <h3 style="margin-top:16px">Publicação de teste</h3>
        <p class="muted" style="font-size:13px;margin-top:0">Publica uma mensagem curta, visível só para suas conexões, para confirmar que a integração funciona.</p>
        <label class="switch"><input type="checkbox" id="confTest"> Confirmo que quero publicar o teste</label>
        <div class="actions" style="margin-top:8px"><button class="btn" id="bTest" ${e.conectado ? "" : "disabled"}>Publicar teste</button></div>
      </div>
    </div>
    <div class="card"><h2>Publicações</h2><div class="list">${d.posts.map((p) => `
      <div class="row">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><span class="t">${esc(p.title)}</span><span>${state(LIST, p.status)}</span></div>
        <div class="meta">${cat(p.category)}<span class="mono">${p.published_at ? "publicado " + fmt(p.published_at) : p.scheduled_for ? "agendado " + fmt(p.scheduled_for) : ""}</span>${p.external_url ? `<a href="${esc(p.external_url)}" target="_blank" rel="noopener">ver no LinkedIn</a>` : ""}${p.image && p.image.autorizada ? `<span>imagem: ${esc(p.image.credito)}</span>` : ""}</div>
        ${p.error ? `<div class="notice bad" style="margin-top:6px">${esc(p.error)}</div>` : ""}
        <details style="margin-top:6px"><summary class="muted" style="cursor:pointer">Texto</summary>
          <textarea id="tx${p.id}" ${["publicado", "publicando"].includes(p.status) ? "readonly" : ""}>${esc(p.body)}</textarea>
          <div class="actions" style="margin-top:6px">
            <button class="btn small" data-copy="${p.id}">Copiar texto</button>
            ${["agendado", "falhou", "suspenso"].includes(p.status) ? `<button class="btn small" data-save="${p.id}">Salvar edição</button>` : ""}
            ${["agendado", "falhou"].includes(p.status) && e.conectado ? `<button class="btn small primary" data-pub="${p.id}">Publicar agora</button>` : ""}
            ${["verificar", "falhou", "suspenso"].includes(p.status) ? `<button class="btn small" data-res="${p.id}" data-a="tentar_de_novo">Tentar de novo</button><button class="btn small" data-res="${p.id}" data-a="marcar_publicado">Já saiu: marcar publicado</button>` : ""}
            ${["agendado", "falhou", "suspenso", "verificar"].includes(p.status) ? `<button class="btn small danger" data-res="${p.id}" data-a="cancelar">Cancelar</button>` : ""}
            ${["agendado", "falhou", "suspenso"].includes(p.status) ? `<label class="btn small" style="cursor:pointer">Anexar imagem sua<input type="file" accept="image/jpeg,image/png,image/gif" data-up="${p.id}" hidden></label>` : ""}
          </div></details>
      </div>`).join("") || '<div class="empty">Nenhuma publicação ainda.</div>'}</div></div>`;
  const auto = $("#auto");
  if (auto) auto.onchange = async () => { try { await api("/api/linkedin/modo", { method: "POST", body: { automatico: auto.checked } }); toast(auto.checked ? "Modo automático ligado." : "Modo automático desligado."); } catch (err) { auto.checked = false; toast(err.message); } };
  const bd = $("#bDisc");
  if (bd) bd.onclick = async () => { await api("/api/linkedin/desconectar", { method: "POST" }); toast("Conta desconectada."); route(); };
  $("#bTest").onclick = async () => {
    if (!$("#confTest").checked) return toast("Marque a confirmação antes de publicar o teste.");
    const r = await api("/api/linkedin/teste", { method: "POST", body: { confirmo: true } });
    toast(r.ok ? "Teste publicado." : r.mensagem, 6000); route();
  };
  $$("[data-copy]", main).forEach((b) => (b.onclick = () => copy($("#tx" + b.dataset.copy).value, b)));
  $$("[data-save]", main).forEach((b) => (b.onclick = async () => { await api(`/api/posts/${b.dataset.save}/texto`, { method: "PUT", body: { texto: $("#tx" + b.dataset.save).value } }); toast("Texto salvo."); }));
  $$("[data-pub]", main).forEach((b) => (b.onclick = async () => { b.disabled = true; const r = await api(`/api/linkedin/posts/${b.dataset.pub}/publicar`, { method: "POST" }); toast(r.ok ? "Publicado." : r.mensagem, 6000); route(); }));
  $$("[data-res]", main).forEach((b) => (b.onclick = async () => {
    let url = null;
    if (b.dataset.a === "marcar_publicado") { url = prompt("Cole o link do post no LinkedIn (opcional):") || null; }
    await api(`/api/linkedin/posts/${b.dataset.res}/resolver`, { method: "POST", body: { acao: b.dataset.a, url } }); route();
  }));
  $$("[data-up]", main).forEach((inp) => (inp.onchange = () => upload(inp)));
};

async function upload(inp) {
  const f = inp.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("arquivo", f);
  try { await api(`/api/posts/${inp.dataset.up}/imagem`, { method: "POST", body: fd }); toast("Imagem anexada."); route(); }
  catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------------- Central do X */
let xFilter = "pronto";
VIEWS.x = async (main) => {
  const d = await api("/api/x?status=" + (xFilter || ""));
  main.innerHTML = `
    <div class="page-head"><div><h1>Central de Publicações do X</h1><p>Conteúdos prontos para você publicar manualmente. O HORIZONTE não publica no X; só você marca o que saiu.</p></div>
      <span class="chips"><button data-f="pronto" aria-pressed="${xFilter === "pronto"}">Prontos</button><button data-f="publicado_manual" aria-pressed="${xFilter === "publicado_manual"}">Publicados</button><button data-f="" aria-pressed="${xFilter === ""}">Todos</button></span></div>
    <div class="xgrid">${d.itens.map((p) => {
      const parts = p.thread && p.thread.length ? p.thread : [p.body];
      const img = p.image || {};
      const src = (p.sources || [])[0] || {};
      return `<article class="card xcard">
        <div class="head"><div style="display:grid;gap:6px">${cat(p.category)}<h3>${esc(p.title)}</h3></div>${state(XST, p.status)}</div>
        <div class="meta muted" style="font-size:12px;display:flex;gap:10px;flex-wrap:wrap"><span class="mono">notícia de ${fmt(p.news_date)}</span><span>${p.format === "thread" ? `thread com ${parts.length} posts` : "post único"}</span></div>
        ${img.autorizada && img.url ? `<img src="${esc(img.url)}" alt="Imagem da pauta" loading="lazy"><div class="faint" style="font-size:12px">${esc(img.credito || "")}</div>` : img.observacao ? `<div class="notice">${esc(img.observacao)}</div>` : '<div class="faint" style="font-size:12px">Sem imagem para esta pauta.</div>'}
        ${parts.map((t, i) => `<div class="tweet"><div class="post-text">${esc(t)}</div><div style="display:flex;justify-content:space-between;align-items:center"><span class="count ${(p.thread_caracteres[i] ?? p.caracteres) > 280 ? "over" : ""}">${p.thread_caracteres[i] ?? p.caracteres}/280</span><button class="btn small" data-c="${p.id}:${i}">Copiar${parts.length > 1 ? ` ${i + 1}/${parts.length}` : ""}</button></div></div>`).join("")}
        ${p.hashtags && p.hashtags.length ? `<div class="faint mono" style="font-size:12px">${p.hashtags.map((h) => "#" + esc(h)).join(" ")}</div>` : ""}
        ${p.error ? `<div class="notice">${esc(p.error)}</div>` : ""}
        <div class="faint" style="font-size:12px">Fontes: ${(p.sources || []).map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.veiculo)}</a>`).join(" · ")}</div>
        <div class="actions">
          ${src.url ? `<a class="btn small" href="${esc(src.url)}" target="_blank" rel="noopener">Abrir fonte</a>` : ""}
          ${img.autorizada && img.url ? `<a class="btn small" href="${esc(img.url)}" target="_blank" rel="noopener">Abrir imagem</a>` : ""}
          <a class="btn small" href="https://x.com/compose/post" target="_blank" rel="noopener">Abrir o X</a>
          ${p.status === "pronto" ? `<button class="btn small primary" data-m="${p.id}">Marcar como publicado</button><label class="btn small" style="cursor:pointer">Anexar imagem sua<input type="file" accept="image/jpeg,image/png,image/gif" data-up="${p.id}" hidden></label><button class="btn small danger" data-d="${p.id}">Descartar</button>` : p.status === "publicado_manual" ? `<button class="btn small" data-u="${p.id}">Desfazer</button>${p.external_url ? `<a class="btn small" href="${esc(p.external_url)}" target="_blank" rel="noopener">Ver post</a>` : ""}` : ""}
        </div></article>`;
    }).join("") || '<div class="card empty">Nada aqui por enquanto.</div>'}</div>`;
  $$("[data-f]", main).forEach((b) => (b.onclick = () => { xFilter = b.dataset.f; route(); }));
  const byId = Object.fromEntries(d.itens.map((p) => [p.id, p]));
  $$("[data-c]", main).forEach((b) => (b.onclick = () => { const [id, i] = b.dataset.c.split(":"); const p = byId[id]; copy((p.thread && p.thread.length ? p.thread : [p.body])[Number(i)], b); }));
  $$("[data-m]", main).forEach((b) => (b.onclick = async () => { const url = prompt("Cole o link do post no X (opcional):") || null; await api(`/api/x/${b.dataset.m}/publicado`, { method: "POST", body: { publicado: true, url } }); toast("Marcado como publicado."); route(); }));
  $$("[data-u]", main).forEach((b) => (b.onclick = async () => { await api(`/api/x/${b.dataset.u}/publicado`, { method: "POST", body: { publicado: false } }); route(); }));
  $$("[data-d]", main).forEach((b) => (b.onclick = async () => { await api(`/api/x/${b.dataset.d}/descartar`, { method: "POST" }); route(); }));
  $$("[data-up]", main).forEach((inp) => (inp.onchange = () => upload(inp)));
};

/* ---------------------------------------------------------------- relatórios */
let repSel = null;
VIEWS.relatorios = async (main) => {
  const d = await api("/api/relatorios");
  if (!repSel && d.itens.length) repSel = d.itens[0].id;
  const label = { diario: "Diário", semanal: "Semanal", mensal: "Mensal" };
  main.innerHTML = `
    <div class="page-head"><div><h1>Relatórios</h1><p>O relatório diário é gerado sozinho no horário configurado. Os semanais e mensais saem no início de cada período.</p></div>
      <div class="actions"><select id="rTipo"><option value="diario">Diário</option><option value="semanal">Semanal</option><option value="mensal">Mensal</option></select><input type="date" id="rData" value="${new Date().toLocaleDateString("sv-SE")}"><button class="btn primary" id="rGen">Gerar agora</button></div></div>
    <div class="split">
      <div class="card" style="padding:8px">${d.itens.map((r) => `<div class="pick" data-id="${r.id}" aria-current="${r.id === repSel}" tabindex="0"><div class="t">${label[r.kind]} · ${r.period_start === r.period_end ? new Date(r.period_start + "T12:00").toLocaleDateString("pt-BR") : `${new Date(r.period_start + "T12:00").toLocaleDateString("pt-BR")} a ${new Date(r.period_end + "T12:00").toLocaleDateString("pt-BR")}`}</div><div class="faint mono" style="font-size:11px">gerado ${fmt(r.created_at)}</div></div>`).join("") || '<div class="empty">Nenhum relatório ainda.</div>'}</div>
      <div class="card report" id="repBox"><div class="empty">Escolha um relatório.</div></div>
    </div>`;
  $("#rGen").onclick = async () => { const r = await api("/api/relatorios/gerar", { method: "POST", body: { tipo: $("#rTipo").value, data: $("#rData").value } }); repSel = r.id; toast("Relatório gerado."); route(); };
  $$(".pick", main).forEach((p) => { const open = () => { repSel = Number(p.dataset.id); $$(".pick", main).forEach((x) => x.setAttribute("aria-current", x === p)); renderReport(); }; p.onclick = open; p.onkeydown = (e) => e.key === "Enter" && open(); });
  if (repSel) renderReport();
};

async function renderReport() {
  const r = await api(`/api/relatorios/${repSel}`);
  const s = r.resumo, o = r.ocorrencias;
  const sec = (title, arr, fn) => `<h3>${title} (${arr.length})</h3>${arr.length ? `<div class="list">${arr.map(fn).join("")}</div>` : '<p class="muted">Nada a registrar.</p>'}`;
  $("#repBox").innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:flex-start">
      <div><h2 class="headline" style="font-family:var(--f-display);font-size:22px;text-transform:none;letter-spacing:0;color:var(--text);margin:0">${esc(r.titulo)}</h2><p class="muted" style="margin:4px 0 0">${r.periodo.inicio === r.periodo.fim ? r.periodo.inicio : `${r.periodo.inicio} a ${r.periodo.fim}`}</p></div>
      <div class="actions"><a class="btn" href="/api/relatorios/${repSel}/pdf">Baixar PDF</a><a class="btn" href="/api/relatorios/${repSel}/csv">Baixar CSV</a></div></div>
    <h3>Resumo executivo</h3>
    <table><tbody>
      <tr><th>Notícias monitoradas</th><td class="mono">${s.noticias_monitoradas}</td></tr>
      <tr><th>Pautas selecionadas</th><td class="mono">${s.pautas_selecionadas}</td></tr>
      <tr><th>Pautas verificadas</th><td class="mono">${s.pautas_verificadas}</td></tr>
      <tr><th>Conteúdos produzidos</th><td class="mono">${s.conteudos_produzidos}</td></tr>
      <tr><th>Publicados no LinkedIn</th><td class="mono">${s.linkedin_publicados}</td></tr>
      <tr><th>Preparados para o X</th><td class="mono">${s.x_preparados}</td></tr>
      ${Object.entries(s.categorias).map(([k, v]) => `<tr><th>${esc(k)}</th><td class="mono">${v}</td></tr>`).join("")}
    </tbody></table>
    ${sec("LinkedIn", r.linkedin, (i) => `<div class="row"><div class="t">${esc(i.titulo)}</div><div class="meta"><span>${esc(i.categoria)}</span><span>${esc(i.situacao)}</span><span class="mono">${fmt(i.data_hora)}</span>${i.link ? `<a href="${esc(i.link)}" target="_blank" rel="noopener">link do post</a>` : ""}</div><details><summary class="muted" style="cursor:pointer">Texto publicado</summary><div class="post-text">${esc(i.texto)}</div></details></div>`)}
    ${sec("X", r.x, (i) => `<div class="row"><div class="t">${esc(i.titulo)}</div><div class="meta"><span>${esc(i.situacao)}</span>${i.link ? `<a href="${esc(i.link)}" target="_blank" rel="noopener">notícia</a>` : ""}${i.poster ? `<span>poster: ${esc(i.poster.credito)}</span>` : ""}</div><details><summary class="muted" style="cursor:pointer">Texto</summary><div class="post-text">${esc(i.thread && i.thread.length ? i.thread.join("\n\n") : i.texto)}</div></details></div>`)}
    <h3>Ocorrências</h3>
    ${sec("Publicações não realizadas", o.publicacoes_nao_realizadas, (i) => `<div class="row"><div class="t">${esc(i.titulo)}</div><div class="meta">${esc(i.situacao)} ${i.motivo ? "· " + esc(i.motivo) : ""}</div></div>`)}
    ${sec("Pautas suspensas", o.pautas_suspensas, (i) => `<div class="row"><div class="meta">Pauta #${i.pauta} · ${esc(i.motivo)}</div></div>`)}
    ${sec("Notícias descartadas", o.noticias_descartadas, (i) => `<div class="row"><div class="t">${esc(i.titulo)}</div><div class="meta">${stamp(i.status)} ${esc(i.motivo)}</div></div>`)}
    ${sec("Restrições de imagem", o.restricoes_de_imagem, (i) => `<div class="row"><div class="t">${esc(i.titulo)}</div><div class="meta">${esc(i.motivo)}</div></div>`)}
    ${sec("Falhas de integração", o.falhas_de_integracao, (i) => `<div class="row"><div class="meta"><span class="mono">${fmt(i.ts)}</span> ${esc(i.message)}</div></div>`)}
    ${sec("Problemas técnicos", o.problemas_tecnicos, (i) => `<div class="row"><div class="meta"><span class="mono">${fmt(i.ts)}</span> ${esc(i.message)}</div></div>`)}
    ${sec("Fontes com erro", o.fontes_com_erro, (i) => `<div class="row"><div class="meta">${esc(i.name)} · ${esc(i.last_error)}</div></div>`)}`;
}

/* ---------------------------------------------------------------- configurações */
let cfgTab = "geral";
VIEWS.config = async (main) => {
  main.innerHTML = `
    <div class="page-head"><div><h1>Configurações</h1><p>Preferências editoriais, horários, fontes, IA local e registros do sistema.</p></div></div>
    <div class="tabs chips" style="display:inline-flex">${[["geral", "Geral"], ["fontes", "Fontes"], ["logs", "Registros"]].map(([k, l]) => `<button data-t="${k}" aria-pressed="${cfgTab === k}">${l}</button>`).join("")}</div>
    <div id="cfgBox"></div>`;
  $$("[data-t]", main).forEach((b) => (b.onclick = () => { cfgTab = b.dataset.t; route(); }));
  if (cfgTab === "geral") return cfgGeral();
  if (cfgTab === "fontes") return cfgFontes();
  return cfgLogs();
};

async function cfgGeral() {
  const c = await api("/api/config");
  const p = c.preferencias, ia = c.ia;
  const models = [...new Set([...(ia.modelos || []), p.ollama_modelo].filter(Boolean))];
  $("#cfgBox").innerHTML = `
    <form class="card" id="cfgForm" style="display:grid;gap:18px">
      <h2>Distribuição e metas</h2>
      <div class="form">
        <div class="field"><label for="c1">Posts por dia no LinkedIn</label><input type="number" min="0" max="10" id="c1" name="linkedin_por_dia" value="${p.linkedin_por_dia}"></div>
        <div class="field"><label for="c2">Conteúdos por dia para o X</label><input type="number" min="0" max="10" id="c2" name="x_por_dia" value="${p.x_por_dia}"></div>
        <div class="field"><label for="c3">Horários do LinkedIn (separe por vírgula)</label><input type="text" id="c3" name="linkedin_horarios" value="${esc(p.linkedin_horarios.join(", "))}"></div>
        <div class="field"><label for="c4">Visibilidade no LinkedIn</label><select id="c4" name="linkedin_visibilidade"><option value="PUBLIC" ${p.linkedin_visibilidade === "PUBLIC" ? "selected" : ""}>Pública</option><option value="CONNECTIONS" ${p.linkedin_visibilidade === "CONNECTIONS" ? "selected" : ""}>Só conexões</option></select></div>
      </div>
      <h2>Equilíbrio editorial (%)</h2>
      <div class="form">
        <div class="field"><label for="d1">Direito e Justiça</label><input type="number" id="d1" data-dist="direito" value="${p.distribuicao.direito}"></div>
        <div class="field"><label for="d2">Política e Instituições</label><input type="number" id="d2" data-dist="politica" value="${p.distribuicao.politica}"></div>
        <div class="field"><label for="d3">Sociedade e Cidadania</label><input type="number" id="d3" data-dist="sociedade" value="${p.distribuicao.sociedade}"></div>
      </div>
      <h2>Rotina automática (fuso ${esc(c.ambiente.fuso)})</h2>
      <div class="form">
        <div class="field"><label for="r1">Horário do ciclo diário</label><input type="time" id="r1" name="horario_ciclo" value="${p.horario_ciclo}"></div>
        <div class="field"><label for="r2">Horário do relatório diário</label><input type="time" id="r2" name="horario_relatorio" value="${p.horario_relatorio}"></div>
        <div class="field"><label for="r3">Radar a cada (minutos)</label><input type="number" min="15" id="r3" name="radar_intervalo_min" value="${p.radar_intervalo_min}"></div>
        <div class="field"><label for="r4">Idade máxima da notícia (horas)</label><input type="number" min="6" id="r4" name="idade_maxima_horas" value="${p.idade_maxima_horas}"></div>
      </div>
      <h2>Assinatura e transparência</h2>
      <div class="form">
        <div class="field" style="grid-column:1/-1"><label for="s1">Assinatura no fim dos posts do LinkedIn</label><input type="text" id="s1" name="assinatura" value="${esc(p.assinatura)}"></div>
        <label class="switch"><input type="checkbox" name="rodape_ia" ${p.rodape_ia ? "checked" : ""}> Informar no rodapé que o conteúdo teve apoio de IA</label>
        <label class="switch"><input type="checkbox" name="notificacoes_windows" ${p.notificacoes_windows ? "checked" : ""}> Notificações do Windows</label>
      </div>
      <h2>IA local</h2>
      <div class="form">
        <div class="field"><label for="m1">Modelo do Ollama</label><select id="m1" name="ollama_modelo">${models.map((m) => `<option ${m === p.ollama_modelo ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></div>
        <div class="field"><label>Situação</label><div><span class="state ${ia.pronto ? "ok" : "warn"}">${ia.pronto ? "Pronta" : "Indisponível"}</span> <span class="muted" style="font-size:13px">${esc(ia.mensagem)}</span></div></div>
      </div>
      <div class="actions"><button class="btn primary" type="submit">Salvar configurações</button></div>
      <p class="faint" style="font-size:12px;margin:0">Dados guardados em <code>${esc(c.ambiente.pasta_dados)}</code>. O modo automático do LinkedIn liga e desliga na seção LinkedIn.</p>
    </form>`;
  $("#cfgForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target, body = {};
    $$("[name]", f).forEach((el) => {
      if (el.type === "checkbox") body[el.name] = el.checked;
      else if (el.name === "linkedin_horarios") body[el.name] = el.value.split(",").map((s) => s.trim()).filter(Boolean);
      else if (el.type === "number") body[el.name] = Number(el.value);
      else body[el.name] = el.value;
    });
    body.distribuicao = Object.fromEntries($$("[data-dist]", f).map((el) => [el.dataset.dist, Number(el.value)]));
    try { await api("/api/config", { method: "PUT", body }); toast("Configurações salvas."); } catch (err) { toast(err.message); }
  };
}

async function cfgFontes() {
  const d = await api("/api/fontes");
  const tier = { primaria: "Primária", publica: "Agência pública", imprensa: "Imprensa" };
  $("#cfgBox").innerHTML = `
    <div class="card" style="margin-bottom:14px"><h2>Fontes de notícias</h2>
      <p class="muted" style="font-size:13px;margin-top:0">Ligue, desligue, teste e ajuste a política de imagem de cada fonte. Só marque <b>reuso com crédito</b> quando a fonte permitir republicar as imagens dela no seu perfil.</p>
      <div class="table-wrap"><table><thead><tr><th>Fonte</th><th>Tipo</th><th>Feed</th><th>Imagens</th><th>Situação</th><th></th></tr></thead><tbody>
      ${d.itens.map((s) => `<tr>
        <td><label class="switch"><input type="checkbox" data-en="${s.id}" ${s.enabled ? "checked" : ""}> <span><b>${esc(s.name)}</b><br><a class="faint" href="${esc(s.homepage)}" target="_blank" rel="noopener" style="font-size:12px">${esc(s.homepage)}</a></span></label></td>
        <td>${tier[s.tier]}${s.region === "PA" ? " · Pará" : ""}</td>
        <td><input type="url" data-feed="${s.id}" value="${esc(s.feed_url || "")}" placeholder="sem feed" style="width:230px"></td>
        <td><select data-img="${s.id}"><option value="nao_liberada" ${s.image_policy === "nao_liberada" ? "selected" : ""}>Sem autorização</option><option value="liberada_com_credito" ${s.image_policy === "liberada_com_credito" ? "selected" : ""}>Reuso com crédito</option></select></td>
        <td style="font-size:12px">${s.last_status ? `<span class="state ${s.last_status === "ok" || s.last_status === "sem_novidades" ? "ok" : "warn"}">${esc(s.last_status)}</span>` : ""} ${esc(s.last_error || s.note || "")}<div class="faint">${s.last_checked ? ago(s.last_checked) : ""} · ${s.items_total} notícias</div></td>
        <td><button class="btn small" data-test="${s.id}">Testar</button></td></tr>`).join("")}
      </tbody></table></div></div>
    <form class="card" id="newSrc"><h2>Adicionar fonte</h2><div class="form">
      <div class="field"><label for="n1">Nome</label><input type="text" id="n1" name="name" required></div>
      <div class="field"><label for="n2">Endereço do site</label><input type="url" id="n2" name="homepage" required placeholder="https://"></div>
      <div class="field"><label for="n3">Feed RSS (opcional, o HORIZONTE tenta achar)</label><input type="url" id="n3" name="feed_url"></div>
      <div class="field"><label for="n4">Tipo</label><select id="n4" name="tier"><option value="imprensa">Imprensa</option><option value="primaria">Primária (órgão oficial)</option><option value="publica">Agência pública</option></select></div>
      <div class="field"><label for="n5">Área principal</label><select id="n5" name="category_hint"><option value="">Automática</option><option value="direito">Direito</option><option value="politica">Política</option><option value="sociedade">Sociedade</option></select></div>
      <div class="field"><label for="n6">Região</label><select id="n6" name="region"><option value="BR">Brasil</option><option value="PA">Pará</option></select></div>
    </div><div class="actions" style="margin-top:12px"><button class="btn primary" type="submit">Adicionar</button></div></form>`;
  $$("[data-en]").forEach((el) => (el.onchange = async () => { await api(`/api/fontes/${el.dataset.en}`, { method: "PUT", body: { enabled: el.checked ? 1 : 0 } }); toast("Fonte atualizada."); }));
  $$("[data-img]").forEach((el) => (el.onchange = async () => { await api(`/api/fontes/${el.dataset.img}`, { method: "PUT", body: { image_policy: el.value } }); toast("Política de imagem atualizada."); }));
  $$("[data-feed]").forEach((el) => (el.onchange = async () => { await api(`/api/fontes/${el.dataset.feed}`, { method: "PUT", body: { feed_url: el.value.trim() || null } }); toast("Feed atualizado."); }));
  $$("[data-test]").forEach((b) => (b.onclick = async () => { b.disabled = true; b.textContent = "Testando…"; const r = await api(`/api/fontes/${b.dataset.test}/testar`, { method: "POST" }); toast(r.mensagem, 5000); route(); }));
  $("#newSrc").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    body.group_name = body.tier === "imprensa" ? "jornalistica" : body.tier === "primaria" ? "juridica" : "politica";
    try { await api("/api/fontes", { method: "POST", body }); toast("Fonte adicionada."); route(); } catch (err) { toast(err.message); }
  };
}

async function cfgLogs() {
  const d = await api("/api/logs?limite=300");
  $("#cfgBox").innerHTML = `<div class="card"><h2>Registros do sistema</h2>${d.itens.map((l) => `<div class="log"><span class="faint">${fmt(l.ts)}</span><span class="lv-${l.level}">${esc(l.level)}</span><span class="muted">${esc(l.module)}</span><span class="m">${esc(l.message)}</span></div>`).join("") || '<div class="empty">Sem registros.</div>'}</div>`;
}

/* ---------------------------------------------------------------- início */
(async () => {
  try { await api("/api/estado"); $("#shell").hidden = false; route(); }
  catch (e) { if (e.message !== "login") { $("#shell").hidden = false; route(); } }
})();
setInterval(() => { if (current === "dashboard" && !document.hidden) route(); }, 60000);
