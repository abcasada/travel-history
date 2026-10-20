import { act, renderHook } from "@testing-library/react";
import { setDesktopMedia } from "../test/media";
import { useShellMode } from "./useShellMode";

test("desktop on large screens with a precise pointer, mobile otherwise", () => {
  const { result } = renderHook(() => useShellMode());
  expect(result.current.mode).toBe("desktop");
  act(() => setDesktopMedia(false));
  expect(result.current.mode).toBe("mobile");
});

test("a manual override wins and is remembered on this device", () => {
  const { result, unmount } = renderHook(() => useShellMode());
  act(() => result.current.setOverride("mobile"));
  expect(result.current.mode).toBe("mobile");
  unmount();
  const again = renderHook(() => useShellMode());
  expect(again.result.current.mode).toBe("mobile");
  act(() => again.result.current.setOverride("auto"));
  expect(again.result.current.mode).toBe("desktop");
});
