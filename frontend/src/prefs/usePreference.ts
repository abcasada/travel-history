import { useCallback, useEffect, useRef, useState } from "react";
import { type DeviceClass, setPreference, useListPreferences } from "../api/generated";

const SAVE_DELAY_MS = 400;

function cacheKey(deviceClass: DeviceClass, key: string) {
  return `pref:${deviceClass}:${key}`;
}

function readCache<T>(deviceClass: DeviceClass, key: string): T | undefined {
  try {
    const raw = window.localStorage.getItem(cacheKey(deviceClass, key));
    return raw === null ? undefined : (JSON.parse(raw) as T);
  } catch {
    return undefined;
  }
}

function writeCache(deviceClass: DeviceClass, key: string, value: unknown) {
  try {
    window.localStorage.setItem(cacheKey(deviceClass, key), JSON.stringify(value));
  } catch {
    // Private mode / quota: the server copy still persists.
  }
}

/**
 * A user preference stored server-side (per device class) with a local cache, so the UI renders
 * immediately with the last known value and stays in sync across devices.
 */
export function usePreference<T>(
  key: string,
  deviceClass: DeviceClass,
  fallback: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => readCache<T>(deviceClass, key) ?? fallback);
  const server = useListPreferences({ device_class: deviceClass });
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const remote = server.data?.[key];
    if (remote !== undefined && !dirty.current) {
      setValue(remote as T);
      writeCache(deviceClass, key, remote);
    }
  }, [server.data, key, deviceClass]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const update = useCallback(
    (next: T) => {
      dirty.current = true;
      setValue(next);
      writeCache(deviceClass, key, next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        void setPreference(key, { value: next, device_class: deviceClass }).finally(() => {
          dirty.current = false;
        });
      }, SAVE_DELAY_MS);
    },
    [key, deviceClass],
  );

  return [value, update];
}
