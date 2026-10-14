import { motion } from "framer-motion";
import { Flame, Users } from "lucide-react";
import { LEVEL } from "../store";

/*
 * James Reason's Swiss-cheese model, live.
 * Each slice is one safeguard. A weakened safeguard opens a hole on the hazard's path.
 * The red trajectory travels through every open hole and stops at the first intact slice,
 * so you can see how many safeguards are still standing between the hazard and people.
 */
const DECOR = [[0.22, 0.05], [0.78, 0.07], [0.34, 0.04], [0.68, 0.06], [0.15, 0.05], [0.85, 0.05]];

export default function SwissCheese({ stack, compact = false }) {
  const barriers = [...stack.barriers].sort((a, b) => Number(b.down) - Number(a.down));
  const n = barriers.length;
  const W = 600, H = compact ? 150 : 200;
  const top = 22, bottom = H - 18, mid = (top + bottom) / 2 + 4;
  const x0 = 110, x1 = 500, slab = 20, skew = 14;
  const gap = n > 1 ? (x1 - x0) / (n - 1) : 0;
  const downCount = barriers.filter((b) => b.down).length;
  const allDown = downCount === n;
  const stopX = allDown ? 548 : x0 + downCount * gap - 4;
  const lvl = LEVEL[stack.level.name] || LEVEL.normal;
  const pathColor = stack.level.name === "normal" ? "#7480a8" : lvl.color;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`${stack.hazard}: ${downCount} of ${n} safeguards weakened`}>
      <defs>
        <linearGradient id={`slab-${stack.hazard_id}`} x1="0" x2="1">
          <stop offset="0%" stopColor="#3a4672" />
          <stop offset="100%" stopColor="#1f2847" />
        </linearGradient>
        <linearGradient id={`slabDown-${stack.hazard_id}`} x1="0" x2="1">
          <stop offset="0%" stopColor="#5a2330" />
          <stop offset="100%" stopColor="#2c1520" />
        </linearGradient>
        <filter id={`glow-${stack.hazard_id}`} filterUnits="userSpaceOnUse" x="0" y="0" width={W} height={H}><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>

      {/* hazard source */}
      <foreignObject x="22" y={mid - 22} width="44" height="44">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-red-500/15 ring-1 ring-red-500/40">
          <Flame className="h-5 w-5 text-red-400" />
        </div>
      </foreignObject>
      {/* people at risk */}
      <foreignObject x={W - 52} y={mid - 22} width="44" height="44">
        <div className={`grid h-11 w-11 place-items-center rounded-full ring-1 ${allDown ? "bg-red-500/30 ring-red-500" : "bg-ink-700 ring-ink-600"}`}>
          <Users className={`h-5 w-5 ${allDown ? "text-red-300" : "text-ink-300"}`} />
        </div>
      </foreignObject>

      {/* trajectory (behind slices): reaches through every open hole, stops at the first intact slice */}
      <line x1="66" y1={mid} x2={stopX} y2={mid} stroke={pathColor} strokeWidth="3" strokeLinecap="round"
        strokeDasharray={downCount ? undefined : "4 6"} opacity={downCount ? 1 : 0.6}
        filter={downCount ? `url(#glow-${stack.hazard_id})` : undefined} />
      {downCount > 0 && (
        <motion.circle cx="66" cy={mid} r="4.5" fill="#fff" filter={`url(#glow-${stack.hazard_id})`}
          animate={{ x: [0, stopX - 66], opacity: [0, 1, 1, 0] }}
          transition={{ duration: 1.6 + downCount * 0.3, repeat: Infinity, ease: "easeIn" }} />
      )}

      {barriers.map((b, i) => {
        const x = x0 + i * gap;
        const d = `M${x},${top + skew} L${x + slab},${top} L${x + slab},${bottom - skew} L${x},${bottom} Z`;
        const cx = x + slab / 2;
        const clip = `clip-${stack.hazard_id}-${i}`;
        return (
          <g key={b.name}>
            <clipPath id={clip}><path d={d} /></clipPath>
            <path d={d} fill={b.down ? `url(#slabDown-${stack.hazard_id})` : `url(#slab-${stack.hazard_id})`} stroke={b.down ? lvl.color : "#56628f"}
              strokeOpacity={b.down ? 0.9 : 0.5} strokeWidth="1.2" />
            <g clipPath={`url(#${clip})`}>
              {DECOR.slice(0, 3).map(([fy, fr], k) => {
                const yy = top + (bottom - top) * ((fy + i * 0.13 + k * 0.29) % 0.8 + 0.1);
                return Math.abs(yy - mid) > 22 ? <ellipse key={k} cx={cx} cy={yy} rx={slab * fr * 4} ry={6} fill="#0a0f1e" opacity="0.8" /> : null;
              })}
              <motion.ellipse cx={cx} cy={mid} rx={slab * 0.36} initial={false}
                animate={{ ry: b.down ? 15 : 0.01 }} transition={{ duration: 0.6, ease: "easeOut" }}
                fill="#050812" />
            </g>
            {!compact && (
              <text x={cx} y={bottom + 14} textAnchor="middle" fontSize="9.5" fill={b.down ? lvl.color : "#7480a8"}
                fontWeight={b.down ? 700 : 500}>{shortName(b.name)}</text>
            )}
          </g>
        );
      })}

      {!allDown && downCount > 0 && (
        <motion.circle cx={stopX + 4} cy={mid} r="5" fill={pathColor} initial={{ scale: 0 }}
          style={{ transformBox: "fill-box", transformOrigin: "center" }}
          animate={{ scale: [1, 1.8, 1] }} transition={{ duration: 1.2, repeat: Infinity }} />
      )}
    </svg>
  );
}

function shortName(name) {
  return name
    .replace(/High-temp alarm & interlock /, "Alarm ")
    .replace(/ within validated limit.*/, " size")
    .replace(/Trained operator on every shift/, "Trained crew")
    .replace(/Exhaust fan (EF-04).*/, "Fan $1")
    .replace(/Gas detector (GD-07).*/, "Detector $1")
    .replace(/Ex-rated electricals.*/, "Ex equipment")
    .replace(/Hot-work permit control/, "Hot-work permit")
    .replace(/Jacket temperature control.*/, "Jacket heat (B-1)")
    .replace(/Reactor high-temp alarm (TAH-201).*/, "Alarm $1")
    .replace(/Explosion vent panel/, "Explosion vent")
    .replace(/ in service$/, "")
    .slice(0, 20);
}
