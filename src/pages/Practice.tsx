import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DailyQuestionsResponse } from "../lib/api";
import { DailyQuiz } from "../components/DailyQuiz";
import { useAuth } from "../context/AuthContext";
import { secondaryClass } from "../components/DailyJourney";

export function Practice() {
  const { user } = useAuth();
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [category, setCategory] = useState<"football" | "general">("football");
  const [data, setData] = useState<DailyQuestionsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    void api.practiceDates().then(value => { if (active) { setDates(value.dates); setDate(current => current || value.dates[0] || ""); setError(null); } })
      .catch((reason: Error) => { if (active) setError(reason); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [version]);
  useEffect(() => {
    if (!date) return;
    let active = true;
    setLoading(true);
    setData(null);
    void api.practiceQuiz(date).then(value => { if (active) { setData(value); setError(null); } })
      .catch((reason: Error) => { if (active) setError(reason); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [date, version]);
  return <section className="space-y-4" aria-label="Practice archive"><h1 className="text-2xl font-black">Just for the fun of it</h1><p className="text-sm text-slate-600">Replay a published past quiz. No league points, no streak pressure, no changes to your daily results. Practice progress lasts while this round is open.</p>
    {dates.length ? <div className="grid grid-cols-2 gap-3"><label className="text-sm font-bold">Past round<select className="mt-1 min-h-12 w-full rounded-xl border bg-white p-2" value={date} onChange={event => setDate(event.target.value)}>{dates.map(value => <option key={value}>{value}</option>)}</select></label><label className="text-sm font-bold">Quiz type<select className="mt-1 min-h-12 w-full rounded-xl border bg-white p-2" value={category} onChange={event => setCategory(event.target.value === "general" ? "general" : "football")}><option value="football">Football</option><option value="general">General knowledge</option></select></label></div> : !loading ? <p>{error?.message ?? "No past published rounds are available yet. Today's games will join the archive after their day ends."}</p> : <p role="status">Finding past rounds…</p>}
    {date ? <DailyQuiz key={`${date}:${category}:${version}`} practice category={category} storageScope={user?.id ?? 0} quizDate={data?.date} questions={data?.[category] ?? []} loading={loading} error={error} serverResult={null} serverAnswers={[]} onRefresh={() => setVersion(value => value + 1)} /> : null}
    {error && !date ? <button className={secondaryClass} onClick={() => setVersion(value => value + 1)}>Retry archive</button> : null}
    <Link className={secondaryClass} to="/">Back to Today</Link>
  </section>;
}
