// Live connection to the Sanjaya server: messages, dashboard snapshot and reasoning traces.
import { useEffect, useRef, useState, useCallback } from "react";
import { speakFor } from "./speech";

export async function api(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function postMessage(fields, files = []) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null && v !== "") fd.append(k, v);
  for (const f of files) fd.append("files", f, f.name || "voice.webm");
  const r = await fetch("/api/messages", { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export function useSanjaya(me) {
  const [state, setState] = useState({
    ready: false, plant: null, users: {}, messages: [], dashboard: null, traces: {}, clockOffset: 0, connected: false,
  });
  const meRef = useRef(me);
  meRef.current = me;

  const load = useCallback(async () => {
    const d = await (await fetch("/api/bootstrap")).json();
    const traces = {};
    for (const t of d.dashboard.traces || []) traces[t.id] = t;
    setState((s) => ({
      ...s, ready: true, plant: d.plant, users: Object.fromEntries(d.users.map((u) => [u.id, u])),
      messages: d.messages, dashboard: d.dashboard, traces, clockOffset: d.dashboard.now - Date.now(),
    }));
  }, []);

  useEffect(() => {
    let ws, ping, closed = false, retry;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws?user=${encodeURIComponent(meRef.current || "viewer")}`);
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onmessage = (ev) => onEvent(JSON.parse(ev.data));
      ws.onclose = () => {
        clearInterval(ping);
        setState((s) => ({ ...s, connected: false }));
        if (!closed) retry = setTimeout(() => { load().catch(() => {}); connect(); }, 1500);
      };
      ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
    };
    const onEvent = (ev) => {
      if (ev.type === "message") {
        speakFor(ev.message, meRef.current);
        setState((s) => ({ ...s, messages: [...s.messages, ev.message] }));
      } else if (ev.type === "message_update") {
        setState((s) => ({ ...s, messages: s.messages.map((m) => (m.id === ev.message.id ? ev.message : m)) }));
      } else if (ev.type === "dashboard") {
        setState((s) => ({ ...s, dashboard: ev.dashboard, clockOffset: ev.dashboard.now - Date.now() }));
      } else if (ev.type === "trace") {
        setState((s) => ({ ...s, traces: { ...s.traces, [ev.trace.id]: ev.trace } }));
      } else if (ev.type === "reset") {
        window.speechSynthesis?.cancel();
        load();
      }
    };
    load().then(connect);
    return () => { closed = true; clearTimeout(retry); clearInterval(ping); ws && ws.close(); };
  }, [load]);

  return state;
}

// Ticks every 500 ms so countdowns re-render.
export function useNow(offset = 0) {
  const [now, setNow] = useState(Date.now() + offset);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() + offset), 500);
    return () => clearInterval(t);
  }, [offset]);
  return now;
}

export const LEVEL = {
  normal: { color: "var(--color-safe)", text: "text-emerald-400", bg: "bg-emerald-500/15", ring: "ring-emerald-500/30", label: "Normal" },
  watch: { color: "var(--color-watch)", text: "text-yellow-300", bg: "bg-yellow-500/15", ring: "ring-yellow-500/30", label: "Watch" },
  elevated: { color: "var(--color-elevated)", text: "text-orange-400", bg: "bg-orange-500/15", ring: "ring-orange-500/40", label: "Elevated" },
  critical: { color: "var(--color-critical)", text: "text-red-400", bg: "bg-red-500/15", ring: "ring-red-500/50", label: "Critical" },
};

export function hhmm(ms) {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const AVATAR = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#64748b"];
export function colorFor(id) {
  if (id === "sanjaya") return "#fca311";
  let h = 0;
  for (const c of id || "") h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATAR[h % AVATAR.length];
}
