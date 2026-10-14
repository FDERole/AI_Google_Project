import { motion } from "framer-motion";
import { LEVEL } from "../store";

/*
 * Plant X floor plan. Each area glows with the worst risk level of the hazards located in it.
 * Active changes pulse on the equipment they touch. The steam line from Boiler B-1 to Reactor R-201
 * stops flowing while the boiler is shut down, and the solvent-room fan spins slower if it's suspect.
 */
const AREAS = [
  { id: "Dryer house", x: 20, y: 20, w: 270, h: 170 },
  { id: "Reaction bay", x: 310, y: 20, w: 270, h: 170 },
  { id: "Solvent room", x: 20, y: 210, w: 270, h: 150 },
  { id: "Utilities", x: 310, y: 210, w: 270, h: 150 },
];
const EQUIP = {
  "SD-1": [110, 110], "TAH-301": [205, 70], "R-201": [430, 110], "TAH-201": [520, 70],
  "B-1": [430, 290], "EF-04": [100, 290], "GD-07": [215, 255],
};
const TAG_EQUIP = {
  batch_size: "SD-1", alarm_TAH_301: "TAH-301", "alarm_TAH-301": "TAH-301", crew_training: "CREW",
  "gas_detector_GD-07": "GD-07", "fan_EF-04": "EF-04", "boiler_B-1": "B-1", "nitrogen_SD-1": "SD-1",
  hot_work: "EF-04", "alarm_TAH-201": "TAH-201",
};

export default function FloorMap({ dashboard, now }) {
  const risk = dashboard?.risk || [];
  const changes = (dashboard?.changes || []).filter((c) => c.status === "active");
  const areaLevel = (area) => {
    const ranks = risk.filter((h) => h.area === area).map((h) => h.level.rank);
    const r = Math.max(0, ...ranks);
    return ["normal", "watch", "elevated", "critical"][Math.min(r, 3)];
  };
  const hit = new Map();
  for (const c of changes) {
    for (const t of c.tags) {
      const eq = TAG_EQUIP[t] || c.equipment;
      if (eq) hit.set(eq, [...(hit.get(eq) || []), c]);
    }
  }
  const boilerOff = changes.some((c) => c.tags.includes("boiler_B-1"));
  const fanSuspect = changes.some((c) => c.tags.includes("fan_EF-04"));
  const timer = (dashboard?.requests || []).find((r) => (r.status === "active" || r.status === "overrun") && r.ends_at);

  return (
    <svg viewBox="0 0 600 380" className="w-full h-auto">
      <defs>
        {AREAS.map((a) => {
          const lvl = LEVEL[areaLevel(a.id)];
          return (
            <radialGradient key={a.id} id={`ag-${a.id.replace(/\s/g, "")}`} cx="50%" cy="50%" r="70%">
              <stop offset="0%" stopColor={lvl.color} stopOpacity={areaLevel(a.id) === "normal" ? 0.05 : 0.32} />
              <stop offset="100%" stopColor={lvl.color} stopOpacity="0.02" />
            </radialGradient>
          );
        })}
      </defs>

      {AREAS.map((a) => {
        const name = areaLevel(a.id);
        const lvl = LEVEL[name];
        return (
          <g key={a.id}>
            <motion.rect x={a.x} y={a.y} width={a.w} height={a.h} rx="14" fill={`url(#ag-${a.id.replace(/\s/g, "")})`}
              stroke={lvl.color} strokeOpacity={name === "normal" ? 0.25 : 0.9} strokeWidth={name === "critical" ? 2 : 1.2}
              animate={name === "critical" ? { strokeOpacity: [0.9, 0.35, 0.9] } : {}}
              transition={{ duration: 1.4, repeat: Infinity }} />
            <text x={a.x + 14} y={a.y + 22} fontSize="11" fontWeight="700" fill="#a3adcf" letterSpacing="0.08em">
              {a.id.toUpperCase()}
            </text>
            {name !== "normal" && (
              <text x={a.x + a.w - 14} y={a.y + 22} textAnchor="end" fontSize="10" fontWeight="800" fill={lvl.color}>
                {lvl.label.toUpperCase()}
              </text>
            )}
          </g>
        );
      })}

      {/* steam line B-1 -> R-201 */}
      <path d="M430 270 L430 150" stroke="#2a3558" strokeWidth="6" strokeLinecap="round" />
      {!boilerOff && (
        <motion.path d="M430 270 L430 150" stroke="#9fb7ff" strokeWidth="2.5" strokeDasharray="6 10"
          animate={{ strokeDashoffset: [0, -32] }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }} />
      )}
      <text x="440" y="215" fontSize="9" fill={boilerOff ? "#f97316" : "#7480a8"}>
        {boilerOff ? "steam OFF" : "steam"}
      </text>

      {/* equipment */}
      <Dryer x={110} y={110} />
      <Reactor x={430} y={110} />
      <Boiler x={430} y={290} off={boilerOff} />
      <Fan x={100} y={290} suspect={fanSuspect} />
      <Sensor x={215} y={255} label="GD-07" />
      <Sensor x={205} y={70} label="TAH-301" bell />
      <Sensor x={520} y={70} label="TAH-201" bell />

      {/* active changes */}
      {[...hit.entries()].map(([eq, cs]) => {
        const [x, y] = eq === "CREW" ? [250, 160] : EQUIP[eq] || [0, 0];
        if (!x) return null;
        const isTimer = eq === "B-1" && timer;
        return (
          <g key={eq}>
            <motion.circle cx={x} cy={y} r="15" fill="none" stroke={isTimer ? "#fca311" : "#ef4444"} strokeWidth="2"
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
              animate={{ scale: [1, 2], opacity: [0.9, 0] }} transition={{ duration: 1.6, repeat: Infinity }} />
            <circle cx={x + 16} cy={y - 16} r="9" fill={isTimer ? "#fca311" : "#ef4444"} />
            <text x={x + 16} y={y - 12.5} textAnchor="middle" fontSize="10" fontWeight="800" fill="#050812">{cs.length}</text>
            {eq === "CREW" && <Person x={x} y={y} />}
          </g>
        );
      })}

      {timer && <TimerRing x={430} y={290} req={timer} now={now} speed={dashboard.speed} />}
    </svg>
  );
}

function Dryer({ x, y }) {
  return (
    <g transform={`translate(${x - 26},${y - 45})`}>
      <rect x="6" y="0" width="40" height="52" rx="6" fill="#1c2542" stroke="#56628f" />
      <path d="M6 52 L26 84 L46 52 Z" fill="#1c2542" stroke="#56628f" />
      <text x="26" y="30" textAnchor="middle" fontSize="10" fontWeight="700" fill="#cdd3ea">SD-1</text>
    </g>
  );
}
function Reactor({ x, y }) {
  return (
    <g transform={`translate(${x - 28},${y - 38})`}>
      <rect x="0" y="10" width="56" height="58" rx="22" fill="#1c2542" stroke="#56628f" />
      <rect x="22" y="0" width="12" height="12" fill="#2a3558" />
      <text x="28" y="44" textAnchor="middle" fontSize="10" fontWeight="700" fill="#cdd3ea">R-201</text>
    </g>
  );
}
function Boiler({ x, y, off }) {
  return (
    <g transform={`translate(${x - 44},${y - 22})`}>
      <rect x="0" y="0" width="88" height="44" rx="22" fill={off ? "#2c1d14" : "#1c2542"} stroke={off ? "#f97316" : "#56628f"} />
      <text x="44" y="27" textAnchor="middle" fontSize="10" fontWeight="700" fill={off ? "#fdba74" : "#cdd3ea"}>
        B-1 {off ? "OFF" : ""}
      </text>
    </g>
  );
}
function Fan({ x, y, suspect }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <circle r="26" fill="#1c2542" stroke={suspect ? "#ef4444" : "#56628f"} />
      <motion.g animate={{ rotate: 360 }} transition={{ duration: suspect ? 4 : 1.2, repeat: Infinity, ease: "linear" }}>
        {[0, 120, 240].map((a) => (
          <path key={a} d="M0 0 C6 -8 6 -18 0 -21 C-4 -14 -4 -6 0 0" fill="#7480a8" transform={`rotate(${a})`} />
        ))}
      </motion.g>
      <text y="42" textAnchor="middle" fontSize="10" fontWeight="700" fill="#cdd3ea">EF-04</text>
    </g>
  );
}
function Sensor({ x, y, label, bell }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x="-9" y="-9" width="18" height="18" rx={bell ? 9 : 4} fill="#131a30" stroke="#56628f" />
      <circle r="3" fill="#7480a8" />
      <text y="22" textAnchor="middle" fontSize="8.5" fill="#a3adcf">{label}</text>
    </g>
  );
}
function Person({ x, y }) {
  return (
    <g transform={`translate(${x},${y})`} fill="#fca5a5">
      <circle cy="-6" r="4" />
      <path d="M-6 8 C-6 0 6 0 6 8 Z" />
    </g>
  );
}
function TimerRing({ x, y, req, now, speed = 1 }) {
  const total = req.max_minutes * 60 * 1000;
  const remaining = (req.ends_at - now) * speed;
  const frac = Math.max(0, Math.min(1, 1 - remaining / total));
  const r = 40, c = 2 * Math.PI * r;
  const over = remaining < 0;
  return (
    <g transform={`translate(${x},${y})`}>
      <circle r={r} fill="none" stroke="#2a3558" strokeWidth="4" />
      <circle r={r} fill="none" stroke={over ? "#ef4444" : "#fca311"} strokeWidth="4" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - frac)} transform="rotate(-90)" />
    </g>
  );
}
