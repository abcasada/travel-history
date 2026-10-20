import { useEffect, useRef, useState } from "react";
import {
  Group,
  type Layout,
  Panel,
  Separator,
  useGroupRef,
  usePanelRef,
} from "react-resizable-panels";
import { NavLink, useNavigate } from "react-router";
import { BaseMap } from "../map/BaseMap";
import { ListRoutes } from "../pages/routes";
import { useShortcuts } from "../platform/shortcuts";
import { usePreference } from "../prefs/usePreference";
import { ShellMenu } from "./ShellMenu";
import { ShortcutHelp } from "./ShortcutHelp";

const NAV = [
  { to: "/", label: "Map", key: "m" },
  { to: "/trips", label: "Trips", key: "t" },
  { to: "/review", label: "Review", key: "r" },
  { to: "/stats", label: "Stats", key: "s" },
  { to: "/vehicles", label: "Vehicles", key: "v" },
  { to: "/history", label: "History", key: "h" },
] as const;

export const DEFAULT_LAYOUT: Layout = { list: 32, map: 68 };
const STEP = 5;

/** Desktop shell: list and map side by side; the divider position is a per-user, per-device-
 * class preference stored on the server (PLAN.md §18.2). */
export default function DesktopShell() {
  const [layout, setLayout] = usePreference<Layout>("split_layout", "desktop", DEFAULT_LAYOUT);
  const groupRef = useGroupRef();
  const listRef = usePanelRef();
  const search = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [helpOpen, setHelpOpen] = useState(false);

  // Apply a layout that arrived from the server after the first render.
  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    const current = group.getLayout();
    if (Math.abs((current.list ?? 0) - (layout.list ?? 0)) > 0.5) group.setLayout(layout);
  }, [layout, groupRef]);

  const resizeList = (delta: number) => {
    const list = groupRef.current?.getLayout().list ?? DEFAULT_LAYOUT.list ?? 32;
    const next = Math.min(60, Math.max(15, list + delta));
    groupRef.current?.setLayout({ list: next, map: 100 - next });
  };

  useShortcuts({
    "?": () => setHelpOpen((open) => !open),
    "/": () => search.current?.focus(),
    Escape: () => setHelpOpen(false),
    "[": () => resizeList(-STEP),
    "]": () => resizeList(STEP),
    "\\": () => {
      const panel = listRef.current;
      if (!panel) return;
      if (panel.isCollapsed()) panel.expand();
      else panel.collapse();
    },
    ...Object.fromEntries(NAV.map((item) => [`g ${item.key}`, () => navigate(item.to)])),
  });

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b bg-white px-4 py-2">
        <span className="font-semibold text-blue-800">◉ Travel</span>
        <nav className="flex gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded px-2 py-1 text-sm ${isActive ? "bg-blue-100 text-blue-900" : "hover:bg-slate-100"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <input
          ref={search}
          type="search"
          placeholder="Search  /"
          aria-label="Search"
          className="ml-auto w-64 rounded border px-2 py-1 text-sm"
        />
        <ShellMenu />
      </header>
      <Group
        orientation="horizontal"
        className="min-h-0 flex-1"
        defaultLayout={layout}
        groupRef={groupRef}
        onLayoutChanged={(next) => setLayout(next)}
      >
        <Panel id="list" minSize="15%" maxSize="60%" collapsible panelRef={listRef}>
          <div className="h-full overflow-auto bg-white">
            <ListRoutes />
          </div>
        </Panel>
        <Separator className="w-1.5 bg-slate-200 outline-none hover:bg-blue-400 focus-visible:bg-blue-500" />
        <Panel id="map">
          <BaseMap />
        </Panel>
      </Group>
      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
    </div>
  );
}
