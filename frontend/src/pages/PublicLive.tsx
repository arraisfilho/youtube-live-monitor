import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useParams } from "react-router";
import { api, type Live } from "../api";
import { LiveDashboard, REFRESH_MS } from "../components/LiveDashboard";
import { QuickPreferences } from "../components/QuickPreferences";
import { AppIcon } from "../components/StatusPill";
import { t } from "../i18n";

/** Page opened from the share link: only the live's metrics, without sign-in or navigation. */
export function PublicLive() {
  const { token = "" } = useParams();
  const live = useQuery({
    queryKey: ["public", token],
    queryFn: () => api.get<Live>(`/api/public/${encodeURIComponent(token)}`),
    refetchInterval: REFRESH_MS,
    retry: false,
  });

  return (
    <div className="public-page">
      <header className="public-header">
        <span className="public-brand">
          <AppIcon size="sm" />
          <strong>Live Monitor</strong>
        </span>
        <QuickPreferences />
      </header>
      <main id="main" className="public-main">
        {live.isError ? (
          <div className="empty-state">
            <p className="headline">{t("Link indisponível")}</p>
            <p className="muted">{t("O compartilhamento desta live foi desligado ou o link mudou.")}</p>
          </div>
        ) : !live.data ? (
          <div className="skeleton skeleton-panel" />
        ) : (
          <>
            <header className="page-heading">
              <div>
                <h1>{live.data.title || live.data.video_id}</h1>
                <p className="page-subtitle">{live.data.channel_name}</p>
              </div>
              <a className="button button-outline" href={live.data.youtube_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={16} aria-hidden="true" />
                {t("Assistir no YouTube")}
              </a>
            </header>
            <LiveDashboard live={live.data} seriesPath={`/api/public/${encodeURIComponent(token)}/series`} />
            <p className="footnote muted public-footer">{t("Atualiza a cada 15 s.")}</p>
          </>
        )}
      </main>
    </div>
  );
}
