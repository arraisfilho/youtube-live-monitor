import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, type Health as HealthData, type Series } from "../api";
import { HistoryToolbar, REFRESH_MS, Stat } from "../components/LiveDashboard";
import { DEFAULT_RANGE, rangeQuery, type TimeRange } from "../components/TimeRangePicker";
import { PageHeading } from "../components/Shell";
import { TimeChart, type Zoom } from "../components/TimeChart";
import { Card } from "../design-kit/ui";
import { DASH, fmtAge, fmtBytes, fmtDateTime, fmtDecimal, fmtInt, fmtPercent } from "../format";
import { t } from "../i18n";

const integerFormat = (value: number) => fmtInt(value);

export function Health() {
  const [range, setRange] = useState<TimeRange>(DEFAULT_RANGE);
  const [zoom, setZoom] = useState<Zoom>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<HealthData>("/api/health"), refetchInterval: REFRESH_MS });
  const series = useQuery({
    queryKey: ["health-series", range],
    queryFn: () => api.get<Series>(`/api/health/series?${rangeQuery(range)}`),
    refetchInterval: REFRESH_MS,
  });
  const h = health.data;
  if (!h) return <div className="skeleton skeleton-panel" />;
  const usage = h.quota.limit ? (h.quota.used * 100) / h.quota.limit : 0;
  const perCall = h.api_calls_total ? h.videos_polled_total / h.api_calls_total : null;

  return (
    <>
      <PageHeading title={t("Saúde do coletor")} subtitle={t("Versão {0} · ciclo a cada {1} s", [h.collector.version, h.collector.interval])} />
      {!h.api_key_configured && (
        <div className="banner warning">
          {t("Nenhuma chave da YouTube API cadastrada: as consultas estão suspensas.")} <Link to="/configuracoes">{t("Cadastrar chave")}</Link>
        </div>
      )}
      {h.quota.paused && (
        <div className="banner warning">{t("Quota diária esgotada. As consultas voltam em {0}.", [fmtDateTime(h.quota.paused_until)])}</div>
      )}
      {!h.collector.alive && <div className="banner warning">{t("O coletor parou. Reinicie o contêiner app.")}</div>}

      <section className="stat-grid stat-grid-auto" aria-label={t("Quota")}>
        <Stat label={t("Chamadas API hoje")} tone="blue" value={fmtInt(h.quota.used)} hint={t("de {0} · {1}", [fmtInt(h.quota.limit), fmtPercent(usage)])} />
        <Stat
          label={t("Quota")}
          value={<span className={h.quota.paused ? "status-pill is-danger" : usage >= 80 ? "status-pill is-warning" : "status-pill is-active"}>
            {h.quota.paused ? t("Esgotada") : usage >= 80 ? t("Acima de 80%") : t("Normal")}
          </span>}
          hint={t("Renova à meia-noite do Pacífico")}
        />
        <Stat label={t("Vídeos por chamada")} tone="teal" value={perCall == null ? DASH : fmtDecimal(perCall)} />
        <Stat label={t("Coletas adiadas")} tone="purple" value={fmtInt(h.scheduled_polls_skipped_total)} hint={t("Evitadas pela agenda adaptativa")} />
        <Stat label={t("Último sucesso")} tone="green" value={fmtAge(h.last_success_age, t)} />
        <Stat label={t("Erros consecutivos")} tone="red" value={fmtInt(h.consecutive_errors)} />
      </section>
      <section className="stat-grid stat-grid-auto" aria-label={t("Lives por estado")}>
        <Stat label={t("Lives habilitadas")} tone="teal" value={fmtInt(h.lives.enabled)} hint={t("{0} cadastradas", [fmtInt(h.lives.registered)])} />
        <Stat label={t("Agendadas")} tone="orange" value={fmtInt(h.lives.scheduled)} />
        <Stat label={t("Ao vivo")} tone="green" value={fmtInt(h.lives.live)} />
        <Stat label={t("Encerradas")} tone="purple" value={fmtInt(h.lives.ended)} />
        <Stat label={t("Indisponíveis")} tone="yellow" value={fmtInt(h.lives.unavailable)} />
        <Stat
          label={t("Banco de dados")}
          tone="sky"
          value={fmtBytes(h.db_size_bytes)}
          hint={t("Último ciclo {0}", [fmtAge(h.collector.last_cycle_at ? Date.now() / 1000 - h.collector.last_cycle_at : null, t)])}
        />
      </section>

      <HistoryToolbar range={range} onRange={setRange} zoom={zoom} onZoom={setZoom} series={series.data} />
      {series.isError && <div className="banner warning">{t("Histórico indisponível no momento.")}</div>}
      <div className="chart-grid chart-grid-pair">
        <TimeChart title={t("Chamadas à API por coleta")} points={series.data?.series.api_calls} format={integerFormat} color="--chart-blue" integer syncKey="health" zoom={zoom} onZoom={setZoom} />
        <TimeChart title={t("Lives ao vivo")} points={series.data?.series.live_lives} format={integerFormat} color="--chart-green" integer syncKey="health" zoom={zoom} onZoom={setZoom} />
      </div>
      <Card className="note-card">
        <p className="footnote muted">
          {t("Cada chamada à YouTube Data API custa 1 unidade e consulta até 50 lives de uma vez. Lives agendadas são consultadas com intervalos maiores e encerradas não são consultadas de novo.")}
        </p>
      </Card>
    </>
  );
}
