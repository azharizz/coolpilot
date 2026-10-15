import { useSyncExternalStore } from "react";

export async function request<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(
    url,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const problem = await response.json();
    throw new Error(
      typeof problem.detail === "string"
        ? problem.detail
        : "The input is invalid. Check the field limits.",
    );
  }
  return response.json();
}

type Snapshot<T> = { data: T | null; error: string | null; loading: boolean };
function resource<T>(url: string, interval: number) {
  let snapshot: Snapshot<T> = { data: null, error: null, loading: true };
  const listeners = new Set<() => void>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending = false;
  async function reload() {
    if (pending) return;
    clearTimeout(timer);
    pending = true;
    try {
      snapshot = { data: await request<T>(url), error: null, loading: false };
    } catch (error) {
      snapshot = {
        ...snapshot,
        error:
          error instanceof Error
            ? error.message
            : "Connection failed. Refresh to retry.",
        loading: false,
      };
    }
    pending = false;
    listeners.forEach((listener) => listener());
    if (listeners.size && interval) timer = setTimeout(reload, interval);
  }
  return {
    reload,
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      if (listeners.size === 1) void reload();
      return () => {
        listeners.delete(listener);
        if (!listeners.size) clearTimeout(timer);
      };
    },
  };
}

const resources = new Map<string, ReturnType<typeof resource<unknown>>>();
export function useResource<T>(url: string, interval = 2000): Snapshot<T> {
  if (!resources.has(url)) resources.set(url, resource<T>(url, interval));
  const store = resources.get(url)!;
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
  ) as Snapshot<T>;
}
export function refresh(...urls: string[]) {
  resources.forEach((store, key) => {
    if (urls.some((url) => key === url || key.startsWith(`${url}?`)))
      void store.reload();
  });
}
