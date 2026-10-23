import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LoaderCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Settings } from "../api";
import { PageHeading } from "../components/Shell";
import { setAppearance, useAppearance, type Appearance } from "../design-kit/appearance";
import { Button, ConfirmDialog, Notice } from "../design-kit/ui";
import { setLanguage, t, useLanguage, type Language } from "../i18n";
import { PasswordForm } from "./Auth";

const REFERENCES: Record<number, string> = { [-2]: "Fernando de Noronha", [-3]: "Brasília", [-4]: "Manaus", [-5]: "Rio Branco", 0: "Londres" };
// City names are not translated.
/** UTC−12 to UTC+14 in whole hours. Etc/GMT zones invert the sign: UTC−3 is Etc/GMT+3. */
const OFFSETS = Array.from({ length: 27 }, (_, i) => {
  const offset = i - 12;
  const sign = offset < 0 ? "−" : "+";
  const label = `UTC${sign}${String(Math.abs(offset)).padStart(2, "0")}:00${REFERENCES[offset] ? ` (${REFERENCES[offset]})` : ""}`;
  return { value: offset === 0 ? "Etc/GMT" : `Etc/GMT${offset < 0 ? "+" : "-"}${Math.abs(offset)}`, label };
});

const message = (exc: unknown) => (exc instanceof ApiError ? exc.message : t("Não foi possível salvar"));

function ApiKeySection({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const done = (data: Settings, text: string) => {
    queryClient.setQueryData(["settings"], data);
    void queryClient.invalidateQueries({ queryKey: ["health"] });
    setStatus({ tone: "success", text });
  };
  const save = useMutation({
    mutationFn: (value: string) => api.put<Settings>("/api/settings/api-key", { api_key: value }),
    onSuccess: (data) => {
      setKey("");
      done(data, t("Chave salva. Use Testar para confirmar que ela funciona."));
    },
    onError: (exc) => setStatus({ tone: "error", text: message(exc) }),
  });
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("/api/settings/api-key/test"),
    onSuccess: (data) => setStatus({ tone: data.ok ? "success" : "error", text: data.ok ? t("Chave válida.") : t("A API recusou a chave: {0}", [data.message]) }),
    onError: (exc) => setStatus({ tone: "error", text: message(exc) }),
  });
  const remove = useMutation({
    mutationFn: () => api.del<Settings>("/api/settings/api-key"),
    onSuccess: (data) => {
      setConfirm(false);
      done(data, t("Chave removida. As consultas ficam suspensas até uma nova chave ser cadastrada."));
    },
    onError: (exc) => setStatus({ tone: "error", text: message(exc) }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) save.mutate(key.trim());
  };
  const configured = settings.api_key.configured;

  return (
    <section className="list-section">
      <p className="list-section-title">YouTube Data API</p>
      <div className="list-group">
        <div className="list-row">
          <span className="list-row-label list-row-icon">
            <KeyRound size={16} aria-hidden="true" />
            {t("Chave")}
          </span>
          <span className="list-row-detail mono">{configured ? settings.api_key.masked : t("Não cadastrada")}</span>
        </div>
      </div>
      <form className="form-stack settings-form" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="api-key">{configured ? t("Substituir chave") : t("Chave da API")}</label>
          <input id="api-key" type="password" autoComplete="off" spellCheck={false} value={key}
            onChange={(event) => setKey(event.target.value)} aria-describedby="api-key-help" />
          <p className="field-help" id="api-key-help">
            {t("Crie no Google Cloud Console, ative a YouTube Data API v3 e restrinja a chave a essa API. Ela é guardada criptografada e nunca volta para a tela.")}
          </p>
        </div>
        <div className="form-actions">
          <Button type="submit" disabled={save.isPending || !key.trim()}>
            {save.isPending && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
            {t("Salvar chave")}
          </Button>
          {configured && (
            <>
              <Button type="button" variant="outline" disabled={test.isPending} onClick={() => test.mutate()}>
                {test.isPending && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
                {t("Testar")}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setConfirm(true)}>{t("Remover")}</Button>
            </>
          )}
        </div>
        <Notice tone={status?.tone ?? "success"} onDismiss={status?.tone === "error" ? () => setStatus(null) : undefined}>
          {status?.text}
        </Notice>
      </form>
      <p className="list-section-footer">{t("O teste faz uma chamada real, que consome 1 unidade da quota.")}</p>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("Remover a chave?")}
        description={t("O coletor para de consultar o YouTube até uma nova chave ser cadastrada. Os dados já coletados continuam.")}
        confirmLabel={t("Remover chave")}
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </section>
  );
}

function CollectionSection({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient();
  const [quota, setQuota] = useState(String(settings.daily_quota));
  const [interval, setIntervalValue] = useState(String(settings.live_interval));
  const [zone, setZone] = useState(settings.display_timezone);
  const [status, setStatus] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  useEffect(() => {
    setQuota(String(settings.daily_quota));
    setIntervalValue(String(settings.live_interval));
    setZone(settings.display_timezone);
  }, [settings.daily_quota, settings.live_interval, settings.display_timezone]);
  const save = useMutation({
    mutationFn: () => api.put<Settings>("/api/settings", {
      daily_quota: Number(quota), live_interval: Number(interval), display_timezone: zone,
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      setStatus({ tone: "success", text: t("Ajustes salvos. Valem a partir do próximo ciclo.") });
    },
    onError: (exc) => setStatus({ tone: "error", text: message(exc) }),
  });
  return (
    <section className="list-section">
      <p className="list-section-title">{t("Coleta")}</p>
      <form className="form-stack settings-form" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
        <div className="two-fields">
          <div className="field">
            <label className="field-label" htmlFor="quota">{t("Quota diária")}</label>
            <input id="quota" type="number" inputMode="numeric" min={1} max={1000000} value={quota}
              onChange={(event) => setQuota(event.target.value)} aria-describedby="quota-help" />
            <p className="field-help" id="quota-help">{t("O padrão do Google é 10.000 unidades por projeto.")}</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="interval">{t("Intervalo das lives ao vivo (s)")}</label>
            <input id="interval" type="number" inputMode="numeric" min={10} max={300} value={interval}
              onChange={(event) => setIntervalValue(event.target.value)} aria-describedby="interval-help" />
            <p className="field-help" id="interval-help">{t("15 s gastam até 5.760 unidades por dia com uma live 24 h no ar.")}</p>
          </div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="zone">{t("Fuso horário de exibição")}</label>
          <select id="zone" value={zone} onChange={(event) => setZone(event.target.value)}>
            {!OFFSETS.some((item) => item.value === zone) && <option value={zone}>{zone.replaceAll("_", " ")}</option>}
            {OFFSETS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </div>
        <div className="form-actions">
          <Button type="submit" variant="outline" disabled={save.isPending}>
            {save.isPending && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
            {t("Salvar ajustes")}
          </Button>
        </div>
        <Notice tone={status?.tone ?? "success"} onDismiss={status?.tone === "error" ? () => setStatus(null) : undefined}>{status?.text}</Notice>
      </form>
    </section>
  );
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const appearance = useAppearance();
  const language = useLanguage();
  if (!settings.data) return <div className="skeleton skeleton-panel" />;
  return (
    <div className="page-narrow">
      <PageHeading title={t("Configurações")} />
      <div className="page-sections">
      <ApiKeySection settings={settings.data} />
      <CollectionSection settings={settings.data} />
      <section className="list-section">
        <p className="list-section-title">{t("Senha")}</p>
        <div className="settings-form">
          <PasswordForm />
        </div>
      </section>
      <section className="list-section">
        <p className="list-section-title">{t("Idioma")}</p>
        <div className="segmented" role="group" aria-label={t("Idioma")}>
          {([["pt", "Português"], ["en", "English"], ["es", "Español"]] as [Language, string][]).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={language === value} onClick={() => setLanguage(value)}>{label}</button>
          ))}
        </div>
      </section>
      <section className="list-section">
        <p className="list-section-title">{t("Aparência")}</p>
        <div className="segmented" role="group" aria-label={t("Aparência")}>
          {([["system", "Sistema"], ["light", "Claro"], ["dark", "Escuro"]] as [Appearance, string][]).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={appearance === value} onClick={() => setAppearance(value)}>{t(label)}</button>
          ))}
        </div>
      </section>
      </div>
    </div>
  );
}
