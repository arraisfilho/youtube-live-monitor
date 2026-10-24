import { useEffect, useRef } from "react";
import uPlot from "uplot";
import { toData, token, useThemeVersion, withAlpha } from "./TimeChart";

/** Trend area under the value. No axes or cursor. */
export function Sparkline({ points, color }: { points: [number, number][] | undefined; color: string }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<uPlot | null>(null);
  const latest = useRef(points);
  latest.current = points;
  const theme = useThemeVersion();
  const empty = !points || points.length < 2;

  useEffect(() => {
    const element = container.current;
    const initial = latest.current;
    if (!element || !initial || initial.length < 2) return;
    const stroke = token(color) || token("--action");
    const u = new uPlot(
      {
        width: element.clientWidth,
        height: element.clientHeight,
        legend: { show: false },
        cursor: { show: false },
        select: { show: false, left: 0, top: 0, width: 0, height: 0 },
        axes: [{ show: false }, { show: false }],
        scales: { x: { time: true }, y: { range: (_u, min, max) => (min === max ? [min, max + 1] : [min, max]) } },
        series: [{}, { stroke, width: 1.5, fill: withAlpha(stroke, 0.18), points: { show: false } }],
        padding: [2, 0, 0, 0],
      },
      toData(initial),
      element,
    );
    chart.current = u;
    const resize = new ResizeObserver(() => u.setSize({ width: element.clientWidth, height: element.clientHeight }));
    resize.observe(element);
    return () => {
      resize.disconnect();
      u.destroy();
      chart.current = null;
    };
  }, [empty, theme, color]);

  useEffect(() => {
    if (chart.current && points && points.length >= 2) chart.current.setData(toData(points));
  }, [points]);

  return <div ref={container} className="stat-spark" aria-hidden="true" />;
}
