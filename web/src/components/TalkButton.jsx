import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { Mic } from "lucide-react";
import { postMessage } from "../store";
import { toWav16k } from "../wav";

/*
 * Hold to talk. Records audio (sent to Gemini for transcription when it's on) and, where the browser
 * supports it, also transcribes on the phone so the offline mode still understands voice.
 */
export default function TalkButton({ me, lang = "en-IN", replyTo, label, round = false }) {
  const [rec, setRec] = useState(false);
  const [level, setLevel] = useState(0);
  const s = useRef(null);

  const start = async (e) => {
    e.preventDefault();
    if (s.current) return;
    const session = { chunks: [], transcript: "", stopped: false };
    s.current = session;
    setRec(true);
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      try {
        const r = new SR();
        r.lang = lang; r.continuous = true; r.interimResults = false;
        r.onresult = (ev) => {
          for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) session.transcript += ev.results[i][0].transcript + " ";
        };
        session.recEnded = new Promise((res) => { r.onend = res; r.onerror = res; });
        r.start();
        session.recog = r;
      } catch { /* not available */ }
    }
    if (navigator.mediaDevices?.getUserMedia && window.MediaRecorder) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mr = new MediaRecorder(stream);
        mr.ondataavailable = (ev) => ev.data.size && session.chunks.push(ev.data);
        session.mrStopped = new Promise((res) => { mr.onstop = res; });
        mr.start();
        session.mr = mr;
        session.stream = stream;
        const ctx = new AudioContext();
        const an = ctx.createAnalyser();
        an.fftSize = 256;
        ctx.createMediaStreamSource(stream).connect(an);
        const buf = new Uint8Array(an.frequencyBinCount);
        const tick = () => {
          if (session.done) return ctx.close();
          an.getByteFrequencyData(buf);
          setLevel(buf.reduce((a, b) => a + b, 0) / buf.length / 128);
          requestAnimationFrame(tick);
        };
        tick();
        if (session.stopped) stop();
      } catch { /* mic denied */ }
    }
    if (!session.recog && !session.mr) {
      s.current = null;
      setRec(false);
      const typed = prompt("Voice isn't available here (phones need HTTPS for the mic). Type it instead:");
      if (typed) postMessage({ user: me, text: typed, reply_to: replyTo });
    }
  };

  const stop = async () => {
    const session = s.current;
    if (!session) return;
    session.stopped = true;
    if (session.mr === undefined && session.recog === undefined) return; // still starting
    s.current = null;
    session.done = true;
    setRec(false);
    setLevel(0);
    try { session.recog?.stop(); } catch { /* ended */ }
    if (session.mr && session.mr.state !== "inactive") session.mr.stop();
    session.stream?.getTracks().forEach((t) => t.stop());
    await Promise.race([Promise.all([session.recEnded, session.mrStopped].filter(Boolean)), new Promise((r) => setTimeout(r, 1500))]);
    const transcript = session.transcript.trim();
    const blob = session.chunks.length ? new Blob(session.chunks, { type: session.mr?.mimeType || "audio/webm" }) : null;
    if ((!blob || blob.size < 800) && !transcript) return;
    let files = [];
    if (blob) {
      try {
        files = [await toWav16k(blob)];
      } catch {
        files = [new File([blob], "voice.webm", { type: blob.type })];  // let the server try the original
      }
    }
    postMessage({ user: me, transcript, reply_to: replyTo, as_voice: files.length ? undefined : "true" }, files)
      .catch((e) => alert(e.message));
  };

  const handlers = {
    onPointerDown: start, onPointerUp: stop, onPointerLeave: stop, onPointerCancel: stop,
    onContextMenu: (e) => e.preventDefault(),
  };

  if (round) {
    return (
      <motion.button {...handlers} whileTap={{ scale: 1.15 }} aria-label="Hold to talk"
        className={`no-select relative grid h-12 w-12 shrink-0 place-items-center rounded-full touch-none ${rec ? "bg-red-500" : "bg-saffron-500"} text-ink-950`}>
        {rec && <span className="absolute inset-0 rounded-full bg-red-500 animate-pulse-ring" />}
        <Mic className="relative h-5 w-5" />
      </motion.button>
    );
  }
  return (
    <button {...handlers}
      className={`no-select relative flex w-full touch-none items-center justify-center gap-2 overflow-hidden rounded-xl px-3 py-2.5 text-[13px] font-bold ${rec ? "bg-red-500 text-white" : "bg-ink-700 text-ink-100"}`}>
      {rec && <span className="absolute inset-y-0 left-0 bg-red-400/50 transition-all" style={{ width: `${Math.min(100, level * 100)}%` }} />}
      <Mic className="relative h-4 w-4" /> <span className="relative">{rec ? "Listening… release to send" : label}</span>
    </button>
  );
}
