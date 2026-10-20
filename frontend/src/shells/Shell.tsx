import { lazy, Suspense } from "react";
import { MobileShell } from "./MobileShell";
import { useShellMode } from "./useShellMode";

// The desktop shell (and everything only it imports: route editor, review queue, stats) is a
// separate chunk, so phones never download it.
const DesktopShell = lazy(() => import("./DesktopShell"));

export function Shell() {
  const { mode } = useShellMode();
  if (mode === "mobile") return <MobileShell />;
  return (
    <Suspense fallback={null}>
      <DesktopShell />
    </Suspense>
  );
}
