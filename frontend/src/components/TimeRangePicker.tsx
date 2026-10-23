import { CalendarRange } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "../design-kit/ui";
import { dateFormat } from "../format";
import { t } from "../i18n";

export type TimeRange = { kind: "relative"; seconds: number } | { kind: "absolute"; start: number; end: number };

export const QUICK_RANGES = [
  { label: "30 min", seconds: 1800 },
  { label: "1 h", seconds: 3600 },
  { label: "6 h", seconds: 21600 },
  { label: "24 h", seconds: 86400 },
  { label: "7 dias", seconds: 604800 },
];

export const DEFAULT_RANGE: TimeRange = { kind: "relative", seconds: 3600 };

/** Series API parameters for the chosen range. */
export function rangeQuery(range: TimeRange) {
  return range.kind === "relative" ? `range=${range.seconds}` : `start=${range.start}&end=${range.end}`;
}

const display = () =>
  dateFormat({ day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const pad = (value: number) => String(value).padStart(2, "0");

/** Unix time → <input type="datetime-local"> value in the browser time zone, with seconds. */
function toInput(unix: number) {
  const d = new Date(unix * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fromInput(value: string) {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : Math.round(time / 1000);
}

export function describeRange(range: TimeRange) {
  return range.kind === "absolute" ? `${display().format(range.start * 1000)} – ${display().format(range.end * 1000)}` : "";
}

/** Quick ranges and a custom range with start and end date and time, down to the second. */
export function TimeRangePicker({ value, onChange }: { value: TimeRange; onChange: (range: TimeRange) => void }) {
  const [open, setOpen] = useState(false);
  const now = Math.floor(Date.now() / 1000);
  const seed = value.kind === "absolute" ? value : { start: now - value.seconds, end: now };
  const [from, setFrom] = useState(toInput(seed.start));
  const [to, setTo] = useState(toInput(seed.end));
  const [error, setError] = useState("");

  const toggle = () => {
    if (!open) {
      const current = value.kind === "absolute" ? value : { start: now - value.seconds, end: now };
      setFrom(toInput(current.start));
      setTo(toInput(current.end));
      setError("");
    }
    setOpen(!open);
  };
  const apply = (event: FormEvent) => {
    event.preventDefault();
    const start = fromInput(from);
    const end = fromInput(to);
    if (start == null || end == null) return setError(t("Informe data e hora completas."));
    if (end - start < 60) return setError(t("O fim precisa ser pelo menos 1 minuto depois do início."));
    if (end - start > 366 * 86400) return setError(t("O período pode ter no máximo 366 dias."));
    onChange({ kind: "absolute", start, end });
    setOpen(false);
  };

  return (
    <div className="range-picker">
      <div className="range-picker-row">
        <div className="segmented" role="group" aria-label={t("Período")}>
          {QUICK_RANGES.map((item) => (
            <button
              key={item.seconds}
              type="button"
              aria-pressed={value.kind === "relative" && value.seconds === item.seconds}
              onClick={() => {
                setOpen(false);
                onChange({ kind: "relative", seconds: item.seconds });
              }}
            >
              {t(item.label)}
            </button>
          ))}
        </div>
        <Button variant={value.kind === "absolute" ? "primary" : "outline"} size="small" aria-expanded={open} onClick={toggle}>
          <CalendarRange size={16} aria-hidden="true" />
          {t("Personalizado")}
        </Button>
      </div>
      {open && (
        <form className="range-form" onSubmit={apply}>
          <div className="field">
            <label className="field-label" htmlFor="range-from">{t("De")}</label>
            <input id="range-from" type="datetime-local" step={1} value={from} max={to} onChange={(e) => setFrom(e.target.value)} required />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="range-to">{t("Até")}</label>
            <input id="range-to" type="datetime-local" step={1} value={to} min={from} onChange={(e) => setTo(e.target.value)} required />
          </div>
          <div className="range-form-actions">
            <Button type="submit" size="small">{t("Aplicar")}</Button>
            <Button type="button" variant="ghost" size="small" onClick={() => setOpen(false)}>{t("Cancelar")}</Button>
          </div>
          {error && <p className="field-error range-form-error">{error}</p>}
        </form>
      )}
    </div>
  );
}
