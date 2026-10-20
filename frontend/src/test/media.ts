/** Controllable window.matchMedia for tests (jsdom has none). */
type Listener = () => void;
const listeners = new Set<Listener>();
let desktop = true;

export function setDesktopMedia(value: boolean) {
  desktop = value;
  for (const listener of listeners) listener();
}

export function installMatchMedia() {
  window.matchMedia = (query: string) =>
    ({
      get matches() {
        return desktop;
      },
      media: query,
      onchange: null,
      addEventListener: (_: string, l: Listener) => listeners.add(l),
      removeEventListener: (_: string, l: Listener) => listeners.delete(l),
      addListener: (l: Listener) => listeners.add(l),
      removeListener: (l: Listener) => listeners.delete(l),
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
