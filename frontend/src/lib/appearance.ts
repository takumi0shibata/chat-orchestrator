import { useEffect, useState } from "react";

export type Appearance = "system" | "light" | "dark";
const STORAGE_KEY = "orchestrator-appearance";

export function readAppearance(): Appearance {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* Storage may be unavailable in private or restricted browsers. */ }
  return "system";
}

export function applyAppearance(appearance: Appearance) {
  const dark = appearance === "dark" || (appearance === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#202022" : "#fafafa");
}

export function useAppearance() {
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);
  useEffect(() => {
    applyAppearance(appearance);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => applyAppearance(appearance);
    if (appearance === "system") media?.addEventListener("change", update);
    return () => media?.removeEventListener("change", update);
  }, [appearance]);

  useEffect(() => {
    const update = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setAppearance(readAppearance());
    };
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, []);

  const changeAppearance = (value: Appearance) => {
    try { localStorage.setItem(STORAGE_KEY, value); } catch { /* Keep the selection for this session. */ }
    setAppearance(value);
  };
  return [appearance, changeAppearance] as const;
}
