import { type ReactNode, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Boxes,
  Cable,
  Clock3,
  Database,
  ExternalLink,
  HardDrive,
  MemoryStick,
  Network,
  RefreshCw,
  Server,
  ShieldAlert,
  TestTube2,
  Trash2,
  Zap,
  Wrench,
} from "lucide-react";
import { Card } from "./Card";
import {
  api,
  type AdminOpsSnapshot,
  type AdminOpsStatus,
  type LocalOpsActionResponse,
  type AdminOpsTest,
  type LocalOpsActionName,
} from "../lib/api";

type AdminOpsDashboardProps = {
  source?: "local";
  standalone?: boolean;
};

const LOCAL_ACTION_POLL_INTERVAL_MS = 1500;
const LOCAL_ACTION_POLL_ATTEMPTS = 180;

function waitForDelay(milliseconds: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function formatBytes(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount >= 100 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function formatPercent(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function formatTimestamp(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatUptime(seconds?: number | null) {
  if (seconds === undefined || seconds === null || seconds < 0) {
    return "n/a";
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

function statusTone(status: AdminOpsStatus) {
  if (status === "healthy") {
    return {
      pill: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-400/30",
      card: "border-emerald-400/20 bg-[linear-gradient(135deg,rgba(16,185,129,0.16),rgba(15,23,42,0.94)_38%)]",
      label: "Healthy",
    };
  }
  if (status === "offline") {
    return {
      pill: "bg-red-500/15 text-red-100 ring-1 ring-red-400/30",
      card: "border-red-500/20 bg-[linear-gradient(135deg,rgba(215,25,32,0.2),rgba(15,23,42,0.95)_38%)]",
      label: "Offline",
    };
  }
  if (status === "disabled") {
    return {
      pill: "bg-slate-500/15 text-slate-200 ring-1 ring-slate-400/20",
      card: "border-slate-500/20 bg-[linear-gradient(135deg,rgba(71,85,105,0.18),rgba(15,23,42,0.95)_38%)]",
      label: "Disabled",
    };
  }
  return {
    pill: "bg-amber-500/15 text-amber-100 ring-1 ring-amber-400/30",
    card: "border-amber-500/20 bg-[linear-gradient(135deg,rgba(245,158,11,0.18),rgba(15,23,42,0.95)_38%)]",
    label: "Degraded",
  };
}

function testTone(status: AdminOpsTest["status"]) {
  if (status === "pass") {
    return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  }
  if (status === "warn") {
    return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  }
  return "bg-red-50 text-saints-red ring-1 ring-red-200";
}

function MetricTile({
  icon,
  label,
  value,
  meta,
}: {
  icon: JSX.Element;
  label: string;
  value: string;
  meta?: string;
}) {
  return (
    <div className="rounded-[1.35rem] border border-white/10 bg-white/6 p-3 backdrop-blur">
      <div className="flex items-center gap-2 text-white/70">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-white">
          {icon}
        </span>
        <p className="text-xs font-bold uppercase tracking-[0.18em]">{label}</p>
      </div>
      <p className="mt-3 text-2xl font-black leading-none text-white">{value}</p>
      {meta ? <p className="mt-2 text-xs font-semibold text-white/65">{meta}</p> : null}
    </div>
  );
}

function SectionHeading({
  icon,
  title,
  subtitle,
  actions,
}: {
  icon: JSX.Element;
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-950 text-white">
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-lg font-black leading-tight text-slate-950">{title}</p>
          <p className="mt-1 text-sm font-semibold text-slate-600">{subtitle}</p>
        </div>
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled = false,
  busy = false,
  tone = "default",
}: {
  icon: JSX.Element;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      className={[
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-2xl px-3 py-2 text-[11px] font-black uppercase tracking-[0.18em] transition focus:outline-none focus:ring-4 disabled:cursor-wait disabled:opacity-70",
        tone === "danger"
          ? "bg-red-50 text-saints-red ring-1 ring-red-200 hover:bg-red-100 focus:ring-red-100"
          : "bg-slate-950 text-white hover:bg-slate-800 focus:ring-slate-200",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

export function AdminOpsDashboard({
  source = "local",
  standalone = false,
}: AdminOpsDashboardProps) {
  const [snapshot, setSnapshot] = useState<AdminOpsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [activeAction, setActiveAction] = useState<
    LocalOpsActionName | "run_available_fixes" | null
  >(null);

  const loadSnapshotApi = (options?: { force?: boolean }) => api.localOpsMonitor(options);

  useEffect(() => {
    let active = true;

    async function loadSnapshot(options?: { force?: boolean; silent?: boolean }) {
      if (!options?.silent) {
        setRefreshing(true);
      }
      setError("");
      try {
        const payload = await loadSnapshotApi({ force: options?.force });
        if (active) {
          setSnapshot(payload);
        }
      } catch (caughtError) {
        if (active) {
          setError(
            caughtError instanceof Error ? caughtError.message : "Ops dashboard failed to load.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    void loadSnapshot();
    const interval = window.setInterval(() => {
      void loadSnapshot({ silent: true });
    }, 15000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [source]);

  const remote = snapshot?.remote;
  const status = statusTone(snapshot?.status ?? "degraded");
  const memory = remote?.resources.memory;
  const disks = remote?.resources.disks ?? [];
  const maxDisk =
    disks
      .filter((disk) => typeof disk.usedPct === "number")
      .sort((left, right) => (right.usedPct ?? 0) - (left.usedPct ?? 0))[0] ?? null;
  const todayQuiz = remote?.quiz.today ?? null;
  const tomorrowQuiz = remote?.quiz.tomorrow ?? null;
  const tests = remote?.tests ?? [];
  const containers = remote?.docker.containers ?? [];
  const volumes = remote?.docker.volumes ?? [];
  const networks = remote?.docker.networks ?? [];
  const orphanedNetworks = networks.filter((networkInfo) => networkInfo.orphaned);
  const batteries = remote?.host.power.batteries ?? [];
  const activeQuizNeedsRepair = Boolean(todayQuiz && todayQuiz.status !== "published");
  const repairDailyQuizLabel = activeQuizNeedsRepair ? "Repair today's quiz" : "Generate tomorrow";
  const repairDailyQuizTestId = activeQuizNeedsRepair ? "today_quiz" : "tomorrow_quiz";
  const canGenerateTomorrowQuiz =
    source === "local"
    && Boolean(
      (activeQuizNeedsRepair && todayQuiz?.date)
      || (tomorrowQuiz && tomorrowQuiz.status !== "published"),
    );
  const canRegenerateTomorrowQuestions =
    source === "local" && Boolean(tomorrowQuiz?.date) && (tomorrowQuiz?.questions.length ?? 0) > 0;
  const canRemoveOrphanedNetworks = source === "local" && orphanedNetworks.length > 0;
  const hasAvailableFixes = canGenerateTomorrowQuiz || canRemoveOrphanedNetworks;

  async function waitForLocalActionJob(jobId: string) {
    let latestResponse: LocalOpsActionResponse | null = null;
    for (let attempt = 0; attempt < LOCAL_ACTION_POLL_ATTEMPTS; attempt += 1) {
      await waitForDelay(LOCAL_ACTION_POLL_INTERVAL_MS);
      latestResponse = await api.localOpsActionStatus(jobId);
      if (latestResponse.message) {
        setActionMessage(latestResponse.message);
      }
      if (latestResponse.done) {
        return latestResponse;
      }
    }
    throw new Error("The action is still running. Reload the board in a moment.");
  }

  async function performLocalAction(
    action: LocalOpsActionName,
    params?: Record<string, unknown>,
  ) {
    const response = await api.localOpsAction({ action, params });
    if (response.done || !response.jobId) {
      return response;
    }
    if (response.message) {
      setActionMessage(response.message);
    }
    return waitForLocalActionJob(response.jobId);
  }

  async function runLocalAction(
    action: LocalOpsActionName,
    params?: Record<string, unknown>,
  ) {
    if (source !== "local") {
      return;
    }
    setActiveAction(action);
    setActionMessage("");
    setActionError("");
    try {
      const response = await performLocalAction(action, params);
      if (response.status !== "succeeded") {
        throw new Error(response.error || response.message || "The requested fix action failed.");
      }
      if (response.snapshot) {
        setSnapshot(response.snapshot);
      }
      setActionMessage(response.message);
      setError("");
    } catch (caughtError) {
      setActionError(
        caughtError instanceof Error ? caughtError.message : "The requested fix action failed.",
      );
    } finally {
      setActiveAction(null);
    }
  }

  async function runAvailableFixes() {
    if (source !== "local") {
      return;
    }
    const actions: LocalOpsActionName[] = [];
    if (canGenerateTomorrowQuiz) {
      actions.push("generate_tomorrow_quiz");
    }
    if (canRemoveOrphanedNetworks) {
      actions.push("remove_orphaned_networks");
    }
    if (actions.length === 0) {
      return;
    }
    setActiveAction("run_available_fixes");
    setActionMessage("");
    setActionError("");
    try {
      let latestSnapshot: AdminOpsSnapshot | null = snapshot;
      const messages: string[] = [];
      for (const action of actions) {
        const response = await performLocalAction(action);
        if (response.status !== "succeeded") {
          throw new Error(response.error || response.message || "The requested fix action failed.");
        }
        if (response.snapshot) {
          latestSnapshot = response.snapshot;
        }
        messages.push(response.message);
      }
      if (latestSnapshot) {
        setSnapshot(latestSnapshot);
      }
      setActionMessage(messages.join(" "));
      setError("");
    } catch (caughtError) {
      setActionError(
        caughtError instanceof Error ? caughtError.message : "The requested fix actions failed.",
      );
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <div className={standalone ? "space-y-5" : "space-y-4"}>
      <Card
        className={[
          "border-slate-950 text-white shadow-[0_22px_54px_rgba(5,5,5,0.24)]",
          status.card,
        ].join(" ")}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={`rounded-full px-3 py-1 text-xs font-black uppercase tracking-[0.18em] ${status.pill}`}>
                {status.label}
              </span>
              {snapshot?.stale ? (
                <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-white/75">
                  stale
                </span>
              ) : null}
            </div>
            <p className="mt-3 text-2xl font-black leading-tight">External server control room</p>
            <p
              className={[
                "mt-2 text-sm font-semibold text-white/75",
                standalone ? "max-w-136" : "max-w-[18rem]",
              ].join(" ")}
            >
              {standalone
                ? "Live local board for the home server: Docker runtime, storage, public edge health, and tomorrow's quiz state."
                : "Live workstation probe of the home server, Docker runtime, storage, public health, and tomorrow's quiz state."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setLoading(false);
              setRefreshing(true);
              void api.localOpsMonitor({ force: true })
                .then((payload) => {
                  setSnapshot(payload);
                  setError("");
                })
                .catch((caughtError) => {
                  setError(
                    caughtError instanceof Error
                      ? caughtError.message
                      : "Ops dashboard failed to refresh.",
                  );
                })
                .finally(() => {
                  setRefreshing(false);
                });
            }}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-white transition hover:bg-white/15 focus:outline-none focus:ring-4 focus:ring-white/20"
            aria-label="Refresh ops dashboard"
          >
            <RefreshCw
              aria-hidden="true"
              className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`}
              strokeWidth={2.4}
            />
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <MetricTile
            icon={<ExternalLink className="h-4 w-4" strokeWidth={2.3} />}
            label="Public Probe"
            value={
              snapshot?.publicProbe
                ? snapshot.publicProbe.ok
                  ? "Up"
                  : "Down"
                : loading
                ? "..."
                : "Unknown"
            }
            meta={
              snapshot?.publicProbe
                ? `${snapshot.publicProbe.status ?? "?"} / ${snapshot.publicProbe.responseTimeMs}ms`
                : "Waiting for response"
            }
          />
          <MetricTile
            icon={<Server className="h-4 w-4" strokeWidth={2.3} />}
            label="SSH Snapshot"
            value={remote ? `${remote.responseTimeMs}ms` : snapshot?.enabled ? "n/a" : "off"}
            meta={remote?.host.hostname ?? snapshot?.reason ?? "No live host snapshot"}
          />
          <MetricTile
            icon={<MemoryStick className="h-4 w-4" strokeWidth={2.3} />}
            label="Memory"
            value={formatPercent(memory?.usedPct)}
            meta={
              memory
                ? `${formatBytes(memory.usedBytes)} / ${formatBytes(memory.totalBytes)}`
                : "Waiting for memory sample"
            }
          />
          <MetricTile
            icon={<HardDrive className="h-4 w-4" strokeWidth={2.3} />}
            label="Fullest Disk"
            value={maxDisk ? formatPercent(maxDisk.usedPct) : "n/a"}
            meta={maxDisk ? maxDisk.path : "Waiting for disk sample"}
          />
          <MetricTile
            icon={<TestTube2 className="h-4 w-4" strokeWidth={2.3} />}
            label="Containers"
            value={loading && snapshot === null ? "..." : String(containers.length)}
            meta={
              containers.length > 0
                ? `${containers.filter((container) => container.state === "running").length} running`
                : remote
                ? "No running containers reported"
                : "No container data yet"
            }
          />
          <MetricTile
            icon={<Zap className="h-4 w-4" strokeWidth={2.3} />}
            label="Tomorrow Quiz"
            value={tomorrowQuiz?.status ?? (loading ? "..." : "missing")}
            meta={
              tomorrowQuiz
                ? `${tomorrowQuiz.acceptedQuestions}/6 approved, ${tomorrowQuiz.failedAttempts} failed attempts`
                : "Waiting for quiz state"
            }
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-3 text-xs font-semibold text-white/65">
          <span>Updated {snapshot ? formatTimestamp(snapshot.generatedAt) : "n/a"}</span>
          <span>Cache age {snapshot ? `${snapshot.cacheAgeSec}s` : "n/a"}</span>
          {snapshot?.lastError ? <span>Last error: {snapshot.lastError}</span> : null}
        </div>
      </Card>

      {snapshot?.alerts.length ? (
        <Card>
          <SectionHeading
            icon={<ShieldAlert aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
            title="Alerts"
            subtitle="Issues that are worth checking before the box falls over."
          />
          <div className="mt-4 space-y-2">
            {snapshot.alerts.map((alert) => (
              <div
                key={alert}
                className="rounded-2xl border border-red-200 bg-red-50 px-3 py-3 text-sm font-bold text-saints-red"
              >
                {alert}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {snapshot?.enabled === false ? (
        <Card>
          <SectionHeading
            icon={<AlertTriangle aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
            title="Monitor disabled"
            subtitle="The UI is wired up, but the workstation collector is still turned off."
          />
          <p className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
            {snapshot.reason}
          </p>
        </Card>
      ) : null}

      {error ? (
        <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">{error}</p>
      ) : null}

      {source === "local" ? (
        <Card>
          <SectionHeading
            icon={<Wrench aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
            title="Quick fixes"
            subtitle="Safe local actions for the common issues this board can repair automatically."
          />
          <div className="mt-4 flex flex-wrap gap-2">
            <ActionButton
              icon={
                <RefreshCw
                  aria-hidden="true"
                  className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
                  strokeWidth={2.4}
                />
              }
              label="Refresh snapshot"
              onClick={() => {
                setLoading(false);
                setRefreshing(true);
                void loadSnapshotApi({ force: true })
                  .then((payload) => {
                    setSnapshot(payload);
                    setError("");
                  })
                  .catch((caughtError) => {
                    setError(
                      caughtError instanceof Error
                        ? caughtError.message
                        : "Ops dashboard failed to refresh.",
                    );
                  })
                  .finally(() => {
                    setRefreshing(false);
                  });
              }}
              disabled={activeAction !== null}
              busy={refreshing}
            />
            {hasAvailableFixes ? (
              <ActionButton
                icon={
                  <Wrench
                    aria-hidden="true"
                    className={`h-4 w-4 ${activeAction === "run_available_fixes" ? "animate-pulse" : ""}`}
                    strokeWidth={2.4}
                  />
                }
                label="Run available fixes"
                onClick={runAvailableFixes}
                disabled={activeAction !== null || refreshing}
                busy={activeAction === "run_available_fixes"}
              />
            ) : null}
            {canGenerateTomorrowQuiz ? (
              <ActionButton
                icon={<Zap aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                label={repairDailyQuizLabel}
                onClick={() => void runLocalAction("generate_tomorrow_quiz")}
                disabled={activeAction !== null || refreshing}
                busy={activeAction === "generate_tomorrow_quiz"}
              />
            ) : null}
            {canRemoveOrphanedNetworks ? (
              <ActionButton
                icon={<Trash2 aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                label={`Clean ${orphanedNetworks.length} orphaned network${orphanedNetworks.length === 1 ? "" : "s"}`}
                onClick={() => void runLocalAction("remove_orphaned_networks")}
                disabled={activeAction !== null || refreshing}
                busy={activeAction === "remove_orphaned_networks"}
                tone="danger"
              />
            ) : null}
          </div>
        </Card>
      ) : null}

      {actionMessage ? (
        <p className="rounded-2xl bg-emerald-50 px-3 py-3 text-sm font-bold text-emerald-700 ring-1 ring-emerald-200">
          {actionMessage}
        </p>
      ) : null}

      {actionError ? (
        <p className="rounded-2xl bg-red-50 px-3 py-3 text-sm font-bold text-saints-red ring-1 ring-red-200">
          {actionError}
        </p>
      ) : null}

      <Card>
        <SectionHeading
          icon={<ExternalLink aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Public health"
          subtitle="Direct probe from this machine to the public site, not from inside the server."
        />
        <div className="mt-4 space-y-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <a
                  href={snapshot?.publicProbe?.url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-sm font-black text-slate-950 underline decoration-slate-300 underline-offset-2"
                >
                  {snapshot?.publicProbe?.url ?? "Waiting for probe"}
                </a>
                <p className="mt-2 text-sm font-semibold text-slate-600">
                  Status {snapshot?.publicProbe?.status ?? "n/a"} /{" "}
                  {snapshot?.publicProbe ? `${snapshot.publicProbe.responseTimeMs}ms` : "n/a"}
                </p>
              </div>
              <span
                className={[
                  "rounded-full px-3 py-1 text-xs font-black uppercase tracking-[0.18em]",
                  snapshot?.publicProbe?.ok
                    ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                    : "bg-red-50 text-saints-red ring-1 ring-red-200",
                ].join(" ")}
              >
                {snapshot?.publicProbe?.ok ? "reachable" : "failing"}
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(snapshot?.publicProbe?.resolvedAddresses ?? []).map((address) => (
                <span
                  key={address}
                  className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200"
                >
                  {address}
                </span>
              ))}
            </div>
            {snapshot?.publicProbe?.error ? (
              <p className="mt-3 text-sm font-bold text-saints-red">{snapshot.publicProbe.error}</p>
            ) : null}
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Server aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Host"
          subtitle="Remote host uptime, load, power state, and when the last SSH sample landed."
        />
        <div className="mt-4 grid gap-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">
                  Hostname
                </p>
                <p className="mt-1 text-base font-black text-slate-950">
                  {remote?.host.hostname ?? "n/a"}
                </p>
              </div>
              <div>
                <p className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">
                  Uptime
                </p>
                <p className="mt-1 text-base font-black text-slate-950">
                  {formatUptime(remote?.host.uptimeSeconds)}
                </p>
              </div>
              <div>
                <p className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">
                  Load average
                </p>
                <p className="mt-1 text-base font-black text-slate-950">
                  {remote?.host.loadAverage?.join(" / ") ?? "n/a"}
                </p>
              </div>
              <div>
                <p className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">
                  Sample time
                </p>
                <p className="mt-1 text-base font-black text-slate-950">
                  {formatTimestamp(remote?.generatedAt)}
                </p>
              </div>
            </div>
          </div>

          {batteries.length > 0 || typeof remote?.host.power.acOnline === "boolean" ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center gap-2">
                <AlertTriangle aria-hidden="true" className="h-4 w-4 text-saints-red" />
                <p className="text-sm font-black text-slate-950">Power</p>
              </div>
              <p className="mt-2 text-sm font-semibold text-slate-700">
                AC online: {remote?.host.power.acOnline === true ? "yes" : remote?.host.power.acOnline === false ? "no" : "unknown"}
              </p>
              <div className="mt-3 space-y-2">
                {batteries.map((battery) => (
                  <div
                    key={battery.name}
                    className="rounded-2xl bg-white px-3 py-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-200"
                  >
                    <p className="font-black text-slate-950">{battery.name}</p>
                    <p className="mt-1">
                      {String(battery.status ?? "unknown")} / capacity {String(battery.capacityPct ?? "n/a")}%
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Activity aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Resources"
          subtitle="Memory and filesystem pressure on the remote box."
        />
        <div className="mt-4 grid gap-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">
                  Memory used
                </p>
                <p className="mt-1 text-2xl font-black text-slate-950">
                  {formatPercent(memory?.usedPct)}
                </p>
              </div>
              <p className="text-sm font-semibold text-slate-600">
                {memory ? `${formatBytes(memory.usedBytes)} / ${formatBytes(memory.totalBytes)}` : "n/a"}
              </p>
            </div>
          </div>
          <div className="space-y-3">
            {disks.map((disk) => (
              <div
                key={`${disk.path}-${disk.mountPoint ?? ""}`}
                className="rounded-2xl border border-slate-200 bg-white p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-black text-slate-950">{disk.path}</p>
                    <p className="mt-1 text-xs font-semibold text-slate-500">
                      {disk.mountPoint ?? "mount unknown"}
                      {disk.source ? ` / ${disk.source}` : ""}
                      {disk.fsType ? ` / ${disk.fsType}` : ""}
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-700">
                    {formatPercent(disk.usedPct)}
                  </span>
                </div>
                <p className="mt-3 text-sm font-semibold text-slate-700">
                  {formatBytes(disk.usedBytes)} used / {formatBytes(disk.totalBytes)} total
                </p>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Boxes aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Containers"
          subtitle="Per-container health, restart count, resource usage, mounts, and published ports."
        />
        <div className="mt-4 space-y-3">
          {containers.map((container) => (
            <article
              key={container.name}
              className="rounded-[1.4rem] border border-slate-200 bg-slate-50 p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-base font-black text-slate-950">{container.name}</p>
                  <p className="mt-1 truncate text-xs font-semibold text-slate-500">
                    {container.image}
                  </p>
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <span className="rounded-full bg-slate-950 px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] text-white">
                    {container.state}
                  </span>
                  {container.health ? (
                    <span
                      className={[
                        "rounded-full px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em]",
                        container.health === "healthy"
                          ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                          : "bg-red-50 text-saints-red ring-1 ring-red-200",
                      ].join(" ")}
                    >
                      {container.health}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-sm font-semibold text-slate-700 sm:grid-cols-2">
                <p>CPU {formatPercent(container.cpuPct)}</p>
                <p>Memory {formatPercent(container.memory.usedPct)}</p>
                <p>Restart count {container.restarts ?? "n/a"}</p>
                <p>PIDs {container.pids ?? "n/a"}</p>
                <p>Started {formatTimestamp(container.startedAt)}</p>
                <p>Ports {container.ports.length > 0 ? container.ports.join(", ") : "none"}</p>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {container.networks.map((networkName) => (
                  <span
                    key={`${container.name}-${networkName}`}
                    className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200"
                  >
                    {networkName}
                  </span>
                ))}
              </div>
              {container.mounts.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {container.mounts.map((mount) => (
                    <div
                      key={`${container.name}-${mount.destination ?? ""}-${mount.source ?? ""}`}
                      className="rounded-2xl bg-white px-3 py-2 text-xs font-semibold text-slate-700 ring-1 ring-slate-200"
                    >
                      {(mount.destination ?? "unknown destination")}{" "}
                      <span className="text-slate-400">from</span> {mount.source ?? "unknown source"}
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Database aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Storage and app data"
          subtitle="SQLite quick check, core table counts, compose paths, and Docker volumes."
        />
        <div className="mt-4 space-y-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-black text-slate-950">Runtime paths</p>
            <div className="mt-3 space-y-2 text-xs font-semibold text-slate-700">
              <p>Compose: {remote?.application.composeFile ?? "n/a"}</p>
              <p>Env: {remote?.application.envFile ?? "n/a"}</p>
              <p>Data: {remote?.application.dataDir ?? "n/a"}</p>
              <p>DB: {remote?.application.dbPath ?? "n/a"}</p>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <p className="text-sm font-semibold text-slate-700">
                DB size {formatBytes(remote?.application.sqlite.dbSizeBytes)}
              </p>
              <p className="text-sm font-semibold text-slate-700">
                quick_check {remote?.application.sqlite.quickCheck ?? "n/a"}
              </p>
              <p className="text-sm font-semibold text-slate-700">
                users {remote?.application.sqlite.userCount ?? "n/a"}
              </p>
              <p className="text-sm font-semibold text-slate-700">
                internal health{" "}
                {remote?.application.health.ok
                  ? "ok"
                  : remote?.application.health.error ?? remote?.application.health.status ?? "n/a"}
              </p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(remote?.application.sqlite.tableCounts ?? {}).map(([table, count]) => (
                <span
                  key={table}
                  className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200"
                >
                  {table}: {count}
                </span>
              ))}
            </div>
          </div>
          <div className="grid gap-3">
            {volumes.length > 0 ? (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center gap-2">
                  <HardDrive aria-hidden="true" className="h-4 w-4 text-slate-900" />
                  <p className="text-sm font-black text-slate-950">Docker volumes</p>
                </div>
                <div className="mt-3 space-y-2">
                  {volumes.map((volume) => (
                    <div
                      key={volume.name}
                      className="rounded-2xl bg-white px-3 py-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-200"
                    >
                      <p className="font-black text-slate-950">{volume.name}</p>
                      <p className="mt-1">
                        {volume.driver ?? "driver n/a"} / {volume.mountpoint ?? "mount n/a"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Network aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Networks"
          subtitle="Docker networks and which containers are attached to each segment."
          actions={
            canRemoveOrphanedNetworks ? (
              <ActionButton
                icon={<Trash2 aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                label="Remove orphaned"
                onClick={() => void runLocalAction("remove_orphaned_networks")}
                disabled={activeAction !== null || refreshing}
                busy={activeAction === "remove_orphaned_networks"}
                tone="danger"
              />
            ) : undefined
          }
        />
        <div className="mt-4 space-y-3">
          {networks.map((networkInfo) => (
            <div
              key={networkInfo.name}
              className="rounded-2xl border border-slate-200 bg-slate-50 p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-black text-slate-950">{networkInfo.name}</p>
                    {networkInfo.builtin ? (
                      <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] text-slate-700">
                        docker default
                      </span>
                    ) : null}
                    {networkInfo.orphaned ? (
                      <span className="rounded-full bg-red-50 px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] text-saints-red ring-1 ring-red-200">
                        orphaned
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs font-semibold text-slate-500">
                    {networkInfo.driver ?? "driver n/a"} / {networkInfo.scope ?? "scope n/a"}
                    {networkInfo.composeProject ? ` / ${networkInfo.composeProject}` : ""}
                    {networkInfo.composeNetwork ? ` / ${networkInfo.composeNetwork}` : ""}
                  </p>
                </div>
                <Cable aria-hidden="true" className="h-4 w-4 text-slate-900" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {networkInfo.subnets.map((subnet) => (
                  <span
                    key={`${networkInfo.name}-${subnet}`}
                    className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200"
                  >
                    {subnet}
                  </span>
                ))}
                {networkInfo.gateways.map((gateway) => (
                  <span
                    key={`${networkInfo.name}-${gateway}`}
                    className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200"
                  >
                    gw {gateway}
                  </span>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {networkInfo.attachedContainers.map((containerName) => (
                  <span
                    key={`${networkInfo.name}-${containerName}`}
                    className="rounded-full bg-slate-950 px-3 py-1 text-xs font-bold text-white"
                  >
                    {containerName}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<Clock3 aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Tomorrow&apos;s quiz"
          subtitle="Preview of the next quiz set on the remote server, including answers and explanations."
          actions={
            <div className="flex flex-wrap justify-end gap-2">
              {canGenerateTomorrowQuiz ? (
                <ActionButton
                  icon={<Zap aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                  label={repairDailyQuizLabel}
                  onClick={() => void runLocalAction("generate_tomorrow_quiz")}
                  disabled={activeAction !== null || refreshing}
                  busy={activeAction === "generate_tomorrow_quiz"}
                />
              ) : null}
              {canRegenerateTomorrowQuestions ? (
                <span className="inline-flex min-h-10 items-center justify-center rounded-2xl bg-slate-100 px-3 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-700 ring-1 ring-slate-200">
                  New question buttons are inline below
                </span>
              ) : null}
            </div>
          }
        />
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-black uppercase tracking-[0.18em] text-white">
              {tomorrowQuiz?.status ?? "unknown"}
            </span>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200">
              {tomorrowQuiz?.date ?? "n/a"}
            </span>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200">
              {tomorrowQuiz ? `${tomorrowQuiz.acceptedQuestions}/6 approved` : "n/a"}
            </span>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-700 ring-1 ring-slate-200">
              {tomorrowQuiz ? `${tomorrowQuiz.failedAttempts} failed attempts` : "n/a"}
            </span>
          </div>
          {tomorrowQuiz?.failureReason ? (
            <p className="mt-3 text-sm font-bold text-saints-red">{tomorrowQuiz.failureReason}</p>
          ) : null}
          <div className="mt-4 space-y-3">
            {tomorrowQuiz?.questions.length ? (
              tomorrowQuiz.questions.map((question, index) => (
                <details
                  key={`${question.subject}-${question.difficulty}-${index}`}
                  className="rounded-[1.35rem] border border-slate-200 bg-white p-3"
                >
                  <summary className="cursor-pointer list-none">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded-full bg-slate-950 px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] text-white">
                            {question.subject === "general_knowledge" ? "general" : "football"}
                          </span>
                          <span className="rounded-full bg-red-50 px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] text-saints-red ring-1 ring-red-200">
                            {question.difficulty}
                          </span>
                        </div>
                        <p className="mt-3 text-sm font-black leading-tight text-slate-950">
                          {question.question}
                        </p>
                      </div>
                      <AlertTriangle aria-hidden="true" className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
                    </div>
                  </summary>
                  <div className="mt-4 space-y-2">
                    {source === "local" && tomorrowQuiz?.date ? (
                      <div className="flex justify-end">
                        <ActionButton
                          icon={<RefreshCw aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                          label="New question"
                          onClick={() =>
                            void runLocalAction("regenerate_question", {
                              date: tomorrowQuiz.date,
                              subject: question.subject,
                              difficulty: question.difficulty,
                            })
                          }
                          disabled={activeAction !== null || refreshing}
                          busy={activeAction === "regenerate_question"}
                        />
                      </div>
                    ) : null}
                    {question.choices.map((choice) => (
                      <div
                        key={`${question.question}-${choice}`}
                        className={[
                          "rounded-2xl px-3 py-2 text-sm font-semibold ring-1",
                          choice === question.correctAnswer
                            ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                            : "bg-slate-50 text-slate-700 ring-slate-200",
                        ].join(" ")}
                      >
                        {choice}
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-sm font-semibold text-slate-600">{question.explanation}</p>
                </details>
              ))
            ) : (
              <p className="text-sm font-semibold text-slate-600">
                No accepted questions have been stored yet for tomorrow.
              </p>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeading
          icon={<TestTube2 aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
          title="Checks"
          subtitle="Collector test results from the remote machine and the public edge."
        />
        <div className="mt-4 space-y-2">
          {tests.map((test) => (
            <div
              key={test.id}
              className="flex items-start justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-black text-slate-950">{test.label}</p>
                <p className="mt-1 wrap-break-word text-xs font-semibold text-slate-600">
                  {test.detail}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {source === "local" && test.id === repairDailyQuizTestId && canGenerateTomorrowQuiz ? (
                  <ActionButton
                    icon={<Zap aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />}
                    label="Repair"
                    onClick={() => void runLocalAction("generate_tomorrow_quiz")}
                    disabled={activeAction !== null || refreshing}
                    busy={activeAction === "generate_tomorrow_quiz"}
                  />
                ) : null}
                <span className={`rounded-full px-3 py-1 text-[11px] font-black uppercase tracking-[0.18em] ${testTone(test.status)}`}>
                  {test.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {snapshot?.errors.length ? (
        <Card>
          <SectionHeading
            icon={<ShieldAlert aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />}
            title="Collector errors"
            subtitle="Raw errors from the latest snapshot attempt."
          />
          <div className="mt-4 space-y-2">
            {snapshot.errors.map((item) => (
              <div
                key={item}
                className="rounded-2xl border border-red-200 bg-red-50 px-3 py-3 text-sm font-bold text-saints-red"
              >
                {item}
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
