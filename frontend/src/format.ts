import { getLocale } from "./i18n";

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>();
function number(options: Intl.NumberFormatOptions) {
  const key = `n:${getLocale()}:${JSON.stringify(options)}`;
  if (!cache.has(key)) cache.set(key, new Intl.NumberFormat(getLocale(), options));
  return cache.get(key) as Intl.NumberFormat;
}
/** Date formatter in the current language, reused across calls. */
export function dateFormat(options: Intl.DateTimeFormatOptions) {
  const key = `d:${getLocale()}:${JSON.stringify(options)}`;
  if (!cache.has(key)) cache.set(key, new Intl.DateTimeFormat(getLocale(), options));
  return cache.get(key) as Intl.DateTimeFormat;
}
const INTEGER = { maximumFractionDigits: 0 };
const DECIMAL = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
const COMPACT = { notation: "compact", maximumFractionDigits: 1 } as const;

export const DASH = "—";

export const fmtInt = (value: number | null | undefined) => (value == null ? DASH : number(INTEGER).format(value));
export const fmtCompact = (value: number) => number(COMPACT).format(value);
export const fmtDecimal = (value: number, digits = 1) =>
  number({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
export const fmtPercent = (value: number | null | undefined) => (value == null ? DASH : `${number(DECIMAL).format(value)}%`);
export const fmtTime = (unix: number | null | undefined) =>
  unix == null ? DASH : dateFormat({ hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(unix * 1000);
export const fmtDate = (unix: number | null | undefined) =>
  unix == null ? DASH : dateFormat({ day: "2-digit", month: "2-digit", year: "numeric" }).format(unix * 1000);
export const fmtDateTime = (unix: number | null | undefined) =>
  unix == null ? DASH : dateFormat({ day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(unix * 1000);

/** 3266 → "54:26"; 7322 → "2:02:02". */
export function fmtDuration(seconds: number | null | undefined) {
  if (seconds == null) return DASH;
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Delay against the scheduled time: "+50 s", "−3 min", "+1 h 05 min". */
export function fmtDelay(seconds: number | null | undefined) {
  if (seconds == null) return DASH;
  const sign = seconds < 0 ? "−" : "+";
  const abs = Math.abs(Math.round(seconds));
  if (abs < 60) return `${sign}${abs} s`;
  if (abs < 3600) return `${sign}${Math.round(abs / 60)} min`;
  return `${sign}${Math.floor(abs / 3600)} h ${String(Math.round((abs % 3600) / 60)).padStart(2, "0")} min`;
}

/** Short relative time in the current language, such as "now" or "45 s ago". */
export function fmtAge(seconds: number | null | undefined, t: (key: string, values?: unknown[]) => string) {
  if (seconds == null) return DASH;
  if (seconds < 5) return t("agora");
  if (seconds < 60) return t("há {0} s", [Math.round(seconds)]);
  if (seconds < 3600) return t("há {0} min", [Math.round(seconds / 60)]);
  if (seconds < 86400) return t("há {0} h", [Math.round(seconds / 3600)]);
  return t("há {0} d", [Math.round(seconds / 86400)]);
}

export function fmtBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${fmtInt(bytes / 1024)} KB`;
  return `${number(DECIMAL).format(bytes / 1024 / 1024)} MB`;
}

/** Portuguese labels; the interface passes them through t(). */
export const STATUS: Record<number, { label: string; tone: string }> = {
  0: { label: "Desconhecida", tone: "is-paused" },
  1: { label: "Agendada", tone: "is-info" },
  2: { label: "Ao vivo", tone: "is-active" },
  3: { label: "Encerrada", tone: "is-ended" },
  4: { label: "Indisponível", tone: "is-warning" },
};
