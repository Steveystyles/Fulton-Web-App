import { useEffect, useId, useState } from "react";
import { Trophy, X } from "lucide-react";
import { DialogPortal } from "./DialogPortal";
import { api, type ActivityId, type LeagueResponse } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type ScoreFilter = ActivityId | "all";
const labels: Record<ScoreFilter, string> = { all: "Overall", wordle: "Wordle", quiz: "Quiz", map: "Map" };

export function ScoresDialog({ currentGame }: { currentGame?: ActivityId }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<ScoreFilter>(currentGame ?? "all");
  const [data, setData] = useState<LeagueResponse | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const { user } = useAuth();
  const id = useId();
  useEffect(() => {
    if (!open) return;
    let active = true;
    void api.league().then(value => { if (active) { setData(value); setError(""); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Scores could not be loaded."); });
    return () => { active = false; };
  }, [open, retry]);
  const score = (player: NonNullable<typeof data>["players"][number]) => filter === "all" ? player.points : player.games[filter];
  const players = [...(data?.players ?? [])].sort((a, b) => score(b) - score(a) || a.username.localeCompare(b.username));
  return <>
    <button type="button" aria-label="Scores" aria-haspopup="dialog" aria-expanded={open} onClick={() => { setFilter(currentGame ?? "all"); setOpen(true); }} className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/15 bg-white/[0.08] text-white transition hover:bg-white/[0.16] saints-focus"><Trophy aria-hidden="true" className="h-5 w-5" strokeWidth={2.3}/></button>
    {open ? <DialogPortal onClose={() => setOpen(false)}><div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/65 p-3"><section id={id} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-4 text-slate-950 shadow-xl">
      <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-bold uppercase text-slate-500">Monday to Sunday · UK time</p><h2 id={`${id}-title`} className="text-xl font-black">Scores</h2></div><button type="button" aria-label="Close scores" onClick={() => setOpen(false)} className="saints-focus flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border"><X aria-hidden="true" className="h-5 w-5"/></button></div>
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Score category">{(Object.keys(labels) as ScoreFilter[]).map(key => <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)} className={`saints-focus min-h-11 rounded-xl border px-3 text-sm font-bold ${filter === key ? "bg-saints-black text-white" : "bg-white"}`}>{labels[key]}</button>)}</div>
      {error ? <div role="alert" className="mt-3"><p>{error}</p><button type="button" onClick={() => setRetry(value => value + 1)} className="saints-focus mt-2 min-h-11 rounded-xl border px-3 font-bold">Retry scores</button></div> : null}
      {!data && !error ? <p role="status" className="mt-3">Loading scores…</p> : null}
      {data ? <><p className="mt-3 text-sm text-slate-600">{data.periodStart} — {data.periodEnd}</p><div className="mt-2 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">{labels[filter]} weekly standings</caption><thead className="bg-slate-100"><tr><th className="p-2">Rank</th><th className="p-2">Player</th><th className="p-2 text-right">Pts</th></tr></thead><tbody>{players.map((player, index) => <tr key={player.id} className={`border-t ${player.id === user?.id ? "bg-red-50 font-black" : ""}`}><td className="p-2">{score(player) > 0 ? players.findIndex(candidate => score(candidate) === score(player)) + 1 : "—"}</td><td className="p-2">{player.username}{player.id === user?.id ? " (you)" : ""}</td><td className="p-2 text-right tabular-nums">{score(player).toFixed(2)}</td></tr>)}</tbody></table></div></> : null}
    </section></div></DialogPortal> : null}
  </>;
}
