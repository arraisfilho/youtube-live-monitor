import { useSyncExternalStore } from "react";
import en from "./locales/en.json";
import es from "./locales/es.json";

/** Portuguese texts are the keys; en and es are catalogs with the translation of each key. */
export type Language = "pt" | "en" | "es";
type Catalog = Record<string, string>;
const catalogs: Record<"en" | "es", Catalog> = { en, es };
const KEY = "app-language";
const LOCALES: Record<Language, string> = { pt: "pt-BR", en: "en-US", es: "es-ES" };
const HTML_LANG: Record<Language, string> = { pt: "pt-BR", en: "en", es: "es" };

export function detectLanguage(value: string): Language {
  const code = value.toLowerCase().split(/[-_]/)[0];
  return code === "pt" || code === "es" ? code : "en";
}

function initial(): Language {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "pt" || saved === "en" || saved === "es") return saved;
  } catch {
    /* Storage unavailable: follow the browser language. */
  }
  return typeof navigator === "undefined" ? "pt" : detectLanguage(navigator.language || "pt");
}

let language = initial();
const listeners = new Set<() => void>();

function apply() {
  if (typeof document !== "undefined") document.documentElement.lang = HTML_LANG[language];
}
apply();

export const getLanguage = () => language;
export const getLocale = () => LOCALES[language];

export function setLanguage(next: Language) {
  language = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* The choice lasts for this visit only. */
  }
  apply();
  listeners.forEach((listener) => listener());
}

export function useLanguage() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => language,
    () => "pt" as Language,
  );
}

/** Text in the current language; `{0}`, `{1}` are replaced with `values`. */
export function t(key: string, values: unknown[] = []): string {
  const text = language === "pt" ? key : catalogs[language][key] || key;
  return text.replace(/\{(\d+)\}/g, (_, index) => String(values[Number(index)] ?? ""));
}

// Server messages with values become a key with {0} before translation.
const SERVER_PATTERNS: [RegExp, string][] = [
  [/^A live (\S+) já está cadastrada$/, "A live {0} já está cadastrada"],
  [/^Muitas tentativas\. Tente de novo em (\d+) s\.$/, "Muitas tentativas. Tente de novo em {0} s."],
  [/^Video ID inválido: (.+)$/, "Endereço ou ID de vídeo inválido: {0}"],
  [/^A senha precisa ter pelo menos (\d+) caracteres$/, "A senha precisa ter pelo menos {0} caracteres"],
];

/** API error messages (in Portuguese) in the current language. */
export function translateServer(message: string): string {
  for (const [pattern, key] of SERVER_PATTERNS) {
    const match = message.match(pattern);
    if (match) return t(key, match.slice(1));
  }
  return t(message);
}
