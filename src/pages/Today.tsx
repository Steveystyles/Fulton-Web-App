import { HelpButton } from "../components/HelpButton";
import { Link } from "react-router-dom";
import { Check, CircleHelp, Hash, MapPinned, ArrowRight, Trophy } from "lucide-react";
import { Card } from "../components/Card";
import { actionClass, secondaryClass, ShareResult, useToday } from "../components/DailyJourney";
import { useAuth } from "../context/AuthContext";

const icons = { wordle: Hash, football: CircleHelp, general: CircleHelp, map: MapPinned };
const descriptions = { wordle: "Six guesses. One word. Your next little victory.", football: "Three questions, from the warm-up to the big finish.", general: "A little knowledge. A satisfying discovery.", map: "Follow the clues. Decide when you're ready to pin." };

export function Today() {
  const { user } = useAuth();
  const { data, error, refresh } = useToday();
  const complete = data?.activities.filter(item => item.status === "completed").length ?? 0;
  return <section className="page-fade space-y-4" aria-label="Today">
    <div className="rounded-2xl bg-saints-black p-5 text-white">
      <p className="text-xs font-black uppercase tracking-wider text-white/60">Your daily games club</p>
      <h1 className="mt-2 text-3xl font-black">Hello, {user?.username}.</h1>
      <p className="mt-2 text-sm leading-relaxed text-white/80">{complete === 4 ? "Four challenges finished. Enjoy the rest of your day." : "A word, a little knowledge, a place to discover. Where will you start?"}</p>
      {data ? <p className="mt-4 flex items-center gap-2 text-sm font-bold"><Check className="h-4 w-4" aria-hidden="true" />{complete} of 4 completed · {new Date(`${data.date}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</p> : null}
    </div>
    {error ? <Card><p role="alert" className="text-sm text-saints-red">{error}</p><button className={`${secondaryClass} mt-3`} onClick={refresh}>Retry daily progress</button></Card> : null}
    {!data && !error ? <p role="status" className="p-5 text-center font-bold">Finding your daily games…</p> : null}
    <div className="grid gap-3 sm:grid-cols-2">
      {data?.activities.map(item => { const Icon = icons[item.id]; return <Card key={item.id}>
        <div className="flex items-center justify-between gap-2"><Icon className="h-6 w-6 text-saints-red" aria-hidden="true" /><span className={`rounded-full px-2 py-1 text-xs font-bold ${item.status === "completed" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>{item.status === "completed" ? "Completed" : item.status === "continue" ? "In progress" : item.status === "ready" ? "Ready to play" : "Not ready yet"}</span></div>
        <h2 className="mt-3 text-xl font-black">{item.title}</h2><p className="mt-1 min-h-10 text-sm text-slate-600">{descriptions[item.id]}</p>
        <Link className={`${item.status === "completed" || item.status === "unavailable" ? secondaryClass : actionClass} mt-4 w-full gap-2`} to={item.href}>{item.status === "completed" ? `View result · ${item.score ?? 0} game points` : item.status === "continue" ? "Continue playing" : item.status === "ready" ? "Let's play" : "Check availability"}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
      </Card>; })}
    </div>
    <Link to="/scores" className="flex min-h-20 items-center gap-4 rounded-2xl border border-saints-line bg-white p-4 saints-focus"><Trophy className="h-7 w-7 text-saints-red" aria-hidden="true" /><div className="flex-1"><h2 className="font-black">This week's league</h2><p className="mt-1 text-sm text-slate-600">Four activities. Equal daily point opportunities.</p></div><ArrowRight className="h-5 w-5" aria-hidden="true" /></Link>
    {complete === 4 && data ? <Card><ShareResult text={`Fulton's Quiz · ${data.date}\nDaily four complete!\n${data.activities.map(item => `${item.title}: ${item.score} game points`).join("\n")}`} /></Card> : null}
    <Link className={`${secondaryClass} w-full`} to="/practice">Fancy another round? Explore practice quizzes</Link>
    <HelpButton title="How the club works"><p className="mt-3 leading-relaxed">Choose any game, in any order. Confirmed answers are saved to your account. Game points record your original achievements; the weekly league balances each activity to a maximum of 10 points per day. Rounds refresh at midnight UK time. There is no timer and no obligation to play everything.</p><Link className={`${secondaryClass} mt-3`} to="/account">Preferences and account help</Link></HelpButton>
  </section>;
}
