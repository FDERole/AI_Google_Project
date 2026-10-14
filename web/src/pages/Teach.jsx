import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, BookOpen, CheckCircle2, FileText, Sparkles, Upload, UserCheck } from "lucide-react";
import { api } from "../store";
import { Eye, ModeBadge } from "../components/Brand";
import { TraceCard } from "../components/Trace";

/*
 * Onboarding: Sanjaya reads a plant's HAZOP and SOPs and drafts the risk model it will run on.
 * The safety officer reviews every hazard, safeguard and limit (each cited to its page) and approves.
 */
export default function Teach({ live }) {
  const { traces, users, dashboard } = live;
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null);
  const [approved, setApproved] = useState(false);
  const [startedAt, setStartedAt] = useState(0);

  const trace = Object.values(traces).filter((t) => t.title === "Teaching Sanjaya the plant" && t.started_at >= startedAt)
    .sort((a, b) => b.started_at - a.started_at)[0];

  const run = async (sample) => {
    setBusy(true); setDraft(null); setApproved(false); setStartedAt(Date.now() + (live.clockOffset || 0) - 2000);
    const fd = new FormData();
    fd.append("user", "meena");
    if (sample) fd.append("sample", "true");
    for (const f of files) fd.append("files", f);
    try {
      const r = await fetch("/api/onboarding/extract", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      setDraft(await r.json());
    } catch (e) { alert(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="grid-bg h-full overflow-y-auto scroll-thin">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-ink-800 bg-ink-950/80 px-5 py-3 backdrop-blur">
        <a href="#/command" className="rounded-lg p-1 text-ink-400 hover:bg-ink-800"><ArrowLeft className="h-5 w-5" /></a>
        <Eye size={34} active={busy} />
        <div>
          <div className="text-[15px] font-extrabold">Teach Sanjaya your plant</div>
          <div className="text-[11.5px] text-ink-400">From HAZOP and SOP documents to a reviewed risk model</div>
        </div>
        <div className="ml-auto"><ModeBadge mode={dashboard?.mode} gemini={dashboard?.gemini} /></div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-5 p-5 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-5">
          <div className="glass rounded-2xl p-5">
            <h3 className="font-bold">1 · Give Sanjaya the documents</h3>
            <p className="mt-1 text-[13px] text-ink-400">HAZOP report, operating SOPs, validation reports, area classification. Scanned PDFs work too.</p>
            <label className="mt-4 flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-ink-600 px-4 py-8 text-center hover:border-saffron-500/60">
              <Upload className="h-7 w-7 text-saffron-400" />
              <span className="text-[13.5px] font-semibold">{files.length ? files.map((f) => f.name).join(", ") : "Drop PDFs or tap to choose"}</span>
              <input type="file" accept="application/pdf" multiple hidden onChange={(e) => setFiles([...e.target.files])} />
            </label>
            <div className="mt-3 flex gap-2">
              <button disabled={busy || !files.length} onClick={() => run(false)}
                className="flex-1 rounded-xl bg-saffron-500 py-2.5 text-[13px] font-bold text-ink-950 disabled:opacity-40">Read my documents</button>
              <button disabled={busy} onClick={() => run(true)}
                className="flex-1 rounded-xl bg-ink-700 py-2.5 text-[13px] font-bold ring-1 ring-ink-600 hover:bg-ink-600 disabled:opacity-40">Use Plant X samples</button>
            </div>
            <SampleDocs />
          </div>
          {trace && <TraceCard trace={trace} users={users} />}
        </div>

        <div className="lg:col-span-7">
          <AnimatePresence mode="wait">
            {!draft ? (
              <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="glass grid h-full min-h-[420px] place-items-center rounded-2xl p-8 text-center">
                <div>
                  <Eye size={72} active={busy} />
                  <p className={`mt-4 text-[15px] font-semibold ${busy ? "thinking-text" : "text-ink-300"}`}>
                    {busy ? "Reading the documents and drafting the risk model…" : "The drafted risk model appears here for review."}
                  </p>
                  <p className="mt-1 text-[12.5px] text-ink-500">Every hazard, safeguard and limit will be cited to its page. Nothing is used until a safety officer approves it.</p>
                </div>
              </motion.div>
            ) : (
              <motion.div key="draft" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                <div className="glass flex flex-wrap items-center justify-between gap-3 rounded-2xl p-4">
                  <div>
                    <h3 className="font-bold">2 · Review the draft</h3>
                    <p className="text-[12.5px] text-ink-400">
                      {draft.hazards.length} hazards · {draft.hazards.reduce((a, h) => a + h.barriers.length, 0)} safeguards · {draft.limits.length} limits · from {draft.documents.length} documents
                      {draft.mode !== "gemini" && " · offline: pre-computed extraction"}
                    </p>
                  </div>
                  {approved ? (
                    <span className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-500/15 px-3 py-2 text-[13px] font-bold text-emerald-300"><CheckCircle2 className="h-4 w-4" /> Approved by Meena</span>
                  ) : (
                    <button onClick={() => api("/api/onboarding/approve", { user: "meena" }).then(() => setApproved(true)).catch((e) => alert(e.message))}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-bold text-ink-950 hover:bg-emerald-400">
                      <UserCheck className="h-4 w-4" /> Approve as Meena (Safety Officer)
                    </button>
                  )}
                </div>

                {draft.hazards.map((h, i) => (
                  <motion.div key={h.name} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}
                    className="glass rounded-2xl p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[15px] font-bold">{h.name}</div>
                        <div className="text-[12.5px] text-ink-400">{h.area} · {h.consequence}</div>
                      </div>
                      <Cite src={h.source} />
                    </div>
                    <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                      {h.barriers.map((b) => (
                        <div key={b.name} className="flex items-start gap-2 rounded-lg bg-ink-900/60 px-2.5 py-2 text-[12.5px] ring-1 ring-ink-700">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                          <span>{b.name} <span className="font-mono text-[10px] text-ink-500">{b.tag}</span></span>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                ))}

                <div className="glass rounded-2xl p-4">
                  <div className="mb-2 text-[13px] font-bold">Documented limits</div>
                  {draft.limits.map((l) => (
                    <div key={l.equipment + l.action} className="flex items-start justify-between gap-3 border-t border-ink-700 py-2 first:border-0">
                      <div className="text-[13px]">
                        <b>{l.equipment}</b> {l.action}: <span className="font-mono text-saffron-300">{l.value} {l.unit}</span>
                        {l.condition && <span className="text-ink-400"> {l.condition}</span>}
                        <div className="text-[12px] text-ink-400">{l.consequence}</div>
                      </div>
                      <Cite src={l.source} />
                    </div>
                  ))}
                </div>

                <div className="rounded-2xl bg-yellow-500/10 p-4 ring-1 ring-yellow-500/25">
                  <div className="mb-2 flex items-center gap-2 text-[13px] font-bold text-yellow-300"><AlertTriangle className="h-4 w-4" /> Gaps for the safety officer</div>
                  <ul className="space-y-1.5 text-[13px] text-yellow-100/90">{draft.gaps.map((g) => <li key={g}>• {g}</li>)}</ul>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function Cite({ src }) {
  if (!src) return null;
  return (
    <a href={`/media/docs/${src.doc}.pdf${src.page ? `#page=${src.page}` : ""}`} target="_blank" rel="noreferrer"
      className="inline-flex shrink-0 items-center gap-1 rounded-md bg-saffron-500/10 px-2 py-1 font-mono text-[10.5px] text-saffron-300 ring-1 ring-saffron-500/25 hover:bg-saffron-500/20">
      <BookOpen className="h-3 w-3" /> {src.doc} {src.section}{src.page ? ` · p.${src.page}` : ""}
    </a>
  );
}

function SampleDocs() {
  const docs = ["HZ-2024", "SOP-R201-07", "PV-SD1-2024", "AC-SR1", "SOP-SD1-03", "SOP-HR-05"];
  return (
    <div className="mt-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-ink-400"><Sparkles className="h-3.5 w-3.5" /> Plant X sample documents</div>
      <div className="flex flex-wrap gap-1.5">
        {docs.map((d) => (
          <a key={d} href={`/media/docs/${d}.pdf`} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-lg bg-ink-800 px-2 py-1 text-[11.5px] font-semibold ring-1 ring-ink-700 hover:bg-ink-700">
            <FileText className="h-3.5 w-3.5 text-ink-400" /> {d}
          </a>
        ))}
      </div>
    </div>
  );
}
