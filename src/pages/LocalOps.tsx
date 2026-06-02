import { FormEvent, useEffect, useState } from "react";
import { Activity, HardDrive, KeyRound, Link2, RefreshCw, Save, ServerCog } from "lucide-react";
import { AdminOpsDashboard } from "../components/AdminOpsDashboard";
import { api, type LocalOpsConfig } from "../lib/api";

const emptyConfig: LocalOpsConfig = {
  cacheTtlSec: 15,
  sshTarget: "",
  sshPort: 22,
  sshKeyPath: "",
  sshConnectTimeoutSec: 6,
  publicHealthUrl: "",
  internalBaseUrl: "",
  internalQuizToken: "",
  composeFile: "",
  envFile: "",
  dataDir: "",
  dbPath: "",
  appPort: 3000,
};

export function LocalOps() {
  const opsUrl =
    typeof window === "undefined" ? "http://127.0.0.1:8765/ops" : `${window.location.origin}/ops`;
  const [config, setConfig] = useState<LocalOpsConfig>(emptyConfig);
  const [settingsPath, setSettingsPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [dashboardKey, setDashboardKey] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadConfig() {
      try {
        const response = await api.localOpsConfig();
        if (!active) {
          return;
        }
        setConfig(response.config);
        setSettingsPath(response.settingsPath);
      } catch (caughtError) {
        if (!active) {
          return;
        }
        setError(
          caughtError instanceof Error ? caughtError.message : "Local ops settings failed to load.",
        );
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadConfig();

    return () => {
      active = false;
    };
  }, []);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const response = await api.updateLocalOpsConfig(config);
      setConfig(response.config);
      setSettingsPath(response.settingsPath);
      setMessage("Settings saved. Dashboard reloading with the new target.");
      setDashboardKey((current) => current + 1);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : "Local ops settings were not saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  function updateField<K extends keyof LocalOpsConfig>(key: K, value: LocalOpsConfig[K]) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  return (
    <main className="min-h-dvh bg-[radial-gradient(circle_at_top,rgba(215,25,32,0.14),transparent_28rem),linear-gradient(180deg,#09090b_0%,#111827_100%)] px-4 py-6 text-white">
      <div className="mx-auto max-w-7xl">
        <section className="overflow-hidden rounded-[2rem] border border-white/10 bg-white/6 shadow-[0_24px_64px_rgba(0,0,0,0.35)] backdrop-blur">
          <div className="border-b border-white/10 px-5 py-5 sm:px-7">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-saints-red text-white">
                    <ServerCog aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </span>
                  <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] font-black uppercase tracking-[0.22em] text-white/75">
                    Local board
                  </span>
                </div>
                <h1 className="mt-4 text-3xl font-black leading-tight sm:text-4xl">
                  Fultons server ops dashboard
                </h1>
                <p className="mt-2 max-w-3xl text-sm font-semibold text-white/70 sm:text-base">
                  This route is intended for this machine only. It shows live public reachability,
                  Docker/runtime state on the home server, and tomorrow&apos;s quiz readiness
                  without needing the main app login flow.
                </p>
              </div>
              <div className="flex items-center gap-2 rounded-2xl bg-white/8 px-4 py-3 text-sm font-bold text-white/80">
                <Activity aria-hidden="true" className="h-4 w-4 text-emerald-300" strokeWidth={2.4} />
                {opsUrl}
              </div>
            </div>
          </div>

          <div className="grid gap-5 px-3 py-3 sm:px-5 sm:py-5 xl:grid-cols-[380px_minmax(0,1fr)]">
            <aside className="space-y-4">
              <section className="rounded-[1.75rem] border border-white/10 bg-slate-950/40 p-4 shadow-[0_18px_40px_rgba(0,0,0,0.2)]">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-white">
                    <KeyRound aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-lg font-black text-white">Connection settings</p>
                    <p className="mt-1 text-sm font-semibold text-white/65">
                      Edit the target and file paths here instead of changing the batch file.
                    </p>
                  </div>
                </div>

                <form className="mt-4 space-y-4" onSubmit={handleSave}>
                  <label className="block">
                    <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                      SSH target
                    </span>
                    <input
                      value={config.sshTarget}
                      onChange={(event) => updateField("sshTarget", event.target.value)}
                      className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                      placeholder="ste@192.168.0.15"
                    />
                  </label>

                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <label className="block">
                      <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                        SSH port
                      </span>
                      <input
                        value={config.sshPort}
                        onChange={(event) =>
                          updateField("sshPort", Number.parseInt(event.target.value || "0", 10) || 0)
                        }
                        className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        inputMode="numeric"
                      />
                    </label>

                    <label className="block">
                      <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                        Connect timeout
                      </span>
                      <input
                        value={config.sshConnectTimeoutSec}
                        onChange={(event) =>
                          updateField(
                            "sshConnectTimeoutSec",
                            Number.parseInt(event.target.value || "0", 10) || 0,
                          )
                        }
                        className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        inputMode="numeric"
                      />
                    </label>
                  </div>

                  <label className="block">
                    <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                      SSH key path
                    </span>
                    <input
                      value={config.sshKeyPath}
                      onChange={(event) => updateField("sshKeyPath", event.target.value)}
                      className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                    />
                  </label>

                  <label className="block">
                    <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                      Public health URL
                    </span>
                    <input
                      value={config.publicHealthUrl}
                      onChange={(event) => updateField("publicHealthUrl", event.target.value)}
                      className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                    />
                  </label>

                  <label className="block">
                    <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                      Internal base URL
                    </span>
                    <input
                      value={config.internalBaseUrl}
                      onChange={(event) => updateField("internalBaseUrl", event.target.value)}
                      className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                      placeholder="https://fultons-quiz.co.uk"
                    />
                  </label>

                  <label className="block">
                    <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                      Internal quiz token
                    </span>
                    <input
                      type="password"
                      value={config.internalQuizToken}
                      onChange={(event) => updateField("internalQuizToken", event.target.value)}
                      className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                      placeholder="Bearer token used for quiz fixes"
                    />
                  </label>

                  <details className="rounded-[1.4rem] border border-white/10 bg-white/5 px-4 py-3">
                    <summary className="cursor-pointer list-none text-sm font-black uppercase tracking-[0.18em] text-white/75">
                      Remote paths
                    </summary>
                    <div className="mt-4 space-y-3">
                      <label className="block">
                        <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                          Compose file
                        </span>
                        <input
                          value={config.composeFile}
                          onChange={(event) => updateField("composeFile", event.target.value)}
                          className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                          Env file
                        </span>
                        <input
                          value={config.envFile}
                          onChange={(event) => updateField("envFile", event.target.value)}
                          className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                          Data dir
                        </span>
                        <input
                          value={config.dataDir}
                          onChange={(event) => updateField("dataDir", event.target.value)}
                          className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                          DB path
                        </span>
                        <input
                          value={config.dbPath}
                          onChange={(event) => updateField("dbPath", event.target.value)}
                          className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs font-black uppercase tracking-[0.18em] text-white/55">
                          Remote app port
                        </span>
                        <input
                          value={config.appPort}
                          onChange={(event) =>
                            updateField("appPort", Number.parseInt(event.target.value || "0", 10) || 0)
                          }
                          className="mt-2 h-12 w-full rounded-2xl border border-white/10 bg-white/8 px-3 text-sm font-bold text-white outline-none transition focus:border-white/30 focus:ring-4 focus:ring-white/10"
                          inputMode="numeric"
                        />
                      </label>
                    </div>
                  </details>

                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <button
                      type="submit"
                      disabled={saving || loading}
                      className="flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-saints-red px-4 text-sm font-black text-white transition hover:bg-red-700 focus:outline-none focus:ring-4 focus:ring-saints-red/25 disabled:cursor-wait disabled:bg-slate-500"
                    >
                      <Save aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                      {saving ? "Saving" : "Save settings"}
                    </button>

                    <button
                      type="button"
                      onClick={() => setDashboardKey((current) => current + 1)}
                      className="flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/8 px-4 text-sm font-black text-white transition hover:bg-white/12 focus:outline-none focus:ring-4 focus:ring-white/10"
                    >
                      <RefreshCw aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                      Reload board
                    </button>
                  </div>
                </form>
              </section>

              <section className="rounded-[1.75rem] border border-white/10 bg-slate-950/40 p-4 shadow-[0_18px_40px_rgba(0,0,0,0.2)]">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-white">
                    <Link2 aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-lg font-black text-white">Board details</p>
                    <p className="mt-1 text-sm font-semibold text-white/65">
                      The startup runner now opens this page as an app-style window when Edge or
                      Chrome is available.
                    </p>
                  </div>
                </div>
                <div className="mt-4 space-y-3 rounded-[1.4rem] border border-white/10 bg-white/5 p-3 text-sm font-semibold text-white/80">
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.18em] text-white/50">
                      App URL
                    </p>
                    <p className="mt-1 break-all">{opsUrl}</p>
                  </div>
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.18em] text-white/50">
                      Settings file
                    </p>
                    <p className="mt-1 break-all">{settingsPath || "Loading..."}</p>
                  </div>
                </div>
              </section>

              {message ? (
                <p className="rounded-2xl bg-emerald-500/12 px-3 py-3 text-sm font-bold text-emerald-200 ring-1 ring-emerald-500/25">
                  {message}
                </p>
              ) : null}

              {error ? (
                <p className="rounded-2xl bg-red-500/12 px-3 py-3 text-sm font-bold text-red-100 ring-1 ring-red-500/25">
                  {error}
                </p>
              ) : null}
            </aside>

            <div className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-[1.75rem] border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/10 text-white">
                      <Activity aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                    </span>
                    <div>
                      <p className="text-xs font-black uppercase tracking-[0.18em] text-white/50">
                        Reachability
                      </p>
                      <p className="mt-1 text-sm font-semibold text-white/80">
                        Live public probe and SSH-backed remote collection
                      </p>
                    </div>
                  </div>
                </div>
                <div className="rounded-[1.75rem] border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/10 text-white">
                      <ServerCog aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                    </span>
                    <div>
                      <p className="text-xs font-black uppercase tracking-[0.18em] text-white/50">
                        Control
                      </p>
                      <p className="mt-1 text-sm font-semibold text-white/80">
                        Save target changes here, then reload the board
                      </p>
                    </div>
                  </div>
                </div>
                <div className="rounded-[1.75rem] border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/10 text-white">
                      <HardDrive aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                    </span>
                    <div>
                      <p className="text-xs font-black uppercase tracking-[0.18em] text-white/50">
                        Persistence
                      </p>
                      <p className="mt-1 text-sm font-semibold text-white/80">
                        Settings are stored locally so startup uses the same config next time
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <AdminOpsDashboard key={dashboardKey} source="local" standalone />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
