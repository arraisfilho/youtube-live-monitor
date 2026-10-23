import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { Card } from "../design-kit/ui";
import { DASH, dateFormat, fmtCompact } from "../format";
import { t } from "../i18n";

export type Zoom = [number, number] | null;

const defaultFormat = (value: number) => fmtCompact(value);
// Axis steps for counts: never fractional, so 0 and 1 are not repeated.
const INTEGER_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
const readoutFormat = () => dateFormat({ day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hourFormat = () => dateFormat({ hour: "2-digit", minute: "2-digit" });
const secondFormat = () => dateFormat({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayFormat = () => dateFormat({ day: "2-digit", month: "2-digit" });

/** Time axis labels in the current language: seconds on short ranges, day/month on long ones. */
function timeLabels(u: uPlot, splits: number[]) {
  const span = (u.scales.x.max ?? 0) - (u.scales.x.min ?? 0);
  const format = (span > 2 * 86400 ? dayFormat : span < 600 ? secondFormat : hourFormat)();
  return splits.map((ts) => format.format(ts * 1000));
}

export function token(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A token color with transparency, for the area fill. */
export function withAlpha(color: string, alpha: number) {
  const hex = color.replace("#", "");
  if (/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(hex)) {
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  const rgb = color.match(/\d+(\.\d+)?/g);
  return rgb && rgb.length >= 3 ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})` : color;
}

/** Changes with the theme (user or system choice), so the chart is redrawn with the new colors. */
export function useThemeVersion() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const observer = new MutationObserver(bump);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", bump);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", bump);
    };
  }, []);
  return version;
}

/** Height proportional to width: on large screens the chart grows and shows more detail. */
const SIZES = { regular: { ratio: 0.5, min: 200, max: 460 }, large: { ratio: 0.3, min: 260, max: 640 } };
function heightFor(width: number, size: keyof typeof SIZES) {
  const { ratio, min, max } = SIZES[size];
  return Math.round(Math.min(max, Math.max(min, width * ratio)));
}

export function toData(points: [number, number][]): uPlot.AlignedData {
  return [points.map((p) => p[0]), points.map((p) => p[1])];
}

/**
 * Time series on uPlot. Charts with the same `syncKey` share the cursor; with `onZoom`,
 * dragging selects a range (applied to all of them by the parent) and a double click restores the full range.
 */
export function TimeChart({
  title,
  points,
  format = defaultFormat,
  size = "regular",
  syncKey,
  zoom = null,
  onZoom,
  color = "--action",
  integer = false,
}: {
  title: string;
  /** Series color token, such as "--chart-green". */
  color?: string;
  /** Counts: integer-only vertical axis starting at zero. */
  integer?: boolean;
  points: [number, number][] | undefined;
  format?: (value: number) => string;
  size?: "regular" | "large";
  syncKey?: string;
  zoom?: Zoom;
  onZoom?: (zoom: Zoom) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLSpanElement>(null);
  const chart = useRef<uPlot | null>(null);
  const latest = useRef({ points, zoom, onZoom, format });
  latest.current = { points, zoom, onZoom, format };
  const theme = useThemeVersion();
  const empty = !points || points.length === 0;

  // Creates the chart once per theme and size kind; data and zoom arrive through the next effect.
  useEffect(() => {
    const element = container.current;
    const initial = latest.current.points;
    if (!element || !initial || initial.length === 0) return;
    const action = token(color) || token("--action");
    const muted = token("--muted");
    const grid = token("--separator");
    const font = `12px ${token("--font-ui") || "system-ui"}`;
    const axis = { stroke: muted, font, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };
    const zoomable = Boolean(latest.current.onZoom);
    const u = new uPlot(
      {
        width: element.clientWidth,
        height: heightFor(element.clientWidth, size),
        legend: { show: false },
        cursor: {
          sync: syncKey ? { key: syncKey } : undefined,
          drag: { x: zoomable, y: false, setScale: false },
          points: { size: 7, fill: action },
        },
        scales: {
          x: { time: true },
          ...(integer ? { y: { range: (_u: uPlot, _min: number, max: number) => [0, Math.max(1, Math.ceil(max))] as uPlot.Range.MinMax } } : {}),
        },
        series: [{}, { stroke: action, width: 2, fill: withAlpha(action, 0.14), points: { show: false } }],
        axes: [
          { ...axis, values: timeLabels },
          {
            ...axis,
            size: 64,
            ...(integer ? { incrs: INTEGER_STEPS } : {}),
            values: (_u, ticks) => ticks.map((tick) => latest.current.format(tick)),
          },
        ],
        hooks: {
          setCursor: [
            (plot) => {
              const target = readout.current;
              const index = plot.cursor.idx;
              if (!target) return;
              if (index == null) {
                target.textContent = "";
                return;
              }
              const value = plot.data[1][index];
              target.textContent = `${readoutFormat().format(plot.data[0][index] * 1000)} · ${value == null ? DASH : latest.current.format(value)}`;
            },
          ],
          setSelect: [
            (plot) => {
              if (plot.select.width > 4) {
                const min = plot.posToVal(plot.select.left, "x");
                const max = plot.posToVal(plot.select.left + plot.select.width, "x");
                latest.current.onZoom?.([min, max]);
              }
              plot.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            },
          ],
        },
      },
      toData(initial),
      element,
    );
    chart.current = u;
    const zoom = latest.current.zoom;
    if (zoom) u.setScale("x", { min: zoom[0], max: zoom[1] });
    const zoomOut = () => latest.current.onZoom?.(null);
    u.over.addEventListener("dblclick", zoomOut);
    const resize = new ResizeObserver(() => u.setSize({ width: element.clientWidth, height: heightFor(element.clientWidth, size) }));
    resize.observe(element);
    return () => {
      resize.disconnect();
      u.over.removeEventListener("dblclick", zoomOut);
      u.destroy();
      chart.current = null;
    };
  }, [empty, size, theme, syncKey, color, integer]);

  // New points on every refresh, keeping the selected range.
  useEffect(() => {
    const u = chart.current;
    if (!u || !points || points.length === 0) return;
    u.setData(toData(points), zoom == null);
    if (zoom) u.setScale("x", { min: zoom[0], max: zoom[1] });
  }, [points, zoom]);

  return (
    <Card className="chart-card">
      <div className="chart-head">
        <h3 className="title-3">{title}</h3>
        <span ref={readout} className="chart-readout tabular" aria-hidden="true" />
      </div>
      {empty ? (
        <p className="chart-empty muted">{t("Sem dados no período")}</p>
      ) : (
        <div ref={container} className="chart-canvas" role="img" aria-label={t("Gráfico: {0}", [title])} />
      )}
    </Card>
  );
}
