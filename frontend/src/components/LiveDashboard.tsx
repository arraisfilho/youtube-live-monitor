import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useState, type ReactNode } from "react";
import { api, type Live, type Series } from "../api";
import { Button } from "../design-kit/ui";
import { fmtDate, fmtDelay, fmtDuration, fmtInt, fmtPercent, fmtTime } from "../format";
import { t } from "../i18n";
import { Sparkline } from "./Sparkline";
import { StatusPill } from "./StatusPill";
import { TimeChart, type Zoom } from "./TimeChart";
import { DEFAULT_RANGE, describeRange, rangeQuery, TimeRangePicker, type TimeRange } from "./TimeRangePicker";

export const REFRESH_MS = 15_000;

export type Tone = "blue" | "orange" | "purple" | "teal" | "sky" | "green" | "yellow" | "amber" | "red";

/** Indicator card: the value in the indicator color and, optionally, its trend over the range. */
export function Stat({ label, value, hint, tone, spark }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  spark?: [number, number][];
}) {
  return (
    <div className={clsx("stat", tone && `tone-${tone}`, spark && "has-spark")}>
      <span className="stat-label">{label}</span>
      <span className="stat-value tabular">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
      {spark && tone && <Sparkline points={spark} color={`--chart-${tone}`} />}
    </div>
  );
}

/** History title, range picker and the note about a selection or grouped points. */
export function HistoryToolbar({ range, onRange, zoom, onZoom, series }: {
  range: TimeRange;
  onRange: (range: TimeRange) => void;
  zoom: Zoom;
  onZoom: (zoom: Zoom) => void;
  series?: Series;
}) {
  const note = zoom
    ? t("Período selecionado no gráfico. Duplo clique também volta.")
    : series?.aggregated
      ? t("Período longo: pontos agrupados a cada {0} s.", [series.step])
      : t("Cada ponto é uma coleta de 15 s. Arraste num gráfico para selecionar um trecho.");
  return (
    <div className="dashboard-toolbar">
      <div className="toolbar-title">
        <h2 className="title-2">{t("Histórico")}</h2>
        <p className="footnote muted">{range.kind === "absolute" ? `${describeRange(range)} · ${note}` : note}</p>
      </div>
      {zoom && (
        <Button variant="ghost" size="small" onClick={() => onZoom(null)}>
          {t("Ver período inteiro")}
        </Button>
      )}
      <TimeRangePicker value={range} onChange={(next) => { onZoom(null); onRange(next); }} />
    </div>
  );
}

/** An ended live opens on its broadcast period; the others on the last hour. */
function initialRange(live: Live): TimeRange {
  const start = live.actual_start ? Date.parse(live.actual_start) / 1000 : NaN;
  const end = live.actual_end ? Date.parse(live.actual_end) / 1000 : NaN;
  if (live.status === 3 && Number.isFinite(start) && Number.isFinite(end) && end > start) {
    return { kind: "absolute", start: Math.floor(start) - 60, end: Math.ceil(end) + 60 };
  }
  return DEFAULT_RANGE;
}

/** Indicators and charts of a live. `seriesPath` points to the private API or to the public link API. */
export function LiveDashboard({ live, seriesPath }: { live: Live; seriesPath: string }) {
  const [range, setRange] = useState<TimeRange>(() => initialRange(live));
  const [zoom, setZoom] = useState<Zoom>(null);
  const series = useQuery({
    queryKey: ["series", seriesPath, range],
    queryFn: () => api.get<Series>(`${seriesPath}?${rangeQuery(range)}`),
    refetchInterval: REFRESH_MS,
  });
  const sync = { syncKey: `live:${seriesPath}`, zoom, onZoom: setZoom };
  const m = live.metrics;
  const s = series.data?.series;
  const hidden = m.viewer_count_available === 0 && live.status === 2;
  const scheduled = live.status === 1;

  return (
    <div className="dashboard">
      <section className="stat-grid" aria-label={t("Indicadores")}>
        <Stat label={t("Espectadores atuais")} tone="blue" spark={s?.viewers} value={fmtInt(m.concurrent_viewers)} hint={hidden ? t("Ocultos pelo canal") : undefined} />
        <Stat label={t("Pico")} tone="orange" spark={s?.peak} value={fmtInt(m.peak_viewers)} />
        <Stat label={t("Média")} tone="purple" spark={s?.average} value={fmtInt(m.average_viewers)} />
        <Stat label={t("Status")} value={<StatusPill status={live.status} />} />
        <Stat
          label={scheduled ? (m.overdue_seconds ? t("Atraso") : t("Começa em")) : t("Tempo decorrido")}
          tone="teal"
          spark={scheduled ? undefined : s?.elapsed}
          value={scheduled ? fmtDuration(m.overdue_seconds || m.seconds_until_start) : fmtDuration(m.elapsed_seconds)}
        />
        <Stat label={t("Visualizações")} tone="sky" spark={s?.views} value={fmtInt(m.total_views)} hint={m.views_since_start ? t("+{0} na live", [fmtInt(m.views_since_start)]) : undefined} />
        <Stat label={t("Curtidas")} tone="orange" spark={s?.likes} value={fmtInt(m.like_count)} />
        <Stat label={t("Comentários")} tone="purple" spark={s?.comments} value={fmtInt(m.comment_count)} />
        <Stat label={t("Engajamento")} tone="green" spark={s?.engagement} value={fmtPercent(m.engagement_rate)} />
        <Stat label={t("Atraso do início")} tone="blue" value={fmtDelay(m.scheduled_delay_seconds)} />
        <Stat label={t("Momento do pico")} tone="teal" value={fmtTime(m.peak_timestamp)} hint={m.peak_timestamp ? fmtDate(m.peak_timestamp) : undefined} />
        <Stat label={t("Tempo até o pico")} tone="yellow" value={fmtDuration(m.time_to_peak_seconds)} />
      </section>

      <HistoryToolbar range={range} onRange={setRange} zoom={zoom} onZoom={setZoom} series={series.data} />
      {series.isError && <div className="banner warning">{t("Histórico indisponível no momento. Os indicadores acima continuam atualizando.")}</div>}
      <div className="chart-grid">
        <TimeChart title={t("Espectadores")} points={s?.viewers} size="large" color="--chart-green" {...sync} />
        <TimeChart title={t("Variação de espectadores/min")} points={s?.viewer_change} color="--chart-amber" {...sync} />
        <TimeChart title={t("Novas visualizações/min")} points={s?.new_views} color="--chart-sky" {...sync} />
        <TimeChart title={t("Novas curtidas/min")} points={s?.new_likes} color="--chart-purple" {...sync} />
      </div>
    </div>
  );
}
