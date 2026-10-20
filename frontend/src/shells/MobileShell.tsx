import { NavLink } from "react-router";
import { BaseMap } from "../map/BaseMap";
import { ListRoutes } from "../pages/routes";
import { ShellMenu } from "./ShellMenu";

const TABS = [
  { to: "/", label: "Map" },
  { to: "/trips", label: "Trips" },
  { to: "/history", label: "History" },
] as const;

/** Mobile shell: browse and light editing; no route editor (PLAN.md §18.3). */
export function MobileShell() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b bg-white px-3 py-2">
        <span className="font-semibold text-blue-800">◉ Travel</span>
        <ShellMenu />
      </header>
      <div className="h-[45%] min-h-48">
        <BaseMap />
      </div>
      <main className="min-h-0 flex-1 overflow-auto bg-white">
        <ListRoutes />
      </main>
      <nav className="grid grid-cols-3 border-t bg-white text-center text-sm">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) => `py-3 ${isActive ? "font-semibold text-blue-800" : ""}`}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
