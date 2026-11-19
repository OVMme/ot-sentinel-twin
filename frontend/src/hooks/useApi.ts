import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | null) => void;
}

/** Fetch JSON from the backend; optionally re-poll. ``path = null`` disables the request. */
export function useApi<T>(path: string | null, pollMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState<boolean>(path != null);
  const ctrl = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    if (path == null) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    try {
      const d = await api.get<T>(path, c.signal);
      if (!c.signal.aborted) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(e as Error);
    } finally {
      if (!c.signal.aborted) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(path != null);
    void reload();
    if (!pollMs || path == null) return () => ctrl.current?.abort();
    const id = window.setInterval(() => void reload(), pollMs);
    return () => {
      window.clearInterval(id);
      ctrl.current?.abort();
    };
  }, [path, pollMs, reload]);

  return { data, error, loading, reload, setData };
}
