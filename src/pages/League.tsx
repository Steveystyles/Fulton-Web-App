import { HelpButton } from "../components/HelpButton";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ActivityId, type LeagueResponse } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Card } from "../components/Card";
import { secondaryClass } from "../components/DailyJourney";

const labels = { all: "Overall", wordle: "Wordle", football: "Football", general: "General", map: "Map" };
export function League() {
  const { user } = useAuth();
  const [data, setData] = useState<LeagueResponse | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [filter, setFilter] = useState<ActivityId | "all">("all");
  useEffect(() => {
    let active = true;
    const load = () => void api.league().then(value => { if (active) { setData(value); setError(""); } }).catch((reason: Error) => { if (active) setError(reason.message); });
    load();
    window.addEventListener("focus", load);
    return () => { active = false; window.removeEventListener("focus", load); };
  }, [version]);
  const score = (player: NonNullable<typeof data>["players"][number]) => filter === "all" ? player.points : player.games[filter];
  const players = [...(data?.players ?? [])].sort((a, b) => score(b) - score(a) || a.username.localeCompare(b.username));
  const me = players.find(player => player.id === user?.id);
  const rival = me ? [...players].reverse().find(player => score(player) > score(me)) : undefined;
  return <section className="page-fade space-y-4" aria-label="Weekly league">
    <div className="rounded-2xl bg-saints-black p-5 text-white"><p className="text-xs font-bold uppercase text-white/65">Monday to Sunday · UK time</p><h1 className="mt-2 text-3xl font-black">The weekly league</h1>{data ? <p className="mt-2 text-sm text-white/70">{data.periodStart} — {data.periodEnd}</p> : null}<p className="mt-4 text-sm">{rival && me ? `${(score(rival) - score(me)).toFixed(2)} points to catch ${rival.username}.` : me && score(me) > 0 ? "You're setting the pace. Enjoy the next challenge." : "A fresh chance to join in every week."}</p></div>
    {error ? <Card><p role="alert">{error}</p><button className={`${secondaryClass} mt-2`} onClick={() => setVersion(value => value + 1)}>Retry standings</button></Card> : null}
    {!data && !error ? <p role="status">Loading this week's standings…</p> : null}
    <div className="flex flex-wrap gap-2" role="group" aria-label="League activity">{(Object.keys(labels) as Array<keyof typeof labels>).map(key => <button key={key} onClick={() => setFilter(key)} aria-pressed={filter === key} className={`min-h-11 rounded-xl border px-3 text-sm font-bold saints-focus ${filter === key ? "bg-saints-black text-white" : "bg-white"}`}>{labels[key]}</button>)}</div>
    {data ? <Card className="overflow-hidden p-0"><table className="w-full text-left text-sm"><caption className="sr-only">{labels[filter]} standings. Equal scores share a rank.</caption><thead className="bg-slate-100"><tr><th className="p-3">Rank</th><th className="p-3">Player</th><th className="p-3 text-right">League pts</th></tr></thead><tbody>{players.map((player, index) => <tr key={player.id} className={`border-t border-slate-100 ${player.id === user?.id ? "bg-red-50 font-black" : ""}`}><td className="p-3">{score(player) > 0 ? players.findIndex(candidate => score(candidate) === score(player)) + 1 : "—"}</td><td className="break-words p-3">{player.username}{player.id === user?.id ? " (you)" : ""}</td><td className="p-3 text-right tabular-nums">{score(player).toFixed(2)}</td></tr>)}</tbody></table></Card> : null}
    {data?.previousWinners.length ? <Card><h2 className="font-black">Last week's winners</h2><p className="mt-2">{data.previousWinners.map(player => player.username).join(" & ")} · {data.previousWinners[0].points.toFixed(2)} league points</p><p className="mt-1 text-xs text-slate-500">Week ending {data.previousPeriodEnd}, using the balanced league rules.</p></Card> : null}
    <HelpButton title="How league points work"><div className="mt-3 space-y-2 text-slate-600"><p>Each of the four daily activities can earn up to 10 league points. Wordle wins earn 10, 9, 8, 7, 6 or 5 by guess number; difficulty levels stay separate.</p><p>Each quiz's game score is converted from its maximum to a score out of 10, rounded to two decimal places. Map points count directly, capped at 10 per day. Unplayed games and losses earn zero.</p><p>This is a separate view of your results, not a rewrite of them. Original game points, Wordle mastery and all-time achievements remain in your score history. Equal league scores share a rank.</p></div></HelpButton>
    <div className="flex flex-wrap gap-2"><Link className={secondaryClass} to="/">Back to Today</Link><Link className={secondaryClass} to="/scores/history">Original scores & mastery</Link></div>
  </section>;
}
