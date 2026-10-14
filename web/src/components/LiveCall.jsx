import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { PhoneOff, Sparkles } from "lucide-react";
import { Eye } from "./Brand";

/*
 * Live voice call with Sanjaya (Gemini Live API through the server).
 * Mic audio is downsampled to 16 kHz PCM16 in an AudioWorklet and streamed; Sanjaya's 24 kHz PCM16
 * voice is scheduled gap-free on an AudioContext. Barge-in: when the server says "interrupted",
 * queued audio is dropped so the approver can cut in.
 */
const WORKLET = `
class Down extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.ratio = sampleRate / 16000; this.acc = 0; }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += 1;
      if (this.acc >= this.ratio) { this.acc -= this.ratio; const s = Math.max(-1, Math.min(1, ch[i])); this.buf.push(s < 0 ? s * 0x8000 : s * 0x7fff); }
    }
    if (this.buf.length >= 1600) { this.port.postMessage(new Int16Array(this.buf).buffer, []); this.buf = []; }
    return true;
  }
}
registerProcessor("down16k", Down);`;

export default function LiveCall({ me, requestId, onClose }) {
  const [status, setStatus] = useState("connecting");
  const [lines, setLines] = useState([]);
  const [level, setLevel] = useState(0);
  const [reqState, setReqState] = useState(null);
  const refs = useRef({});

  useEffect(() => {
    const r = refs.current;
    let cancelled = false;
    (async () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/live?user=${me}&request=${requestId}`);
      ws.binaryType = "arraybuffer";
      r.ws = ws;
      const out = new AudioContext({ sampleRate: 24000 });
      r.out = out;
      r.playAt = 0;
      r.sources = [];
      const analyser = out.createAnalyser();
      analyser.connect(out.destination);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const meter = () => {
        if (cancelled) return;
        analyser.getByteFrequencyData(data);
        setLevel(data.reduce((a, b) => a + b, 0) / data.length / 90);
        requestAnimationFrame(meter);
      };
      meter();

      ws.onmessage = async (ev) => {
        if (typeof ev.data !== "string") {
          const pcm = new Int16Array(ev.data);
          const f = new Float32Array(pcm.length);
          for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 0x8000;
          const b = out.createBuffer(1, f.length, 24000);
          b.copyToChannel(f, 0);
          const src = out.createBufferSource();
          src.buffer = b;
          src.connect(analyser);
          r.playAt = Math.max(r.playAt, out.currentTime + 0.02);
          src.start(r.playAt);
          r.playAt += b.duration;
          r.sources.push(src);
          src.onended = () => { r.sources = r.sources.filter((x) => x !== src); };
          return;
        }
        const msg = JSON.parse(ev.data);
        if (msg.type === "ready") { setStatus("live"); startMic(); }
        else if (msg.type === "unavailable" || msg.type === "error") setStatus(`error:${msg.reason}`);
        else if (msg.type === "interrupted") { r.sources.forEach((s) => { try { s.stop(); } catch { /* done */ } }); r.sources = []; r.playAt = 0; }
        else if (msg.type === "status") setReqState(msg.request);
        else if (msg.type === "you" || msg.type === "sanjaya") {
          setLines((ls) => {
            const last = ls[ls.length - 1];
            if (last && last.who === msg.type) return [...ls.slice(0, -1), { who: msg.type, text: last.text + msg.text }];
            return [...ls, { who: msg.type, text: msg.text }];
          });
        }
      };
      ws.onclose = () => setStatus((s) => (s.startsWith("error") ? s : "ended"));

      async function startMic() {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
          r.stream = stream;
          const ctx = new AudioContext();
          r.inCtx = ctx;
          await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
          const node = new AudioWorkletNode(ctx, "down16k");
          node.port.onmessage = (e) => ws.readyState === 1 && ws.send(e.data);
          ctx.createMediaStreamSource(stream).connect(node);
        } catch (e) {
          setStatus(`error:Microphone unavailable (${e.message}). Phones need HTTPS.`);
        }
      }
    })();
    return () => {
      cancelled = true;
      try { r.ws?.readyState === 1 && r.ws.send("hangup"); r.ws?.close(); } catch { /* closed */ }
      r.stream?.getTracks().forEach((t) => t.stop());
      r.inCtx?.close();
      r.out?.close();
    };
  }, [me, requestId]);

  const error = status.startsWith("error:") ? status.slice(6) : null;
  const decided = reqState && ["approved", "rejected"].includes(reqState.status);
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="absolute inset-0 z-40 flex flex-col items-center justify-between bg-gradient-to-b from-ink-900 via-ink-950 to-black px-6 py-10">
      <div className="text-center">
        <div className="inline-flex items-center gap-1.5 rounded-full bg-gemini/15 px-3 py-1 text-xs font-semibold text-gemini">
          <Sparkles className="h-3.5 w-3.5" /> Gemini Live
        </div>
        <h2 className="mt-3 text-2xl font-bold">Sanjaya</h2>
        <p className="text-sm text-ink-400">{error ? "Call unavailable" : status === "live" ? "On call" : status === "ended" ? "Call ended" : "Connecting…"}</p>
      </div>

      <div className="relative grid place-items-center">
        {[0, 1, 2].map((i) => (
          <motion.span key={i} className="absolute rounded-full border border-saffron-500/40"
            style={{ width: 160 + i * 60, height: 160 + i * 60 }}
            animate={{ scale: 1 + level * (0.15 + i * 0.08), opacity: 0.6 - i * 0.18 }} transition={{ duration: 0.12 }} />
        ))}
        <motion.div animate={{ scale: 1 + level * 0.12 }} transition={{ duration: 0.1 }}
          className="grid h-36 w-36 place-items-center rounded-full bg-ink-850 glow-saffron">
          <Eye size={96} active={level > 0.1} />
        </motion.div>
      </div>

      <div className="w-full max-w-md">
        {error && <p className="mb-4 rounded-xl bg-red-500/15 p-3 text-center text-sm text-red-200">{error}</p>}
        {decided && (
          <p className="mb-3 rounded-xl bg-emerald-500/15 p-2.5 text-center text-sm font-semibold text-emerald-300">
            Decision confirmed: {reqState.status}{reqState.max_minutes ? `, max ${reqState.max_minutes} min` : ""}
          </p>
        )}
        <div className="mb-6 max-h-40 space-y-1.5 overflow-y-auto scroll-thin text-[14px]">
          {lines.slice(-6).map((l, i) => (
            <p key={i} className={l.who === "sanjaya" ? "text-saffron-200" : "text-right text-ink-200"}>{l.text}</p>
          ))}
        </div>
        <div className="flex justify-center">
          <motion.button whileTap={{ scale: 0.92 }} onClick={onClose}
            className="grid h-16 w-16 place-items-center rounded-full bg-red-500 text-white shadow-lg shadow-red-500/30">
            <PhoneOff className="h-7 w-7" />
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}
