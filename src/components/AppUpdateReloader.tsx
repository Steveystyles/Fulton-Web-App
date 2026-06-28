import { useEffect } from "react";

const buildVersionStorageKey = "fultons-app-build-version";
const buildReloadStorageKey = "fultons-app-reloaded-build-version";
const updateCheckIntervalMs = 5 * 60 * 1000;

type HealthPayload = {
  build?: {
    version?: unknown;
  };
};

function readStorage(storage: Storage | undefined, key: string) {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage | undefined, key: string, value: string) {
  try {
    storage?.setItem(key, value);
  } catch {
    // Version checks should never block the app if browser storage is unavailable.
  }
}

function removeStorage(storage: Storage | undefined, key: string) {
  try {
    storage?.removeItem(key);
  } catch {
    // Ignore storage failures; the next health check can try again.
  }
}

function browserStorage(kind: "localStorage" | "sessionStorage") {
  try {
    return window[kind];
  } catch {
    return undefined;
  }
}

function versionFromPayload(payload: HealthPayload) {
  const version = payload.build?.version;
  return typeof version === "string" && version.trim() ? version.trim() : null;
}

async function fetchServerBuildVersion(signal: AbortSignal) {
  const response = await fetch(`/api/health?updateCheck=${Date.now()}`, {
    cache: "no-store",
    credentials: "include",
    headers: {
      Accept: "application/json",
    },
    signal,
  });
  const payload = (await response.json().catch(() => null)) as HealthPayload | null;
  return payload === null ? null : versionFromPayload(payload);
}

export function AppUpdateReloader() {
  useEffect(() => {
    let disposed = false;
    let checking = false;
    const localStorage = browserStorage("localStorage");
    const sessionStorage = browserStorage("sessionStorage");
    let rememberedVersion = readStorage(localStorage, buildVersionStorageKey);
    const abortController = new AbortController();

    async function checkForUpdate() {
      if (disposed || checking || document.visibilityState === "hidden") {
        return;
      }

      checking = true;
      try {
        const serverVersion = await fetchServerBuildVersion(abortController.signal);
        if (disposed || serverVersion === null) {
          return;
        }

        const previousVersion =
          readStorage(localStorage, buildVersionStorageKey) ?? rememberedVersion;
        if (previousVersion === null) {
          rememberedVersion = serverVersion;
          writeStorage(localStorage, buildVersionStorageKey, serverVersion);
          return;
        }

        if (previousVersion === serverVersion) {
          rememberedVersion = serverVersion;
          removeStorage(sessionStorage, buildReloadStorageKey);
          return;
        }

        rememberedVersion = serverVersion;
        writeStorage(localStorage, buildVersionStorageKey, serverVersion);

        if (readStorage(sessionStorage, buildReloadStorageKey) === serverVersion) {
          return;
        }

        writeStorage(sessionStorage, buildReloadStorageKey, serverVersion);
        window.setTimeout(() => {
          if (!disposed) {
            window.location.reload();
          }
        }, 300);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
      } finally {
        checking = false;
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkForUpdate();
      }
    };
    const handleFocus = () => {
      void checkForUpdate();
    };

    void checkForUpdate();
    const intervalId = window.setInterval(() => {
      void checkForUpdate();
    }, updateCheckIntervalMs);

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleFocus);

    return () => {
      disposed = true;
      abortController.abort();
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleFocus);
    };
  }, []);

  return null;
}
