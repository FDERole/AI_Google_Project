/* Sanjaya mobile web app: live group chat, voice in/out, request cards, countdowns, dashboard. */
"use strict";

const S = {
  me: null, plant: null, users: {}, messages: new Map(), dashboard: null,
  clockOffset: 0, replyTo: null, files: [], ws: null, voices: [],
};
const COLORS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#475569"];
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const now = () => Date.now() + S.clockOffset;
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

function colorFor(id) {
  let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return id === "sanjaya" ? "#fca311" : COLORS[h % COLORS.length];
}
function hhmm(ms) { return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
function userLang(id) { return (S.users[id] && S.users[id].lang) || "en-IN"; }
function isDashboard() { return S.me === "dashboard"; }

// ---------------------------------------------------------------- boot / join
async function boot() {
  const data = await (await fetch("/api/bootstrap")).json();
  applyBootstrap(data);
  $("#plant-name").textContent = `${data.plant.name} · ${data.plant.company}`;
  const people = [...data.users, { id: "dashboard", name: "Dashboard", title: "Big screen: risk stack, timers, audit" }];
  const wrap = $("#people");
  wrap.innerHTML = "";
  let selected = store.get("sanjaya.me");
  for (const p of people) {
    const el = document.createElement("button");
    el.className = "person";
    el.innerHTML = `<span class="avatar" style="background:${p.id === "dashboard" ? "#14213d" : colorFor(p.id)}">${p.id === "dashboard" ? "📊" : esc(p.name[0])}</span>
      <span><b>${esc(p.name)}</b><small>${esc(p.title)}${p.approver_level ? ` · approver L${p.approver_level}` : ""}</small></span>`;
    el.onclick = () => { selected = p.id; [...wrap.children].forEach((c) => c.classList.remove("selected")); el.classList.add("selected"); $("#join-btn").disabled = false; };
    if (p.id === selected) { el.classList.add("selected"); $("#join-btn").disabled = false; }
    wrap.appendChild(el);
  }
  $("#join-btn").onclick = () => join(selected);
}

function applyBootstrap(data) {
  S.plant = data.plant;
  S.users = Object.fromEntries(data.users.map((u) => [u.id, u]));
  S.messages = new Map(data.messages.map((m) => [m.id, m]));
  setDashboard(data.dashboard);
}

function join(id) {
  if (!id) return;
  S.me = id;
  store.set("sanjaya.me", id);
  // Phones block audio until a tap: speaking an empty utterance inside this click unlocks speech.
  try { speechSynthesis.speak(new SpeechSynthesisUtterance(" ")); } catch { /* no TTS */ }
  $("#join").classList.add("hidden");
  $("#main").classList.remove("hidden");
  $("#group-name").textContent = S.plant.group_name;
  const u = S.users[id];
  $("#me-label").textContent = u ? `You: ${u.name} · ${u.title}` : "Dashboard";
  if (isDashboard()) { document.body.classList.add("dashboard-mode"); showView("dash"); $("#composer").classList.add("hidden"); }
  renderAllMessages();
  connect();
  buildDemo();
}

function showView(view) {
  $("#chat").classList.toggle("hidden", view !== "chat");
  $("#dash").classList.toggle("hidden", view !== "dash");
  if (!isDashboard()) $("#composer").classList.toggle("hidden", view !== "chat");
  $("#tab-btn").textContent = view === "chat" ? "📊" : "💬";
  $("#tab-btn").dataset.view = view;
  if (view === "chat") scrollBottom(true);
}
$("#tab-btn").onclick = () => showView($("#tab-btn").dataset.view === "dash" ? "chat" : "dash");

// ---------------------------------------------------------------- websocket
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?user=${encodeURIComponent(S.me)}`);
  S.ws = ws;
  const ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
  ws.onmessage = (ev) => onEvent(JSON.parse(ev.data));
  ws.onclose = () => {
    clearInterval(ping);
    setTimeout(async () => { // reconnect and resync anything missed
      try { applyBootstrap(await (await fetch("/api/bootstrap")).json()); renderAllMessages(); } catch { /* retry */ }
      connect();
    }, 1500);
  };
}

function onEvent(ev) {
  if (ev.type === "message") {
    S.messages.set(ev.message.id, ev.message);
    renderMessage(ev.message, true);
    speakFor(ev.message);
  } else if (ev.type === "message_update") {
    S.messages.set(ev.message.id, ev.message);
    renderMessage(ev.message, false);
    rerenderLinked(ev.message);
  } else if (ev.type === "dashboard") {
    setDashboard(ev.dashboard);
  } else if (ev.type === "reset") {
    speechSynthesis.cancel();
    fetch("/api/bootstrap").then((r) => r.json()).then((d) => { applyBootstrap(d); renderAllMessages(); });
  }
}

function setDashboard(d) {
  S.dashboard = d;
  if (d.now) S.clockOffset = d.now - Date.now();
  const badge = $("#mode-badge");
  badge.className = `badge ${d.mode}`;
  badge.textContent = d.mode === "gemini" ? "✨ Gemini live" : "Offline mode";
  if ($("#speed")) $("#speed").value = String(d.speed);
  renderDash();
  // Relay cards show a Start button only while the request is approved: refresh them.
  for (const m of S.messages.values()) if (m.type === "relay_card") renderMessage(m, false);
}

function requestById(id) { return (S.dashboard?.requests || []).find((r) => r.id === id); }

// ---------------------------------------------------------------- speech out
let speakQueue = Promise.resolve();
function loadVoices() { try { S.voices = speechSynthesis.getVoices(); } catch { S.voices = []; } }
if ("speechSynthesis" in window) { loadVoices(); speechSynthesis.onvoiceschanged = loadVoices; }

function say(text, lang) {
  if (!("speechSynthesis" in window) || !text) return Promise.resolve();
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = lang === "hi-IN" ? 0.95 : 1;
    const norm = (l) => l.replace("_", "-").toLowerCase();
    u.voice = S.voices.find((v) => norm(v.lang) === lang.toLowerCase()) ||
      S.voices.find((v) => norm(v.lang).startsWith(lang.slice(0, 2))) || null;
    $("#speaking").classList.remove("hidden");
    const done = () => { $("#speaking").classList.add("hidden"); resolve(); };
    u.onend = done; u.onerror = done;
    speechSynthesis.speak(u);
  });
}
function speakFor(m) {
  for (const entry of m.speak || []) {
    if (entry.to.includes(S.me)) speakQueue = speakQueue.then(() => say(entry.text, entry.lang));
  }
}

// ---------------------------------------------------------------- rendering
function renderAllMessages() {
  $("#chat").innerHTML = "";
  for (const m of S.messages.values()) renderMessage(m, false);
  scrollBottom(true);
}

// Stay pinned to the newest message unless the user has scrolled up to read history.
let stick = true;
$("#chat").addEventListener("scroll", () => {
  const c = $("#chat");
  stick = c.scrollHeight - c.scrollTop - c.clientHeight < 120;
});
function scrollBottom(force) {
  const c = $("#chat");
  if (force || stick) { c.scrollTop = c.scrollHeight; stick = true; }
}

function renderMessage(m, isNew) {
  const el = buildMessage(m);
  el.id = `msg-${m.id}`;
  const old = document.getElementById(el.id);
  if (old) old.replaceWith(el); else $("#chat").appendChild(el);
  el.querySelectorAll("img").forEach((img) => img.addEventListener("load", () => scrollBottom(false)));
  if (isNew || !old) scrollBottom(m.author === S.me);
}

function rerenderLinked(m) {
  const reqId = m.data?.request?.id;
  if (!reqId) return;
  for (const other of S.messages.values()) {
    if (other.data?.request_id === reqId) renderMessage(other, false);
  }
}

function buildMessage(m) {
  const wrap = document.createElement("div");
  const mine = m.author === S.me;
  const wide = m.type.endsWith("_card") || m.type === "alert";
  wrap.className = `msg ${mine ? "mine" : ""} ${m.author === "sanjaya" ? "sanjaya" : ""} ${wide ? "wide" : ""}`;
  const who = mine ? "" : `<div class="who" style="color:${colorFor(m.author)}">${esc(m.author_name)}${S.users[m.author] ? ` · ${esc(S.users[m.author].title)}` : ""}</div>`;
  let body;
  switch (m.type) {
    case "request_card": body = requestCard(m); break;
    case "readback_card": body = readbackCard(m); break;
    case "relay_card": body = relayCard(m); break;
    case "timer_card": body = timerCard(m); break;
    case "report_card": body = reportCard(m); break;
    case "alert": body = alertCard(m); break;
    default: body = bubble(m);
  }
  wrap.innerHTML = `${who}${typeof body === "string" ? body : ""}<div class="time">${hhmm(m.at)}</div>`;
  if (typeof body !== "string") wrap.insertBefore(body, wrap.querySelector(".time"));
  wireCard(wrap, m);
  return wrap;
}

function bubble(m) {
  let html = "";
  for (const media of m.media || []) {
    if (media.kind === "photo") html += `<img class="photo" src="${esc(media.url)}" alt="photo">`;
    else if (media.kind === "document") html += `<a class="doc" href="${esc(media.url)}" target="_blank">📄 ${esc(media.name || "document")}</a>`;
  }
  if (m.type === "voice") {
    const audio = (m.media || []).find((x) => x.kind === "voice");
    html += `<div class="voice"><button class="play" data-audio="${audio ? esc(audio.url) : ""}" data-lang="${userLang(m.author)}">▶</button><div class="wave"></div></div>`;
    if (m.transcript) html += `<div class="transcript">“${esc(m.transcript)}”</div>`;
  }
  if (m.text) html += `<div>${esc(m.text)}</div>`;
  const chips = [];
  if (m.data?.change) chips.push(`<span class="chip change">📝 Logged change: ${esc(m.data.change.summary)}</span>`);
  if (m.data?.seen) chips.push(`<span class="chip seen">👁 ${esc(m.data.seen)}</span>`);
  if (m.data?.request) chips.push(`<span class="chip">📨 Sent for approval</span>`);
  if (m.mode === "gemini" && m.author !== "sanjaya") chips.push(`<span class="chip mode">✨ read by Gemini</span>`);
  if (chips.length) html += `<div class="chips">${chips.join("")}</div>`;
  return `<div class="bubble">${html}</div>`;
}

const STATUS_LABEL = {
  pending: "waiting", awaiting_readback: "read-back", approved: "approved", rejected: "rejected",
  active: "in progress", overrun: "over time", done: "done",
};

function requestCard(m) {
  const r = m.data.request;
  const latest = r; // the server refreshes this card on every status change
  const canDecide = latest.status === "pending" && latest.approvers.includes(S.me);
  let html = `<div class="card request"><div class="card-head"><span>${r.kind === "part" ? "🔧 Part change approval" : "✋ Approval needed"} · ${esc(latest.approver_names.join(", "))}</span><span class="status">${STATUS_LABEL[latest.status] || latest.status}</span></div><div class="card-body">`;
  html += `<div><b>${esc(r.requester_name)}</b>: ${esc(r.summary)}</div>`;
  let text = m.text;
  for (const n of r.stack_notes || []) text = text.replace(n, "");  // shown below as a highlighted note
  html += `<p>${esc(text.replace(/\s+/g, " ").trim())}</p>`;
  if (r.limit) html += `<span class="cite">📘 Limit: ${r.limit.max_minutes} min · ${esc(r.limit.source)}</span>`;
  else if (r.kind === "equipment") html += `<span class="cite">⚠️ No documented limit in plant data</span>`;
  for (const n of r.stack_notes || []) html += `<div class="note">${esc(n)}</div>`;
  if ((latest.escalations || []).length) html += `<div class="note">Escalated to level ${latest.level}</div>`;
  if (latest.decider_name && ["approved", "rejected", "active", "overrun", "done"].includes(latest.status)) {
    html += `<div class="note" style="background:var(--ok-bg);color:var(--ok)">Decision by ${esc(latest.decider_name)}${latest.max_minutes ? ` · max ${latest.max_minutes} min` : ""}${latest.conditions && r.kind === "part" ? ` · ${esc(latest.conditions)}` : ""}</div>`;
  }
  if (canDecide) {
    html += `<div class="actions">
      <button class="btn-ok" data-act="approve">Approve</button>
      <button class="btn-cond" data-act="cond">${r.kind === "part" ? "With conditions" : "Approve with limit"}</button>
      <button class="btn-bad" data-act="reject">Reject</button>
      <button class="btn-talk" data-talk="${m.id}">🎤 Hold to reply</button></div>
      <div class="minutes hidden">Max minutes: ${[5, 10, 15, 20].map((n) => `<button data-min="${n}">${n}</button>`).join("")}</div>`;
  }
  return html + "</div></div>";
}

function readbackCard(m) {
  const open = !m.data.resolved && m.data.decider === S.me;
  let html = `<div class="card readback"><div class="card-head"><span>🔁 Read-back</span>${m.data.resolved ? `<span class="status">${m.data.resolved}</span>` : ""}</div><div class="card-body"><p>${esc(m.text)}</p>`;
  if (open) html += `<div class="actions"><button class="btn-ok" data-act="confirm">✓ Correct</button><button class="btn-plain" data-act="change">✗ Change</button><button class="btn-talk" data-talk="${m.id}">🎤 Say it</button></div>`;
  return html + "</div></div>";
}

function relayCard(m) {
  const d = m.data;
  const req = requestById(d.request_id);
  let html = `<div class="card relay ${d.approved ? "" : "rejected"}"><div class="card-head"><span>${d.approved ? "✅ Approved" : "⛔ Rejected"} · for ${esc(S.users[d.requester]?.name || "")}</span></div><div class="card-body"><p>${esc(m.text)}</p>`;
  if (d.english) html += `<div class="transcript">${esc(d.english)}</div>`;
  if (d.approved && d.kind === "equipment" && req && req.status === "approved" && d.requester === S.me) {
    html += `<div class="actions"><button class="btn-ok" data-act="start">▶ Starting now</button></div>`;
  }
  return html + "</div></div>";
}

function timerCard(m) {
  const d = m.data;
  const el = document.createElement("div");
  el.className = "card timer";
  el.dataset.timer = m.id;
  const mine = d.requester === S.me && (d.status === "running" || d.status === "overrun");
  el.innerHTML = `<div class="card-head"><span>⏱ ${esc(m.text)}</span><span class="status">${d.status}</span></div>
    <div class="card-body"><div class="countdown"></div><div class="bar"><div></div></div>
    <div class="timer-meta"></div>
    ${mine ? `<div class="actions"><button class="btn-ok" data-act="finish">✓ Back on: done</button></div>` : ""}</div>`;
  updateTimer(el, d);
  return el;
}

function fmt(sec) {
  const s = Math.abs(Math.round(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function updateTimer(el, d) {
  const cd = el.querySelector(".countdown"), bar = el.querySelector(".bar"), meta = el.querySelector(".timer-meta");
  if (!cd) return;
  if (d.status === "done") {
    cd.textContent = "✓"; cd.className = "countdown";
    bar.className = "bar"; bar.firstElementChild.style.width = "100%";
    meta.textContent = `Back on after ${d.elapsed_minutes} min${d.max_minutes ? ` (limit ${d.max_minutes} min)` : ""}`;
    return;
  }
  if (!d.ends_at) { cd.textContent = "—"; meta.textContent = "No time limit"; return; }
  const total = d.max_minutes * 60;
  const remaining = ((d.ends_at - now()) / 1000) * d.speed; // plant seconds
  const elapsed = total - remaining;
  const over = remaining < 0, warn = !over && remaining < 5 * 60;
  cd.textContent = (over ? "+" : "") + fmt(remaining);
  cd.className = `countdown ${over ? "over" : warn ? "warn" : ""}`;
  bar.className = `bar ${over ? "over" : warn ? "warn" : ""}`;
  bar.firstElementChild.style.width = `${Math.min(100, (elapsed / total) * 100)}%`;
  meta.textContent = `${over ? "Over the approved limit" : "Remaining"} · max ${d.max_minutes} min${d.speed !== 1 ? ` · demo clock ${d.speed}×` : ""}`;
}

setInterval(() => {
  document.querySelectorAll("[data-timer]").forEach((el) => {
    const m = S.messages.get(el.dataset.timer);
    if (m && (m.data.status === "running" || m.data.status === "overrun")) updateTimer(el, m.data);
  });
  document.querySelectorAll("[data-dash-timer]").forEach((el) => {
    const m = S.messages.get(el.dataset.dashTimer);
    if (m) el.textContent = m.data.ends_at ? ((m.data.ends_at - now() < 0) ? "+" : "") + fmt(((m.data.ends_at - now()) / 1000) * m.data.speed) : "—";
  });
}, 500);

function reportCard(m) {
  const r = m.data.report;
  const ok = r.like_for_like;
  const rows = r.rows.map((row) => `<tr><td>${esc(row.label)}${row.source ? `<br><small class="st-info">${esc(row.source)}</small>` : ""}</td>
      <td>${esc(row.current)}</td><td>${esc(row.proposed)}</td><td class="st-${row.status}">${esc(row.note)}</td></tr>`).join("");
  let html = `<div class="card report ${ok ? "ok" : ""}"><div class="card-head"><span>${r.unreviewed ? "🔍 Unreviewed change check" : "🔧 Like-for-like check"} · ${esc(r.equipment_name)}</span><span class="status">${ok ? "like-for-like" : "not like-for-like"}</span></div><div class="card-body">`;
  html += `<div class="transcript">${esc(r.safety_role)}</div>`;
  html += `<div class="table-wrap"><table class="spec"><tr><th>Requirement</th><th>Current<br>${esc(r.current_model)}</th><th>Proposed<br>${esc(r.proposed_model)}</th><th>Status</th></tr>${rows}</table></div>`;
  for (const n of r.plant_state || []) html += `<div class="note">${esc(n)}</div>`;
  html += `<div class="verdict">Verdict: ${esc(r.verdict)}</div>`;
  return html + "</div></div>";
}

function alertCard(m) {
  const level = m.data?.stack?.level?.name;
  const title = level === "critical" ? "⚠️ Risk stack: critical" : level === "elevated" ? "Risk stack: elevated" : "Sanjaya alert";
  return `<div class="card alert ${level === "elevated" ? "elevated" : ""}"><div class="card-head"><span>${title}</span></div><div class="card-body">${esc(m.text)}</div></div>`;
}

// ---------------------------------------------------------------- card actions
async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (!r.ok) { const t = await r.text(); alert(`Couldn't do that: ${t}`); }
}

function wireCard(wrap, m) {
  wrap.querySelectorAll(".play").forEach((b) => b.onclick = () => {
    if (b.dataset.audio) new Audio(b.dataset.audio).play();
    else say(m.transcript || m.text, b.dataset.lang);
  });
  wrap.querySelectorAll("[data-talk]").forEach((b) => setupTalk(b, b.dataset.talk));
  const reqId = m.data?.request?.id || m.data?.request_id;
  wrap.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
    const act = b.dataset.act;
    const isPart = m.data?.request?.kind === "part";
    if (act === "approve") api(`/api/requests/${reqId}/decision`, { user: S.me, decision: "approve" });
    if (act === "reject") api(`/api/requests/${reqId}/decision`, { user: S.me, decision: "reject" });
    if (act === "cond") {
      if (isPart) {
        const c = prompt("Conditions for approval:", "Supplier must provide Ex-certified, T4, spark-resistant model meeting 12,000 m³/h");
        if (c) api(`/api/requests/${reqId}/decision`, { user: S.me, decision: "approve_with_conditions", conditions: c });
      } else wrap.querySelector(".minutes").classList.toggle("hidden");
    }
    if (act === "confirm") api(`/api/requests/${reqId}/confirm`, { user: S.me, yes: true });
    if (act === "change") api(`/api/requests/${reqId}/confirm`, { user: S.me, yes: false });
    if (act === "start") api(`/api/requests/${reqId}/start`, { user: S.me });
    if (act === "finish") api(`/api/requests/${reqId}/finish`, { user: S.me });
  });
  wrap.querySelectorAll("[data-min]").forEach((b) => b.onclick = () =>
    api(`/api/requests/${reqId}/decision`, { user: S.me, decision: "approve_with_conditions", max_minutes: +b.dataset.min, conditions: `maximum ${b.dataset.min} minutes` }));
}

// ---------------------------------------------------------------- posting
async function postForm(fields, files = []) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) fd.append(k, v);
  for (const f of files) fd.append("files", f, f.name || "voice.webm");
  const r = await fetch("/api/messages", { method: "POST", body: fd });
  if (!r.ok) alert(`Couldn't send: ${await r.text()}`);
}

async function send() {
  const text = $("#text").value.trim();
  if (!text && !S.files.length) return;
  $("#text").value = "";
  const files = S.files; S.files = []; $("#file").value = ""; updateAttachPreview();
  await postForm({ user: S.me, text, reply_to: S.replyTo }, files);
  setReply(null);
}
$("#send").onclick = send;
$("#text").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
$("#file").onchange = (e) => { S.files = [...e.target.files]; updateAttachPreview(); };
function updateAttachPreview() {
  const p = $("#attach-preview");
  p.classList.toggle("hidden", !S.files.length);
  p.textContent = S.files.map((f) => `📎 ${f.name}`).join("  ");
}
function setReply(id) {
  S.replyTo = id;
  $("#reply-bar").classList.toggle("hidden", !id);
  if (id) $("#reply-bar span").textContent = "Replying to Sanjaya's card";
}
$("#reply-cancel").onclick = () => setReply(null);

// ---------------------------------------------------------------- hold to talk
function setupTalk(button, replyTo) {
  let session = null;
  const start = async (e) => {
    e.preventDefault();
    if (session) return;
    session = { chunks: [], transcript: "", stopped: false };
    button.classList.add("recording");
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      const rec = new SR();
      rec.lang = userLang(S.me); rec.continuous = true; rec.interimResults = false;
      rec.onresult = (ev) => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) session.transcript += ev.results[i][0].transcript + " "; };
      session.recEnded = new Promise((res) => { rec.onend = res; rec.onerror = res; });
      try { rec.start(); session.rec = rec; } catch { session.rec = null; }
    }
    if (navigator.mediaDevices?.getUserMedia && window.MediaRecorder) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mr = new MediaRecorder(stream);
        mr.ondataavailable = (ev) => ev.data.size && session && session.chunks.push(ev.data);
        session.mrStopped = new Promise((res) => { mr.onstop = () => { stream.getTracks().forEach((t) => t.stop()); res(); }; });
        session.mr = mr; mr.start();
        if (session.stopped) stop();
      } catch { session.mr = null; }
    }
    if (!session.rec && !session.mr) {
      button.classList.remove("recording"); session = null;
      const typed = prompt("Voice isn't available in this browser. Type your reply:");
      if (typed) postForm({ user: S.me, text: typed, reply_to: replyTo });
    }
  };
  const stop = async () => {
    if (!session) return;
    session.stopped = true;
    if (session.mr === undefined && session.rec === undefined) return;
    const s = session; session = null;
    button.classList.remove("recording");
    if (s.rec) { try { s.rec.stop(); } catch { /* ended */ } }
    if (s.mr && s.mr.state !== "inactive") s.mr.stop();
    const timeout = new Promise((res) => setTimeout(res, 1500));
    await Promise.race([Promise.all([s.recEnded, s.mrStopped].filter(Boolean)), timeout]);
    const transcript = s.transcript.trim();
    const blob = s.chunks.length ? new Blob(s.chunks, { type: s.mr?.mimeType || "audio/webm" }) : null;
    if ((!blob || blob.size < 800) && !transcript) return;
    const files = blob ? [new File([blob], "voice.webm", { type: blob.type })] : [];
    await postForm({ user: S.me, transcript, reply_to: replyTo, as_voice: files.length ? undefined : "true" }, files);
  };
  button.addEventListener("pointerdown", start);
  button.addEventListener("pointerup", stop);
  button.addEventListener("pointerleave", stop);
  button.addEventListener("pointercancel", stop);
  button.addEventListener("contextmenu", (e) => e.preventDefault());
}
setupTalk($("#mic"), null);

// ---------------------------------------------------------------- dashboard
function renderDash() {
  const d = S.dashboard;
  if (!d || !$("#stacks")) return;
  $("#stacks").innerHTML = d.risk.map((s) => `
    <div class="stack ${s.level.name}">
      <div class="stack-head"><strong>${esc(s.hazard)}</strong><span class="level ${s.level.name}">${s.level.name}</span></div>
      <div class="meter">${s.barriers.map((b) => `<span class="${b.down ? "down" : ""}" title="${esc(b.name)}"></span>`).join("")}</div>
      <div class="meta" style="font-size:12px;color:var(--muted)">${s.degraded.length} of ${s.total_barriers} safeguards weakened · ${esc(s.source)}</div>
      ${s.barriers.map((b) => {
        const deg = s.degraded.find((x) => x.barrier === b.name);
        return `<div class="barrier ${b.down ? "down" : ""}">${b.down ? "✗" : "✓"} ${esc(b.name)}${deg ? `<br><small>↳ ${esc(deg.changes.map((c) => c.summary).join("; "))}</small>` : ""}</div>`;
      }).join("")}
    </div>`).join("");

  const timers = d.requests.filter((r) => r.status === "active" || r.status === "overrun");
  $("#timers").innerHTML = timers.length ? timers.map((r) => `<div class="item"><span>${esc(r.summary)}<br><span class="meta">by ${esc(r.requester_name)} · approved by ${esc(r.decider_name)} · max ${r.max_minutes} min</span></span><b data-dash-timer="${esc(r.timer_msg_id)}" style="font-size:20px;${r.status === "overrun" ? "color:var(--bad)" : ""}"></b></div>`).join("") : `<div class="empty">No live timers</div>`;

  $("#requests").innerHTML = d.requests.length ? d.requests.map((r) => `<div class="item"><span>${esc(r.summary)}<br><span class="meta">${esc(r.requester_name)} → ${esc(r.approver_names.join(", "))}</span></span><span class="level ${r.status === "rejected" || r.status === "overrun" ? "critical" : r.status === "pending" || r.status === "awaiting_readback" ? "elevated" : ""}">${STATUS_LABEL[r.status] || r.status}</span></div>`).join("") : `<div class="empty">No requests yet</div>`;

  const actor = isDashboard() ? "meena" : S.me;
  $("#changes").innerHTML = d.changes.length ? d.changes.map((c) => `<div class="item"><span>${esc(c.summary)}<br><span class="meta">${esc(c.by_name)} · ${hhmm(c.at)} · ${c.kind} · ${c.status}</span></span>${c.status === "active" && c.kind !== "approved" ? `<button data-restore="${c.id}">Restore</button>` : ""}</div>`).join("") : `<div class="empty">No changes logged</div>`;
  $("#changes").querySelectorAll("[data-restore]").forEach((b) => b.onclick = () => api(`/api/changes/${b.dataset.restore}/close`, { user: actor }));

  $("#audit").innerHTML = d.audit.map((a) => {
    const { at, event, ...rest } = a;
    const detail = Object.entries(rest).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ");
    return `<div class="item">${hhmm(at)} <b>${esc(event)}</b> ${esc(detail).slice(0, 220)}</div>`;
  }).join("");
}

// ---------------------------------------------------------------- demo drawer
const DEMO = [
  { act: "1 · Watch: small changes stack up" },
  { label: "Arjun 🎤 batch raised to 480 kg", user: "arjun", as_voice: true, transcript: "आज का बैच 400 से बढ़ाकर 480 किलो कर दिया है" },
  { label: "Suresh 📷 muted alarm panel", user: "suresh", text: "Alarm baar baar baj raha tha, mute kar diya", demo: "demo:alarm_panel_muted.png" },
  { label: "Suresh: trainee on night shift", user: "suresh", text: "Night shift mein naya trainee Raju add kiya hai, aaj uska pehla din hai" },
  { act: "2 · Approve: live voice loop" },
  { label: "Arjun: asks to shut down the boiler", user: "arjun", text: "Boiler B-1 band karna hai, maintenance ke liye. Kya kar sakte hain?" },
  { label: "Ravi 🎤 “Yes, but 15 minutes max”", user: "ravi", as_voice: true, transcript: "Yes, but 15 minutes max" },
  { label: "Ravi: “Yes, correct” (read-back)", user: "ravi", text: "Yes, correct" },
  { label: "Arjun: boiler is off now", user: "arjun", text: "Boiler band kar diya" },
  { label: "Arjun: boiler back on", user: "arjun", text: "Boiler wapas chalu kar diya" },
  { label: "No reply → escalate latest request", special: "skip" },
  { act: "3 · Evaluate: replacement part" },
  { label: "Suresh: gas detector in maintenance", user: "suresh", text: "Gas detector GD-07 calibration ke liye maintenance mein hai" },
  { label: "Priya 📄 evaluate Supplier B fan", user: "priya", text: "We're planning to switch to Supplier B for the solvent-room fan. Go through the attached docs and evaluate the risk.", demo: "datasheet:kestrel_kx120.pdf,datasheet:brightline_bf105.pdf" },
  { label: "Arjun 📷 fan replaced without review", user: "arjun", text: "Solvent room ka fan badal diya", demo: "demo:fan_nameplate_bf105.png" },
];

function buildDemo() {
  const box = $("#demo-steps");
  box.innerHTML = "";
  for (const step of DEMO) {
    if (step.act) { const h = document.createElement("div"); h.className = "act"; h.textContent = step.act; box.appendChild(h); continue; }
    const b = document.createElement("button");
    b.innerHTML = `<b>${esc(step.label)}</b>`;
    b.onclick = async () => {
      if (step.special === "skip") {
        const pending = (S.dashboard?.requests || []).find((r) => r.status === "pending");
        if (pending) await api(`/api/requests/${pending.id}/skip-wait`);
        return;
      }
      await postForm({ user: step.user, text: step.text || "", transcript: step.transcript, as_voice: step.as_voice ? "true" : undefined, demo: step.demo || "" });
    };
    box.appendChild(b);
  }
}
$("#demo-btn").onclick = () => $("#demo").classList.toggle("hidden");
$("#demo-close").onclick = () => $("#demo").classList.add("hidden");
$("#speed").onchange = (e) => api("/api/demo/settings", { speed: +e.target.value });
$("#offline").onchange = (e) => api("/api/demo/settings", { offline: e.target.checked });
$("#reset").onclick = () => { if (confirm("Reset the demo for everyone?")) api("/api/demo/reset"); };

boot();
