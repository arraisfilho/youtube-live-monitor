import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, MonitorPlay, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, ApiError, type Live } from "../api";
import { REFRESH_MS } from "../components/LiveDashboard";
import { PageHeading } from "../components/Shell";
import { StatusPill } from "../components/StatusPill";
import { Button, Card, Notice } from "../design-kit/ui";
import { fmtInt } from "../format";
import { t } from "../i18n";

export function Lives() {
  const queryClient = useQueryClient();
  const lives = useQuery({ queryKey: ["lives"], queryFn: () => api.get<Live[]>("/api/lives"), refetchInterval: REFRESH_MS });
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [added, setAdded] = useState("");
  const add = useMutation({
    mutationFn: (value: string) => api.post<Live>("/api/lives", { url: value }),
    onSuccess: (live) => {
      setUrl("");
      setError("");
      setAdded(t("Live {0} cadastrada. A primeira leitura chega em até 15 s.", [live.video_id]));
      void queryClient.invalidateQueries({ queryKey: ["lives"] });
    },
    onError: (exc) => {
      setAdded("");
      setError(exc instanceof ApiError ? exc.message : t("Não foi possível cadastrar"));
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (url.trim()) add.mutate(url.trim());
  };
  const items = lives.data ?? [];
  const live = items.filter((item) => item.status === 2).length;

  return (
    <div className="page-narrow">
      <PageHeading
        title={t("Lives")}
        subtitle={lives.data ? t(items.length === 1 ? "{0} cadastrada · {1} ao vivo" : "{0} cadastradas · {1} ao vivo", [items.length, live]) : undefined}
      />
      <Card className="add-card">
        <form className="add-form" onSubmit={submit}>
          <div className="field">
            <label className="field-label" htmlFor="live-url">{t("URL ou ID do vídeo")}</label>
            <input
              id="live-url"
              inputMode="url"
              autoComplete="off"
              placeholder={t("https://www.youtube.com/watch?v=… ou AbCdEfGhI12")}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              aria-invalid={Boolean(error)}
              aria-describedby="live-url-help"
            />
            <p className="field-help" id="live-url-help">{t("Aceita links watch, youtu.be, /live, shorts, embed e YouTube Studio.")}</p>
          </div>
          <Button type="submit" disabled={add.isPending || !url.trim()}>
            {add.isPending ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
            {t("Adicionar")}
          </Button>
        </form>
        <Notice tone="error">{error}</Notice>
        <Notice>{added}</Notice>
      </Card>

      {lives.isPending ? (
        <div className="list-group">
          <div className="list-row"><span className="skeleton skeleton-line" style={{ width: "60%" }} /></div>
          <div className="list-row"><span className="skeleton skeleton-line" style={{ width: "45%" }} /></div>
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <MonitorPlay size={40} className="empty-icon" aria-hidden="true" />
          <p className="headline">{t("Nenhuma live cadastrada")}</p>
          <p className="muted">{t("Cole o link de uma transmissão acima para começar.")}</p>
        </div>
      ) : (
        <section className="list-section">
          <div className="list-group">
            {items.map((item) => (
              <div key={item.video_id} className="list-row is-link live-row">
                <img className="live-thumb" src={item.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" />
                <div className="live-row-text">
                  <Link className="stretched-link live-row-title" to={`/lives/${item.video_id}`}>
                    {item.title || item.video_id}
                  </Link>
                  <span className="muted">{item.channel_name || t("Aguardando a primeira leitura")}</span>
                </div>
                <div className="live-row-meta">
                  {item.status === 2 && item.metrics.concurrent_viewers != null && (
                    <span className="tabular">{t("{0} assistindo", [fmtInt(item.metrics.concurrent_viewers)])}</span>
                  )}
                  {item.enabled === false ? <span className="status-pill is-paused">{t("Pausada")}</span> : <StatusPill status={item.status} />}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
