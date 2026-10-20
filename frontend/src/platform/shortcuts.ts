/**
 * Keyboard shortcuts adapter (PLAN.md §18.4, §19.2). Bindings are single keys ("?", "/", "[")
 * or two-key sequences ("g m"). No Ctrl/Alt/Meta combinations are ever bound, so browser and OS
 * shortcuts keep working. Keys typed into form fields are ignored, except Escape. A desktop
 * wrapper can replace this module to add global shortcuts.
 */
import { useEffect, useRef } from "react";

export type ShortcutHandler = (event: KeyboardEvent) => void;
export type ShortcutMap = Record<string, ShortcutHandler>;

const SEQUENCE_TIMEOUT_MS = 1000;

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true
  );
}

export function bindShortcuts(map: ShortcutMap, target: Window | HTMLElement = window) {
  let pending: string | null = null;
  let pendingAt = 0;

  const onKeyDown = (event: Event) => {
    const e = event as KeyboardEvent;
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (isTypingTarget(e.target) && e.key !== "Escape") return;
    const now = Date.now();
    if (pending && now - pendingAt <= SEQUENCE_TIMEOUT_MS) {
      const handler = map[`${pending} ${e.key}`];
      pending = null;
      if (handler) {
        e.preventDefault();
        handler(e);
        return;
      }
    }
    const handler = map[e.key];
    if (handler) {
      e.preventDefault();
      handler(e);
      return;
    }
    if (Object.keys(map).some((binding) => binding.startsWith(`${e.key} `))) {
      pending = e.key;
      pendingAt = now;
    }
  };
  target.addEventListener("keydown", onKeyDown);
  return () => target.removeEventListener("keydown", onKeyDown);
}

/** React hook form; the latest handlers are always used without re-binding. */
export function useShortcuts(map: ShortcutMap, enabled = true) {
  const latest = useRef(map);
  latest.current = map;
  useEffect(() => {
    if (!enabled) return;
    const proxy: ShortcutMap = {};
    for (const key of Object.keys(latest.current)) {
      proxy[key] = (event) => latest.current[key]?.(event);
    }
    return bindShortcuts(proxy);
  }, [enabled]);
}
