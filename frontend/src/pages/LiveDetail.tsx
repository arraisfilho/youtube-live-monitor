import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Copy, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, ApiError, type Live } from "../api";
import { LiveDashboard, REFRESH_MS } from "../components/LiveDashboard";
import { PageHeading } from "../components/Shell";
import { Button, Card, ConfirmDialog, Notice } from "../design-kit/ui";
import { t } from "../i18n";

export function LiveDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const live = useQuery({
    queryKey: ["live", id],
    queryFn: () => api.get<Live>(`/api/lives/${id}`),
    refetchInterval: REFRESH_MS,
  });
  const update = (data: Live) => {
    queryClient.setQueryData(["live", id], data);
    void queryClient.invalidateQueries({ queryKey: ["lives"] });
  };
  const onError = (exc: unknown) => setError(exc instanceof ApiError ? exc.message : t("Não foi possível salvar"));
  const patch = useMutation({
    mutationFn: (body: { enabled?: boolean; share_enabled?: boolean }) => api.patch<Live>(`/api/lives/${id}`, body),
    onSuccess: update,
    onError,
  });
  const rotate = useMutation({
    mutationFn: () => api.post<Live>(`/api/lives/${id}/share-token`),
    onSuccess: (data) => {
      update(data);
      setMessage(t("Novo link gerado. O anterior deixou de funcionar."));
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/lives/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["lives"] });
      navigate("/", { replace: true });
    },
    onError,
  });

  const back = (
    <Link className="page-back button button-ghost button-small" to="/">
      <ChevronLeft size={16} aria-hidden="true" />
      {t("Lives")}
    </Link>
  );
  if (live.isError) {
    return (
      <>
        <PageHeading title={t("Live não encontrada")} back={back} />
        <div className="banner warning">{t("Ela pode ter sido removida.")}</div>
      </>
    );
  }
  if (!live.data) return <div className="skeleton skeleton-panel" />;
  const data = live.data;
  const shareUrl = data.share_path ? `${window.location.origin}${data.share_path}` : "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setMessage(t("Link copiado."));
    } catch {
      setMessage(t("Selecione o link e copie manualmente."));
    }
  };

  return (
    <>
      <PageHeading
        title={data.title || data.video_id}
        subtitle={data.channel_name || t("Aguardando a primeira leitura")}
        back={back}
        action={
          <a className="button button-outline" href={data.youtube_url} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={16} aria-hidden="true" />
            {t("Abrir no YouTube")}
          </a>
        }
      />
      {data.enabled === false && <div className="banner warning">{t("Coleta pausada: os números abaixo são da última leitura.")}</div>}
      <LiveDashboard live={data} seriesPath={`/api/lives/${id}/series`} />

      <div className="detail-cards">
        <Card>
          <h2 className="title-3">{t("Link público")}</h2>
          <label className="switch-row">
            <span>{t("Compartilhar métricas sem login")}</span>
            <input
              className="switch"
              type="checkbox"
              checked={Boolean(data.share_enabled)}
              disabled={patch.isPending}
              onChange={(event) => patch.mutate({ share_enabled: event.target.checked })}
            />
          </label>
          {shareUrl && (
            <div className="share-box">
              <input readOnly value={shareUrl} aria-label={t("Link público")} onFocus={(event) => event.target.select()} />
              <div className="share-actions">
                <Button variant="outline" size="small" onClick={() => void copy()}>
                  <Copy size={16} aria-hidden="true" />
                  {t("Copiar")}
                </Button>
                <Button variant="ghost" size="small" disabled={rotate.isPending} onClick={() => rotate.mutate()}>
                  <RefreshCw size={16} aria-hidden="true" />
                  {t("Gerar novo link")}
                </Button>
              </div>
            </div>
          )}
          <p className="footnote muted">{t("Quem tiver o link vê os indicadores e gráficos desta live. A saúde do coletor e a quota nunca aparecem.")}</p>
        </Card>
        <Card>
          <h2 className="title-3">{t("Coleta")}</h2>
          <label className="switch-row">
            <span>{t("Monitorar esta live")}</span>
            <input
              className="switch"
              type="checkbox"
              checked={data.enabled !== false}
              disabled={patch.isPending}
              onChange={(event) => patch.mutate({ enabled: event.target.checked })}
            />
          </label>
          <Button variant="danger" size="small" onClick={() => setConfirm(true)}>
            <Trash2 size={16} aria-hidden="true" />
            {t("Remover live")}
          </Button>
        </Card>
      </div>
      <Notice>{message}</Notice>
      <Notice tone="error" onDismiss={() => setError("")}>{error}</Notice>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("Remover esta live?")}
        description={t("Ela sai da lista e deixa de ser consultada. O histórico já coletado continua guardado até o fim da retenção.")}
        confirmLabel={t("Remover")}
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
