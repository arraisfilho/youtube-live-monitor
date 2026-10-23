import { clsx } from "clsx";
import { MonitorPlay } from "lucide-react";
import { STATUS } from "../format";
import { t } from "../i18n";

export function StatusPill({ status }: { status: number }) {
  const info = STATUS[status] ?? STATUS[0];
  return <span className={clsx("status-pill", info.tone)}>{t(info.label)}</span>;
}

export function AppIcon({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  return (
    <span className={clsx("app-icon", size !== "md" && `app-icon-${size}`)} aria-hidden="true">
      <MonitorPlay strokeWidth={2.2} />
    </span>
  );
}
