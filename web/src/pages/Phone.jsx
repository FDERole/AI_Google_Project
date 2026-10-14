import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Clapperboard, Eye as EyeIcon, FileText, Paperclip, Send, Sparkles, Volume2 } from "lucide-react";
import { colorFor, hhmm, postMessage, useNow } from "../store";
import { onSpeaking } from "../speech";
import { Avatar, Eye, ModeBadge } from "../components/Brand";
import {
  AlertCard, CallCard, HowIDecided, ReadbackCard, RelayCard, ReportCard, RequestCard, TimerCard, VoiceBody,
} from "../components/Cards";
import TalkButton from "../components/TalkButton";
import DemoDrawer from "../components/DemoDrawer";
import LiveCall from "../components/LiveCall";

export default function Phone({ me, live, frame }) {
  const { users, messages, dashboard, traces, plant, clockOffset, connected } = live;
  const user = users[me];
  const now = useNow(clockOffset);
  const [demo, setDemo] = useState(false);
  const [call, setCall] = useState(null);
  const [speaking, setSpeaking] = useState(false);
  const scroller = useRef(null);
  const stick = useRef(true);

  useEffect(() => onSpeaking(setSpeaking), []);
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, messages]);

  const withColor = (id) => users[id] ? { ...users[id], color: colorFor(id) }
    : id === "sanjaya" ? { id, name: "Sanjaya", title: "Safety agent", color: colorFor(id) } : { id, name: id, color: colorFor(id) };
  const requests = dashboard?.requests || [];

  return (
    <div className={`relative flex h-full flex-col overflow-hidden bg-ink-950 ${frame ? "rounded-[2.4rem]" : ""}`}>
      <header className="z-10 flex items-center gap-3 border-b border-ink-800 bg-ink-900/90 px-3 py-2.5 backdrop-blur" style={{ paddingTop: frame ? 28 : undefined }}>
        <a href="#/" className="rounded-lg p-1 text-ink-400 hover:bg-ink-800"><ArrowLeft className="h-5 w-5" /></a>
        <Eye size={34} active={speaking} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-bold">{plant?.group_name}</div>
          <div className="truncate text-[11.5px] text-ink-400">
            {connected ? <span className="text-emerald-400">●</span> : <span className="text-red-400">●</span>} You: {user?.name} · {user?.title}
          </div>
        </div>
        <ModeBadge mode={dashboard?.mode} small />
        <button onClick={() => setDemo(true)} className="rounded-lg p-1.5 text-ink-300 hover:bg-ink-800" title="Demo script">
          <Clapperboard className="h-5 w-5" />
        </button>
      </header>

      <AnimatePresence>
        {speaking && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }}
            className="overflow-hidden bg-saffron-500 text-center text-[12px] font-bold text-ink-950">
            <div className="flex items-center justify-center gap-1.5 py-1"><Volume2 className="h-3.5 w-3.5" /> Sanjaya is speaking to you</div>
          </motion.div>
        )}
      </AnimatePresence>

      <main ref={scroller} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160; }}
        className="grid-bg flex-1 space-y-3 overflow-y-auto scroll-thin px-3 py-4">
        {messages.map((m) => (
          <Message key={m.id} m={m} me={me} author={withColor(m.author)} trace={traces[m.data?.trace_id]}
            requests={requests} now={now} mode={dashboard?.mode} onCall={setCall} />
        ))}
      </main>

      <Composer me={me} lang={user?.lang} />

      <AnimatePresence>{demo && <DemoDrawer dashboard={dashboard} onClose={() => setDemo(false)} />}</AnimatePresence>
      <AnimatePresence>{call && <LiveCall me={me} requestId={call} onClose={() => setCall(null)} />}</AnimatePresence>
    </div>
  );
}

function Message({ m, me, author, trace, requests, now, mode, onCall }) {
  const mine = m.author === me;
  const isSanjaya = m.author === "sanjaya";
  const card = {
    request_card: <RequestCard m={m} me={me} trace={trace} onCall={onCall} mode={mode} />,
    readback_card: <ReadbackCard m={m} me={me} />,
    relay_card: <RelayCard m={m} me={me} requests={requests} />,
    timer_card: <TimerCard m={m} me={me} now={now} />,
    report_card: <ReportCard m={m} trace={trace} />,
    alert: <AlertCard m={m} trace={trace} />,
    call_card: <CallCard m={m} />,
  }[m.type];

  return (
    <motion.div initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 300, damping: 26 }}
      className={`flex gap-2 ${mine ? "flex-row-reverse" : ""}`}>
      {!mine && <Avatar user={author} size={30} />}
      <div className={`flex min-w-0 flex-col ${card ? "w-full" : "max-w-[84%]"} ${mine ? "items-end" : "items-start"}`}>
        {!mine && (
          <div className="mb-1 flex items-center gap-1.5 px-1 text-[11.5px]">
            <span className="font-semibold" style={{ color: author.color }}>{author.name}</span>
            {author.title && <span className="text-ink-500">{author.title}</span>}
          </div>
        )}
        {card || <Bubble m={m} mine={mine} isSanjaya={isSanjaya} author={author} trace={trace} />}
        <span className="mt-1 px-1 text-[10px] text-ink-500">{hhmm(m.at)}</span>
      </div>
    </motion.div>
  );
}

function Bubble({ m, mine, isSanjaya, author, trace }) {
  const d = m.data || {};
  return (
    <div className={`rounded-2xl px-3.5 py-2.5 text-[14.5px] leading-relaxed shadow-sm ${mine ? "rounded-tr-md bg-saffron-500 text-ink-950" : isSanjaya ? "rounded-tl-md bg-ink-800 text-ink-100 ring-1 ring-saffron-500/30" : "rounded-tl-md bg-ink-800 text-ink-100 ring-1 ring-ink-700"}`}>
      {(m.media || []).map((x) => x.kind === "photo" ? (
        <img key={x.url} src={x.url} alt="" className="mb-2 max-h-64 w-full rounded-xl object-cover" />
      ) : x.kind === "document" ? (
        <a key={x.url} href={x.url} target="_blank" rel="noreferrer"
          className={`mb-1.5 mr-1.5 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] font-semibold ${mine ? "bg-ink-950/15" : "bg-ink-700"}`}>
          <FileText className="h-4 w-4" /> {x.name}
        </a>
      ) : null)}
      {m.type === "voice" && <VoiceBody m={m} lang={author.lang} />}
      {m.text && <p className="whitespace-pre-wrap break-words">{m.text}</p>}
      {(d.change || d.seen || d.request || m.mode === "gemini") && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {d.change && <Chip tone="change">Logged change · {d.change.summary}</Chip>}
          {d.seen && <Chip tone="seen"><EyeIcon className="h-3 w-3" /> {d.seen}</Chip>}
          {d.request && <Chip tone="req">Sent for approval</Chip>}
          {m.mode === "gemini" && !isSanjaya && <Chip tone="gemini"><Sparkles className="h-3 w-3" /> read by Gemini</Chip>}
        </div>
      )}
      {isSanjaya && <HowIDecided trace={trace} />}
    </div>
  );
}

function Chip({ tone, children }) {
  const t = {
    change: "bg-orange-500/15 text-orange-300 ring-orange-500/30", seen: "bg-ink-700 text-ink-200 ring-ink-600",
    req: "bg-saffron-500/15 text-saffron-300 ring-saffron-500/30", gemini: "bg-gemini/15 text-gemini ring-gemini/30",
  }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${t}`}>{children}</span>;
}

function Composer({ me, lang }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState([]);
  const send = async () => {
    if (!text.trim() && !files.length) return;
    const t = text, f = files;
    setText(""); setFiles([]);
    await postMessage({ user: me, text: t.trim() }, f).catch((e) => alert(e.message));
  };
  return (
    <footer className="border-t border-ink-800 bg-ink-900/95 px-3 py-2.5" style={{ paddingBottom: "max(10px, env(safe-area-inset-bottom))" }}>
      {files.length > 0 && <div className="mb-2 truncate text-[12px] text-ink-400">📎 {files.map((f) => f.name).join(", ")}</div>}
      <div className="flex items-center gap-2">
        <label className="grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-full text-ink-300 hover:bg-ink-800">
          <Paperclip className="h-5 w-5" />
          <input type="file" multiple hidden accept="image/*,application/pdf,audio/*" onChange={(e) => setFiles([...e.target.files])} />
        </label>
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Message, or ask “Sanjaya, …”"
          className="h-11 min-w-0 flex-1 rounded-full bg-ink-800 px-4 text-[15px] text-ink-100 placeholder:text-ink-500 outline-none ring-1 ring-ink-700 focus:ring-saffron-500/50" />
        {text.trim() || files.length ? (
          <motion.button whileTap={{ scale: 0.9 }} onClick={send} className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-saffron-500 text-ink-950">
            <Send className="h-5 w-5" />
          </motion.button>
        ) : (
          <TalkButton me={me} lang={lang} round />
        )}
      </div>
    </footer>
  );
}
