import { motion } from "framer-motion";

// Sanjaya's mark: an eye given divine sight. The iris breathes while Sanjaya is thinking or speaking.
export function Eye({ size = 40, active = false }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <defs>
        <radialGradient id="iris" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#ffe3a3" />
          <stop offset="55%" stopColor="#fca311" />
          <stop offset="100%" stopColor="#b86b00" />
        </radialGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="#0e1426" />
      <path d="M7 32c6.5-10.5 15-16 25-16s18.5 5.5 25 16c-6.5 10.5-15 16-25 16S13.5 42.5 7 32z"
        fill="none" stroke="#fca311" strokeWidth="3.2" strokeLinejoin="round" />
      <motion.circle cx="32" cy="32" r="9" fill="url(#iris)" style={{ transformBox: "fill-box", transformOrigin: "center" }}
        animate={active ? { scale: [0.9, 1.15, 0.9] } : { scale: 1 }}
        transition={{ duration: 1.4, repeat: active ? Infinity : 0, ease: "easeInOut" }} />
      <circle cx="32" cy="32" r="3.4" fill="#0e1426" />
      <circle cx="35" cy="29" r="1.4" fill="#fff" opacity="0.85" />
      <path d="M32 5v6M15 11l4 4M49 11l-4 4" stroke="#fca311" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

export function ModeBadge({ mode, small }) {
  const gemini = mode === "gemini";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-semibold whitespace-nowrap ${small ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs"} ${gemini ? "bg-gemini/15 text-gemini ring-1 ring-gemini/30" : "bg-ink-700 text-ink-300 ring-1 ring-ink-600"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${gemini ? "bg-gemini animate-pulse" : "bg-ink-400"}`} />
      {gemini ? "Gemini live" : "Offline mode"}
    </span>
  );
}

export function Avatar({ user, size = 36 }) {
  const id = user?.id || "?";
  const isSanjaya = id === "sanjaya";
  return (
    <span className="relative inline-grid shrink-0 place-items-center rounded-full font-bold text-white"
      style={{ width: size, height: size, background: isSanjaya ? "#0e1426" : user?.color, fontSize: size * 0.4 }}>
      {isSanjaya ? <Eye size={size} /> : (user?.name || "?")[0]}
    </span>
  );
}
