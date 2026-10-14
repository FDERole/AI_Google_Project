import { motion } from "framer-motion";
import { Clapperboard, RotateCcw, X } from "lucide-react";
import { api, postMessage } from "../store";

// Each step posts as that person, so one presenter can drive the whole story from one screen.
export const DEMO = [
  { act: "1 · Watch: small changes stack up" },
  { label: "Arjun 🎤 batch raised to 480 kg", user: "arjun", as_voice: true, transcript: "आज का बैच 400 से बढ़ाकर 480 किलो कर दिया है" },
  { label: "Suresh 📷 muted alarm panel", user: "suresh", text: "Alarm baar baar baj raha tha, mute kar diya", demo: "demo:alarm_panel_muted.png" },
  { label: "Suresh: trainee on the night shift", user: "suresh", text: "Night shift mein naya trainee Raju add kiya hai, aaj uska pehla din hai" },
  { act: "2 · Approve: the live voice loop" },
  { label: "Arjun asks to shut down Boiler B-1", user: "arjun", text: "Boiler B-1 band karna hai, maintenance ke liye. Kya kar sakte hain?" },
  { label: "Ravi 🎤 “Yes, but 15 minutes max”", user: "ravi", as_voice: true, transcript: "Yes, but 15 minutes max" },
  { label: "Ravi confirms the read-back", user: "ravi", text: "Yes, correct" },
  { label: "Arjun: boiler is off now", user: "arjun", text: "Boiler band kar diya" },
  { label: "Arjun: boiler back on", user: "arjun", text: "Boiler wapas chalu kar diya" },
  { label: "Nobody answers → escalate", special: "skip" },
  { act: "3 · Evaluate: a cheaper replacement part" },
  { label: "Suresh: gas detector into maintenance", user: "suresh", text: "Gas detector GD-07 calibration ke liye maintenance mein hai" },
  { label: "Priya 📄 evaluate Supplier B's fan", user: "priya", text: "We're planning to switch to Supplier B for the solvent-room fan. Go through the attached docs and evaluate the risk.", demo: "datasheet:kestrel_kx120.pdf,datasheet:brightline_bf105.pdf" },
  { label: "Arjun 📷 fan swapped without review", user: "arjun", text: "Solvent room ka fan badal diya", demo: "demo:fan_nameplate_bf105.png" },
  { act: "4 · Ask: anyone can question Sanjaya" },
  { label: "Arjun: “Sanjaya, boiler kitni der band?”", user: "arjun", text: "Sanjaya, boiler kitni der band kar sakte hain?" },
  { label: "Ravi: “Sanjaya, what's riskiest now?”", user: "ravi", text: "Sanjaya, what's the riskiest thing right now?" },
];

export async function runStep(step, dashboard) {
  if (step.special === "skip") {
    const pending = (dashboard?.requests || []).find((r) => r.status === "pending");
    if (pending) await api(`/api/requests/${pending.id}/skip-wait`);
    return;
  }
  await postMessage({ user: step.user, text: step.text, transcript: step.transcript, as_voice: step.as_voice ? "true" : undefined, demo: step.demo });
}

export default function DemoDrawer({ dashboard, onClose }) {
  return (
    <motion.aside initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", damping: 26, stiffness: 260 }}
      className="absolute inset-y-0 right-0 z-50 flex w-[min(380px,92%)] flex-col bg-ink-900/95 shadow-2xl ring-1 ring-ink-700 backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <span className="flex items-center gap-2 font-bold"><Clapperboard className="h-4 w-4 text-saffron-400" /> Demo script</span>
        <button onClick={onClose} className="rounded-lg p-1 hover:bg-ink-700"><X className="h-5 w-5" /></button>
      </div>
      <div className="flex-1 space-y-1.5 overflow-y-auto scroll-thin p-3">
        {DEMO.map((s, i) => s.act ? (
          <div key={i} className="px-1 pt-3 text-[11px] font-bold uppercase tracking-wider text-ink-400">{s.act}</div>
        ) : (
          <motion.button key={i} whileTap={{ scale: 0.98 }} onClick={() => runStep(s, dashboard).catch((e) => alert(e.message))}
            className="w-full rounded-xl bg-ink-800 px-3 py-2.5 text-left text-[13px] font-semibold text-ink-100 ring-1 ring-ink-700 hover:bg-ink-700 hover:ring-saffron-500/40">
            {s.label}
          </motion.button>
        ))}
      </div>
      <div className="space-y-3 border-t border-ink-700 p-4 text-[13px]">
        <label className="flex items-center justify-between gap-2">
          Clock speed
          <select value={dashboard?.speed || 1} onChange={(e) => api("/api/demo/settings", { speed: +e.target.value })}
            className="rounded-lg bg-ink-800 px-2 py-1.5 ring-1 ring-ink-600">
            <option value="1">1× real time</option><option value="10">10×</option>
            <option value="20">20× (15 min ≈ 45 s)</option><option value="60">60×</option>
          </select>
        </label>
        <label className="flex items-center justify-between gap-2">
          Force offline mode
          <input type="checkbox" defaultChecked={false} onChange={(e) => api("/api/demo/settings", { offline: e.target.checked })} />
        </label>
        <button onClick={() => confirm("Reset the demo for everyone?") && api("/api/demo/reset")}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-red-500/15 py-2.5 font-bold text-red-300 ring-1 ring-red-500/30 hover:bg-red-500/25">
          <RotateCcw className="h-4 w-4" /> Reset demo
        </button>
      </div>
    </motion.aside>
  );
}
