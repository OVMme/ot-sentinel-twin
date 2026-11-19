import { AlertTriangle, Loader2, RefreshCw, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { CLASSIFICATION_LABEL, cn } from "../lib/format";

export type Tone = "neutral" | "cyan" | "ok" | "warn" | "crit" | "replay" | "truth";

const TONE: Record<Tone, string> = {
  neutral: "bg-white/5 text-muted ring-white/10",
  cyan: "bg-cyan/10 text-cyan ring-cyan/25",
  ok: "bg-ok/10 text-ok ring-ok/25",
  warn: "bg-warn/10 text-warn ring-warn/30",
  crit: "bg-crit/12 text-crit ring-crit/30",
  replay: "bg-replay/12 text-replay ring-replay/30",
  truth: "bg-truth/10 text-truth ring-truth/25",
};

export function Badge({ tone = "neutral", children, className, title }: {
  tone?: Tone; children: ReactNode; className?: string; title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Card({ title, subtitle, actions, children, className, bodyClassName, icon: Icon }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  icon?: LucideIcon;
}) {
  return (
    <section className={cn("panel flex flex-col min-w-0", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-2">
          <div className="min-w-0">
            {title && (
              <h2 className="flex items-center gap-2 text-[13px] font-semibold text-text">
                {Icon && <Icon className="size-4 text-cyan" aria-hidden />}
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("px-4 pb-4 min-w-0", !title && !actions && "pt-4", bodyClassName)}>{children}</div>
    </section>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: LucideIcon;
  busy?: boolean;
};

export function Button({ variant = "secondary", size = "md", icon: Icon, busy, className, children, disabled, ...rest }: ButtonProps) {
  const v = {
    primary: "bg-cyan text-bg hover:bg-cyan/90 font-semibold shadow-[0_0_24px_-8px_rgba(34,211,238,0.8)]",
    secondary: "bg-raised text-text ring-1 ring-inset ring-line-strong hover:bg-line-strong/60",
    ghost: "text-muted hover:text-text hover:bg-white/5",
    danger: "bg-crit/15 text-crit ring-1 ring-inset ring-crit/30 hover:bg-crit/25",
  }[variant];
  const s = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-9 px-3.5 text-[13px] gap-2";
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center justify-center rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        v,
        s,
        className,
      )}
      disabled={disabled || busy}
      {...rest}
    >
      {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : Icon ? <Icon className="size-3.5" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function Stat({ label, value, unit, sub, tone = "cyan", icon: Icon, className }: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: Tone;
  icon?: LucideIcon;
  className?: string;
}) {
  const color = {
    neutral: "text-text", cyan: "text-cyan", ok: "text-ok", warn: "text-warn", crit: "text-crit",
    replay: "text-replay", truth: "text-truth",
  }[tone];
  return (
    <div className={cn("panel px-4 py-3 min-w-0", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="label truncate">{label}</span>
        {Icon && <Icon className={cn("size-4 shrink-0", color)} aria-hidden />}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className={cn("num text-2xl font-semibold leading-none", color)}>{value}</span>
        {unit && <span className="text-xs text-muted">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 text-xs text-muted truncate">{sub}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <div className="rounded-full bg-white/5 p-3 ring-1 ring-white/10">
        <Icon className="size-5 text-muted" aria-hidden />
      </div>
      <p className="text-sm font-medium text-text">{title}</p>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 py-8 text-center">
      <AlertTriangle className="size-6 text-warn" aria-hidden />
      <p className="text-sm font-medium">Could not load data</p>
      <p className="max-w-md text-xs text-muted">{error.message}</p>
      {onRetry && (
        <Button size="sm" icon={RefreshCw} onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label, disabled }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-bg p-0.5 ring-1 ring-line-strong">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-7 rounded-md px-2.5 text-xs font-medium transition-colors disabled:opacity-40",
            o.value === value ? "bg-cyan/15 text-cyan ring-1 ring-inset ring-cyan/30" : "text-muted hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SyntheticTag({ className }: { className?: string }) {
  return (
    <Badge tone="neutral" className={className} title="All telemetry is generated by the simulator">
      SIMULATED DATA
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const tone: Tone = severity === "critical" || severity === "high" ? "crit" : severity === "medium" ? "warn" : "neutral";
  return <Badge tone={tone}>{severity.toUpperCase()}</Badge>;
}

export function ClassificationBadge({ value }: { value: string }) {
  const tone: Tone = {
    suspected_manipulation: "crit",
    equipment_fault: "warn",
    physical_anomaly: "cyan",
    data_quality: "neutral",
  }[value] as Tone ?? "neutral";
  return <Badge tone={tone}>{CLASSIFICATION_LABEL[value] ?? value}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "open" ? "warn" : status === "closed" || status === "reviewed" ? "ok" : "cyan";
  return <Badge tone={tone}>{status}</Badge>;
}

export function KV({ items, className }: { items: [string, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-[13px]", className)}>
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 text-text">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: {
  title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-[13px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Meter({ value, max = 1, tone }: { value: number; max?: number; tone?: Tone }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  const t = tone ?? (value >= max ? "crit" : value >= 0.6 * max ? "warn" : "cyan");
  const bg = { neutral: "bg-muted", cyan: "bg-cyan", ok: "bg-ok", warn: "bg-warn", crit: "bg-crit", replay: "bg-replay", truth: "bg-truth" }[t];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={cn("h-full rounded-full transition-[width] duration-300", bg)} style={{ width: `${pct}%` }} />
    </div>
  );
}
