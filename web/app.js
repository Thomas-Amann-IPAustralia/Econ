// IP economics evidence chat: a static front end for the API on Render.
// Every string from the server is escaped before it reaches the page.

const CFG = Object.assign({ api: "", pdfBase: "pdfs/" }, window.ECON_CONFIG || {});
const params = new URLSearchParams(location.search);
if (params.get("api")) CFG.api = params.get("api");
const API = CFG.api.replace(/\/$/, "");
const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";
const PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";

const STARTERS = [
  "What statistical methods does the Office of the Chief Economist use to establish causality?",
  "How sure can we be that the IP system is actually beneficial for innovation?",
  "How do trade marks, design rights and copyright intersect?",
  "Looking across the documents, what opportunity spaces could IP Australia take advantage of that may not yet be explored?",
];

const $ = (s, el = document) => el.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
  return el;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pages = (p) => (p.length === 1 ? `p. ${p[0]}` : `pp. ${p[0]}–${p[p.length - 1]}`);

// One conversation per page; its id groups the conversation's traces (D-022).
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join(""));
const state = { docs: {}, turns: [], selected: null, health: null, session: newId() };

// --- the theme: the reader's choice if they made one (remembered in this browser), otherwise the system's --

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function currentTheme() {
  return document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light");
}
function showTheme() {
  const cur = currentTheme();
  document.querySelectorAll("[data-theme-choice]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === cur)));
}
function initTheme() {
  document.querySelectorAll("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => {
    document.documentElement.dataset.theme = b.dataset.themeChoice;
    try { localStorage.setItem("econ-theme", b.dataset.themeChoice); } catch (e) { /* not remembered; still applied */ }
    showTheme();
  }));
  darkQuery.addEventListener("change", showTheme);
  showTheme();
}

// --- server status: wake Render (and through it Cloud Run) as soon as the page opens ----------------

async function wake() {
  const el = $("#status"), txt = $("#status-text");
  if (!API) {
    el.className = "status down";
    txt.textContent = "No API configured";
    return;
  }
  const t0 = Date.now();
  el.className = "status waking";
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`${API}/api/health`, { cache: "no-store" });
      if (r.ok) {
        state.health = await r.json();
        const llm = state.health.llm;
        const emb = state.health.embedder;
        if (llm.mode === "answer") {
          el.className = "status ready";
          txt.textContent = `Ready · ${llm.answer_model}`;
        } else {
          el.className = "status evidence";
          txt.textContent = llm.budget_reached ? "Evidence only (daily budget reached)" : "Evidence only (no model key)";
        }
        el.title = `Search model: ${state.health.build.index.embedder} (${emb.configured ? (emb.warm ? "warm" : "waking") : "not configured"})`;
        $("#build").textContent = `Build ${String(state.health.build.commit).slice(0, 8)} · index ${state.health.build.index.strategy} / ${state.health.build.index.embedder} · ${state.health.build.index.chunks} passages · prompt ${state.health.build.prompt}`;
        return;
      }
    } catch (e) { /* still waking */ }
    const s = Math.round((Date.now() - t0) / 1000);
    txt.textContent = `Waking the server… ${s}s (free hosting sleeps when idle; about a minute)`;
    await new Promise((r) => setTimeout(r, 3000));
  }
  el.className = "status down";
  txt.textContent = "Server unavailable";
}

// --- the library ---------------------------------------------------------------------------------------

async function loadCatalogue() {
  let docs = null;
  try {
    const r = await fetch("data/catalogue.json");
    if (r.ok) docs = (await r.json()).documents;
  } catch (e) { /* fall back to the API */ }
  if (!docs && API) {
    try { docs = (await (await fetch(`${API}/api/catalogue`)).json()).documents; } catch (e) { docs = {}; }
  }
  state.docs = docs || {};
  const list = Object.values(state.docs).sort((a, b) => b.year - a.year || a.title.localeCompare(b.title));
  const lib = $("#library");
  lib.replaceChildren(...list.map((d) => h("div", { class: "doc" },
    h("div", { class: "doc-year" }, d.year),
    h("div", {},
      h("div", { class: "doc-title" }, d.title),
      h("div", { class: "doc-meta" }, `${d.series} · ${d.page_count} pages · ${d.chunks} passages · ${d.licence || "no licence statement in the document"}${d.ocr ? " · text from OCR" : ""}`),
      d.note ? h("div", { class: "doc-meta" }, d.note) : null),
    h("div", {}, h("button", { class: "linkish", onclick: () => openViewer(d.doc_id, 1, []) }, "View"),
      d.url ? h("a", { class: "linkish", href: d.url, target: "_blank", rel: "noopener" }, "Publisher page") : null),
  )));
  const pagesTotal = list.reduce((a, d) => a + d.page_count, 0);
  $("#lib-summary").textContent = `${list.length} documents, ${pagesTotal} pages, published by IP Australia under Creative Commons Attribution 4.0 unless noted.`;
  const years = [...new Set(list.map((d) => d.year))].sort();
  for (const sel of [$("#y0"), $("#y1")]) sel.replaceChildren(...years.map((y) => h("option", { value: y }, y)));
  $("#y0").value = years[0];
  $("#y1").value = years[years.length - 1];
}

// --- asking -----------------------------------------------------------------------------------------------

async function* sse(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
      if (data) yield JSON.parse(data);
    }
  }
}

async function ask(question, context) {
  $("#empty")?.remove();
  const years = [+$("#y0").value, +$("#y1").value].sort((a, b) => a - b);
  const allYears = Object.values(state.docs).map((d) => d.year);
  const filtered = allYears.length && (years[0] > Math.min(...allYears) || years[1] < Math.max(...allYears));
  const turn = { question, context, events: {}, checks: [], el: null, t0: performance.now(), shown: {},
    askedAt: new Date().toISOString(), years: filtered ? years : null };
  state.turns.push(turn);
  showChatBar();
  $("#thread").append(h("div", { class: "msg user" }, question,
    context ? h("span", { class: "ctxnote" }, `+ ${context.length.toLocaleString()} characters of your material`) : null,
    filtered ? h("span", { class: "ctxnote" }, `Limited to ${years[0]}–${years[1]}`) : null));
  const bot = h("div", { class: "msg bot", tabindex: "0", onclick: () => {
    select(turn);
    if (narrow()) $("#trail").scrollIntoView({ behavior: "smooth" });
  } },
    h("div", { class: "progress" }, h("span", { class: "spinner" }), h("span", {}, "Planning the search…")));
  turn.el = bot;
  $("#thread").append(bot);
  bot.scrollIntoView({ block: "end" });
  select(turn);

  const history = state.turns.slice(0, -1).flatMap((t) => [
    { role: "user", text: t.question },
    t.events.answer ? { role: "assistant", text: t.events.answer.answer.replace(/\[\d+\]/g, "") } : null,
  ]).filter(Boolean).slice(-6);

  $("#send").disabled = true;
  try {
    const resp = await fetch(`${API}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context, history, years: filtered ? years : null, session_id: state.session }),
    });
    if (!resp.ok) {
      const msg = (await resp.json().catch(() => ({}))).detail || `The server answered ${resp.status}.`;
      throw new Error(msg);
    }
    for await (const ev of sse(resp)) {
      if (ev.event === "draft") {  // the prose while it is written (D-024): shown, not yet checked
        if (turn.draft?.attempt !== ev.attempt) turn.draft = { attempt: ev.attempt, text: "" };
        if (ev.withheld) turn.draft.withheld = true;
        else turn.draft.text += ev.text;
        drawSoon(turn);
        continue;
      }
      ev._t = (performance.now() - turn.t0) / 1000;  // when it arrived, for the activity log
      if (ev.event === "check") turn.checks.push(ev);
      if (ev.event === "answer") turn.events.answers = [...(turn.events.answers || []), ev];
      turn.events[ev.event] = ev;
      renderBot(turn);
      if (state.selected === turn) renderTrail(turn);
    }
  } catch (e) {
    turn.events.error = { message: e.message || String(e), _t: (performance.now() - turn.t0) / 1000 };
    renderBot(turn);
    if (state.selected === turn) renderTrail(turn);
  } finally {
    $("#send").disabled = false;
  }
}

// Drafts arrive many times a second: draw at most once a frame, and leave the evidence trail alone.
function drawSoon(t) {
  if (t.drawing) return;
  t.drawing = true;
  requestAnimationFrame(() => { t.drawing = false; renderBot(t); });
}

// The draft being written, unless the answer it will become (or a later one) has arrived.
const liveDraft = (t) => (t.draft && !t.events.done && !(t.events.answer && t.events.answer.attempt >= t.draft.attempt) ? t.draft : null);

function progressText(t) {
  const e = t.events;
  if (e.error && !e.answer) return null;
  if (e.done) return null;
  if (liveDraft(t)) return "Writing the answer… the quotes are checked when it is finished.";
  if (e.answer) return "Checking the quotes…";
  if (e.retrieval) {
    if (e.meta?.mode !== "answer") return "Collecting passages…";
    const f = e.retrieval.filter;
    return f?.status === "ok"
      ? `Chose ${e.retrieval.evidence.length} of ${f.read} passages. Writing the answer…`
      : `Found ${e.retrieval.evidence.length} passages. Writing the answer…`;
  }
  if (e.search) return `Found ${e.search.read} passages. Choosing the most useful…`;
  if (e.plan) return `Searching: ${e.plan.queries.join(" · ")}`;
  return "Planning the search…";
}

// Emphasis is marked before escaping, so a run of prose cut at a claim marker can close what is open at its
// end and reopen it in the next run: every run's HTML is balanced.
const EMPH = { "\uE000": ["strong", true], "\uE001": ["strong", false], "\uE002": ["em", true], "\uE003": ["em", false] };
const emphasis = (s) => s.replace(/[\uE000-\uE003]/g, "").replace(/\*\*(.+?)\*\*/g, "\uE000$1\uE001").replace(/(^|[^*])\*([^*]+)\*/g, "$1\uE002$2\uE003");
function emphHtml(s, open) {
  if (!s) return "";
  let out = (open.strong ? "<strong>" : "") + (open.em ? "<em>" : "");
  out += esc(s).replace(/[\uE000-\uE003]/g, (c) => { const [tag, on] = EMPH[c]; open[tag] = on; return on ? `<${tag}>` : `</${tag}>`; });
  return out + (open.em ? "</em>" : "") + (open.strong ? "</strong>" : "");
}

// The answer's prose in runs (D-030). A run that ends in claim markers rests on those claims' sentences; the
// prose after a line's last marker, or on a line with none, is the assistant's own words. It is the rule that
// labels the claims on the server (cite._claim_text): a group of ids backs all the prose since the previous
// group or the start of the line. Runs without a word in them (a full stop after a marker) are neither.
const MARKER_RUN = /((?:\[\d{1,3}\][ \t]*)+)/;
function lineParts(line) {
  const bits = line.split(MARKER_RUN);
  const parts = [];
  for (let i = 0; i < bits.length; i += 2) {
    const text = bits[i], run = bits[i + 1];
    if (run) parts.push({ kind: "cited", text, claims: [...run.matchAll(/\[(\d{1,3})\]/g)].map((m) => +m[1]), run });
    else if (text) parts.push({ kind: /\w/.test(text) ? "own" : "plain", text });
  }
  return parts;
}

// The same runs for a whole answer, without markdown: what the JSON export records. Headings are drawn plain.
function answerParts(md) {
  return md.split("\n").flatMap((line) => {
    const heading = /^\s*#{1,4}\s+/.test(line);
    return lineParts(line.replace(/^\s*(?:[-*•]|\d+[.)]|#{1,4})\s+/, "").replace(/\*+/g, ""))
      .filter((p) => p.kind !== "plain")
      .map((p) => (p.kind === "cited" ? { kind: "cited", claims: p.claims, text: p.text.trim() } : { kind: heading ? "heading" : "own", text: p.text.trim() }));
  });
}

// Markdown-lite: escape first, then paragraphs, lists, bold, italics; [n] markers become buttons. With
// `parts`, each run of prose that rests on cited sentences is drawn in navy (D-031); the assistant's own words
// keep the ordinary colour, so the model's formatting is the only other mark on the text.
function renderMarkdown(md, { claims = [], draft = false, parts = false } = {}) {
  const failed = new Set(claims.filter((c) => !c.verified).map((c) => c.n));
  const marker = (n) => `<button class="cite${failed.has(n) ? " failed" : ""}" type="button" data-claim="${n}" title="Claim ${n}${failed.has(n) ? ": failed the check" : ""}. Select to read the sentences it cites">${n}</button>`;
  const inline = (s) => emphHtml(emphasis(s), {})
    // A draft's markers are not yet claims: [n] (answer-v4) or a sentence id [3.2] (answer-v5, D-026).
    .replace(draft ? /\[(\d{1,3}(?:\.\d{1,3})?)\]/g : /\[(\d{1,3})\]/g, (_, n) => draft
      ? `<span class="cite pending" title="${n.includes(".") ? `Passage ${n.split(".")[0]}, sentence ${n.split(".")[1]}` : `Claim ${n}`}: not yet checked">${n}</span>`
      : marker(+n));
  const said = (s) => {
    const open = {};
    return lineParts(emphasis(s)).map((p) => {
      if (p.kind !== "cited") return emphHtml(p.text, open);
      // Leading punctuation (the full stop after the previous marker) and trailing space stay outside the run.
      const lead = p.text.match(/^[\s.,;:!?)\]”’"']*/)[0];
      const rest = p.text.slice(lead.length);
      const tail = rest.match(/\s*$/)[0];
      const body = rest.slice(0, rest.length - tail.length);
      return emphHtml(lead, open)
        + (body ? `<span class="said cited" data-claims="${p.claims.join(" ")}" title="Rests on the sentences claim ${p.claims.join(", ")} cites">${emphHtml(body, open)}</span>` : "")
        + emphHtml(tail, open) + p.run.replace(/\[(\d{1,3})\]/g, (_, n) => marker(+n));
    }).join("");
  };
  const text = (s) => (parts && !draft ? said(s) : inline(s));
  const out = [];
  let list = null;
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    const m = line.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
    if (m) {
      const kind = /\d/.test(m[1]) ? "ol" : "ul";
      if (!list || list.kind !== kind) { if (list) out.push(`</${list.kind}>`); out.push(`<${kind}>`); list = { kind }; }
      out.push(`<li>${text(m[2])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list.kind}>`); list = null; }
    if (!line.trim()) continue;
    const hd = line.match(/^#{1,4}\s+(.*)$/);
    out.push(hd ? `<p><strong>${text(hd[1])}</strong></p>` : `<p>${text(line)}</p>`);
  }
  if (list) out.push(`</${list.kind}>`);
  return out.join("");
}

function renderBot(t) {
  const e = t.events;
  const el = t.el;
  el.replaceChildren();
  const prog = progressText(t);
  const meta = e.meta;
  const check = t.checks[t.checks.length - 1];
  const badges = h("div", { class: "badges" });
  if (e.answer) {
    const cov = { complete: ["ok", "Complete answer"], partial: ["warn", "Partial answer"], not_in_kb: ["info", "Not in the library"] }[e.answer.coverage];
    badges.append(h("span", { class: `badge ${cov[0]}` }, cov[1]));
    if (check) {
      const n = check.claims.length, bad = check.claims.filter((c) => !c.verified).length;
      // answer-v5 (D-026): code copies the cited sentences, so "verbatim" is no longer the model's doing.
      const bySentence = e.answer.citations_by === "sentence";
      const ok = bySentence
        ? h("span", { class: "badge ok", title: "Each claim's quotes are whole sentences, copied exactly by code from the passages the model was shown. The check does not judge whether a sentence supports its claim." },
          `All ${n} claims cite sentences copied exactly from their sources`)
        : h("span", { class: "badge ok" }, `All ${n} claims quote their sources verbatim`);
      badges.append(check.passed
        ? (n ? ok : h("span", { class: "badge ok" }, "Checked"))
        : h("span", { class: "badge bad", title: check.errors.join("\n") }, `${bad || "Some"} of ${n} claims failed the check`));
    }
  } else if (meta?.mode === "evidence_only" && e.retrieval) {
    badges.append(h("span", { class: "badge info" }, "Evidence only"));
  }
  const draft = liveDraft(t);
  if (draft) {
    badges.replaceChildren(h("span", { class: "badge info" }, draft.withheld ? "Draft hidden: it failed a text check" : "Draft · not yet checked"));
  }
  if (badges.childNodes.length) el.append(badges);
  if (draft) {
    if (!draft.withheld) {
      const body = h("div", { class: "draft" });
      body.innerHTML = renderMarkdown(draft.text, { draft: true });
      el.append(body);
    }
  } else if (e.answer) {
    // A new attempt has new claims: what was selected in the last one no longer applies.
    if (t.shownAttempt !== e.answer.attempt) Object.assign(t, { shownAttempt: e.answer.attempt, claimOn: null });
    const claims = claimsOf(t);
    if (claims.length) el.append(answerTabs(t, claims.length));
    el.append(t.view === "claims" && claims.length ? claimsPanel(t, claims) : answerPanel(t, claims));
  } else if (e.retrieval && meta?.mode === "evidence_only") {
    const docs = new Set(e.retrieval.evidence.map((x) => x.doc_id));
    el.append(h("p", {}, `No language model is configured, so here are the ${e.retrieval.evidence.length} most relevant passages, from ${docs.size} documents. They are in the evidence trail, best first.`));
  }
  if (e.error) el.append(h("p", { class: "badge bad" }, `Something went wrong: ${e.error.message}`));
  if (prog) el.append(h("div", { class: "progress" }, h("span", { class: "spinner" }), h("span", {}, prog)));
  if (e.done) {
    const cost = e.done.cost_usd ? ` · US$${e.done.cost_usd.toFixed(4)}` : "";
    el.append(h("div", { class: "gaps answer-foot" },
      e.answer ? h("button", { class: "linkish copy", type: "button", title: "Copy the answer and its sources", onclick: (ev) => { ev.stopPropagation(); copyAnswer(t, ev.currentTarget); } }, "Copy") : null,
      `${e.done.seconds}s${cost} · ${narrow() ? "tap to see the evidence trail" : "select to see the evidence trail"}`));
    // Suggested next questions (answer-v3 onwards, D-024): one select asks it, in this conversation.
    const next = e.answer?.follow_ups || [];
    if (next.length) {
      el.append(h("div", { class: "followups" }, h("span", { class: "muted" }, "You could ask next:"),
        ...next.map((q) => h("button", { class: "starter followup", type: "button", onclick: (ev) => {
          ev.stopPropagation();
          if (!$("#send").disabled) ask(q, "");
        } }, q))));
    }
  }
  // A claim marker selects its claim and goes to its sentences in the evidence trail.
  el.querySelectorAll(".answer-panel button.cite").forEach((b, i) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    pickClaim(t, +b.dataset.claim, { focus: () => t.el.querySelectorAll(".answer-panel button.cite")[i], scroll: true });
  }));
  // The selected claim, lit in the prose and the claim list.
  if (t.claimOn != null) {
    el.querySelectorAll(`.cite[data-claim="${t.claimOn}"], .claim-card[data-claim="${t.claimOn}"]`).forEach((x) => x.classList.add("on"));
    el.querySelectorAll(".said.cited[data-claims]").forEach((x) => x.classList.toggle("on", x.dataset.claims.split(" ").includes(String(t.claimOn))));
  }
}

// --- the answer's two views: the answer itself, and the claims it makes beside the sentences they cite ----

// The claims of the answer on screen: the last check's, if it checked the answer shown.
function claimsOf(t) {
  const c = t.checks[t.checks.length - 1];
  return c && (!t.events.answer || c.attempt === t.events.answer.attempt) ? c.claims : [];
}
// How many passages a claim's sentences come from: more than one is shown in green (D-031).
const passagesOf = (c) => new Set(c.citations.map((q) => q.evidence)).size;
const evidenceByN = (t) => Object.fromEntries((t.events.retrieval?.evidence || []).map((x) => [x.n, x]));
const narrow = () => window.matchMedia("(max-width: 860px)").matches;

function answerTabs(t, n) {
  const views = [["answer", "Answer"], ["claims", `Claims made by the chatbot (${n})`]];
  const cur = t.view === "claims" ? "claims" : "answer";
  const go = (key) => {
    if (state.selected !== t) select(t);
    t.view = key;
    renderBot(t);
    t.el.querySelector(`.atab[data-view="${key}"]`)?.focus();
    if (t.claimOn != null) focusClaim(t, t.claimOn);
  };
  return h("div", { class: "atabs", role: "tablist", "aria-label": "This answer", onkeydown: (ev) => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    ev.preventDefault();
    go(cur === "answer" ? "claims" : "answer");
  } }, views.map(([key, label]) => h("button", {
    class: `atab${key === cur ? " on" : ""}`, type: "button", role: "tab", "data-view": key,
    "aria-selected": String(key === cur), tabindex: key === cur ? "0" : "-1",
    onclick: (ev) => { ev.stopPropagation(); if (key !== cur) go(key); },
  }, label)));
}

function answerPanel(t, claims) {
  const a = t.events.answer;
  const panel = h("div", { class: "answer-panel", role: claims.length ? "tabpanel" : null });
  const body = h("div", { class: "prose-answer" });
  body.innerHTML = renderMarkdown(a.answer, { claims, parts: true });
  panel.append(body);
  if (a.gaps?.length) panel.append(h("div", { class: "gaps" }, "Not covered: ", a.gaps.join("; ")));
  return panel;
}

// One cited sentence (or, under answer-v4, one quote), as the publication has it, with where it is from.
function quoteBlock(t, q, src, n) {
  return h("figure", { class: `verbatim${q.found ? "" : " missing"}` },
    h("blockquote", {}, q.quote),
    h("figcaption", {},
      h("span", {}, src ? sourceLine(src) : `Passage ${q.evidence}`, q.found ? "" : " · not found in the passage"),
      h("button", { class: "linkish", type: "button", title: "Show this passage in the evidence trail", onclick: (ev) => {
        ev.stopPropagation();
        pickClaim(t, n, { passage: q.evidence, scroll: true });
      } }, `Passage ${q.evidence}`),
      src ? h("button", { class: "linkish", type: "button", onclick: (ev) => { ev.stopPropagation(); openViewer(src.doc_id, src.pages[0], src.boxes); } }, `Show on ${pages(src.pages)}`) : null));
}

function claimsPanel(t, claims) {
  const ev = evidenceByN(t);
  const at = claims.findIndex((c) => c.n === t.claimOn);
  const step = (d) => (e2) => {
    e2.stopPropagation();
    const i = Math.max(0, Math.min(claims.length - 1, at + d));
    pickClaim(t, claims[i].n, { focus: () => t.el.querySelector(`.claim-nav [data-step="${d}"]:not(:disabled)`) || t.el.querySelector(".claim-nav [data-step]:not(:disabled)"), reveal: true });
  };
  const panel = h("div", { class: "claims-panel", role: "tabpanel", onkeydown: (e2) => {
    const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e2.key];
    if (!d || !e2.target.closest(".claim-card, .claim-nav")) return;
    e2.preventDefault();
    const card = e2.target.closest(".claim-card");
    const from = card ? claims.findIndex((c) => c.n === +card.dataset.claim) : at;
    const i = Math.max(0, Math.min(claims.length - 1, from < 0 ? 0 : from + d));
    pickClaim(t, claims[i].n, { focus: () => t.el.querySelector(`.claim-card[data-claim="${claims[i].n}"]`), reveal: true });
  } });
  panel.append(h("div", { class: "claim-nav" },
    h("span", { class: "claim-pos", "aria-live": "polite" }, at >= 0 ? `Claim ${at + 1} of ${claims.length}` : `${claims.length} claims`),
    h("button", { class: "linkish", type: "button", "data-step": "-1", disabled: at <= 0, onclick: step(-1) }, "‹ Previous"),
    h("button", { class: "linkish", type: "button", "data-step": "1", disabled: at === claims.length - 1, onclick: step(1) }, at < 0 ? "First claim ›" : "Next ›")));
  panel.append(h("p", { class: "claims-intro" }, "Each claim is in the assistant's words, above the sentences it cites, copied word for word by code, not by the AI. Green marks a claim drawn from more than one passage. Select a claim, or step through them, to see its passages in the evidence trail."));
  panel.append(h("ol", { class: "claim-cards" }, claims.map((c) => h("li", {
    class: `claim-card${c.verified ? "" : " failed"}${passagesOf(c) > 1 ? " multi" : ""}`, "data-claim": c.n, tabindex: "0",
    "aria-label": `Claim ${c.n}${c.verified ? "" : ", failed the check"}`,
    onclick: (e2) => { e2.stopPropagation(); pickClaim(t, c.n, { focus: () => t.el.querySelector(`.claim-card[data-claim="${c.n}"]`) }); },
    onkeydown: (e2) => {
      if (e2.target !== e2.currentTarget || (e2.key !== "Enter" && e2.key !== " ")) return;
      e2.preventDefault();
      e2.currentTarget.click();
    },
  },
  h("div", { class: "cc-head" },
    h("span", { class: `cite${c.verified ? "" : " failed"}`, "aria-hidden": "true" }, c.n),
    c.verified ? h("span", { class: "badge ok" }, "Found word for word") : h("span", { class: "badge bad" }, "Failed the check")),
  h("div", { class: "cc-label" }, "In the assistant's words"),
  h("p", { class: "cc-text" }, c.text),
  h("div", { class: "cc-label" }, passagesOf(c) > 1 ? `What the sources say, word for word: ${passagesOf(c)} passages` : "What the source says, word for word"),
  c.citations.map((q) => quoteBlock(t, q, ev[q.evidence], c.n)),
  c.errors.length ? h("div", { class: "why-failed" }, c.errors.join("; ")) : null))));
  return panel;
}

// Select a claim: lit in the answer, its passages focused in the trail. From the chat the trail scrolls to the
// passage (on a narrow screen only from a number or a passage button, as the trail is then below the chat);
// from the trail, the chat scrolls to the claim.
function pickClaim(t, n, { focus = null, passage = null, scroll = false, reveal = false, fromTrail = false } = {}) {
  if (state.selected !== t) select(t);
  t.claimOn = n;
  renderBot(t);
  focus?.()?.focus({ preventScroll: true });
  const wide = !narrow();
  focusClaim(t, n, { scroll: scroll || (wide && !fromTrail), passage });
  if (fromTrail || reveal) {
    const target = t.el.querySelector(t.view === "claims" ? `.claim-card[data-claim="${n}"]` : `.answer-panel .cite[data-claim="${n}"]`);
    target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// --- copying an answer out: the prose with its markers, then every source with its quote and page ------

function answerSources(t) {
  const ev = evidenceByN(t);
  return claimsOf(t).map((c) => ({
    n: c.n,
    cites: c.citations.map((q) => ({ quote: q.quote, src: ev[q.evidence] })),
  }));
}

const sourceLine = (s) => s ? `${s.title} (${s.year})${s.section?.length ? `, ${s.section[s.section.length - 1]}` : ""}, ${pages(s.pages)}` : "";

function copyAnswer(t, btn) {
  const a = t.events.answer;
  const sources = answerSources(t);
  const plain = [
    `Q: ${t.question}`, "", a.answer.trim(), "",
    a.gaps?.length ? `Not covered: ${a.gaps.join("; ")}\n` : null,
    sources.length ? "Sources" : null,
    ...sources.map((s) => `[${s.n}] ${s.cites.map((c) => `"${c.quote}" (${sourceLine(c.src)})`).join("; ")}`),
    "", "From IP Australia's Office of the Chief Economist publications; every quote was checked against the source text.",
  ].filter((x) => x !== null).join("\n");
  // The same, formatted, for pasting into a document: the answer as shown, with markers as superscripts.
  const box = document.createElement("div");
  box.innerHTML = renderMarkdown(a.answer);
  box.querySelectorAll(".cite").forEach((b) => b.replaceWith(Object.assign(document.createElement("sup"), { textContent: `[${b.dataset.claim}]` })));
  const html = `<p><strong>${esc(t.question)}</strong></p>${box.innerHTML}`
    + (a.gaps?.length ? `<p><em>Not covered: ${esc(a.gaps.join("; "))}</em></p>` : "")
    + (sources.length ? `<p><strong>Sources</strong></p><ol>${sources.map((s) => `<li value="${s.n}">${s.cites.map((c) => `“${esc(c.quote)}” (${esc(sourceLine(c.src))})`).join("; ")}</li>`).join("")}</ol>` : "")
    + "<p><em>From IP Australia's Office of the Chief Economist publications; every quote was checked against the source text.</em></p>";
  copyOut(btn, plain, html);
}

// To the clipboard: formatted where the browser allows it, plain text otherwise, a hidden textarea last.
function copyOut(btn, plain, html = null) {
  const label = btn.textContent;
  const done = (ok) => {
    btn.textContent = ok ? "Copied" : "Couldn't copy";
    setTimeout(() => { btn.textContent = label; }, 1600);
  };
  const fallback = () => {
    const ta = Object.assign(document.createElement("textarea"), { value: plain });
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    done(ok);
  };
  if (html && navigator.clipboard && window.ClipboardItem) {
    navigator.clipboard.write([new ClipboardItem({
      "text/plain": new Blob([plain], { type: "text/plain" }),
      "text/html": new Blob([html], { type: "text/html" }),
    })]).then(() => done(true), () => navigator.clipboard.writeText(plain).then(() => done(true), fallback));
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(plain).then(() => done(true), fallback);
  } else {
    fallback();
  }
}

// --- the conversation as JSON (D-030): everything on screen but the passages' text --------------------------

const pageUrl = (doc, page) => new URL(`${CFG.pdfBase}${encodeURIComponent(doc)}.pdf#page=${page}`, location.href).href;
const sourceOf = (x) => ({ doc_id: x.doc_id, title: x.title, year: x.year, section: x.section, pages: x.pages, page_url: pageUrl(x.doc_id, x.pages[0]) });

function exportTurn(t, i) {
  const e = t.events, r = e.retrieval, a = e.answer;
  const ev = evidenceByN(t);
  const claims = claimsOf(t);
  const check = t.checks[t.checks.length - 1];
  const citedBy = {};
  for (const c of claims) for (const x of c.citations) (citedBy[x.evidence] ||= new Set()).add(c.n);
  const claimOut = (c) => ({
    n: c.n, text: c.text, verified: c.verified, errors: c.errors,
    citations: c.citations.map((q) => ({
      passage: q.evidence, chunk_id: q.chunk_id, quote: q.quote, found: q.found, start: q.start, end: q.end,
      source: ev[q.evidence] ? sourceOf(ev[q.evidence]) : null,
    })),
  });
  const found = e.search || r;
  return {
    n: i + 1,
    asked_at: t.askedAt,
    question: t.question,
    pasted_context: t.context || null,
    years: t.years,
    status: e.error ? "error" : e.done ? (e.done.outcome || e.done.mode) : "in progress",
    request_id: e.meta?.request_id ?? null,
    mode: e.meta?.mode ?? null,
    models: { plan: e.meta?.plan_model ?? null, filter: r?.filter?.model ?? null, answer: e.meta?.answer_model ?? null },
    prompt: e.meta?.prompt ?? null,
    plan: e.plan ? { standalone_question: e.plan.standalone_question, queries: e.plan.queries, error: e.plan.error ?? null } : null,
    search: found ? { candidates: found.candidates, dense: found.dense, read: r ? (r.pool?.length ?? r.evidence.length) : e.search.read } : null,
    filter: r?.filter ?? null,
    answer: a ? {
      attempt: a.attempt, coverage: a.coverage, citations_by: a.citations_by ?? null,
      text: a.answer, parts: answerParts(a.answer), gaps: a.gaps, follow_ups: a.follow_ups || [],
    } : null,
    check: check && a && check.attempt === a.attempt ? { passed: check.passed, errors: check.errors } : null,
    claims: claims.map(claimOut),
    earlier_attempts: (e.answers || []).filter((x) => x.attempt !== a?.attempt).map((x) => {
      const c = t.checks.find((k) => k.attempt === x.attempt);
      return { attempt: x.attempt, coverage: x.coverage, text: x.answer, gaps: x.gaps, check: c ? { passed: c.passed, errors: c.errors } : null, claims: (c?.claims || []).map(claimOut) };
    }),
    evidence: (r?.evidence || []).map((x) => ({
      n: x.n, chunk_id: x.chunk_id, ...sourceOf(x), series: x.series,
      search_rank: x.search_rank ?? x.merged_rank, filter_rating: x.filter_grade ?? null, cited_by: [...(citedBy[x.n] || [])],
      matched_terms: x.matched_terms, per_query: Object.entries(x.per_query).map(([qi, s]) => ({ query: r.queries[+qi], ...s })),
      ocr: Boolean(x.ocr), note: x.note || null,
    })),
    passages_read: (r?.pool || []).map((x) => ({
      search_rank: x.search_rank, filter_rating: x.filter_grade ?? null, selected: x.selected, n: x.n ?? null, chunk_id: x.chunk_id, ...sourceOf(x),
    })),
    search_traces: (r?.traces || []).map((tr) => ({ query: tr.query, lanes: tr.lanes, hits: tr.hits.map(({ row, ...hit }) => hit) })),
    activity: activityItems(t).map(([at, level, text]) => ({ at_seconds: at == null ? null : Math.round(at * 100) / 100, level: level || "info", text })),
    done: e.done ? { outcome: e.done.outcome ?? null, attempts: e.done.attempts ?? null, seconds: e.done.seconds, cost_usd: e.done.cost_usd, timings: e.done.timings, usage: e.done.usage } : null,
    error: e.error?.message ?? null,
  };
}

function exportChat() {
  return {
    format: "econ-chat-export/1",
    exported_at: new Date().toISOString(),
    page: location.origin + location.pathname,
    session_id: state.session,
    service: state.health ? { build: state.health.build, llm: state.health.llm } : null,
    notes: [
      "Everything the page showed for each question except the passages' full text: each passage is named by its chunk_id and links to its page (page_url).",
      "answer.text is the assistant's prose, where [k] marks claim k. answer.parts splits it into runs that rest on claims (kind cited), runs in the assistant's own words with no citation (kind own), and headings.",
      "Each claim's quotes are the sentences it cites, copied word for word from the passage by code; start and end are character offsets in the passage's text. verified means every quote was found there; it does not judge whether a quote supports its claim.",
      "filter_rating: 3 essential, 2 useful, 1 on topic but not usable, 0 not about the question. Only the evidence (the passages_read with selected true, numbered n) was given to the answer model.",
    ],
    turns: state.turns.map(exportTurn),
  };
}

function chatJson() { return JSON.stringify(exportChat(), null, 2); }

function saveChat() {
  const url = URL.createObjectURL(new Blob([chatJson()], { type: "application/json" }));
  const a = h("a", { href: url, download: `ip-economics-chat-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.json` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showChatBar() {
  const n = state.turns.length;
  $("#chat-bar").hidden = !n;
  $("#chat-count").textContent = `${n} ${n === 1 ? "question" : "questions"} in this conversation`;
}

// --- the evidence trail ---------------------------------------------------------------------------------

function select(t) {
  if (state.selected === t) return;
  state.selected = t;
  document.querySelectorAll(".msg.bot").forEach((m) => m.classList.toggle("selected", m === t.el));
  renderTrail(t);
}

function quoteRanges(t) {
  // evidence n -> [{start, end, claims}] from the last check; a sentence cited by several claims is one range
  const by = {};
  for (const c of claimsOf(t)) {
    for (const cit of c.citations) {
      if (!cit.found || cit.start == null) continue;
      const list = (by[cit.evidence] ||= []);
      const same = list.find((r) => r.start === cit.start && r.end === cit.end);
      if (same) same.claims.push(c.n);
      else list.push({ start: cit.start, end: cit.end, claims: [c.n] });
    }
  }
  return by;
}

function highlight(text, quotes, terms) {
  const ranges = (quotes || []).map((q) => ({ ...q, cls: "q" }));
  if (terms?.length) {
    const re = new RegExp(`\\b(${terms.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\w*`, "gi");
    for (const m of text.matchAll(re)) {
      const s = m.index, e = s + m[0].length;
      if (!ranges.some((r) => r.cls === "q" && s < r.end && e > r.start)) ranges.push({ start: s, end: e, cls: "t" });
    }
  }
  ranges.sort((a, b) => a.start - b.start);
  let out = "", pos = 0;
  for (const r of ranges) {
    if (r.start < pos) continue;
    out += esc(text.slice(pos, r.start));
    const by = r.claims ? ` data-claims="${r.claims.join(" ")}" title="Cited by claim ${r.claims.join(", ")}: select to show it in the answer"` : "";
    out += `<mark class="${r.cls}"${by}>${esc(text.slice(r.start, r.end))}</mark>`;
    pos = r.end;
  }
  return out + esc(text.slice(pos));
}

function renderTrail(t) {
  const e = t.events;
  const pane = $("#trail");
  pane.replaceChildren(h("h2", {}, "Evidence trail"));
  if (!e.meta && !e.error) { pane.append(h("p", { class: "muted" }, "Waiting for the server…")); return; }
  const r = e.retrieval;
  const f = r?.filter;
  const filtered = f && !f.status.startsWith("off");
  pane.append(processView(t), activityLog(t));
  const strip = passageStrip(t);
  if (strip) pane.append(strip);

  // The claims are listed with the answer (its "Claims made by the chatbot" view, D-030); here each passage
  // says which claims cite it.
  if (!e.retrieval) return;
  const ev = e.retrieval.evidence;
  const quotes = quoteRanges(t);
  const citedBy = {};
  for (const c of claimsOf(t)) for (const x of c.citations) (citedBy[x.evidence] ||= new Set()).add(c.n);

  // Source map: where the evidence came from, by year.
  pane.append(h("h3", {}, "Where the evidence came from"));
  const byYear = {};
  for (const x of ev) (byYear[x.year] ||= {})[x.doc_id] = [...((byYear[x.year] || {})[x.doc_id] || []), x];
  const map = h("div", { class: "map" });
  for (const y of Object.keys(byYear).sort().reverse()) {
    map.append(h("div", { class: "map-row" }, h("span", { class: "map-year" }, y), h("div", { class: "map-docs" },
      Object.entries(byYear[y]).map(([doc, xs]) => h("button", { class: "map-doc", title: state.docs[doc]?.title || doc, onclick: (ev) => filterDoc(doc, ev.currentTarget) },
        (state.docs[doc]?.series || "").replace("IP Australia Economic Research Paper", "ERP").replace("Australian IP Report", "IP Report").replace("Office of the Chief Economist", "OCE"),
        xs.map((x) => h("span", { class: `pip${citedBy[x.n] ? " cited" : ""}`, title: `Passage ${x.n}${citedBy[x.n] ? ", cited" : ""}` })))))));
  }
  pane.append(map);

  pane.append(h("div", { class: "ev-head" }, h("h3", {}, filtered ? `Passages the answer model read (${ev.length})` : `Passages (${ev.length})`), h("span", { class: "filter-note muted", id: "filter-note" }, "Filled pips and a blue edge mark cited passages.")));
  const list = h("div", { id: "evlist" });
  for (const x of ev) {
    const cited = citedBy[x.n];
    const textEl = h("div", { class: "ev-text" });
    textEl.innerHTML = highlight(x.text, quotes[x.n], x.matched_terms);
    const why = h("details", { class: "why" }, h("summary", {}, "Why it ranked"), h("table", {},
      h("tr", {}, h("th", {}, "Search"), h("th", {}, "Rank"), h("th", {}, "Meaning"), h("th", {}, "Keywords")),
      Object.entries(x.per_query).map(([qi, s]) => h("tr", {},
        h("td", {}, e.retrieval.queries[+qi]), h("td", {}, s.rank),
        h("td", {}, s.dense != null ? `${s.dense.toFixed(3)} (#${s.dense_rank})` : "–"),
        h("td", {}, s.bm25 != null ? `${s.bm25.toFixed(2)} (#${s.bm25_rank})` : "–")))),
      x.matched_terms.length ? h("p", { class: "muted" }, `Keywords matched: ${x.matched_terms.join(", ")}`) : null);
    list.append(h("article", { class: `ev${cited ? " cited" : ""}`, id: `ev-${x.n}`, "data-doc": x.doc_id },
      h("div", { class: "ev-top" }, h("div", {}, h("span", { class: "ev-n" }, x.n), h("span", { class: "ev-title" }, x.title)),
        cited ? h("span", { class: "cited-by" }, "cited by", [...cited].map((n) => h("button", {
          class: "cite", type: "button", "data-claim": n, title: `Claim ${n}: show it in the answer`,
          onclick: () => pickClaim(t, n, { fromTrail: true, passage: x.n }),
        }, n))) : null),
      h("div", { class: "ev-meta" }, `${x.year} · ${x.section.length ? x.section.join(" › ") + " · " : ""}${pages(x.pages)} · search rank ${x.search_rank ?? x.merged_rank}${x.filter_grade != null ? ` · rated ${x.filter_grade} (${RATING[x.filter_grade]})` : ""}`),
      x.note ? h("div", { class: "ev-note" }, x.note) : null,
      x.ocr ? h("div", { class: "ev-note" }, "Text read from a scanned page by OCR: check the wording against the page.") : null,
      textEl,
      h("div", { class: "ev-actions" },
        h("button", { onclick: () => textEl.classList.toggle("open") }, "Expand"),
        h("button", { onclick: () => openViewer(x.doc_id, x.pages[0], x.boxes) }, `Show on ${pages(x.pages)}`),
        h("button", { onclick: (ev2) => readAround(x.chunk_id, textEl, ev2.target) }, "Read around")),
      why));
  }
  pane.append(list);
  if (filtered) pane.append(poolTable(t, r, citedBy));

  const trace = h("details", { class: "trace" }, h("summary", {}, "Full search trace"));
  for (const tr of e.retrieval.traces) {
    const maxD = Math.max(...tr.hits.map((x) => x.dense || 0), 1e-9), maxB = Math.max(...tr.hits.map((x) => x.bm25 || 0), 1e-9);
    trace.append(h("p", {}, h("strong", {}, `“${tr.query}”`), ` · lanes: ${tr.lanes.join(" + ")}`));
    trace.append(h("table", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Passage"), h("th", {}, "Meaning"), h("th", {}, "Keywords"), h("th", {}, "Combined")),
      tr.hits.map((x) => h("tr", {}, h("td", {}, x.rank), h("td", {}, x.chunk_id),
        h("td", {}, x.dense != null ? h("span", { class: "bar", style: `width:${Math.round(60 * x.dense / maxD)}px`, title: x.dense.toFixed(3) }) : "–"),
        h("td", {}, x.bm25 != null ? h("span", { class: "bar kw", style: `width:${Math.round(60 * x.bm25 / maxB)}px`, title: x.bm25.toFixed(2) }) : "–"),
        h("td", {}, x.score.toFixed(3))))));
  }
  pane.append(trace);
  if (t.claimOn != null) focusClaim(t, t.claimOn);  // a claim selected before the trail was redrawn
}

// --- the process view (after wind-tunnel's pipeline view): the steps as nodes, lit as the events arrive ---

const STEPS = [
  ["plan", "Plan"],
  ["search", "Search"],
  ["filter", "Filter"],
  ["answer", "Answer"],
  ["check", "Check"],
];
const WORD = { pending: "waiting", active: "working", done: "done", warn: "done, with a note", failed: "failed", skipped: "skipped" };

function nodeStates(t) {
  const e = t.events, r = e.retrieval, f = r?.filter;
  const evidenceOnly = e.meta && e.meta.mode !== "answer";
  const answers = e.answers || [], checks = t.checks;
  const last = checks[checks.length - 1];
  const s = {}, sub = {};
  // plan
  if (evidenceOnly) { s.plan = "skipped"; sub.plan = "no model: the question is searched as asked"; }
  else if (e.plan) { s.plan = e.plan.error ? "warn" : "done"; sub.plan = e.plan.error ? "searched as asked" : `${e.plan.queries.length} searches`; }
  else if (e.meta) { s.plan = "active"; sub.plan = "rewriting and splitting the question"; }
  else { s.plan = "pending"; sub.plan = "waking the server"; }
  // search
  const dense = (e.search || r)?.dense;
  if (e.search || r) { s.search = dense === "ok" ? "done" : "warn"; sub.search = `${(e.search || r).candidates} found${dense === "ok" ? "" : ", keywords only"}`; }
  else if (["done", "warn", "skipped"].includes(s.plan) && e.meta) { s.search = "active"; sub.search = "by meaning and by keywords"; }
  else { s.search = "pending"; sub.search = "by meaning and by keywords"; }
  // filter
  if (evidenceOnly || (r && !(f && !f.status.startsWith("off")))) { s.filter = "skipped"; sub.filter = evidenceOnly ? "no model" : "off"; }
  else if (r) { s.filter = f.status === "ok" ? "done" : "warn"; sub.filter = f.status === "ok" ? `kept ${r.evidence.length} of ${f.read}` : `failed: search's top ${r.evidence.length}`; }
  else if (e.search) { s.filter = "active"; sub.filter = `rating ${e.search.read} passages`; }
  else { s.filter = "pending"; sub.filter = "chooses 20 passages"; }
  // answer and check
  if (evidenceOnly) {
    s.answer = s.check = "skipped";
    sub.answer = "no model";
    sub.check = "nothing to check";
  } else {
    const retrying = checks.length && checks.length === answers.length && !last.passed && !e.done;
    if (retrying) { s.answer = "active"; sub.answer = "second attempt, after the check"; }
    else if (answers.length) { s.answer = "done"; const a = answers[answers.length - 1]; sub.answer = `${a.claims.length} claims${a.attempt > 1 ? ", 2nd attempt" : ""}`; }
    else if (r) { s.answer = "active"; sub.answer = `reading ${r.evidence.length} passages`; }
    else { s.answer = "pending"; sub.answer = e.meta?.answer_model || "the answer model"; }
    if (last && checks.length === answers.length) {
      const bad = last.claims.filter((c) => !c.verified).length;
      s.check = last.passed ? "done" : (e.done ? "failed" : "warn");
      sub.check = last.passed ? "every quote found" : `${bad || "some"} claim${bad === 1 ? "" : "s"} failed`;
    } else if (answers.length > checks.length) { s.check = "active"; sub.check = "matching quotes to passages"; }
    else { s.check = "pending"; sub.check = "quotes, word for word"; }
    if (e.done?.outcome === "no_answer") { s.answer = "failed"; sub.answer = "no answer"; }
  }
  if (e.error) {
    const k = STEPS.map(([key]) => key).find((key) => s[key] === "active") || "answer";
    s[k] = "failed";
    sub[k] = "stopped here";
    for (const [key] of STEPS) if (s[key] === "active") s[key] = "pending";
  }
  return { s, sub };
}

function processView(t) {
  const { s, sub } = nodeStates(t);
  const flow = h("ol", { class: "flow", "aria-label": "How this answer is made" });
  STEPS.forEach(([key, name], i) => {
    if (i) {
      const nxt = s[key];
      flow.append(h("li", { class: `edge ${nxt === "active" ? "live" : ["done", "warn"].includes(nxt) ? "done" : ""}`, "aria-hidden": "true" }));
    }
    const prev = t.shown[key];
    const settled = ["done", "warn"].includes(s[key]) && prev && !["done", "warn"].includes(prev);
    const mark = { done: "✓", warn: "!", failed: "✕", skipped: "–", active: i + 1, pending: i + 1 }[s[key]];
    flow.append(h("li", { class: `node ${s[key]}${settled ? " settle" : ""}${prev === undefined ? " enter" : ""}` },
      h("span", { class: "mark", "aria-hidden": "true" }, mark),
      h("span", { class: "name" }, name),
      h("span", { class: "word" }, WORD[s[key]]),
      h("span", { class: "sub" }, sub[key], s[key] === "active" ? h("span", { class: "elapsed" }) : null)));
    t.shown[key] = s[key];
  });
  return flow;
}

// What happened, when: [seconds, level, text], for the activity log and the JSON export.
function activityItems(t) {
  const e = t.events, r = e.retrieval, f = r?.filter;
  const items = [[0, "", "Question sent"]];
  if (e.meta) items.push([e.meta._t, "", e.meta.mode === "answer" ? `Server ready: ${e.meta.answer_model} will answer` : "Evidence only: no language model is configured"]);
  if (e.plan) items.push([e.plan._t, e.plan.error ? "warn" : "", e.plan.error ? `Planning failed; searching the question as asked` : `Planned ${e.plan.queries.length} searches: ${e.plan.queries.map((q) => `“${q}”`).join(", ")}`]);
  const found = e.search || r;
  if (found) items.push([found._t, found.dense === "ok" ? "" : "warn",
    `Found ${found.candidates} candidate passages ${found.dense === "ok" ? "by meaning and keywords" : `by keywords only (meaning search ${found.dense.split(";")[0]})`}${e.search ? `; the filter reads the first ${e.search.read}` : ""}`]);
  if (r && f && !f.status.startsWith("off")) {
    const counts = [3, 2, 1, 0].map((g) => `${r.pool.filter((x) => x.filter_grade === g).length} ${RATING[g]}`).join(", ");
    items.push([r._t, f.status === "ok" ? "" : "warn", f.status === "ok"
      ? `${f.model} rated ${f.read} passages in ${f.seconds}s (${counts}) and kept the ${r.evidence.length} rated highest`
      : `The filter failed (${f.status}); the search's top ${r.evidence.length} go forward`]);
  } else if (r) {
    items.push([r._t, "", `Kept the best ${r.evidence.length} passages from ${new Set(r.evidence.map((x) => x.doc_id)).size} documents`]);
  }
  for (const a of e.answers || []) {
    items.push([a._t, "", `${a.attempt > 1 ? "Second answer" : "Answer"} written: ${a.claims.length} claims, ${a.claims.reduce((n, c) => n + c.citations.length, 0)} quotes`]);
    const c = t.checks.find((x) => x.attempt === a.attempt);
    if (c) items.push([c._t, c.passed ? "" : "bad", c.passed ? "Check: every quote was found word for word in the passage it cites" : `Check failed: ${c.errors.slice(0, 2).join("; ")}`]);
  }
  if (e.done) items.push([e.done._t, "", `Done in ${e.done.seconds}s${e.done.cost_usd ? ` · US$${e.done.cost_usd.toFixed(4)}` : ""}`]);
  if (e.error) items.push([e.error._t ?? null, "bad", `Stopped: ${e.error.message}`]);
  return items;
}

function activityLog(t) {
  const items = activityItems(t);
  const now = progressText(t);
  const log = h("ol", { class: "log", "aria-live": "polite", "aria-label": "Activity" });
  const seen = t.logShown || 0;
  items.forEach(([at, cls, text], i) => log.append(h("li", { class: `${cls}${i >= seen ? " enter" : ""}` },
    h("time", {}, at == null ? "" : `${at.toFixed(1)}s`), h("span", {}, text))));
  if (now) log.append(h("li", { class: "now" }, h("time", {}), h("span", {}, now.replace(/…$/, ""))));
  t.logShown = items.length;
  return log;
}

// Every passage the filter read, as one tile each in search order: coloured by rating, the kept ones outlined.
function passageStrip(t) {
  const e = t.events, r = e.retrieval, f = r?.filter;
  const filtering = f ? !f.status.startsWith("off") : Boolean(e.search);
  if (!filtering) return null;
  const wrap = h("div", { class: "strip-wrap" });
  const strip = h("div", { class: "strip", role: "list", "aria-label": "Passages the filter read, in search order" });
  if (!r) {
    for (let i = 0; i < e.search.read; i++) strip.append(h("span", { class: "tile waiting", style: `--i:${i}`, role: "listitem", "aria-label": `Passage ${i + 1}: being rated` }));
    wrap.append(h("div", { class: "legend" }, h("span", {}, `The filter is rating ${e.search.read} passages…`)), strip);
    return wrap;
  }
  const check = t.checks[t.checks.length - 1];
  const cited = new Set();
  for (const c of check?.claims || []) for (const x of c.citations) cited.add(x.evidence);
  const first = !t.stripShown;
  r.pool.forEach((x, i) => {
    const g = x.filter_grade;
    const label = `Search rank ${x.search_rank}: ${g == null ? "not rated" : `rated ${g} (${RATING[g]})`}${x.selected ? `, kept as passage ${x.n}` : ", not used"}${cited.has(x.n) ? ", cited" : ""}. ${x.title}`;
    strip.append(h("button", {
      class: `tile${g != null ? ` r${g}` : ""}${x.selected ? " kept" : ""}${x.selected && cited.has(x.n) ? " cited" : ""}${first ? " enter" : ""}`,
      style: first ? `animation-delay:${i * 18}ms` : null, title: label, "aria-label": label, role: "listitem",
      onclick: () => openPoolRow(x.search_rank),
    }, x.selected && !cited.has(x.n) ? x.n : ""));
  });
  t.stripShown = true;
  wrap.append(h("div", { class: "legend" },
    h("span", {}, h("i", { class: "r3" }), "3 essential"), h("span", {}, h("i", { class: "r2" }), "2 useful"),
    h("span", {}, h("i", { class: "r1" }), "1 on topic"), h("span", {}, h("i", {}), "0 not about it"),
    h("span", {}, h("i", { class: "k" }), "kept for the answer (a dot: cited)")), strip);
  return wrap;
}

function openPoolRow(rank) {
  const row = $(`#pool-${rank}`);
  if (!row) return;
  row.closest("details").open = true;
  if (row.nextElementSibling?.hidden) row.click();
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("flash");
  setTimeout(() => row.classList.remove("flash"), 1200);
}

// While a step works, its node counts the seconds, so a long wait never looks frozen.
setInterval(() => {
  const t = state.selected;
  if (!t || t.events.done || t.events.error) return;
  const el = $("#trail .node.active .elapsed");
  if (el) el.textContent = ` · ${Math.round((performance.now() - t.t0) / 1000)}s`;
}, 1000);

// Every passage the relevance filter read: its search rank, its rating, and whether the answer model got it.
const RATING = { 3: "essential", 2: "useful", 1: "on topic, not usable", 0: "not about the question" };

function poolTable(t, r, citedBy) {
  const f = r.filter;
  const used = r.pool.filter((x) => x.selected).length;
  const box = h("details", { class: "pool", open: true }, h("summary", {},
    h("strong", {}, `All ${r.pool.length} passages the filter read`),
    h("span", { class: "muted" }, ` · ${used} used, ${r.pool.length - used} not used${f.status === "ok" ? ` · rated by ${f.model}` : " · not rated (the filter failed)"}`)));
  box.append(h("p", { class: "muted" }, "In search order. The rating is how much the filter judged an answer could use the passage: 3 essential, 2 useful, 1 on topic but not usable, 0 not about the question. The answer model got the passages rated highest (ties in search order); only those can be cited."));
  const table = h("table", { class: "pool-table" }, h("tr", {}, h("th", {}, "Search"), h("th", {}, "Rating"), h("th", {}, "Used"), h("th", {}, "Passage")));
  for (const brief of r.pool) {
    const x = brief.selected ? { ...r.evidence[brief.n - 1], ...brief } : brief;  // chosen: full text in evidence
    const textEl = h("div", { class: "ev-text pool-text" });
    const open = () => {
      if (!textEl.dataset.ready) {
        textEl.innerHTML = highlight(x.text, [], x.matched_terms);
        textEl.dataset.ready = "1";
      }
      detail.hidden = !detail.hidden;
    };
    const detail = h("tr", { class: "pool-detail", hidden: true }, h("td", { colspan: 4 }, textEl,
      h("div", { class: "ev-actions" },
        h("button", { onclick: () => textEl.classList.toggle("open") }, "Expand"),
        h("button", { onclick: () => openViewer(x.doc_id, x.pages[0], x.boxes) }, `Show on ${pages(x.pages)}`),
        h("button", { onclick: (ev2) => readAround(x.chunk_id, textEl, ev2.target) }, "Read around"),
        x.selected ? h("button", { onclick: () => { const c = $(`#ev-${x.n}`); if (c) { c.style.display = ""; c.scrollIntoView({ behavior: "smooth", block: "center" }); } } }, `Go to passage ${x.n}`) : null)));
    const g = x.filter_grade;
    table.append(
      h("tr", { class: `pool-row${x.selected ? " used" : ""}`, id: `pool-${x.search_rank}`, onclick: open, title: "Show the passage" },
        h("td", {}, x.search_rank),
        h("td", {}, g == null ? h("span", { class: "muted" }, "–") : h("span", { class: `rating r${g}`, title: RATING[g] }, g)),
        h("td", {}, x.selected ? h("span", { class: `badge ${citedBy[x.n] ? "info" : "ok"}` }, citedBy[x.n] ? `[${x.n}] cited` : `[${x.n}]`) : h("span", { class: "muted" }, "not used")),
        h("td", {}, h("div", { class: "pool-title" }, `${x.title}`), h("div", { class: "muted" }, `${x.year} · ${x.section.length ? x.section.join(" › ") + " · " : ""}${pages(x.pages)}`))),
      detail);
  }
  box.append(table);
  return box;
}

function filterDoc(doc, btn) {
  const items = document.querySelectorAll("#evlist .ev");
  const on = [...items].some((a) => a.style.display === "none") && [...items].find((a) => a.style.display !== "none")?.dataset.doc === doc;
  items.forEach((a) => { a.style.display = on || a.dataset.doc === doc ? "" : "none"; });
  document.querySelectorAll(".map-doc").forEach((b) => b.classList.remove("active"));
  if (!on) btn?.classList.add("active");
  $("#filter-note").textContent = on ? "Filled pips and a blue edge mark cited passages." : `Showing ${state.docs[doc]?.title || doc}. Select it again to show all.`;
}

// A claim's passages in the trail: outlined, opened, its sentences lit; scrolled to on request (to `passage`
// if given, otherwise the first it cites).
function focusClaim(t, n, { scroll = false, passage = null } = {}) {
  if (state.selected !== t) return;
  const pane = $("#trail");
  pane.querySelectorAll(".cite.on, mark.q.on").forEach((x) => x.classList.remove("on", "multi"));
  pane.querySelectorAll(".ev.focus").forEach((a) => a.classList.remove("focus"));
  const claim = claimsOf(t).find((c) => c.n === n);
  if (!claim) return;
  pane.querySelectorAll(`.cite[data-claim="${n}"]`).forEach((b) => b.classList.add("on"));
  const multi = passagesOf(claim) > 1;
  pane.querySelectorAll("mark.q[data-claims]").forEach((m) => {
    const on = m.dataset.claims.split(" ").includes(String(n));
    m.classList.toggle("on", on);
    m.classList.toggle("multi", on && multi);
  });
  let first = null;
  for (const c of claim.citations) {
    const card = $(`#ev-${c.evidence}`);
    if (!card) continue;
    card.style.display = "";
    card.classList.add("focus");
    card.querySelector(".ev-text").classList.add("open");
    if (passage == null || c.evidence === passage) first ||= card.querySelector("mark.q.on") || card;
  }
  if (scroll) first?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function readAround(chunkId, textEl, btn) {
  btn.disabled = true;
  try {
    const cur = await (await fetch(`${API}/api/chunk/${encodeURIComponent(chunkId)}`)).json();
    const get = async (id) => (id ? (await (await fetch(`${API}/api/chunk/${encodeURIComponent(id)}`)).json()).text : "");
    const [before, after] = await Promise.all([get(cur.prev), get(cur.next)]);
    const extra = (s, label) => (s ? `<div class="muted">${label}</div><div>${esc(s)}</div>` : "");
    textEl.insertAdjacentHTML("afterbegin", extra(before, "Before:") + (before ? "<hr>" : ""));
    textEl.insertAdjacentHTML("beforeend", (after ? "<hr>" : "") + extra(after, "After:"));
    textEl.classList.add("open");
    btn.textContent = "Showing neighbours";
  } catch (e) {
    btn.textContent = "Couldn't load";
  }
}

// --- the page viewer: PDF.js renders the cited page and the passage's boxes are drawn over it -----------

let pdfjs = null;
const viewer = { doc: null, pdf: null, page: 1, boxes: [] };

async function openViewer(docId, page, boxes) {
  const d = state.docs[docId] || { title: docId, pages: {} };
  const dlg = $("#viewer");
  $("#viewer-title").textContent = d.title;
  $("#viewer-meta").textContent = ` · ${d.year || ""} · ${d.licence || ""}`;
  const url = `${CFG.pdfBase}${docId}.pdf`;
  $("#viewer-open").href = d.url || url;
  $("#viewer-open").textContent = d.url ? "Publisher page" : "Open PDF";
  $("#viewer-msg").textContent = "Loading the document…";
  if (!dlg.open) dlg.showModal();
  try {
    pdfjs ||= await import(PDFJS);
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
    if (viewer.doc !== docId) {
      viewer.pdf = await pdfjs.getDocument({ url }).promise;
      viewer.doc = docId;
    }
    viewer.boxes = boxes;
    await renderPage(page);
    $("#viewer-msg").textContent = boxes.length ? "Highlighted: the passage's text blocks on this page." : "";
  } catch (e) {
    $("#viewer-msg").textContent = `This copy of the PDF isn't available here (${e.message || e}). ${d.url ? "Use the publisher page link above." : ""}`;
  }
}

async function renderPage(n) {
  const pdf = viewer.pdf;
  n = Math.max(1, Math.min(n, pdf.numPages));
  viewer.page = n;
  const page = await pdf.getPage(n);
  const base = page.getViewport({ scale: 1 });
  const width = Math.min($("#viewer-body").clientWidth - 30, 900);
  const scale = width / base.width;
  const vp = page.getViewport({ scale });
  const canvas = $("#page-canvas");
  const ratio = window.devicePixelRatio || 1;
  canvas.width = vp.width * ratio;
  canvas.height = vp.height * ratio;
  canvas.style.width = `${vp.width}px`;
  canvas.style.height = `${vp.height}px`;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
  const size = state.docs[viewer.doc]?.pages?.[n];
  const sx = size ? vp.width / size.width : scale, sy = size ? vp.height / size.height : scale;
  const marks = $("#page-marks");
  marks.replaceChildren();
  for (const b of viewer.boxes.filter((x) => x.page === n)) {
    const [l, t, r, bt] = b.bbox;
    marks.append(h("div", { class: "box", style: `left:${l * sx - 3}px;top:${t * sy - 3}px;width:${(r - l) * sx + 6}px;height:${(bt - t) * sy + 6}px` }));
  }
  $("#pg-num").textContent = `${n} / ${pdf.numPages}`;
  marks.firstChild?.scrollIntoView({ block: "center" });
}

// --- wiring ---------------------------------------------------------------------------------------------

// Chart tooltips on "How it works": the same text on hover and on keyboard focus. The tables carry every value too.
function initChartTips() {
  const tip = h("div", { class: "viz-tip", role: "tooltip" });
  tip.hidden = true;
  document.body.append(tip);
  const show = (el, x, y) => {
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    tip.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - r.width - 8))}px`;
    tip.style.top = `${Math.max(8, y - r.height - 12)}px`;
  };
  const at = (el) => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top]; };
  const hide = () => { tip.hidden = true; };
  document.querySelectorAll(".viz [data-tip]").forEach((el) => {
    el.addEventListener("pointermove", (ev) => show(el, ev.clientX, ev.clientY));
    el.addEventListener("pointerleave", hide);
    el.addEventListener("focus", () => show(el, ...at(el)));
    el.addEventListener("blur", hide);
  });
}

function init() {
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => { x.classList.toggle("active", x === b); x.removeAttribute("aria-current"); });
    b.setAttribute("aria-current", "page");
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${b.dataset.view}`));
  }));
  $("#starters").append(...STARTERS.map((q) => h("button", { class: "starter", type: "button", onclick: () => { $("#q").value = q; $("#q").focus(); } }, q)));
  $("#ask").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("#q").value.trim();
    if (!q || $("#send").disabled) return;
    const ctx = $("#ctx").value.trim();
    $("#q").value = "";
    $("#ctx").value = "";
    $("#extra").open = false;
    ask(q, ctx);
  });
  $("#q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("#ask").requestSubmit(); }
  });
  $("#viewer-close").addEventListener("click", () => $("#viewer").close());
  $("#save-chat").addEventListener("click", saveChat);
  $("#copy-chat").addEventListener("click", (ev) => copyOut(ev.currentTarget, chatJson()));
  // A cited sentence in a passage shows the claim that cites it, in the answer.
  $("#trail").addEventListener("click", (ev) => {
    const m = ev.target.closest("mark.q[data-claims]");
    if (m && state.selected) pickClaim(state.selected, +m.dataset.claims.split(" ")[0], { fromTrail: true });
  });
  initTheme();
  initChartTips();
  $("#pg-prev").addEventListener("click", () => viewer.pdf && renderPage(viewer.page - 1));
  $("#pg-next").addEventListener("click", () => viewer.pdf && renderPage(viewer.page + 1));
  wake();
  loadCatalogue();
}

init();
