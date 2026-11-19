import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
]);

export type EChartsOption = echarts.EChartsCoreOption;

/** Minimal React wrapper: one chart instance per mount, incremental option updates, auto-resize. */
export function EChart({ option, height = 220, ariaLabel, onClickX }: {
  option: EChartsOption;
  height?: number;
  ariaLabel: string;
  onClickX?: (x: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClickX);
  clickRef.current = onClickX;

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    c.getZr().on("click", (e: { offsetX: number; offsetY: number }) => {
      if (!clickRef.current) return;
      const p = c.convertFromPixel({ gridIndex: 0 }, [e.offsetX, e.offsetY]) as number[] | undefined;
      if (p && Number.isFinite(p[0])) clickRef.current(p[0]);
    });
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { replaceMerge: ["series"], lazyUpdate: true });
  }, [option]);

  return <div ref={ref} style={{ height }} role="img" aria-label={ariaLabel} className="w-full" />;
}
