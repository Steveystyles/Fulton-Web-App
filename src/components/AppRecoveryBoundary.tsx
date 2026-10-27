import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };
const routeReloadKey = "fultons-stale-route-reload";
const routeReloadWindowMs = 60_000;

export function canRecoverStaleRoute(
  error: unknown,
  loadedPath: string,
  currentPath: string,
  lastAttempt: number,
  now: number,
): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return currentPath !== loadedPath
    && /Failed to fetch dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk .* failed/i.test(message)
    && (!Number.isFinite(lastAttempt) || now - lastAttempt > routeReloadWindowMs);
}

/** Keep a stale lazy-loaded route from turning the entire app into a blank page. */
export class AppRecoveryBoundary extends Component<Props, State> {
  private readonly loadedPath = typeof window === "undefined" ? "" : window.location.pathname;
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    if (typeof window === "undefined") return;
    try {
      const now = Date.now();
      const lastAttempt = Number(window.sessionStorage.getItem(routeReloadKey) || 0);
      if (!canRecoverStaleRoute(error, this.loadedPath, window.location.pathname, lastAttempt, now)) return;
      window.sessionStorage.setItem(routeReloadKey, String(now));
      window.location.reload();
    } catch { /* Without session storage, keep the visible manual reload. */ }
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="saints-shell-bg flex min-h-dvh items-center justify-center px-4 text-slate-950">
        <div role="alert" className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
          <p className="text-2xl font-black">Couldn't open this screen</p>
          <p className="mt-3 text-sm leading-6 text-slate-700">
            The site may have updated while this tab was open. Reload to continue.
          </p>
          <button
            type="button"
            className="saints-focus mt-5 min-h-11 rounded-xl bg-saints-black px-5 font-bold text-white"
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </div>
      </main>
    );
  }
}
