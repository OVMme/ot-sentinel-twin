import { memo } from "react";
import type { PlantView } from "../lib/plant";

/**
 * Original SVG rendering of the synthetic plant. Every value comes from telemetry (live or
 * recorded); nothing is hard-coded. In "twin" view the simulator's physical truth is overlaid
 * (magenta) so the difference between reported and real behaviour is visible; "hmi" shows only
 * what an operator's instruments report.
 */

type Anchors = Record<string, { rules: string[]; severity: string }>;

interface Props {
  view: PlantView | null;
  anchors?: Anchors;
  variant?: "twin" | "hmi";
  className?: string;
  replay?: boolean;
}

const TANK = { x: 410, y: 110, w: 180, h: 360 };
const INNER = { x: TANK.x + 5, y: TANK.y + 5, w: TANK.w - 10, h: TANK.h - 10 };
const C = {
  pipe: "#1f2d4a",
  pipeEdge: "#2d4066",
  flow: "#22d3ee",
  text: "#dce5f5",
  muted: "#8492ad",
  ok: "#22c55e",
  warn: "#f59e0b",
  crit: "#ef4444",
  truth: "#f0abfc",
  replay: "#a78bfa",
};

const fmt = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d));
const levelY = (pct: number) => INNER.y + INNER.h * (1 - Math.max(0, Math.min(100, pct)) / 100);

function flowDuration(flow: number | null): number | null {
  if (flow == null || flow < 0.3) return null;
  return Math.max(0.25, Math.min(6, 24 / flow));
}

function Pipe({ d, flow, color = C.flow, id }: { d: string; flow: number | null; color?: string; id: string }) {
  const dur = flowDuration(flow);
  return (
    <g data-testid={id}>
      <path d={d} stroke={C.pipeEdge} strokeWidth={14} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d={d} stroke={C.pipe} strokeWidth={10} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {dur != null && (
        <path
          d={d}
          className="flow-line"
          stroke={color}
          strokeOpacity={0.9}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ animationDuration: `${dur}s` }}
        />
      )}
    </g>
  );
}

function AlertRing({ x, y, r, a }: { x: number; y: number; r: number; a?: { rules: string[]; severity: string } }) {
  if (!a) return null;
  const color = a.severity === "high" || a.severity === "critical" ? C.crit : C.warn;
  return (
    <g aria-label={`Active alert ${a.rules.join(", ")}`}>
      <circle cx={x} cy={y} r={r} fill="none" stroke={color} strokeWidth={2.5} className="pulse" />
      <g transform={`translate(${x + r * 0.7}, ${y - r * 0.9})`}>
        <rect x={0} y={-11} rx={5} width={a.rules.join(" · ").length * 7 + 12} height={18} fill={color} />
        <text x={6} y={2} fontSize={11} fontWeight={700} fill="#0b0f19" fontFamily="var(--font-mono)">
          {a.rules.join(" · ")}
        </text>
      </g>
    </g>
  );
}

function Valve({ x, y, tag, cmd, pos, anchor }: {
  x: number; y: number; tag: string; cmd: number | null; pos: number | null; anchor?: Anchors[string];
}) {
  const open = pos ?? 0;
  const mismatch = cmd != null && pos != null && Math.abs(cmd - pos) > 5;
  const fill = open > 2 ? `rgba(34,211,238,${0.25 + 0.6 * (open / 100)})` : "#334155";
  const stroke = mismatch ? C.warn : "#93a4c4";
  return (
    <g data-testid={`valve-${tag}`}>
      <rect x={x - 24} y={y - 46} width={48} height={14} rx={3} fill="#0c1322" stroke="#2a3b5e" />
      <line x1={x} y1={y - 32} x2={x} y2={y - 14} stroke="#93a4c4" strokeWidth={2} />
      <path d={`M${x - 20} ${y - 13} L${x} ${y} L${x - 20} ${y + 13} Z`} fill={fill} stroke={stroke} strokeWidth={2} />
      <path d={`M${x + 20} ${y - 13} L${x} ${y} L${x + 20} ${y + 13} Z`} fill={fill} stroke={stroke} strokeWidth={2} />
      <text x={x} y={y - 36} textAnchor="middle" fontSize={9.5} fontWeight={700} fill={C.text} fontFamily="var(--font-mono)">
        {tag}
      </text>
      <text x={x} y={y + 30} textAnchor="middle" fontSize={11} fill={C.muted} fontFamily="var(--font-mono)">
        CMD <tspan fill={C.text}>{fmt(cmd)}%</tspan>
      </text>
      <text x={x} y={y + 44} textAnchor="middle" fontSize={11} fill={C.muted} fontFamily="var(--font-mono)">
        POS <tspan fill={mismatch ? C.warn : C.text}>{fmt(pos)}%</tspan>
      </text>
      <AlertRing x={x} y={y} r={30} a={anchor} />
    </g>
  );
}

function Meter({ x, y, tag, value, unit, quality, anchor, below = true }: {
  x: number; y: number; tag: string; value: number | null; unit: string; quality?: string;
  anchor?: Anchors[string]; below?: boolean;
}) {
  const bad = quality && quality !== "good";
  const ty = below ? y + 32 : y - 38;
  return (
    <g data-testid={`meter-${tag}`}>
      <circle cx={x} cy={y} r={14} fill="#0c1322" stroke={bad ? C.warn : "#93a4c4"} strokeWidth={2} />
      <text x={x} y={y + 3.5} textAnchor="middle" fontSize={8.5} fontWeight={700} fill={C.muted}>
        {tag.split("-")[0]}
      </text>
      <text x={x} y={ty} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="var(--font-mono)">
        {tag}
        {bad ? ` · ${quality?.toUpperCase()}` : ""}
      </text>
      <text x={x} y={ty + 15} textAnchor="middle" fontSize={13} fontWeight={600} fill={bad ? C.warn : C.flow} fontFamily="var(--font-mono)">
        {fmt(value, unit === "bar" ? 2 : 1)} <tspan fontSize={10} fill={C.muted}>{unit}</tspan>
      </text>
      <AlertRing x={x} y={y} r={22} a={anchor} />
    </g>
  );
}

function Pump({ x, y, running, cmd, kw, anchor }: {
  x: number; y: number; running: boolean | null; cmd: boolean | null; kw: number | null; anchor?: Anchors[string];
}) {
  const on = Boolean(running);
  const mismatch = cmd != null && running != null && cmd !== running;
  const ring = on ? C.ok : "#475569";
  return (
    <g data-testid="pump-P-101">
      <rect x={x - 34} y={y + 24} width={68} height={8} rx={2} fill="#1a2640" />
      <circle cx={x} cy={y} r={27} fill="#0c1322" stroke={mismatch ? C.warn : ring} strokeWidth={3} />
      <g className={on ? "rotor" : undefined}>
        {[0, 90, 180, 270].map((a) => (
          <path
            key={a}
            d={`M${x} ${y} q 6 -12 0 -20`}
            stroke={on ? C.ok : "#64748b"}
            strokeWidth={3}
            fill="none"
            transform={`rotate(${a} ${x} ${y})`}
            strokeLinecap="round"
          />
        ))}
        <circle cx={x} cy={y} r={4.5} fill={on ? C.ok : "#64748b"} />
      </g>
      <text x={x} y={y + 50} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="var(--font-mono)">
        P-101 · {on ? <tspan fill={C.ok}>RUNNING</tspan> : <tspan fill="#94a3b8">STOPPED</tspan>}
      </text>
      <text x={x} y={y + 65} textAnchor="middle" fontSize={12} fontWeight={600} fill={C.text} fontFamily="var(--font-mono)">
        {fmt(kw)} <tspan fontSize={10} fill={C.muted}>kW</tspan>
      </text>
      <AlertRing x={x} y={y} r={36} a={anchor} />
    </g>
  );
}

function LevelMarker({ side, pct, tag, valueM, quality, color }: {
  side: "left" | "right"; pct: number | null; tag: string; valueM: number | null; quality?: string; color: string;
}) {
  if (pct == null) return null;
  const y = levelY(pct);
  const bad = quality && quality !== "good";
  const c = bad ? C.warn : color;
  const x = side === "left" ? TANK.x : TANK.x + TANK.w;
  const tri = side === "left" ? `M${x - 2} ${y} l-10 -7 v14 z` : `M${x + 2} ${y} l10 -7 v14 z`;
  const bx = side === "left" ? x - 132 : x + 16;
  return (
    <g data-testid={`marker-${tag}`}>
      <line x1={TANK.x + 4} x2={TANK.x + TANK.w - 4} y1={y} y2={y} stroke={c} strokeOpacity={0.35} strokeDasharray="2 4" />
      <path d={tri} fill={c} />
      <rect x={bx} y={y - 17} width={116} height={34} rx={7} fill="#0c1322" stroke={c} strokeOpacity={0.6} />
      <text x={bx + 8} y={y - 3} fontSize={9.5} fontWeight={700} fill={C.muted} fontFamily="var(--font-mono)">
        {tag}
        {bad ? ` · ${quality?.toUpperCase()}` : ""}
      </text>
      <text x={bx + 8} y={y + 11} fontSize={13} fontWeight={600} fill={c} fontFamily="var(--font-mono)">
        {pct.toFixed(1)}% <tspan fontSize={10} fill={C.muted}>{fmt(valueM, 3)} m</tspan>
      </text>
    </g>
  );
}

function PlantDiagramImpl({ view, anchors = {}, variant = "twin", className, replay }: Props) {
  const v = view;
  const h = v?.tankHeightM ?? 5;
  const pct = (m: number | null | undefined) => (m == null ? null : (m / h) * 100);
  const reported = pct(v?.levelPrimaryM);
  const truth = pct(v?.trueLevelM);
  const fillPct = variant === "twin" && truth != null ? truth : reported ?? 0;
  const fillY = levelY(fillPct);
  const flowIn = variant === "twin" && v?.trueFlowIn != null ? v.trueFlowIn : v?.flowIn ?? null;
  const flowOut = variant === "twin" && v?.trueFlowOut != null ? v.trueFlowOut : v?.flowOut ?? null;
  const accent = replay ? C.replay : C.flow;

  return (
    <svg
      viewBox="0 0 1000 560"
      className={className}
      role="img"
      aria-label={`Synthetic plant diagram. Tank level ${fmt(reported)} percent reported by LT-101.`}
      data-testid="plant-diagram"
    >
      <defs>
        <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M28 0H0V28" fill="none" stroke="#ffffff" strokeOpacity="0.025" />
        </pattern>
        <linearGradient id="liquid" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#38bdf8" stopOpacity="0.85" />
          <stop offset="1" stopColor="#1d4ed8" stopOpacity="0.75" />
        </linearGradient>
        <linearGradient id="shell" x1="0" x2="1">
          <stop offset="0" stopColor="#1b2944" />
          <stop offset="0.5" stopColor="#24375a" />
          <stop offset="1" stopColor="#1b2944" />
        </linearGradient>
        <clipPath id="tank-inner">
          <rect x={INNER.x} y={INNER.y} width={INNER.w} height={INNER.h} rx={10} />
        </clipPath>
      </defs>
      <rect width="1000" height="560" fill="url(#grid)" />

      {/* Inlet line */}
      <rect x={18} y={68} width={112} height={48} rx={8} fill="#0c1322" stroke="#2a3b5e" />
      <text x={74} y={89} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.muted}>SUPPLY</text>
      <text x={74} y={104} textAnchor="middle" fontSize={10} fill={C.muted}>HEADER</text>
      <Pipe id="pipe-inlet" d="M130 92 H 470 V 122" flow={flowIn} color={accent} />
      <Valve x={262} y={92} tag="XV-101" cmd={v?.inletCmd ?? null} pos={v?.inletPos ?? null} anchor={anchors["XV-101"]} />
      <Meter x={372} y={92} tag="FT-101" value={v?.flowIn ?? null} unit="L/s" quality={v?.quality["FT-101"]} anchor={anchors["FT-101"]} />

      {/* Outlet line */}
      <Pipe id="pipe-outlet" d="M590 440 H 990" flow={flowOut} color={accent} />
      <line x1={752} y1={440} x2={752} y2={398} stroke={C.pipeEdge} strokeWidth={5} />
      <Pump x={672} y={440} running={v?.pumpRunning ?? null} cmd={v?.pumpCmd ?? null} kw={v?.pumpKw ?? null} anchor={anchors["P-101"]} />
      <Meter x={752} y={384} tag="PT-101" value={v?.pressure ?? null} unit="bar" quality={v?.quality["PT-101"]} anchor={anchors["PT-101"]} below={false} />
      <Valve x={838} y={440} tag="XV-102" cmd={v?.outletCmd ?? null} pos={v?.outletPos ?? null} anchor={anchors["XV-102"]} />
      <Meter x={930} y={440} tag="FT-102" value={v?.flowOut ?? null} unit="L/s" quality={v?.quality["FT-102"]} anchor={anchors["FT-102"]} />
      <text x={990} y={516} textAnchor="end" fontSize={10} fontWeight={700} fill={C.muted}>TO DISTRIBUTION →</text>
      {anchors["OUTLET-LINE"] && <AlertRing x={880} y={440} r={44} a={anchors["OUTLET-LINE"]} />}

      {/* Tank */}
      <rect x={TANK.x} y={TANK.y} width={TANK.w} height={TANK.h} rx={14} fill="url(#shell)" stroke="#3a5080" strokeWidth={2} />
      <g clipPath="url(#tank-inner)">
        <rect x={INNER.x} y={INNER.y} width={INNER.w} height={INNER.h} fill="#070d1a" />
        <rect className="liquid" x={INNER.x} y={fillY} width={INNER.w} height={INNER.y + INNER.h - fillY} fill="url(#liquid)" />
        <g transform={`translate(0 ${fillY - 6})`}>
          <path
            className="wave"
            d={`M${INNER.x - 80} 6 ${Array.from({ length: 6 }, () => "q 20 -8 40 0 t 40 0").join(" ")} V 14 H ${INNER.x - 80} Z`}
            fill="#7dd3fc"
            fillOpacity={0.35}
          />
        </g>
      </g>
      {[0, 25, 50, 75, 100].map((p) => (
        <g key={p}>
          <line x1={TANK.x + TANK.w - 14} x2={TANK.x + TANK.w - 5} y1={levelY(p)} y2={levelY(p)} stroke="#93a4c4" strokeOpacity={0.5} />
          <text x={TANK.x + TANK.w - 18} y={levelY(p) + 3.5} textAnchor="end" fontSize={9} fill="#93a4c4" fillOpacity={0.7} fontFamily="var(--font-mono)">
            {p}
          </text>
        </g>
      ))}
      <line x1={TANK.x + 6} x2={TANK.x + TANK.w - 6} y1={levelY(95)} y2={levelY(95)} stroke={C.crit} strokeDasharray="6 4" strokeOpacity={0.7} />
      <text x={TANK.x + 10} y={levelY(95) - 4} fontSize={9} fill={C.crit} fillOpacity={0.85}>LSHH 95% (LT-102)</text>
      {v?.setpointPct != null && (
        <g data-testid="setpoint-line">
          <line x1={TANK.x + 6} x2={TANK.x + TANK.w - 6} y1={levelY(v.setpointPct)} y2={levelY(v.setpointPct)} stroke="#e2e8f0" strokeDasharray="8 5" strokeOpacity={0.55} />
          <text x={TANK.x + 10} y={levelY(v.setpointPct) - 5} fontSize={9.5} fill="#e2e8f0" fillOpacity={0.75}>
            SP {v.setpointPct.toFixed(0)}%
          </text>
        </g>
      )}
      {variant === "twin" && truth != null && (
        <g data-testid="truth-line">
          <line x1={TANK.x - 6} x2={TANK.x + TANK.w + 6} y1={levelY(truth)} y2={levelY(truth)} stroke={C.truth} strokeWidth={2} />
          <text x={TANK.x + TANK.w / 2} y={levelY(truth) + 16} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.truth}>
            TRUE {truth.toFixed(1)}%
          </text>
        </g>
      )}
      <text x={TANK.x + TANK.w / 2} y={TANK.y + TANK.h + 50} textAnchor="middle" fontSize={11} fontWeight={700} fill={C.text}>
        TK-001 MAIN STORAGE TANK
      </text>
      <text x={TANK.x + TANK.w / 2} y={TANK.y + TANK.h + 64} textAnchor="middle" fontSize={9.5} fill={C.muted} fontFamily="var(--font-mono)">
        level span 0 – {fmt(v?.tankHeightM, 1)} m
      </text>
      {anchors["TANK-001"] && (
        <g>
          <rect x={TANK.x - 4} y={TANK.y - 4} width={TANK.w + 8} height={TANK.h + 8} rx={17} fill="none" stroke={C.crit} strokeWidth={2.5} className="pulse" />
          <rect x={TANK.x + 10} y={TANK.y + TANK.h + 12} rx={5} width={anchors["TANK-001"].rules.join(" · ").length * 7 + 12} height={18} fill={C.crit} />
          <text x={TANK.x + 16} y={TANK.y + TANK.h + 25} fontSize={11} fontWeight={700} fill="#0b0f19" fontFamily="var(--font-mono)">
            {anchors["TANK-001"].rules.join(" · ")}
          </text>
        </g>
      )}
      <LevelMarker side="left" pct={reported} tag="LT-101" valueM={v?.levelPrimaryM ?? null} quality={v?.quality["LT-101"]} color={C.flow} />
      <LevelMarker side="right" pct={pct(v?.levelSecondaryM)} tag="LT-102" valueM={v?.levelSecondaryM ?? null} quality={v?.quality["LT-102"]} color="#7dd3fc" />

      {/* Controller */}
      <g data-testid="plc-box">
        <rect x={770} y={56} width={210} height={124} rx={10} fill="#0c1322" stroke="#2a3b5e" />
        <text x={784} y={78} fontSize={10.5} fontWeight={700} fill={C.text}>PLC-001 · LIC-101 (simulated)</text>
        <text x={784} y={100} fontSize={11} fill={C.muted}>Mode</text>
        <text x={966} y={100} textAnchor="end" fontSize={11} fontWeight={700} fill={v?.mode === "manual" ? C.warn : C.ok} fontFamily="var(--font-mono)">
          {(v?.mode ?? "—").toUpperCase()}
        </text>
        <text x={784} y={120} fontSize={11} fill={C.muted}>Setpoint</text>
        <text x={966} y={120} textAnchor="end" fontSize={11} fill={C.text} fontFamily="var(--font-mono)">{fmt(v?.setpointPct)} %</text>
        <text x={784} y={140} fontSize={11} fill={C.muted}>Health</text>
        <text x={966} y={140} textAnchor="end" fontSize={11} fill={v?.health === "ok" || v?.health == null ? C.ok : C.warn} fontFamily="var(--font-mono)">
          {(v?.health ?? (replay ? "recorded" : "—")).toUpperCase()}
        </text>
        <text x={784} y={162} fontSize={11} fill={C.muted}>Interlocks</text>
        <text x={966} y={162} textAnchor="end" fontSize={11} fill={v?.interlockHigh || v?.interlockLow ? C.crit : C.muted} fontFamily="var(--font-mono)">
          {v?.interlockHigh ? "HIGH TRIP" : v?.interlockLow ? "LOW TRIP" : "NORMAL"}
        </text>
      </g>

      {variant === "twin" && (v?.overflow ?? 0) > 0.05 && (
        <text x={TANK.x + TANK.w + 12} y={TANK.y + 20} fontSize={11} fontWeight={700} fill={C.crit}>
          OVERFLOW {fmt(v?.overflow)} L/s
        </text>
      )}

      {/* Legend */}
      <g transform="translate(18 512)" fontSize={10.5} fill={C.muted}>
        <rect width={variant === "twin" ? 360 : 230} height={30} rx={7} fill="#0c1322" stroke="#1c2943" />
        <line x1={12} x2={32} y1={15} y2={15} stroke={accent} strokeWidth={3} className="flow-line" style={{ animationDuration: "1s" }} />
        <text x={38} y={19}>flow</text>
        <path d="M78 9 l10 6 -10 6 z" fill={C.flow} />
        <text x={94} y={19}>reported level</text>
        {variant === "twin" ? (
          <>
            <line x1={180} x2={200} y1={15} y2={15} stroke={C.truth} strokeWidth={2} />
            <text x={206} y={19}>physical truth (simulator only)</text>
          </>
        ) : (
          <text x={180} y={19}>HMI view</text>
        )}
      </g>
    </svg>
  );
}

export const PlantDiagram = memo(PlantDiagramImpl);
