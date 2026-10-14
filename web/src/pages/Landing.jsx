import { motion } from "framer-motion";
import { ArrowRight, Brain, GraduationCap, Layers, MonitorSmartphone, PhoneCall, ShieldCheck } from "lucide-react";
import { colorFor } from "../store";
import { unlockAudio } from "../speech";
import { Avatar, Eye, ModeBadge } from "../components/Brand";

export default function Landing({ live }) {
  const { users, plant, dashboard } = live;
  const people = Object.values(users);
  const go = (hash) => { unlockAudio(); location.hash = hash; };
  return (
    <div className="grid-bg h-full overflow-y-auto scroll-thin">
      <div className="mx-auto max-w-6xl px-5 py-10 md:py-16">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3"><Eye size={40} /><span className="text-lg font-extrabold tracking-tight">Sanjaya</span></div>
          <ModeBadge mode={dashboard?.mode} gemini={dashboard?.gemini} />
        </div>

        <div className="mt-12 grid items-center gap-10 md:grid-cols-2">
          <div>
            <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              className="text-4xl font-extrabold leading-[1.05] tracking-tight md:text-6xl">
              Every disaster is a <span className="text-saffron-400">stack of small changes</span> that each looked fine.
            </motion.h1>
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}
              className="mt-5 max-w-lg text-[16px] leading-relaxed text-ink-300">
              Sanjaya watches every message, photo and voice note on the plant floor, judges every change against the
              plant's own HAZOP and SOPs, asks the right person for a decision by voice, and watches that decision until
              it's safely done.
            </motion.p>
            <div className="mt-7 flex flex-wrap gap-3">
              <button onClick={() => go("#/command")}
                className="inline-flex items-center gap-2 rounded-xl bg-saffron-500 px-5 py-3 font-bold text-ink-950 hover:bg-saffron-400">
                Open command center <ArrowRight className="h-4 w-4" />
              </button>
              <button onClick={() => go("#/stage")}
                className="inline-flex items-center gap-2 rounded-xl bg-ink-800 px-5 py-3 font-bold ring-1 ring-ink-600 hover:bg-ink-700">
                <MonitorSmartphone className="h-4 w-4 text-saffron-400" /> Stage view
              </button>
              <button onClick={() => go("#/teach")}
                className="inline-flex items-center gap-2 rounded-xl bg-ink-800 px-5 py-3 font-bold ring-1 ring-ink-600 hover:bg-ink-700">
                <GraduationCap className="h-4 w-4 text-saffron-400" /> Teach Sanjaya
              </button>
            </div>
          </div>

          <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.1 }} className="glass rounded-3xl p-5">
            <div className="mb-3 text-[12px] font-bold uppercase tracking-[0.12em] text-ink-400">Join {plant?.group_name} as</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {people.map((u) => (
                <motion.button key={u.id} whileHover={{ y: -2 }} whileTap={{ scale: 0.98 }} onClick={() => go(`#/phone/${u.id}`)}
                  className="flex items-center gap-3 rounded-2xl bg-ink-900/70 p-3 text-left ring-1 ring-ink-700 hover:ring-saffron-500/50">
                  <Avatar user={{ ...u, color: colorFor(u.id) }} size={40} />
                  <div className="min-w-0">
                    <div className="font-bold">{u.name}</div>
                    <div className="truncate text-[12px] text-ink-400">{u.title}{u.approver_level ? ` · approver L${u.approver_level}` : ""}</div>
                  </div>
                </motion.button>
              ))}
            </div>
            <p className="mt-3 text-[11.5px] text-ink-500">Open different people on different phones. Tap once so the phone is allowed to speak.</p>
          </motion.div>
        </div>

        <div className="mt-16 grid gap-4 md:grid-cols-4">
          {[
            [Layers, "Watch", "Reads chat, photos and Hindi voice notes. Judges each hazard against all active changes together."],
            [PhoneCall, "Approve", "Spoken evaluations, live voice decisions, read-back, countdowns and escalation."],
            [ShieldCheck, "Evaluate", "Like-for-like checks of replacement parts from datasheets and nameplate photos."],
            [Brain, "Explain", "Every step and every source is visible. Numbers come only from the plant's documents."],
          ].map(([Icon, t, d]) => (
            <div key={t} className="glass rounded-2xl p-4">
              <Icon className="h-5 w-5 text-saffron-400" />
              <div className="mt-2 font-bold">{t}</div>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-400">{d}</p>
            </div>
          ))}
        </div>
        <p className="mt-10 text-center text-[11.5px] text-ink-500">AI Builder Camp 2026 · Manufacturing track · All plant data, people and documents are fictional.</p>
      </div>
    </div>
  );
}
