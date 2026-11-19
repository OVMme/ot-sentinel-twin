import { useMemo } from "react";
import { EChart, type EChartsOption } from "./EChart";

export interface Series {
  name: string;
  data: [number, number | null][];
  color: string;
  dashed?: boolean;
  area?: boolean;
  step?: boolean;
  width?: number;
  yAxisIndex?: 0 | 1;
}

export interface Marker {
  x: number;
  label: string;
  color?: string;
}

export interface Band {
  from: number;
  to: number;
  label?: string;
  color?: string;
}

interface Props {
  series: Series[];
  ariaLabel: string;
  height?: number;
  unit?: string;
  digits?: number;
  yMin?: number;
  yMax?: number;
  thresholds?: { value: number; label?: string; color?: string }[];
  markers?: Marker[];
  bands?: Band[];
  playhead?: number | null;
  zoom?: boolean;
  slider?: boolean;
  y2?: { unit: string; min?: number; max?: number; digits?: number };
  onClickX?: (x: number) => void;
}

const AXIS = "#1c2943";
const LABEL = "#8492ad";

function hms(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19);
}

export function TimeChart({
  series, ariaLabel, height = 210, unit = "", digits = 2, yMin, yMax, thresholds = [], markers = [], bands = [],
  playhead = null, zoom = true, slider = false, y2, onClickX,
}: Props) {
  const option = useMemo<EChartsOption>(() => {
    // Merge alert markers that are close together so their labels stay readable.
    let xMin = Infinity;
    let xMax = -Infinity;
    for (const s of series) {
      if (s.data.length) {
        xMin = Math.min(xMin, s.data[0][0]);
        xMax = Math.max(xMax, s.data[s.data.length - 1][0]);
      }
    }
    const mergeWithin = Number.isFinite(xMax - xMin) ? (xMax - xMin) * 0.06 : 0;
    const groups: { x: number; labels: string[]; color?: string }[] = [];
    for (const m of [...markers].sort((a, b) => a.x - b.x)) {
      const g = groups[groups.length - 1];
      if (g && m.x - g.x <= mergeWithin) {
        if (!g.labels.includes(m.label)) g.labels.push(m.label);
      } else groups.push({ x: m.x, labels: [m.label], color: m.color });
    }
    const markLineData: object[] = [
      ...thresholds.map((t) => ({
        yAxis: t.value,
        label: { formatter: t.label ?? "", color: t.color ?? "#f59e0b", fontSize: 10, position: "insideEndTop" },
        lineStyle: { color: t.color ?? "#f59e0b", type: "dashed", width: 1, opacity: 0.8 },
      })),
      ...groups.map((g) => ({
        xAxis: g.x,
        label: {
          formatter: g.labels.length > 1 ? `${g.labels[0]} +${g.labels.length - 1}` : g.labels[0],
          color: g.color ?? "#ef4444",
          fontSize: 10,
          position: "insideEndTop",
          backgroundColor: "rgba(6,10,19,0.85)",
          padding: [1, 3],
        },
        lineStyle: { color: g.color ?? "#ef4444", type: "solid", width: 1, opacity: 0.75 },
      })),
      ...(playhead != null
        ? [{ xAxis: playhead, label: { show: false }, lineStyle: { color: "#a78bfa", width: 2, type: "solid" } }]
        : []),
    ];
    const markAreaData = bands.map((b) => [
      { xAxis: b.from, itemStyle: { color: b.color ?? "rgba(167,139,250,0.10)" }, label: { show: !!b.label, formatter: b.label, color: "#a78bfa", fontSize: 10, position: "insideTop" } },
      { xAxis: b.to },
    ]);
    return {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 52, right: y2 ? 52 : 16, top: 44, bottom: slider ? 48 : 24, containLabel: false },
      legend: {
        top: 0,
        left: 0,
        type: "scroll",
        pageTextStyle: { color: LABEL },
        textStyle: { color: LABEL, fontSize: 11 },
        itemWidth: 14,
        itemHeight: 3,
        icon: "rect",
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0c1322",
        borderColor: "#2a3b5e",
        textStyle: { color: "#dce5f5", fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: "#3a5080" } },
        valueFormatter: (v: unknown) => (typeof v === "number" ? v.toFixed(digits) : "—"),
        formatter: (params: unknown) => {
          const ps = params as { seriesName: string; value: [number, number | null]; color: string; seriesIndex: number }[];
          if (!ps.length) return "";
          const head = `<div style="font-family:var(--font-mono);color:#8492ad;margin-bottom:4px">${hms(ps[0].value[0])} (sim)</div>`;
          const rows = ps
            .map((p) => {
              const s = series[p.seriesIndex];
              const u = s?.yAxisIndex === 1 ? y2?.unit ?? "" : unit;
              const d = s?.yAxisIndex === 1 ? y2?.digits ?? digits : digits;
              const v = p.value[1];
              return `<div style="display:flex;gap:10px;justify-content:space-between"><span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>${p.seriesName}</span><b style="font-family:var(--font-mono)">${v == null ? "—" : v.toFixed(d)} ${u}</b></div>`;
            })
            .join("");
          return head + rows;
        },
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: AXIS } },
        axisLabel: { color: LABEL, fontSize: 10, formatter: (v: number) => hms(v), hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          name: unit,
          nameTextStyle: { color: LABEL, fontSize: 10, align: "right" },
          min: yMin,
          max: yMax,
          scale: yMin == null,
          axisLine: { show: false },
          axisLabel: { color: LABEL, fontSize: 10 },
          splitLine: { lineStyle: { color: AXIS, opacity: 0.6 } },
        },
        ...(y2
          ? [{
              type: "value",
              name: y2.unit,
              nameTextStyle: { color: LABEL, fontSize: 10, align: "left" },
              min: y2.min,
              max: y2.max,
              axisLabel: { color: LABEL, fontSize: 10 },
              splitLine: { show: false },
            }]
          : []),
      ],
      dataZoom: zoom
        ? [
            { type: "inside", throttle: 60, filterMode: "none" },
            ...(slider
              ? [{ type: "slider", height: 16, bottom: 6, borderColor: AXIS, textStyle: { color: LABEL, fontSize: 9 }, fillerColor: "rgba(34,211,238,0.12)", handleStyle: { color: "#22d3ee" }, filterMode: "none" }]
              : []),
          ]
        : [],
      series: series.map((s, i) => ({
        name: s.name,
        type: "line",
        data: s.data,
        yAxisIndex: s.yAxisIndex ?? 0,
        showSymbol: false,
        connectNulls: false,
        step: s.step ? "end" : undefined,
        sampling: "lttb",
        lineStyle: { color: s.color, width: s.width ?? 1.6, type: s.dashed ? "dashed" : "solid" },
        itemStyle: { color: s.color },
        areaStyle: s.area ? { color: s.color, opacity: 0.08 } : undefined,
        emphasis: { disabled: true },
        markLine: i === 0 && markLineData.length ? { symbol: "none", silent: true, data: markLineData } : undefined,
        markArea: i === 0 && markAreaData.length ? { silent: true, data: markAreaData } : undefined,
      })),
    };
  }, [series, thresholds, markers, bands, playhead, unit, digits, yMin, yMax, zoom, slider, y2]);

  return <EChart option={option} height={height} ariaLabel={ariaLabel} onClickX={onClickX} />;
}
