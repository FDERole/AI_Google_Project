// Voice out: speaks Sanjaya's voice notes only on the devices they're addressed to.
let voices = [];
let queue = Promise.resolve();
const listeners = new Set();
let speaking = false;

function loadVoices() {
  try { voices = window.speechSynthesis.getVoices(); } catch { voices = []; }
}
if (typeof window !== "undefined" && "speechSynthesis" in window) {
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

export function onSpeaking(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function setSpeaking(v) {
  speaking = v;
  listeners.forEach((fn) => fn(v));
}

export function unlockAudio() {
  // Phones block audio until a tap; speaking an empty utterance inside the tap unlocks it.
  try { window.speechSynthesis.speak(new SpeechSynthesisUtterance(" ")); } catch { /* no TTS */ }
}

export function say(text, lang = "en-IN") {
  if (!("speechSynthesis" in window) || !text) return Promise.resolve();
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text.replace(/[⚠️⏰🚨✅🔍]/gu, ""));
    u.lang = lang;
    u.rate = lang === "hi-IN" ? 0.95 : 1.02;
    const norm = (l) => l.replace("_", "-").toLowerCase();
    const pick = voices.filter((v) => norm(v.lang) === lang.toLowerCase());
    u.voice = pick.find((v) => /google|natural|neural/i.test(v.name)) || pick[0] ||
      voices.find((v) => norm(v.lang).startsWith(lang.slice(0, 2))) || null;
    setSpeaking(true);
    const done = () => { setSpeaking(false); resolve(); };
    u.onend = done;
    u.onerror = done;
    window.speechSynthesis.speak(u);
  });
}

export function speakFor(message, me) {
  for (const entry of message.speak || []) {
    if (me && entry.to.includes(me)) queue = queue.then(() => say(entry.text, entry.lang));
  }
}

export function isSpeaking() {
  return speaking;
}
