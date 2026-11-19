import {
  Activity,
  Factory,
  FileText,
  FlaskConical,
  History,
  Info,
  LayoutDashboard,
  Radar,
  ShieldAlert,
  SlidersHorizontal,
  WifiOff,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useLive } from "../hooks/useLive";
import { cn, simClock } from "../lib/format";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/plant", label: "Digital Twin", icon: Factory },
  { to: "/telemetry", label: "Live Telemetry", icon: Activity },
  { to: "/detection", label: "Detection Analytics", icon: Radar },
  { to: "/incidents", label: "Incidents", icon: ShieldAlert },
  { to: "/scenarios", label: "Scenario Lab", icon: FlaskConical },
  { to: "/replay", label: "Replay", icon: History },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
  { to: "/about", label: "Architecture", icon: Info },
];

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 64 64" className="size-8 shrink-0" aria-hidden>
        <rect width="64" height="64" rx="14" fill="#0b1324" stroke="#1c2943" />
        <path d="M32 8 52 16v16c0 12-8.5 20.5-20 24-11.5-3.5-20-12-20-24V16z" fill="none" stroke="#22d3ee" strokeWidth="4" strokeLinejoin="round" />
        <rect x="24" y="24" width="16" height="20" rx="3" fill="none" stroke="#dce5f5" strokeWidth="3" />
        <rect x="26.5" y="34" width="11" height="7.5" rx="1.5" fill="#22d3ee" />
      </svg>
      {!compact && (
        <div className="leading-tight">
          <div className="text-[13px] font-bold tracking-[0.14em] text-text">OT SENTINEL</div>
          <div className="text-[10px] font-semibold tracking-[0.3em] text-cyan">TWIN</div>
        </div>
      )}
    </div>
  );
}

function Sidebar() {
  const { activeAlerts } = useLive();
  return (
    <aside className="no-print sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-line bg-panel/70 backdrop-blur lg:w-60">
      <div className="flex h-14 items-center px-4">
        <span className="lg:hidden"><Logo compact /></span>
        <span className="hidden lg:block"><Logo /></span>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            title={label}
            className={({ isActive }) =>
              cn(
                "group flex h-9 items-center gap-3 rounded-lg px-2.5 text-[13px] font-medium transition-colors",
                isActive ? "bg-cyan/10 text-cyan ring-1 ring-inset ring-cyan/20" : "text-muted hover:bg-white/5 hover:text-text",
              )
            }
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            <span className="hidden flex-1 truncate lg:block">{label}</span>
            {to === "/incidents" && activeAlerts.length > 0 && (
              <span className="hidden rounded-full bg-crit px-1.5 text-[10px] font-bold text-white lg:inline" aria-label={`${activeAlerts.length} active alerts`}>
                {activeAlerts.length}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="hidden border-t border-line p-4 text-[11px] leading-relaxed text-faint lg:block">
        Isolated, synthetic digital twin. Not connected to real equipment. Not a safety system.
      </div>
    </aside>
  );
}

function TopBar() {
  const { state, connection, activeAlerts } = useLive();
  const loc = useLocation();
  const isReplay = loc.pathname.startsWith("/replay");
  const dot = connection === "open" ? "bg-ok" : connection === "connecting" ? "bg-warn pulse" : "bg-crit";
  return (
    <header className="no-print sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur md:px-6">
      <div className="flex items-center gap-2 text-xs text-muted" aria-live="polite">
        <span className={cn("size-2 rounded-full", dot)} aria-hidden />
        <span className="hidden sm:inline">{connection === "open" ? "Live" : connection === "connecting" ? "Connecting" : "Disconnected"}</span>
      </div>
      {state && (
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          <Badge tone={state.status === "running" ? "ok" : state.status === "error" ? "crit" : "warn"}>
            {state.status.toUpperCase()}
          </Badge>
          <span className="num text-sm text-text" title="Simulated time since run start">T+{simClock(state.sim_time_s)}</span>
          <span className="num hidden text-xs text-muted md:inline">{state.speed}x</span>
          <span className="num hidden truncate text-xs text-faint xl:inline" title="Current run id">{state.run_id}</span>
          {state.scenario && (
            <Badge tone="warn" title="A synthetic scenario is active">
              SCENARIO {state.scenario.code} · {state.scenario.phase.toUpperCase()}
            </Badge>
          )}
          {state.demo_mode && <Badge tone="replay">DEMO</Badge>}
        </div>
      )}
      <div className="ml-auto flex items-center gap-2">
        {isReplay && <Badge tone="replay">REPLAY MODE</Badge>}
        {activeAlerts.length > 0 && <Badge tone="crit">{activeAlerts.length} ACTIVE ALERT{activeAlerts.length > 1 ? "S" : ""}</Badge>}
        {state?.read_only && <Badge tone="neutral">READ-ONLY</Badge>}
        <Badge tone="neutral" title="All telemetry is generated by the simulator">SIMULATED DATA</Badge>
      </div>
    </header>
  );
}

function ConnectionBanner() {
  const { connection, reconnects } = useLive();
  if (connection === "open" || (connection === "connecting" && reconnects === 0)) return null;
  return (
    <div role="status" className="no-print flex items-center gap-2 border-b border-warn/30 bg-warn/10 px-6 py-2 text-xs text-warn">
      <WifiOff className="size-3.5" aria-hidden />
      Live connection to the simulator lost — reconnecting automatically. Views show the last data received.
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <ConnectionBanner />
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}
