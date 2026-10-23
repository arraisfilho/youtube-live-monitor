import { useQueryClient } from "@tanstack/react-query";
import { HeartPulse, List, LogOut, Settings } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
import { api } from "../api";
import { Button, ContextMenu } from "../design-kit/ui";
import { t } from "../i18n";
import { QuickPreferences } from "./QuickPreferences";
import { AppIcon } from "./StatusPill";

export function Shell({ version, children }: { version: string; children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const nav = [
    { to: "/", label: t("Lives"), short: t("Lives"), icon: List, end: true },
    { to: "/saude", label: t("Saúde do coletor"), short: t("Saúde"), icon: HeartPulse, end: false },
    { to: "/configuracoes", label: t("Configurações"), short: t("Ajustes"), icon: Settings, end: false },
  ];
  const logout = async () => {
    await api.post("/api/logout").catch(() => undefined);
    queryClient.clear();
    navigate("/", { replace: true });
    await queryClient.invalidateQueries({ queryKey: ["session"] });
  };
  const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "selected" : undefined);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {t("Pular para o conteúdo")}
      </a>
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label={t("YouTube Live Monitor, início")}>
          <AppIcon />
          <span>Live Monitor</span>
        </NavLink>
        <nav aria-label={t("Navegação principal")}>
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
              <item.icon size={18} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-meta">
            <QuickPreferences placement="up" />
            <small className="system-version">v{version}</small>
          </div>
          <Button variant="ghost" onClick={() => void logout()}>
            <LogOut size={16} aria-hidden="true" />
            {t("Sair")}
          </Button>
        </div>
      </aside>
      <header className="mobile-header">
        <NavLink className="mobile-brand" to="/" aria-label={t("YouTube Live Monitor, início")}>
          <AppIcon size="sm" />
          <strong>Live Monitor</strong>
        </NavLink>
        <div className="mobile-actions">
          <QuickPreferences />
          <ContextMenu summaryClassName="pref-trigger" summaryLabel={t("Conta")} label={<LogOut size={18} aria-hidden="true" />}>
            <button type="button" className="menu-item" onClick={() => void logout()}>
              <LogOut size={18} aria-hidden="true" />
              {t("Sair")}
            </button>
          </ContextMenu>
        </div>
      </header>
      <main id="main" className="main-content" tabIndex={-1}>
        <div className="main-inner">{children}</div>
      </main>
      <nav className="mobile-nav" aria-label={t("Navegação no celular")}>
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
            <item.icon size={24} aria-hidden="true" />
            <span>{item.short}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function PageHeading({ title, subtitle, back, action }: {
  title: string;
  subtitle?: ReactNode;
  back?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {back}
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}
