import { CalendarDays, LoaderCircle, MapPin, Search } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type HistoryResponse } from "../lib/api";
import { Card } from "./Card";

const defaultLocation = "Paisley";

function todayIsoDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function HistoryKnowledge() {
  const [location, setLocation] = useState(defaultLocation);
  const [submittedLocation, setSubmittedLocation] = useState(defaultLocation);
  const [historyDate, setHistoryDate] = useState(todayIsoDate);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    async function loadHistory() {
      try {
        const response = await api.history({
          location: submittedLocation,
          date: historyDate,
          lang: "en",
        });
        if (active) {
          setHistory(response);
        }
      } catch (caughtError) {
        if (active) {
          setHistory(null);
          setError(
            caughtError instanceof Error ? caughtError.message : "History failed to load.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadHistory();

    return () => {
      active = false;
    };
  }, [historyDate, submittedLocation]);

  const events = useMemo(() => history?.globalEvents.slice(0, 4) ?? [], [history]);
  const facts = history?.location?.facts ?? [];

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedLocation = location.trim();
    if (trimmedLocation) {
      setSubmittedLocation(trimmedLocation);
    }
  }

  return (
    <section className="space-y-3" aria-label="Local knowledge and history">
      <Card>
        <form className="space-y-3" onSubmit={submitLocation}>
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-saints-black text-white">
              <MapPin aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
            </span>
            <div className="min-w-0">
              <p className="text-lg font-black leading-tight text-slate-950">
                Local knowledge
              </p>
              <p className="mt-1 text-sm font-bold text-slate-500">
                {history?.location?.title ?? submittedLocation}
              </p>
            </div>
          </div>

          <div className="grid gap-2">
            <label className="block">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Location
              </span>
              <input
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>

            <label className="block">
              <span className="text-xs font-black uppercase tracking-normal text-slate-500">
                Date
              </span>
              <input
                value={historyDate}
                onChange={(event) => setHistoryDate(event.target.value)}
                type="date"
                className="mt-1 h-12 w-full rounded-2xl border border-slate-300 bg-white px-3 text-base font-bold text-slate-950 outline-none transition focus:border-saints-red focus:ring-4 focus:ring-saints-red/15"
              />
            </label>
          </div>

          <button
            type="submit"
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-2xl bg-saints-black px-4 py-2 text-sm font-black text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-saints-red/20"
          >
            <Search aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
            Update
          </button>
        </form>
      </Card>

      <Card>
        {loading ? (
          <div className="flex min-h-24 items-center justify-center gap-2 text-sm font-black text-slate-500">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading history
          </div>
        ) : error ? (
          <p className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-bold text-saints-red">
            {error}
          </p>
        ) : (
          <div className="space-y-4">
            {facts.length > 0 ? (
              <div className="space-y-2">
                {facts.map((fact) => (
                  <p key={fact} className="text-sm font-semibold leading-relaxed text-slate-600">
                    {fact}
                  </p>
                ))}
              </div>
            ) : null}

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-saints-red">
                <CalendarDays aria-hidden="true" className="h-4 w-4" strokeWidth={2.4} />
                <p className="text-sm font-black uppercase tracking-normal">
                  This day in history
                </p>
              </div>
              {events.map((event) => (
                <div key={`${event.year}-${event.text}`} className="rounded-2xl bg-slate-50 p-3">
                  <p className="text-sm font-black text-slate-950">{event.year}</p>
                  <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-600">
                    {event.text}
                  </p>
                </div>
              ))}
              {events.length === 0 ? (
                <p className="rounded-2xl bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-600">
                  No history events are available for this date just now.
                </p>
              ) : null}
            </div>
          </div>
        )}
      </Card>
    </section>
  );
}
