"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

/**
 * Fetch-on-mount with a manual `reload()`, written to satisfy the "Rules of React"
 * lint rules (react-hooks v7: no ref mutation during render, no synchronous setState
 * reachable from an effect body):
 * - `fetcherRef` is written inside its own effect, never during render.
 * - The fetch effect itself never calls setState synchronously — every setState call is
 *   inside a `.then()/.catch()/.finally()` callback, which runs as a microtask after the
 *   effect body has already finished executing.
 * - `reload()` just bumps a counter via `setReloadIndex`, which re-triggers the fetch
 *   effect; calling it is safe from event handlers (button clicks) since that rule only
 *   targets effect bodies, not handlers.
 */
export function useApiData<T>(fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadIndex, setReloadIndex] = useState(0);

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let cancelled = false;
    fetcherRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Something went wrong");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadIndex]);

  const reload = useCallback(() => {
    setLoading(true);
    setReloadIndex((i) => i + 1);
  }, []);

  return { data, error, loading, reload };
}
