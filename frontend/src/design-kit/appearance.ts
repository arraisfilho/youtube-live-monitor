import { useSyncExternalStore } from "react";

/** Sistema follows the device; Claro and Escuro are kept on this device, like the language. */
export type Appearance = "system" | "light" | "dark";
const KEY = "app-appearance";
const listeners = new Set<() => void>();

function stored(): Appearance {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}
let current: Appearance = typeof window === "undefined" ? "system" : stored();

/**
 * data-theme on <html> (theme.css), the color-scheme meta and the theme-color metas, as the boot
 * script in index.html sets them before the first paint.
 */
export function applyAppearance(value: Appearance) {
  const root = document.documentElement;
  if (value === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", value);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", value === "system" ? "light dark" : value);
  document.querySelectorAll<HTMLMetaElement>("meta[data-scheme]").forEach((meta) => {
    const scheme = meta.getAttribute("data-scheme");
    meta.setAttribute("media", value === "system" ? `(prefers-color-scheme: ${scheme})` : scheme === value ? "all" : "not all");
  });
}

export function setAppearance(value: Appearance) {
  current = value;
  try {
    if (value === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, value);
  } catch {
    /* Storage is optional: the choice lasts for this visit. */
  }
  applyAppearance(value);
  listeners.forEach((listener) => listener());
}

export const getAppearance = () => current;

if (typeof window !== "undefined")
  // Another tab changed it.
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY) return;
    current = stored();
    applyAppearance(current);
    listeners.forEach((listener) => listener());
  });

export function useAppearance(): Appearance {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
    () => "system",
  );
}
