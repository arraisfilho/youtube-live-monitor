import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { AppIcon } from "../components/StatusPill";
import { QuickPreferences } from "../components/QuickPreferences";
import { Button, Card, Notice } from "../design-kit/ui";
import { t } from "../i18n";

function AuthFrame({ heading, intro, children }: { heading: string; intro: string; children: React.ReactNode }) {
  return (
    <main className="auth-page">
      <div className="auth-toolbar">
        <QuickPreferences />
      </div>
      <Card className="auth-card">
        <div className="auth-intro">
          <AppIcon size="lg" />
          <h1>Live Monitor</h1>
          <h2 className="auth-heading">{heading}</h2>
          <p>{intro}</p>
        </div>
        {children}
      </Card>
    </main>
  );
}

export function Login() {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/api/login", { password });
      await queryClient.invalidateQueries({ queryKey: ["session"] });
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : t("Não foi possível entrar"));
      setBusy(false);
    }
  };
  return (
    <AuthFrame heading={t("Entrar")} intro={t("Acompanhe suas lives do YouTube.")}>
      <form onSubmit={submit}>
        <label>
          {t("Senha")}
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <Notice tone="error">{error}</Notice>
        <Button type="submit" disabled={busy || !password}>
          {busy && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
          {t("Entrar")}
        </Button>
      </form>
    </AuthFrame>
  );
}

/** Password change: required on first sign-in and available later in Settings. */
export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && next !== confirm;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api.post("/api/password", { current, new: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setSuccess(t("Senha alterada."));
      onDone?.();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : t("Não foi possível alterar a senha"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="form-stack" onSubmit={submit}>
      <div className="field">
        <label className="field-label" htmlFor="pw-current">{t("Senha atual")}</label>
        <input id="pw-current" type="password" autoComplete="current-password" required value={current}
          onChange={(event) => setCurrent(event.target.value)} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="pw-new">{t("Nova senha")}</label>
        <input id="pw-new" type="password" autoComplete="new-password" minLength={10} required value={next}
          onChange={(event) => setNext(event.target.value)} aria-describedby="pw-help" />
        <p className="field-help" id="pw-help">{t("Pelo menos 10 caracteres.")}</p>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="pw-confirm">{t("Confirme a nova senha")}</label>
        <input id="pw-confirm" type="password" autoComplete="new-password" required value={confirm}
          aria-invalid={mismatch} onChange={(event) => setConfirm(event.target.value)} />
        {mismatch && <p className="field-error">{t("As senhas não conferem.")}</p>}
      </div>
      <Notice tone="error">{error}</Notice>
      <Notice>{success}</Notice>
      <div>
        <Button type="submit" disabled={busy || !current || next.length < 10 || mismatch}>
          {busy && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
          {t("Alterar senha")}
        </Button>
      </div>
    </form>
  );
}

export function FirstAccess() {
  const queryClient = useQueryClient();
  return (
    <AuthFrame heading={t("Defina sua senha")} intro={t("Primeiro acesso: troque a senha temporária para continuar.")}>
      <PasswordForm onDone={() => void queryClient.invalidateQueries({ queryKey: ["session"] })} />
    </AuthFrame>
  );
}
