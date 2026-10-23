import { clsx } from "clsx";
import { Globe, Monitor, Moon, Sun, SunMoon } from "lucide-react";
import { setAppearance, useAppearance, type Appearance } from "../design-kit/appearance";
import { ContextMenu } from "../design-kit/ui";
import { setLanguage, t, useLanguage, type Language } from "../i18n";

const LANGUAGES: { value: Language; label: string; lang: string }[] = [
  { value: "pt", label: "Português", lang: "pt-BR" },
  { value: "en", label: "English", lang: "en" },
  { value: "es", label: "Español", lang: "es" },
];

const THEMES: { value: Appearance; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "Sistema", Icon: Monitor },
  { value: "light", label: "Claro", Icon: Sun },
  { value: "dark", label: "Escuro", Icon: Moon },
];

/** Simplified SVG flags: flag emoji do not render on Windows. */
function Flag({ language }: { language: Language }) {
  if (language === "en")
    return (
      <svg viewBox="0 0 30 20" aria-hidden="true">
        <rect width="30" height="20" fill="#b22234" />
        {[2, 6, 10, 14, 18].map((y) => (
          <rect key={y} y={y - 0.75} width="30" height="1.5" fill="#fff" />
        ))}
        <rect width="13" height="10.5" fill="#3c3b6e" />
      </svg>
    );
  if (language === "es")
    return (
      <svg viewBox="0 0 30 20" aria-hidden="true">
        <rect width="30" height="20" fill="#aa151b" />
        <rect y="5" width="30" height="10" fill="#f1bf00" />
      </svg>
    );
  return (
    <svg viewBox="0 0 30 20" aria-hidden="true">
      <rect width="30" height="20" fill="#009c3b" />
      <path d="M15 2.5 27 10 15 17.5 3 10Z" fill="#ffdf00" />
      <circle cx="15" cy="10" r="4.2" fill="#002776" />
    </svg>
  );
}

/**
 * Language and appearance as two small icons that open their options (flags and theme icons).
 * `placement` "up" opens the menu upwards, at the foot of the sidebar;
 * "down" opens it downwards and right-aligned, at the top of the screens.
 */
export function QuickPreferences({ placement = "down" }: { placement?: "up" | "down" }) {
  const language = useLanguage();
  const appearance = useAppearance();
  const current = LANGUAGES.find((item) => item.value === language) ?? LANGUAGES[0];
  const theme = THEMES.find((item) => item.value === appearance) ?? THEMES[0];
  const menuClass = clsx("pref-menu", placement === "up" && "is-up");
  return (
    <div className="quick-prefs">
      <ContextMenu
        className={menuClass}
        align={placement === "down" ? "end" : "start"}
        summaryClassName="pref-trigger"
        summaryLabel={t("Idioma: {0}", [current.label])}
        label={<Globe size={18} aria-hidden="true" />}
      >
        <div className="pref-options" role="group" aria-label={t("Idioma")}>
          {LANGUAGES.map((item) => (
            <button
              key={item.value}
              type="button"
              className="pref-option"
              lang={item.lang}
              aria-label={item.label}
              title={item.label}
              aria-pressed={item.value === language}
              onClick={() => setLanguage(item.value)}
            >
              <Flag language={item.value} />
            </button>
          ))}
        </div>
      </ContextMenu>
      <ContextMenu
        className={menuClass}
        align={placement === "down" ? "end" : "start"}
        summaryClassName="pref-trigger"
        summaryLabel={t("Aparência: {0}", [t(theme.label)])}
        label={<SunMoon size={18} aria-hidden="true" />}
      >
        <div className="pref-options" role="group" aria-label={t("Aparência")}>
          {THEMES.map(({ value, label, Icon }) => (
            <button
              key={value}
              type="button"
              className="pref-option"
              aria-label={t(label)}
              title={t(label)}
              aria-pressed={appearance === value}
              onClick={() => setAppearance(value)}
            >
              <Icon size={18} aria-hidden="true" />
            </button>
          ))}
        </div>
      </ContextMenu>
    </div>
  );
}
