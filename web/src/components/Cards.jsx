import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, BookOpen, Check, ChevronDown, Clock, FileText, Hand, Phone, PhoneCall, Play, Repeat, Search,
  ShieldAlert, Sparkles, ThumbsDown, ThumbsUp, Timer, Wrench, X,
} from "lucide-react";
import { api, hhmm, LEVEL } from "../store";
import { say } from "../speech";
import { TraceSteps } from "./Trace";
import TalkButton from "./TalkButton";

const STATUS = {
  pending: ["Waiting", "bg-saffron-500/15 text-saffron-300"], awaiting_readback: ["Read-back", "bg-violet-500/20 text-violet-300"],
  approved: ["Approved", "bg-emerald-500/15 text-emerald-300"], rejected: ["Rejected", "bg-red-500/15 text-red-300"],
  active: ["In progress", "bg-sky-500/15 text-sky-300"], overrun: ["Over time", "bg-red-500/25 text-red-200"],
  done: ["Done", "bg-ink-700 text-ink-300"],
};

function Pill({ status }) {
  const [label, cls] = STATUS[status] || [status, "bg-ink-700 text-ink-300"];
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${cls}`}>{label}</span>;
}

function Shell({ tone = "ink", icon: Icon, title, right, children, glow }) {
  const tones = {
    ink: "from-ink-700 to-ink-800", saffron: "from-saffron-600/40 to-ink-800", violet: "from-violet-600/40 to-ink-800",
    green: "from-emerald-600/35 to-ink-800", red: "from-red-600/45 to-ink-800", orange: "from-orange-600/40 to-ink-800",
    sky: "from-sky-600/35 to-ink-800",
  };
  return (
    <div className={`w-full overflow-hidden rounded-2xl bg-ink-850 ring-1 ring-ink-700 ${glow || ""}`}>
      <div className={`flex items-center justify-between gap-2 bg-gradient-to-r px-3.5 py-2.5 ${tones[tone]}`}>
        <span className="flex min-w-0 items-center gap-2 text-[13px] font-bold">
          {Icon && <Icon className="h-4 w-4 shrink-0" />} <span className="truncate">{title}</span>
        </span>
        {right}
      </div>
      <div className="px-3.5 py-3 text-[14px] leading-relaxed text-ink-200">{children}</div>
    </div>
  );
}

function Btn({ children, onClick, tone = "plain", icon: Icon }) {
  const tones = {
    ok: "bg-emerald-500 text-ink-950 hover:bg-emerald-400", bad: "bg-red-500 text-white hover:bg-red-400",
    cond: "bg-saffron-500 text-ink-950 hover:bg-saffron-400", plain: "bg-ink-700 text-ink-100 hover:bg-ink-600",
    call: "bg-gemini text-ink-950 hover:brightness-110",
  };
  return (
    <motion.button whileTap={{ scale: 0.96 }} onClick={onClick}
      className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-[13px] font-bold transition ${tones[tone]}`}>
      {Icon && <Icon className="h-4 w-4" />} {children}
    </motion.button>
  );
}

const act = (path, body) => api(path, body).catch((e) => alert(`Couldn't do that: ${e.message}`));

export function HowIDecided({ trace }) {
  const [open, setOpen] = useState(false);
  if (!trace || !trace.steps.length) return null;
  const cites = trace.steps.filter((s) => s.cite).length;
  return (
    <div className="mt-2.5">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-[11.5px] font-semibold text-saffron-300 hover:text-saffron-200">
        <Sparkles className="h-3.5 w-3.5" /> How I decided · {trace.steps.length} steps{cites ? ` · ${cites} sources` : ""}
        <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden">
            <div className="mt-2 rounded-xl bg-ink-900/80 p-3 ring-1 ring-ink-700"><TraceSteps trace={trace} /></div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function RequestCard({ m, me, trace, onCall, mode }) {
  const r = m.data.request;
  const [showMinutes, setShowMinutes] = useState(false);
  const canDecide = r.status === "pending" && r.approvers.includes(me);
  let text = m.text;
  for (const n of r.stack_notes || []) text = text.replace(n, "");
  const isPart = r.kind === "part";
  return (
    <Shell tone={isPart ? "orange" : "saffron"} icon={isPart ? Wrench : Hand} glow={canDecide ? "glow-saffron" : ""}
      title={`${isPart ? "Part change" : "Approval needed"} · ${r.approver_names.join(", ")}`} right={<Pill status={r.status} />}>
      <div className="text-[13px] text-ink-400"><b className="text-ink-100">{r.requester_name}</b> · {r.summary}</div>
      <p className="mt-1.5">{text.replace(/\s+/g, " ").trim()}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {r.limit && (
          <span className="inline-flex items-center gap-1 rounded-md bg-saffron-500/10 px-2 py-0.5 font-mono text-[11px] text-saffron-300 ring-1 ring-saffron-500/25">
            <BookOpen className="h-3 w-3" /> Limit {r.limit.max_minutes} min · {r.limit_cite || r.limit.source}
          </span>
        )}
        {!r.limit && !isPart && (
          <span className="inline-flex items-center gap-1 rounded-md bg-yellow-500/10 px-2 py-0.5 text-[11px] text-yellow-300 ring-1 ring-yellow-500/25">
            <AlertTriangle className="h-3 w-3" /> No documented limit
          </span>
        )}
      </div>
      {(r.stack_notes || []).map((n) => (
        <div key={n} className="mt-2 flex gap-2 rounded-xl bg-orange-500/10 p-2.5 text-[12.5px] text-orange-200 ring-1 ring-orange-500/25">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" /> {n}
        </div>
      ))}
      {r.escalations?.length > 0 && (
        <div className="mt-2 text-[12px] font-semibold text-red-300">Escalated to level {r.level}</div>
      )}
      {r.decider_name && ["approved", "rejected", "active", "overrun", "done"].includes(r.status) && (
        <div className="mt-2 rounded-xl bg-emerald-500/10 px-2.5 py-1.5 text-[12.5px] text-emerald-300 ring-1 ring-emerald-500/25">
          Decision by {r.decider_name}{r.max_minutes ? ` · max ${r.max_minutes} min` : ""}{isPart && r.conditions ? ` · ${r.conditions}` : ""}
        </div>
      )}
      {canDecide && (
        <div className="mt-3 space-y-2">
          {mode === "gemini" && (
            <Btn tone="call" icon={PhoneCall} onClick={() => onCall(r.id)}>Talk to Sanjaya live</Btn>
          )}
          <div className="flex gap-2">
            <Btn tone="ok" icon={ThumbsUp} onClick={() => act(`/api/requests/${r.id}/decision`, { user: me, decision: "approve" })}>Approve</Btn>
            <Btn tone="cond" icon={Clock} onClick={() => {
              if (!isPart) return setShowMinutes(!showMinutes);
              const c = prompt("Conditions for approval:", "Supplier must provide an Ex-certified, T4, spark-resistant model meeting 12,000 m³/h");
              if (c) act(`/api/requests/${r.id}/decision`, { user: me, decision: "approve_with_conditions", conditions: c });
            }}>{isPart ? "Conditions" : "Limit"}</Btn>
            <Btn tone="bad" icon={ThumbsDown} onClick={() => act(`/api/requests/${r.id}/decision`, { user: me, decision: "reject" })}>Reject</Btn>
          </div>
          <AnimatePresence>
            {showMinutes && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                className="flex items-center gap-1.5 overflow-hidden text-[12px] text-ink-400">
                Max minutes:
                {[5, 10, 15, 20].map((n) => (
                  <button key={n} onClick={() => act(`/api/requests/${r.id}/decision`, { user: me, decision: "approve_with_conditions", max_minutes: n, conditions: `maximum ${n} minutes` })}
                    className="rounded-lg bg-ink-700 px-3 py-1.5 font-bold text-ink-100 hover:bg-ink-600">{n}</button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
          <TalkButton me={me} replyTo={m.id} label="Hold to answer by voice" />
        </div>
      )}
      <HowIDecided trace={trace} />
    </Shell>
  );
}

export function ReadbackCard({ m, me }) {
  const open = !m.data.resolved && m.data.decider === me;
  return (
    <Shell tone="violet" icon={Repeat} title="Read-back" right={m.data.resolved && <Pill status={m.data.resolved === "confirmed" ? "approved" : "pending"} />}>
      <p className="text-[15px] font-semibold text-ink-100">{m.text}</p>
      {open && (
        <div className="mt-3 space-y-2">
          <div className="flex gap-2">
            <Btn tone="ok" icon={Check} onClick={() => act(`/api/requests/${m.data.request_id}/confirm`, { user: me, yes: true })}>Correct</Btn>
            <Btn tone="plain" icon={X} onClick={() => act(`/api/requests/${m.data.request_id}/confirm`, { user: me, yes: false })}>Change</Btn>
          </div>
          <TalkButton me={me} replyTo={m.id} label="Hold to answer by voice" />
        </div>
      )}
    </Shell>
  );
}

export function RelayCard({ m, me, requests }) {
  const d = m.data;
  const req = requests.find((r) => r.id === d.request_id);
  return (
    <Shell tone={d.approved ? "green" : "red"} icon={d.approved ? ThumbsUp : ThumbsDown}
      title={`${d.approved ? "Approved" : "Rejected"} · for ${req?.requester_name || ""}`}>
      <p className="text-[15px] font-semibold text-ink-100">{m.text}</p>
      {d.english && <p className="mt-1 text-[12.5px] italic text-ink-400">{d.english}</p>}
      {d.approved && d.kind === "equipment" && req?.status === "approved" && d.requester === me && (
        <div className="mt-3 flex"><Btn tone="ok" icon={Play} onClick={() => act(`/api/requests/${d.request_id}/start`, { user: me })}>Starting now</Btn></div>
      )}
    </Shell>
  );
}

export function TimerCard({ m, me, now }) {
  const d = m.data;
  const running = d.status === "running" || d.status === "overrun";
  const total = (d.max_minutes || 1) * 60;
  const remaining = d.ends_at ? ((d.ends_at - now) / 1000) * d.speed : total;
  const over = running && remaining < 0;
  const warn = running && !over && remaining < 300;
  const frac = d.status === "done" ? 1 : Math.max(0, Math.min(1, 1 - remaining / total));
  const R = 54, C = 2 * Math.PI * R;
  const color = d.status === "done" ? "#22c55e" : over ? "#ef4444" : warn ? "#f97316" : "#fca311";
  const fmt = (s) => `${String(Math.floor(Math.abs(s) / 60)).padStart(2, "0")}:${String(Math.floor(Math.abs(s) % 60)).padStart(2, "0")}`;
  return (
    <Shell tone={over ? "red" : "sky"} icon={Timer} title={m.text} right={<Pill status={d.status === "running" ? "active" : d.status} />}
      glow={over ? "glow-critical" : ""}>
      <div className="flex items-center gap-4">
        <svg width="132" height="132" viewBox="0 0 132 132" className="shrink-0">
          <circle cx="66" cy="66" r={R} fill="none" stroke="#1c2542" strokeWidth="10" />
          <motion.circle cx="66" cy="66" r={R} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
            strokeDasharray={C} animate={{ strokeDashoffset: C * (1 - frac) }} transform="rotate(-90 66 66)" />
          <text x="66" y="64" textAnchor="middle" fontSize="26" fontWeight="800" fill={color} fontFamily="JetBrains Mono">
            {d.status === "done" ? "✓" : (over ? "+" : "") + fmt(remaining)}
          </text>
          <text x="66" y="84" textAnchor="middle" fontSize="10" fill="#7480a8">
            {d.status === "done" ? `after ${d.elapsed_minutes} min` : over ? "OVER LIMIT" : "remaining"}
          </text>
        </svg>
        <div className="text-[12.5px] text-ink-400">
          <div>Approved max <b className="text-ink-100">{d.max_minutes} min</b></div>
          {d.speed !== 1 && <div className="mt-1 font-mono text-[11px]">demo clock {d.speed}×</div>}
          {running && d.requester === me && (
            <div className="mt-3"><Btn tone="ok" icon={Check} onClick={() => act(`/api/requests/${d.request_id}/finish`, { user: me })}>Back on: done</Btn></div>
          )}
        </div>
      </div>
    </Shell>
  );
}

export function ReportCard({ m, trace }) {
  const r = m.data.report;
  const st = { pass: "text-emerald-400", fail: "text-red-400", missing: "text-orange-300", info: "text-ink-400" };
  return (
    <Shell tone={r.like_for_like ? "green" : "red"} icon={r.unreviewed ? Search : FileText}
      title={`${r.unreviewed ? "Unreviewed change check" : "Like-for-like check"} · ${r.equipment_name}`}
      right={<span className="text-[10px] font-bold uppercase">{r.like_for_like ? "like-for-like" : "not like-for-like"}</span>}>
      <p className="text-[12.5px] italic text-ink-400">{r.safety_role}</p>
      <div className="mt-2 overflow-x-auto scroll-thin">
        <table className="w-full min-w-[420px] text-[12px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-ink-400">
              <th className="py-1.5 pr-2">Requirement</th><th className="pr-2">{r.current_model}</th><th className="pr-2">{r.proposed_model}</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {r.rows.map((row) => (
              <tr key={row.key} className="border-t border-ink-700 align-top">
                <td className="py-1.5 pr-2 text-ink-200">{row.label}{row.source && <div className="font-mono text-[10px] text-ink-500">{row.source}</div>}</td>
                <td className="py-1.5 pr-2">{row.current}</td>
                <td className="py-1.5 pr-2">{row.proposed}</td>
                <td className={`py-1.5 font-semibold ${st[row.status]}`}>{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {r.plant_state.map((n) => (
        <div key={n} className="mt-2 rounded-xl bg-orange-500/10 p-2.5 text-[12.5px] text-orange-200 ring-1 ring-orange-500/25">{n}</div>
      ))}
      <p className="mt-2.5 font-semibold text-ink-100">{r.verdict}</p>
      <HowIDecided trace={trace} />
    </Shell>
  );
}

export function AlertCard({ m, trace }) {
  const level = m.data?.stack?.level?.name;
  const tone = level === "elevated" ? "orange" : "red";
  return (
    <Shell tone={tone} icon={AlertTriangle} glow={level === "critical" ? "glow-critical" : ""}
      title={level === "critical" ? "Risk stack: critical" : level === "elevated" ? "Risk stack: elevated" : "Sanjaya alert"}>
      <p>{m.text.replace(/^[⚠️⏰🚨🔍✅]\s*/u, "")}</p>
      <HowIDecided trace={trace} />
    </Shell>
  );
}

export function CallCard({ m }) {
  return (
    <Shell tone="sky" icon={Phone} title={m.text}>
      <div className="space-y-1.5">
        {m.data.transcript.map((t, i) => (
          <div key={i} className={`text-[13px] ${t.who === "sanjaya" ? "text-saffron-200" : "text-ink-200"}`}>
            <b>{t.who === "sanjaya" ? "Sanjaya" : "Approver"}:</b> {t.text}
          </div>
        ))}
      </div>
    </Shell>
  );
}

export function VoiceBody({ m, lang }) {
  const audio = (m.media || []).find((x) => x.kind === "voice");
  const [playing, setPlaying] = useState(false);
  const play = async () => {
    setPlaying(true);
    if (audio) {
      const a = new Audio(audio.url);
      a.onended = () => setPlaying(false);
      await a.play().catch(() => setPlaying(false));
    } else {
      await say(m.transcript || m.text, lang);
      setPlaying(false);
    }
  };
  return (
    <div>
      <div className="flex items-center gap-2.5">
        <button onClick={play} className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-saffron-500 text-ink-950">
          <Play className="h-4 w-4 fill-current" />
        </button>
        <div className="flex h-8 flex-1 items-center gap-[3px]">
          {Array.from({ length: 28 }).map((_, i) => (
            <motion.span key={i} className="w-[3px] rounded-full bg-ink-400"
              style={{ height: 6 + ((i * 37) % 19) }}
              animate={playing ? { scaleY: [1, 1.8, 0.6, 1] } : { scaleY: 1 }}
              transition={{ duration: 0.8, repeat: playing ? Infinity : 0, delay: i * 0.03 }} />
          ))}
        </div>
      </div>
      {m.transcript && <p className="mt-1.5 text-[13.5px] italic text-ink-200">“{m.transcript}”</p>}
    </div>
  );
}

export const hhmmStr = hhmm;
