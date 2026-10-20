import { useCallback, useSyncExternalStore } from "react";

export type ShellMode = "desktop" | "mobile";
export type ShellOverride = ShellMode | "auto";

/** Desktop shell for large screens with a precise pointer; mobile otherwise (PLAN.md §18.1). */
export const DESKTOP_QUERY = "(min-width: 1024px) and (pointer: fine)";
const OVERRIDE_KEY = "shell_override";
const listeners = new Set<() => void>();

function readOverride(): ShellOverride {
  try {
    const value = window.localStorage.getItem(OVERRIDE_KEY);
    return value === "desktop" || value === "mobile" ? value : "auto";
  } catch {
    return "auto";
  }
}

function subscribe(callback: () => void) {
  const media = window.matchMedia(DESKTOP_QUERY);
  media.addEventListener("change", callback);
  listeners.add(callback);
  return () => {
    media.removeEventListener("change", callback);
    listeners.delete(callback);
  };
}

function snapshot(): string {
  return `${window.matchMedia(DESKTOP_QUERY).matches ? "desktop" : "mobile"}|${readOverride()}`;
}

/** The override is per device (stored locally), since it describes this screen. */
export function useShellMode() {
  const [auto, override] = useSyncExternalStore(subscribe, snapshot).split("|") as [
    ShellMode,
    ShellOverride,
  ];
  const setOverride = useCallback((next: ShellOverride) => {
    try {
      if (next === "auto") window.localStorage.removeItem(OVERRIDE_KEY);
      else window.localStorage.setItem(OVERRIDE_KEY, next);
    } catch {
      // Ignore storage failures; the automatic choice still applies.
    }
    for (const listener of listeners) listener();
  }, []);
  const mode: ShellMode = override === "auto" ? auto : override;
  return { mode, auto, override, setOverride };
}
