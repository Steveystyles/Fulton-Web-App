import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ActivityId, type TodayResponse } from "../lib/api";

export const actionClass = "inline-flex min-h-11 items-center justify-center rounded-xl bg-saints-black px-4 py-2 text-sm font-black text-white saints-focus";
export const secondaryClass = "inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 saints-focus";

export function useToday() {
  const [data, setData] = useState<TodayResponse | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    let active = true;
    const load = () => void api.today().then(value => { if (active) { setData(value); setError(""); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Your daily progress could not be loaded."); });
    load();
    const visible = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    const interval = window.setInterval(visible, 60000);
    return () => { active = false; window.clearInterval(interval); window.removeEventListener("focus", visible); document.removeEventListener("visibilitychange", visible); };
  }, [version]);
  return { data, error, refresh };
}

export function ShareResult({ text }: { text: string }) {
  const [message, setMessage] = useState("");
  const [manual, setManual] = useState(false);
  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: "Fulton's Quiz", text });
      else { await navigator.clipboard.writeText(text); setMessage("Result copied — no answers included."); }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setManual(true);
      setMessage("Select and copy your result below.");
    }
  }
  return <div><button type="button" className={secondaryClass} onClick={() => void share()}>Share result · no spoilers</button>
    <p role="status" className="mt-2 text-sm text-slate-600">{message}</p>
    {manual ? <textarea readOnly aria-label="Spoiler-free result to copy" className="w-full rounded-lg border p-3 text-sm" value={text} onFocus={event => event.currentTarget.select()} /> : null}
  </div>;
}

export function DailyJourney({ current, summary }: { current: ActivityId; summary: string }) {
  const { data, error, refresh } = useToday();
  const next = data?.activities.find(item => item.id !== current && item.status === "continue")
    ?? data?.activities.find(item => item.id !== current && item.status === "ready");
  const allDone = data?.activities.every(item => item.id === current || item.status === "completed");
  return <div className="mt-4 space-y-3 border-t border-slate-200 pt-4 text-left">
    <p className="font-black text-slate-950">{allDone ? "That's your daily round complete. Nicely played." : "Fancy another challenge?"}</p>
    <div className="flex flex-wrap gap-2">
      {next ? <Link className={actionClass} to={next.href}>{next.status === "continue" ? "Continue" : "Play"} {next.title}</Link> : <Link className={actionClass} to="/wordle">Back to Wordle</Link>}
      <Link className={secondaryClass} to="/scores">View weekly league</Link>
    </div>
    {error ? <button className="min-h-11 text-sm underline saints-focus" onClick={refresh}>Refresh daily progress</button> : null}
    <ShareResult text={summary} />
    <p className="text-sm text-slate-500">New daily rounds arrive at midnight, UK time. Play as much or as little as you like.</p>
  </div>;
}
