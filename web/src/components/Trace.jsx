import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, BellRing, BookOpen, Brain, CheckCircle2, Eye, FileText, FolderOpen, Gavel, Layers, Mic, PenLine,
  Phone, Play, Repeat, Route, Scale, Send, ShieldCheck, Sparkles, Volume2, Wrench,
} from "lucide-react";
import { LEVEL } from "../store";

const ICONS = {
  mic: Mic, eye: Eye, brain: Brain, book: BookOpen, pen: PenLine, layers: Layers, bell: BellRing, alert: AlertTriangle,
  route: Route, speaker: Volume2, gavel: Gavel, repeat: Repeat, send: Send, play: Play, check: CheckCircle2,
  file: FileText, folder: FolderOpen, shield: ShieldCheck, scale: Scale, tool: Wrench, phone: Phone,
};

export function Step({ step, i }) {
  const Icon = ICONS[step.icon] || Sparkles;
  const lvl = step.level ? LEVEL[step.level] : null;
  return (
    <motion.li initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i * 0.05, 0.3) }}
      className="relative flex gap-2.5 pb-3 last:pb-0">
      <span className={`relative z-10 mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full ring-1 ${lvl ? `${lvl.bg} ${lvl.ring}` : "bg-ink-800 ring-ink-600"}`}>
        <Icon className={`h-3.5 w-3.5 ${lvl ? lvl.text : "text-saffron-400"}`} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-[13px] font-semibold text-ink-100">{step.label}</span>
          {step.mode === "gemini" && (
            <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-gemini">
              <Sparkles className="h-3 w-3" /> Gemini
            </span>
          )}
        </div>
        {step.detail && <p className="mt-0.5 text-[12px] leading-snug text-ink-300 break-words">{step.detail}</p>}
        {step.cite && (
          <span className="mt-1 inline-flex items-center gap-1 rounded-md bg-saffron-500/10 px-1.5 py-0.5 font-mono text-[10.5px] text-saffron-300 ring-1 ring-saffron-500/25">
            <BookOpen className="h-3 w-3" /> {step.cite}
          </span>
        )}
      </div>
    </motion.li>
  );
}

export function TraceSteps({ trace }) {
  return (
    <ol className="relative before:absolute before:left-3 before:top-2 before:bottom-2 before:w-px before:bg-ink-600">
      {trace.steps.map((s, i) => <Step key={i} step={s} i={i} />)}
    </ol>
  );
}

export function TraceCard({ trace, users }) {
  const thinking = trace.status === "thinking";
  return (
    <motion.div layout initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
      className={`glass rounded-2xl p-3.5 ${thinking ? "glow-saffron" : ""}`}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-ink-100">{trace.title}</div>
          {trace.actor && users?.[trace.actor] && (
            <div className="text-[11px] text-ink-400">{users[trace.actor].title}</div>
          )}
        </div>
        {thinking ? (
          <span className="thinking-text text-xs font-semibold">thinking…</span>
        ) : (
          <span className="font-mono text-[10px] text-ink-400">{trace.steps.length} steps · {trace.ms ?? 0} ms</span>
        )}
      </div>
      <TraceSteps trace={trace} />
      <AnimatePresence>
        {trace.outcome && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="mt-3 rounded-lg bg-ink-900/70 px-2.5 py-1.5 text-[12px] font-semibold text-saffron-300 ring-1 ring-ink-700">
            → {trace.outcome}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
