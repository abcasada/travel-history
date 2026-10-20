import { csrfToken } from "../api/client";
import { useMe } from "../auth/AuthGate";
import { type ShellOverride, useShellMode } from "./useShellMode";

const LABELS: Record<ShellOverride, string> = {
  auto: "Automatic layout",
  desktop: "Desktop layout",
  mobile: "Mobile layout",
};

/** Account menu: who is signed in, the manual layout switch, and sign-out. */
export function ShellMenu() {
  const me = useMe();
  const { override, setOverride } = useShellMode();
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded px-2 py-1 hover:bg-slate-100">
        {me.display_name || me.email}
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border bg-white p-2 shadow-lg">
        <label className="block text-sm text-slate-600" htmlFor="shell-override">
          Layout
        </label>
        <select
          id="shell-override"
          className="mb-2 w-full rounded border px-2 py-1"
          value={override}
          onChange={(e) => setOverride(e.target.value as ShellOverride)}
        >
          {(Object.keys(LABELS) as ShellOverride[]).map((key) => (
            <option key={key} value={key}>
              {LABELS[key]}
            </option>
          ))}
        </select>
        <form method="post" action="/auth/logout">
          <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken() ?? ""} />
          <button type="submit" className="w-full rounded px-2 py-1 text-left hover:bg-slate-100">
            Sign out
          </button>
        </form>
      </div>
    </details>
  );
}
