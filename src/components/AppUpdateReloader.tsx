import { useEffect, useRef, useState } from "react";

const clientVersion = import.meta.env.VITE_FULTONS_BUILD_COMMIT as string | undefined;
const autoReloadKey = "fultons-auto-update-version";
const idleRoutes = new Set(["/", "/today", "/scores", "/scores/history", "/leaderboard"]);

export function canApplyUpdateWithoutInterrupting(pathname: string, doc: Document): boolean {
  if (!idleRoutes.has(pathname.replace(/\/+$/, "") || "/")) return false;
  if (doc.querySelector('dialog[open], [role="dialog"]')) return false;
  const fields = doc.querySelectorAll('input:not([type="hidden"]), textarea, select, [contenteditable="true"]');
  for (const field of fields) {
    if (field === doc.activeElement) return false;
    if ("value" in field && typeof field.value === "string" && field.value.trim()) return false;
    if ("isContentEditable" in field && field.isContentEditable && field.textContent?.trim()) return false;
  }
  return true;
}

/** Never interrupt a game, form or unsent selection with an automatic reload. */
export function AppUpdateReloader() {
  const initialVersion = useRef<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    let disposed = false;
    let checking = false;
    let pending: AbortController | null = null;
    async function check() {
      if (checking || document.visibilityState === "hidden") return;
      checking = true;
      const controller = new AbortController();
      pending = controller;
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(`/api/health?updateCheck=${Date.now()}`, { cache: "no-store", signal: controller.signal });
        const payload = await response.json();
        const version = payload?.build?.version;
        if (!disposed && typeof version === "string" && version) {
          const loadedVersion = clientVersion && clientVersion !== "unknown" ? clientVersion : initialVersion.current;
          if (loadedVersion === null) initialVersion.current = version;
          else if (version !== loadedVersion) {
            if (canApplyUpdateWithoutInterrupting(window.location.pathname, document)) {
              try {
                if (window.sessionStorage.getItem(autoReloadKey) !== version) {
                  window.sessionStorage.setItem(autoReloadKey, version);
                  window.location.reload();
                  return;
                }
              } catch { /* If storage is unavailable, offer the manual update instead. */ }
            }
            setAvailable(true);
          } else {
            try { window.sessionStorage.removeItem(autoReloadKey); } catch { /* Storage may be unavailable. */ }
          }
        }
      } catch { /* A failed update check must not block play. */ }
      finally { checking = false; window.clearTimeout(timeout); }
    }
    void check();
    const interval = window.setInterval(() => void check(), 5 * 60 * 1000);
    const focus = () => void check();
    window.addEventListener("focus", focus);
    return () => { disposed = true; pending?.abort(); window.clearInterval(interval); window.removeEventListener("focus", focus); };
  }, []);
  if (!available || dismissed) return null;
  return <aside role="status" className="fixed left-3 right-3 top-3 z-2000 mx-auto max-w-md rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-950 shadow-xl">
    <p className="font-black">An update is ready</p>
    <p className="mt-1">Finish and save your current game first. Updating reloads this page.</p>
    <div className="mt-3 flex gap-3">
      <button className="min-h-11 rounded-lg bg-saints-black px-4 font-bold text-white saints-focus" onClick={() => window.location.reload()}>Update now</button>
      <button className="min-h-11 rounded-lg border px-4 font-bold saints-focus" onClick={() => setDismissed(true)}>Later</button>
    </div>
  </aside>;
}
