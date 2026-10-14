import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, ArrowLeft, BookOpen, Brain, Clapperboard, ClipboardList, FileSearch, GraduationCap, History, Layers,
  MonitorSmartphone, RotateCcw, ShieldCheck, Timer,
} from "lucide-react";
import { api, hhmm, LEVEL, useNow } from "../store";
import { Eye, ModeBadge } from "../components/Brand";
import SwissCheese from "../components/SwissCheese";
import FloorMap from "../components/FloorMap";
import { TraceCard } from "../components/Trace";
import DemoDrawer from "../components/DemoDrawer";

function Panel({ title, icon: Icon, right, children, className = "" }) {
  return (
    <section className={`glass flex flex-col rounded-2xl ${className}`}>
      <div className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-2">
        <h2 className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.12em] text-ink-300">
          {Icon && <Icon className="h-4 w-4 text-saffron-400" />} {title}
        </h2>
        {right}
      </div>
      <div className="flex-1 px-4 pb-4">{children}</div>
    </section>
  );
}

export default function Command({ live, compact = false }) {
  const { dashboard, traces, users, plant, clockOffset, connected } = live;
  const now = useNow(clockOffset);
  const [demo, setDemo] = useState(false);
  if (!dashboard) return null;

  const risk = dashboard.risk;
  const worst = risk.reduce((a, s) => (s.level.rank > a.level.rank ? s : a), risk[0]);
  const active = dashboard.changes.filter((c) => c.status === "active");
  const open = dashboard.requests.filter((r) => ["pending", "awaiting_readback", "approved", "active", "overrun"].includes(r.status));
  const timers = dashboard.requests.filter((r) => (r.status === "active" || r.status === "overrun") && r.ends_at);
  const traceList = Object.values(traces).sort((a, b) => b.started_at - a.started_at).slice(0, 12);
  const worstLvl = LEVEL[worst?.level.name || "normal"];

  return (
    <div className={`grid-bg relative flex h-full flex-col overflow-hidden ${compact ? "rounded-3xl ring-1 ring-ink-700" : ""}`}>
      <header className="flex items-center gap-3 border-b border-ink-800 bg-ink-950/70 px-5 py-3 backdrop-blur">
        {!compact && <a href="#/" className="rounded-lg p-1 text-ink-400 hover:bg-ink-800"><ArrowLeft className="h-5 w-5" /></a>}
        <Eye size={36} active={traceList[0]?.status === "thinking"} />
        <div className="min-w-0">
          <div className="text-[15px] font-extrabold tracking-tight">Sanjaya <span className="font-medium text-ink-400">· Command center</span></div>
          <div className="text-[11.5px] text-ink-400">{plant?.name} · {plant?.company}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold sm:inline-flex ${connected ? "text-emerald-300" : "text-red-300"}`}>
            <Activity className="h-3.5 w-3.5" /> {connected ? "Live" : "Reconnecting"}
          </span>
          <ModeBadge mode={dashboard.mode} />
          {!compact && (
            <>
              <a href="#/teach" className="hidden items-center gap-1.5 rounded-xl bg-ink-800 px-3 py-1.5 text-xs font-bold ring-1 ring-ink-700 hover:bg-ink-700 md:inline-flex">
                <GraduationCap className="h-4 w-4 text-saffron-400" /> Teach Sanjaya
              </a>
              <a href="#/stage" className="hidden items-center gap-1.5 rounded-xl bg-ink-800 px-3 py-1.5 text-xs font-bold ring-1 ring-ink-700 hover:bg-ink-700 md:inline-flex">
                <MonitorSmartphone className="h-4 w-4 text-saffron-400" /> Stage view
              </a>
            </>
          )}
          <button onClick={() => setDemo(true)} className="rounded-xl bg-saffron-500 p-2 text-ink-950 hover:bg-saffron-400" title="Demo script">
            <Clapperboard className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className={`grid min-h-0 flex-1 content-start items-start gap-4 overflow-y-auto scroll-thin p-4 ${compact ? "grid-cols-12" : "grid-cols-1 xl:grid-cols-12"}`}>
        {/* KPIs */}
        <div className="col-span-full grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Worst hazard" value={worstLvl.label} sub={worst?.level.rank ? worst.hazard : "All safeguards in place"} color={worstLvl.color} pulse={worst?.level.name === "critical"} />
          <Kpi label="Safeguards weakened" value={risk.reduce((a, s) => a + s.degraded.length, 0)} sub={`of ${risk.reduce((a, s) => a + s.total_barriers, 0)} across ${risk.length} hazards`} />
          <Kpi label="Active changes" value={active.length} sub={active[0] ? active[0].summary : "Nothing changed on the floor"} />
          <Kpi label="Open decisions" value={open.length} sub={timers.length ? `${timers.length} countdown running` : "No live timers"} />
        </div>

        <Panel title="Plant floor" icon={Layers} className={compact ? "col-span-7" : "xl:col-span-5"}>
          <FloorMap dashboard={dashboard} now={now} />
          {timers.map((t) => <LiveTimer key={t.id} req={t} now={now} speed={dashboard.speed} />)}
        </Panel>

        <Panel title="Risk stack · Swiss-cheese view" icon={ShieldCheck} className={compact ? "col-span-5" : "xl:col-span-4"}
          right={<span className="text-[10.5px] text-ink-500">holes line up = disaster</span>}>
          <div className="space-y-3">
            {risk.map((s) => <StackRow key={s.hazard_id} stack={s} compact={compact} />)}
          </div>
        </Panel>

        <Panel title="Sanjaya's mind" icon={Brain} className={`${compact ? "col-span-12" : "xl:col-span-3 xl:row-span-2"}`}
          right={<span className="text-[10.5px] text-ink-500">every step, every source</span>}>
          <div className={`space-y-3 overflow-y-auto scroll-thin pr-1 ${compact ? "grid max-h-[380px] grid-cols-2 items-start gap-3 space-y-0" : "max-h-[1040px]"}`}>
            <AnimatePresence initial={false}>
              {traceList.map((t) => <TraceCard key={t.id} trace={t} users={users} />)}
            </AnimatePresence>
            {!traceList.length && <Empty icon={Brain} text="Sanjaya's reasoning appears here, live, as people post." />}
          </div>
        </Panel>

        {!compact && (
          <>
            <Panel title="What changed, in order" icon={History} className="xl:col-span-5">
              <Timeline changes={dashboard.changes} />
            </Panel>
            <Panel title="Decisions" icon={ClipboardList} className="xl:col-span-4">
              <Requests requests={dashboard.requests} />
            </Panel>
            <Panel title="Audit trail" icon={FileSearch} className="xl:col-span-9"
              right={<a href="/api/audit" target="_blank" rel="noreferrer" className="text-[11px] font-semibold text-saffron-400 hover:underline">download JSON</a>}>
              <Audit audit={dashboard.audit} />
            </Panel>
          </>
        )}
      </div>

      <AnimatePresence>{demo && <DemoDrawer dashboard={dashboard} onClose={() => setDemo(false)} />}</AnimatePresence>
    </div>
  );
}

function Kpi({ label, value, sub, color, pulse }) {
  return (
    <motion.div layout className={`glass rounded-2xl px-4 py-3 ${pulse ? "glow-critical" : ""}`}>
      <div className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-ink-400">{label}</div>
      <div className="mt-1 text-2xl font-extrabold tracking-tight" style={{ color }}>{value}</div>
      <div className="mt-0.5 truncate text-[11.5px] text-ink-400">{sub}</div>
    </motion.div>
  );
}

function StackRow({ stack, compact }) {
  const lvl = LEVEL[stack.level.name];
  return (
    <motion.div layout className={`rounded-xl bg-ink-900/60 p-3 ring-1 ${stack.level.name === "critical" ? "ring-red-500/60 glow-critical" : stack.level.name === "elevated" ? "ring-orange-500/40" : "ring-ink-700"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-bold">{stack.hazard}</div>
          <div className="font-mono text-[10.5px] text-ink-500">{stack.source}</div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase ${lvl.bg} ${lvl.text}`}>
          {stack.degraded.length}/{stack.total_barriers} · {lvl.label}
        </span>
      </div>
      <SwissCheese stack={stack} compact={compact} />
      {stack.degraded.length > 0 && (
        <div className={`-mt-1 mb-1 text-center text-[11.5px] font-bold ${lvl.text}`}>
          {stack.total_barriers - stack.degraded.length === 0 ? "No safeguards left between the hazard and people"
            : `Only ${stack.total_barriers - stack.degraded.length} safeguard${stack.total_barriers - stack.degraded.length > 1 ? "s" : ""} left between the hazard and people`}
        </div>
      )}
      {!compact && stack.degraded.map((d) => (
        <div key={d.barrier_id} className="mt-1 text-[11.5px] text-ink-300">
          <span className={lvl.text}>✗ {d.barrier}</span> <span className="text-ink-500">← {d.changes.map((c) => c.summary).join("; ")}</span>
        </div>
      ))}
    </motion.div>
  );
}

function LiveTimer({ req, now, speed }) {
  const total = req.max_minutes * 60;
  const remaining = ((req.ends_at - now) / 1000) * speed;
  const over = remaining < 0;
  const fmt = (s) => `${String(Math.floor(Math.abs(s) / 60)).padStart(2, "0")}:${String(Math.floor(Math.abs(s) % 60)).padStart(2, "0")}`;
  return (
    <div className={`mt-3 flex items-center justify-between rounded-xl px-3.5 py-2.5 ring-1 ${over ? "bg-red-500/15 ring-red-500/50" : "bg-saffron-500/10 ring-saffron-500/30"}`}>
      <div className="flex items-center gap-2.5">
        <Timer className={`h-5 w-5 ${over ? "text-red-400" : "text-saffron-400"}`} />
        <div>
          <div className="text-[13px] font-bold">{req.summary}</div>
          <div className="text-[11px] text-ink-400">approved by {req.decider_name} · max {req.max_minutes} min</div>
        </div>
      </div>
      <div className={`font-mono text-2xl font-extrabold ${over ? "text-red-400" : "text-saffron-300"}`}>
        {over ? "+" : ""}{fmt(remaining)}
      </div>
      <div className="sr-only">{Math.round((1 - remaining / total) * 100)}%</div>
    </div>
  );
}

function Timeline({ changes }) {
  if (!changes.length) return <Empty icon={History} text="No changes logged yet." />;
  const kind = { routine: "bg-orange-500/15 text-orange-300", unreviewed: "bg-red-500/15 text-red-300", approved: "bg-sky-500/15 text-sky-300" };
  return (
    <ol className="relative max-h-80 space-y-2.5 overflow-y-auto scroll-thin pl-4 before:absolute before:left-1 before:top-1 before:bottom-1 before:w-px before:bg-ink-600">
      {changes.map((c) => (
        <motion.li layout key={c.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: c.status === "active" ? 1 : 0.5, x: 0 }} className="relative">
          <span className={`absolute -left-[15px] top-1.5 h-2.5 w-2.5 rounded-full ${c.status === "active" ? "bg-saffron-400" : "bg-ink-500"}`} />
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold">{c.summary}</div>
              <div className="text-[11px] text-ink-400">{c.by_name} · {hhmm(c.at)} · {c.status}</div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${kind[c.kind] || "bg-ink-700"}`}>{c.kind}</span>
              {c.status === "active" && c.kind !== "approved" && (
                <button onClick={() => api(`/api/changes/${c.id}/close`, { user: "meena" })} title="Mark restored"
                  className="rounded-lg bg-emerald-500/15 p-1 text-emerald-300 hover:bg-emerald-500/25"><RotateCcw className="h-3.5 w-3.5" /></button>
              )}
            </div>
          </div>
        </motion.li>
      ))}
    </ol>
  );
}

function Requests({ requests }) {
  if (!requests.length) return <Empty icon={ClipboardList} text="No requests yet." />;
  const tone = { pending: "text-saffron-300", awaiting_readback: "text-violet-300", approved: "text-emerald-300", rejected: "text-red-300", active: "text-sky-300", overrun: "text-red-300", done: "text-ink-400" };
  return (
    <div className="max-h-80 space-y-2 overflow-y-auto scroll-thin">
      {requests.map((r) => (
        <div key={r.id} className="rounded-xl bg-ink-900/60 px-3 py-2.5 ring-1 ring-ink-700">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[13px] font-semibold">{r.summary}</span>
            <span className={`text-[10.5px] font-extrabold uppercase ${tone[r.status]}`}>{r.status.replace("_", " ")}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-ink-400">
            {r.requester_name} → {r.approver_names.join(", ")}{r.decider_name ? ` · decided by ${r.decider_name}` : ""}{r.max_minutes ? ` · max ${r.max_minutes} min` : ""}
          </div>
          {r.limit_cite && <div className="mt-1 inline-flex items-center gap-1 font-mono text-[10.5px] text-saffron-300"><BookOpen className="h-3 w-3" />{r.limit_cite}</div>}
        </div>
      ))}
    </div>
  );
}

function Audit({ audit }) {
  return (
    <div className="max-h-64 overflow-y-auto scroll-thin rounded-xl bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed ring-1 ring-ink-800">
      {audit.map((a, i) => {
        const { at, event, ...rest } = a;
        const detail = Object.entries(rest).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length))
          .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ");
        return (
          <div key={i} className="truncate"><span className="text-ink-500">{hhmm(at)}</span> <span className="text-saffron-300">{event}</span> <span className="text-ink-300">{detail}</span></div>
        );
      })}
    </div>
  );
}

function Empty({ icon: Icon, text }) {
  return <div className="flex flex-col items-center gap-2 py-8 text-center text-[12.5px] text-ink-500"><Icon className="h-6 w-6" />{text}</div>;
}
